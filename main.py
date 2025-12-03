import os
import json
from typing import Optional, Dict, Any, List

import requests
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

HEYGEN_BASE_URL = "https://api.heygen.com"


# ============================================================
#                   ERROR + CLIENT
# ============================================================

class HeyGenError(Exception):
    pass


class HeyGenStreamingClient:
    def __init__(self, api_key: str, base_url: str = HEYGEN_BASE_URL):
        if not api_key:
            raise ValueError("HEYGEN_API_KEY is required")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")

    def _api_headers(self) -> Dict[str, str]:
        return {
            "X-Api-Key": self.api_key,
            "Content-Type": "application/json",
        }

    def _streaming_headers(self, session_token: str) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {session_token}",
            "Content-Type": "application/json",
        }

    def _handle_response(self, r: requests.Response):
        try:
            data = r.json()
        except Exception:
            raise HeyGenError(f"Non-JSON response: {r.status_code} {r.text[:200]}")
        if not r.ok:
            raise HeyGenError(f"HTTP {r.status_code}: {data}")
        return data

    # ============= HeyGen API =============

    def list_streaming_avatars(self):
        url = f"{self.base_url}/v1/streaming/avatar.list"
        r = requests.get(url, headers=self._api_headers(), timeout=10)
        data = self._handle_response(r)
        return data.get("data", [])

    def create_session_token(self):
        url = f"{self.base_url}/v1/streaming.create_token"
        r = requests.post(url, headers=self._api_headers(), timeout=10)
        data = self._handle_response(r)
        token = data.get("data", {}).get("token")
        if not token:
            raise HeyGenError("create_token returned no token")
        return token

    def new_session(self, session_token, avatar_id, voice_id=None):
        url = f"{self.base_url}/v1/streaming.new"
        payload = {
            "quality": "high",
            "version": "v2",
            "activity_idle_timeout": 120,
            "avatar_id": avatar_id,
        }
        if voice_id:
            payload["voice"] = {"voice_id": voice_id}

        r = requests.post(
            url,
            headers=self._streaming_headers(session_token),
            data=json.dumps(payload),
            timeout=30,
        )
        data = self._handle_response(r)
        if data.get("code") != 100:
            raise HeyGenError(f"new_session failed: {data}")
        return data["data"]

    def start_session(self, session_token, session_id):
        url = f"{self.base_url}/v1/streaming.start"
        payload = {"session_id": session_id}
        r = requests.post(
            url,
            headers=self._streaming_headers(session_token),
            data=json.dumps(payload),
        )
        return self._handle_response(r)

    def send_task(self, session_token, session_id, text):
        url = f"{self.base_url}/v1/streaming.task"
        payload = {
            "session_id": session_id,
            "text": text,
            "task_type": "repeat",
            "task_mode": "async",
        }
        r = requests.post(
            url,
            headers=self._streaming_headers(session_token),
            data=json.dumps(payload),
            timeout=30,
        )
        return self._handle_response(r)

    def stop_session(self, session_token, session_id):
        url = f"{self.base_url}/v1/streaming.stop"
        payload = {"session_id": session_id}
        r = requests.post(
            url,
            headers=self._streaming_headers(session_token),
            data=json.dumps(payload),
        )
        return self._handle_response(r)


# ============================================================
#                     ENV + LANGUAGE MAP
# ============================================================

load_dotenv()

HEYGEN_API_KEY = os.getenv("HEYGEN_API_KEY")
if not HEYGEN_API_KEY:
    raise RuntimeError("HEYGEN_API_KEY is required")

DEFAULT_LANG = (os.getenv("DEFAULT_LANG") or "en").lower()

LANG_MAP = {
    "fa": {
        "avatar": os.getenv("FA_AVATAR_ID"),
        "voice": os.getenv("FA_VOICE_ID"),
    },
    "en": {
        "avatar": os.getenv("EN_AVATAR_ID"),
        "voice": os.getenv("EN_VOICE_ID"),
    },
    "zh": {
        "avatar": os.getenv("ZH_AVATAR_ID"),
        "voice": os.getenv("ZH_VOICE_ID"),
    },
}

# fallback defaults
GLOBAL_AVATAR = os.getenv("AVATAR_ID")
GLOBAL_VOICE = os.getenv("VOICE_ID")

client = HeyGenStreamingClient(HEYGEN_API_KEY)
sessions: Dict[str, str] = {}


def resolve_avatar_and_voice(req_avatar, req_voice):
    """
    Priority:
    1) Request override
    2) Language-based mapping
    3) Global defaults
    4) Auto-pick first avatar from API
    """

    # 1: Request override
    if req_avatar:
        avatar_id = req_avatar
    else:
        avatar_id = LANG_MAP.get(DEFAULT_LANG, {}).get("avatar") or GLOBAL_AVATAR

    if req_voice:
        voice_id = req_voice
    else:
        voice_id = LANG_MAP.get(DEFAULT_LANG, {}).get("voice") or GLOBAL_VOICE

    # 4: No avatar → pick first
    if not avatar_id:
        avatars = client.list_streaming_avatars()
        if not avatars:
            raise HeyGenError("No streaming avatars available")
        avatar_id = avatars[0].get("avatar_id") or avatars[0].get("id")

    return avatar_id, voice_id


# ============================================================
#                  FASTAPI SETUP
# ============================================================

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================
#                      SCHEMAS
# ============================================================

class CreateSessionRequest(BaseModel):
    avatar_id: Optional[str] = None
    voice_id: Optional[str] = None


class CreateSessionResponse(BaseModel):
    session_id: str
    livekit_url: str
    access_token: str


class TalkRequest(BaseModel):
    session_id: str
    text: str


class StopRequest(BaseModel):
    session_id: str


# ============================================================
#                      ENDPOINTS
# ============================================================

@app.post("/api/avatar/session", response_model=CreateSessionResponse)
def create_session(req: CreateSessionRequest):
    try:
        avatar_id, voice_id = resolve_avatar_and_voice(req.avatar_id, req.voice_id)

        session_token = client.create_session_token()
        session_info = client.new_session(
            session_token=session_token,
            avatar_id=avatar_id,
            voice_id=voice_id,
        )
        session_id = session_info["session_id"]

        client.start_session(session_token, session_id)
        sessions[session_id] = session_token

        return CreateSessionResponse(
            session_id=session_id,
            livekit_url=session_info["url"],
            access_token=session_info["access_token"],
        )

    except HeyGenError as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/avatar/talk")
def talk(req: TalkRequest):
    session_token = sessions.get(req.session_id)
    if not session_token:
        raise HTTPException(status_code=404, detail="Unknown session_id")

    try:
        return client.send_task(
            session_token=session_token,
            session_id=req.session_id,
            text=req.text,
        )
    except HeyGenError as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/avatar/stop")
def stop(req: StopRequest):
    session_token = sessions.get(req.session_id)
    if not session_token:
        return {"status": "already_closed"}

    try:
        resp = client.stop_session(session_token, req.session_id)
        return resp
    finally:
        sessions.pop(req.session_id, None)
