import os
import json
import logging
from typing import Optional, Dict, Any, List, Tuple

import requests
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

HEYGEN_BASE_URL = "https://api.heygen.com"

# ------------------------------------------------------------
# Logging
# ------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)
logger = logging.getLogger("heygen-avatar-service")


# ============================================================
#                   ERROR CLASSES
# ============================================================

class HeyGenError(Exception):
    """Base error for HeyGen integration."""
    pass


class HeyGenNetworkError(HeyGenError):
    """Problems talking to HeyGen at HTTP/network level."""
    pass


class HeyGenQuotaError(HeyGenError):
    """HeyGen says: you are out of quota (code 10008)."""
    pass


# ============================================================
#                         CLIENT
# ============================================================

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
        """Normalize HeyGen HTTP responses and raise typed errors."""
        try:
            data = r.json()
        except Exception:
            logger.error("Non-JSON response from HeyGen: %s", r.text[:200])
            raise HeyGenError(f"Non-JSON response: {r.status_code} {r.text[:200]}")

        # Quota exhausted: HeyGen specific
        if r.status_code == 400 and isinstance(data, dict):
            if data.get("code") == 10008:
                # "quota not enough"
                logger.error("HeyGen quota not enough: %s", data)
                raise HeyGenQuotaError("HeyGen quota not enough (code 10008)")

        if not r.ok:
            logger.error("HTTP error from HeyGen: %s %s", r.status_code, data)
            raise HeyGenError(f"HTTP {r.status_code}: {data}")

        return data

    # ============= HeyGen API =============

    def list_streaming_avatars(self) -> List[Dict[str, Any]]:
        url = f"{self.base_url}/v1/streaming/avatar.list"
        try:
            r = requests.get(url, headers=self._api_headers(), timeout=10)
        except requests.RequestException as exc:
            logger.exception("Network error calling list_streaming_avatars")
            raise HeyGenNetworkError(f"HeyGen API unreachable: {exc}") from exc

        data = self._handle_response(r)
        return data.get("data", [])

    def create_session_token(self) -> str:
        url = f"{self.base_url}/v1/streaming.create_token"
        try:
            r = requests.post(url, headers=self._api_headers(), timeout=10)
        except requests.RequestException as exc:
            logger.exception("Network error calling create_session_token")
            raise HeyGenNetworkError(f"HeyGen API unreachable: {exc}") from exc

        data = self._handle_response(r)
        token = data.get("data", {}).get("token")
        if not token:
            logger.error("create_session_token returned no token: %s", data)
            raise HeyGenError("create_session_token returned no token")
        return token

    def new_session(
        self,
        session_token: str,
        avatar_id: str,
        voice_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        if not avatar_id:
            raise HeyGenError("avatar_id is required for new_session")

        url = f"{self.base_url}/v1/streaming.new"
        payload: Dict[str, Any] = {
            "quality": "high",
            "version": "v2",
            "activity_idle_timeout": 120,
            "avatar_id": avatar_id,
        }
        if voice_id:
            payload["voice"] = {"voice_id": voice_id}

        try:
            r = requests.post(
                url,
                headers=self._streaming_headers(session_token),
                data=json.dumps(payload),
                timeout=30,
            )
        except requests.RequestException as exc:
            logger.exception("Network error calling new_session")
            raise HeyGenNetworkError(f"HeyGen API unreachable: {exc}") from exc

        data = self._handle_response(r)
        if data.get("code") != 100:
            logger.error("new_session failed: %s", data)
            raise HeyGenError(f"new_session failed: {data}")
        return data["data"]

    def start_session(self, session_token: str, session_id: str) -> Dict[str, Any]:
        if not session_id:
            raise HeyGenError("session_id is required for start_session")

        url = f"{self.base_url}/v1/streaming.start"
        payload = {"session_id": session_id}
        try:
            r = requests.post(
                url,
                headers=self._streaming_headers(session_token),
                data=json.dumps(payload),
                timeout=10,
            )
        except requests.RequestException as exc:
            logger.exception("Network error calling start_session")
            raise HeyGenNetworkError(f"HeyGen API unreachable: {exc}") from exc

        return self._handle_response(r)

    def send_task(self, session_token: str, session_id: str, text: str) -> Dict[str, Any]:
        if not text or not text.strip():
            raise HeyGenError("Text for send_task cannot be empty")

        url = f"{self.base_url}/v1/streaming.task"
        payload = {
            "session_id": session_id,
            "text": text,
            "task_type": "repeat",
            "task_mode": "async",
        }
        try:
            r = requests.post(
                url,
                headers=self._streaming_headers(session_token),
                data=json.dumps(payload),
                timeout=30,
            )
        except requests.RequestException as exc:
            logger.exception("Network error calling send_task")
            raise HeyGenNetworkError(f"HeyGen API unreachable: {exc}") from exc

        return self._handle_response(r)

    def stop_session(self, session_token: str, session_id: str) -> Dict[str, Any]:
        url = f"{self.base_url}/v1/streaming.stop"
        payload = {"session_id": session_id}
        try:
            r = requests.post(
                url,
                headers=self._streaming_headers(session_token),
                data=json.dumps(payload),
                timeout=10,
            )
        except requests.RequestException as exc:
            logger.exception("Network error calling stop_session")
            raise HeyGenNetworkError(f"HeyGen API unreachable: {exc}") from exc

        return self._handle_response(r)


# ============================================================
#                     ENV + LANGUAGE MAP
# ============================================================

load_dotenv()

HEYGEN_API_KEY = os.getenv("HEYGEN_API_KEY")
if not HEYGEN_API_KEY:
    raise RuntimeError("HEYGEN_API_KEY is required")

raw_default_lang = os.getenv("DEFAULT_LANG") or "en"
DEFAULT_LANG = raw_default_lang.lower()

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

if DEFAULT_LANG not in LANG_MAP:
    logger.warning(
        "DEFAULT_LANG=%r not in LANG_MAP, falling back to 'en'", DEFAULT_LANG
    )
    DEFAULT_LANG = "en"

GLOBAL_AVATAR = os.getenv("AVATAR_ID")
GLOBAL_VOICE = os.getenv("VOICE_ID")

client = HeyGenStreamingClient(HEYGEN_API_KEY)
sessions: Dict[str, str] = {}


def resolve_avatar_and_voice(
    req_avatar: Optional[str],
    req_voice: Optional[str],
) -> Tuple[str, Optional[str]]:
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
        logger.info(
            "No avatar configured for DEFAULT_LANG='%s', fetching first streaming avatar",
            DEFAULT_LANG,
        )
        avatars = client.list_streaming_avatars()
        if not avatars:
            logger.error("list_streaming_avatars returned empty list")
            raise HeyGenError("No streaming avatars available")
        first = avatars[0]
        avatar_id = first.get("avatar_id") or first.get("id")
        if not avatar_id:
            logger.error("Could not resolve avatar_id from first avatar object: %s", first)
            raise HeyGenError("Could not resolve avatar_id from avatar list")

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
        logger.info(
            "Creating HeyGen session with avatar=%s voice=%s (DEFAULT_LANG=%s)",
            avatar_id,
            voice_id,
            DEFAULT_LANG,
        )

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

    except HeyGenQuotaError as e:
        logger.error("HeyGenQuotaError in /api/avatar/session: %s", e)
        raise HTTPException(
            status_code=429,
            detail="HeyGen quota exhausted. Please top up your HeyGen credits.",
        )
    except HeyGenNetworkError as e:
        logger.error("HeyGenNetworkError in /api/avatar/session: %s", e)
        raise HTTPException(
            status_code=503,
            detail="Unable to reach HeyGen API (network/DNS issue).",
        )
    except HeyGenError as e:
        logger.error("HeyGenError in /api/avatar/session: %s", e)
        raise HTTPException(status_code=502, detail="Error from HeyGen backend.")
    except Exception:
        logger.exception("Unexpected error in /api/avatar/session")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post("/api/avatar/talk")
def talk(req: TalkRequest):
    session_token = sessions.get(req.session_id)
    if not session_token:
        logger.warning("talk called with unknown session_id=%s", req.session_id)
        raise HTTPException(status_code=404, detail="Unknown session_id")

    if not req.text or not req.text.strip():
        raise HTTPException(status_code=400, detail="text is required")

    try:
        resp = client.send_task(
            session_token=session_token,
            session_id=req.session_id,
            text=req.text,
        )
        return resp
    except HeyGenQuotaError:
        raise HTTPException(
            status_code=429,
            detail="HeyGen quota exhausted. Please top up your HeyGen credits.",
        )
    except HeyGenNetworkError:
        raise HTTPException(
            status_code=503,
            detail="Unable to reach HeyGen API (network/DNS issue).",
        )
    except HeyGenError:
        raise HTTPException(status_code=502, detail="Error from HeyGen backend.")
    except Exception:
        logger.exception("Unexpected error in /api/avatar/talk")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post("/api/avatar/stop")
def stop(req: StopRequest):
    session_token = sessions.get(req.session_id)
    if not session_token:
        logger.info("stop called for non-existent session_id=%s", req.session_id)
        return {"status": "already_closed"}

    try:
        resp = client.stop_session(session_token, req.session_id)
        return resp
    except HeyGenNetworkError:
        raise HTTPException(
            status_code=503,
            detail="Unable to reach HeyGen API (network/DNS issue).",
        )
    except HeyGenError:
        raise HTTPException(status_code=502, detail="Error from HeyGen backend.")
    except Exception:
        logger.exception("Unexpected error in /api/avatar/stop")
        raise HTTPException(status_code=500, detail="Internal server error")
    finally:
        sessions.pop(req.session_id, None)
