import os
import json
from typing import Optional, Dict, Any, List

import requests
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

HEYGEN_BASE_URL = "https://api.heygen.com"


class HeyGenError(Exception):
    pass


class HeyGenStreamingClient:
    def __init__(self, api_key: str, base_url: str = HEYGEN_BASE_URL):
        if not api_key:
            raise ValueError("HEYGEN_API_KEY is required")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")

    # ----- low-level helpers -----

    def _api_headers(self) -> Dict[str, str]:
        # API key auth (create_token, avatar.list)
        return {
            "X-Api-Key": self.api_key,
            "Content-Type": "application/json",
        }

    def _streaming_headers(self, session_token: str) -> Dict[str, str]:
        # Bearer token auth (streaming.new/start/task/stop)
        return {
            "Authorization": f"Bearer {session_token}",
            "Content-Type": "application/json",
        }

    def _handle_response(self, r: requests.Response) -> Any:
        try:
            data = r.json()
        except Exception:
            raise HeyGenError(f"Non-JSON response: {r.status_code} {r.text[:200]}")
        if not r.ok:
            raise HeyGenError(f"HTTP {r.status_code}: {data}")
        return data

    # ----- API methods -----

    def list_streaming_avatars(self) -> List[Dict[str, Any]]:
        url = f"{self.base_url}/v1/streaming/avatar.list"
        r = requests.get(url, headers=self._api_headers(), timeout=15)
        data = self._handle_response(r)
        return data.get("data", [])

    def create_session_token(self) -> str:
        url = f"{self.base_url}/v1/streaming.create_token"
        r = requests.post(url, headers=self._api_headers(), timeout=15)
        data = self._handle_response(r)
        if data.get("error"):
            raise HeyGenError(f"Create token error: {data}")
        token = data.get("data", {}).get("token")
        if not token:
            raise HeyGenError(f"No token in response: {data}")
        return token

    def new_session(
        self,
        session_token: str,
        avatar_id: str,
        voice_id: Optional[str] = None,
        quality: str = "high",
        version: str = "v2",
        activity_idle_timeout: int = 120,
    ) -> Dict[str, Any]:
        url = f"{self.base_url}/v1/streaming.new"
        payload: Dict[str, Any] = {
            "quality": quality,
            "version": version,
            "activity_idle_timeout": activity_idle_timeout,
            "avatar_id": avatar_id,
        }

        voice: Dict[str, Any] = {}
        if voice_id:
            voice["voice_id"] = voice_id
        if voice:
            payload["voice"] = voice

        r = requests.post(
            url,
            headers=self._streaming_headers(session_token),
            data=json.dumps(payload),
            timeout=30,
        )
        data = self._handle_response(r)
        if data.get("code") != 100:
            raise HeyGenError(f"new_session failed: {data}")
        return data["data"]  # session_id, url, access_token

    def start_session(self, session_token: str, session_id: str) -> Dict[str, Any]:
        url = f"{self.base_url}/v1/streaming.start"
        payload = {"session_id": session_id}
        r = requests.post(
            url,
            headers=self._streaming_headers(session_token),
            data=json.dumps(payload),
            timeout=15,
        )
        return self._handle_response(r)

    def send_task(
        self,
        session_token: str,
        session_id: str,
        text: str,
        task_type: str = "repeat",
        task_mode: str = "async",
    ) -> Dict[str, Any]:
        url = f"{self.base_url}/v1/streaming.task"
        payload = {
            "session_id": session_id,
            "text": text,
            "task_type": task_type,  # "repeat" -> verbatim
            "task_mode": task_mode,
        }
        r = requests.post(
            url,
            headers=self._streaming_headers(session_token),
            data=json.dumps(payload),
            timeout=30,
        )
        return self._handle_response(r)

    def stop_session(self, session_token: str, session_id: str) -> Dict[str, Any]:
        url = f"{self.base_url}/v1/streaming.stop"
        payload = {"session_id": session_id}
        r = requests.post(
            url,
            headers=self._streaming_headers(session_token),
            data=json.dumps(payload),
            timeout=15,
        )
        return self._handle_response(r)


# ------------------ FastAPI wiring ------------------

load_dotenv()
HEYGEN_API_KEY = os.getenv("HEYGEN_API_KEY")
DEFAULT_AVATAR_ID = os.getenv("AVATAR_ID")  # optional
DEFAULT_VOICE_ID = os.getenv("VOICE_ID")    # optional

if not HEYGEN_API_KEY:
    raise RuntimeError("HEYGEN_API_KEY env var is required")

client = HeyGenStreamingClient(HEYGEN_API_KEY)

# In-memory: session_id -> session_token
sessions: Dict[str, str] = {}

app = FastAPI()

# CORS for React dev
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------- Schemas ----------

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


# ---------- Endpoints ----------

@app.post("/api/avatar/session", response_model=CreateSessionResponse)
def create_session(req: CreateSessionRequest):
    try:
        avatar_id = req.avatar_id or DEFAULT_AVATAR_ID
        if not avatar_id:
            # pick first streaming avatar as fallback
            avatars = client.list_streaming_avatars()
            if not avatars:
                raise HeyGenError("No streaming avatars available")
            first = avatars[0]
            avatar_id = first.get("avatar_id") or first.get("id")

        voice_id = req.voice_id or DEFAULT_VOICE_ID

        # 1) per-session token
        session_token = client.create_session_token()

        # 2) new streaming session
        session_info = client.new_session(
            session_token=session_token,
            avatar_id=avatar_id,
            voice_id=voice_id,
        )
        session_id = session_info["session_id"]

        # 3) start streaming
        client.start_session(session_token, session_id)

        # 4) store token for later
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

    if not req.text:
        raise HTTPException(status_code=400, detail="text is required")

    try:
        resp = client.send_task(
            session_token=session_token,
            session_id=req.session_id,
            text=req.text,
            task_type="repeat",  # verbatim
            task_mode="async",
        )
        return resp
    except HeyGenError as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/avatar/stop")
def stop(req: StopRequest):
    session_token = sessions.get(req.session_id)
    if not session_token:
        return {"status": "already_closed"}

    try:
        resp = client.stop_session(session_token, req.session_id)
    except HeyGenError as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        sessions.pop(req.session_id, None)

    return resp
