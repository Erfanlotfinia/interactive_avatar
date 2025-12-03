"""
HEYGEN STREAMING AVATAR – LOCAL DEMO SCRIPT (multi-lang: fa, en, zh)

What it does:
1. Reads HEYGEN_API_KEY from environment.
2. Chooses avatar/voice based on DEFAULT_LANG in .env:
   - DEFAULT_LANG=fa    -> FA_AVATAR_ID / FA_VOICE_ID
   - DEFAULT_LANG=eng   -> EN_AVATAR_ID / EN_VOICE_ID
   - DEFAULT_LANG=china -> ZH_AVATAR_ID / ZH_VOICE_ID
   Fallbacks:
     - AVATAR_ID / VOICE_ID
     - auto: first streaming avatar.

3. Creates a HeyGen streaming session (avatar + optional voice).
4. Opens a local HTML page that connects to LiveKit (video/audio).
5. Sends a static text message (language-dependent) so the avatar reads it.

Example .env:

    HEYGEN_API_KEY=your-key
    DEFAULT_LANG=fa

    FA_AVATAR_ID=...
    FA_VOICE_ID=...

    EN_AVATAR_ID=...
    EN_VOICE_ID=...

    ZH_AVATAR_ID=...
    ZH_VOICE_ID=...

    # Optional overrides:
    # AVATAR_ID=...
    # VOICE_ID=...
    # DEMO_TEXT=custom text...
"""

import os
import json
import time
import tempfile
import webbrowser
from typing import Optional, Dict, Any, List, Tuple

import requests
from dotenv import load_dotenv

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
        """
        Returns list of streaming-capable avatars.
        """
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
        # should contain: session_id, url, access_token
        return data["data"]

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
        task_type: str = "repeat",   # verbatim TTS
        task_mode: str = "async",
    ) -> Dict[str, Any]:
        """
        task_type:
          - "repeat" -> avatar repeats EXACTLY the given text
          - "chat"   -> avatar uses its own LLM / KB to answer

        task_mode:
          - "sync" or "async" (async returns immediately, avatar streams via LiveKit)
        """
        url = f"{self.base_url}/v1/streaming.task"
        payload = {
            "session_id": session_id,
            "text": text,
            "task_type": task_type,
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


def normalize_lang(env_value: str) -> str:
    """
    Map various env values to canonical language codes:
    - "fa", "fa-ir", "persian" -> "fa"
    - "en", "eng", "en-us", "en-gb" -> "en"
    - "zh", "cn", "china", "chinese" -> "zh"
    """
    v = (env_value or "").strip().lower()
    if v in ("fa", "fa-ir", "persian"):
        return "fa"
    if v in ("en", "eng", "en-us", "en-gb", "english"):
        return "en"
    if v in ("zh", "cn", "china", "chinese", "zh-cn", "zh-hans"):
        return "zh"
    # default fallback
    return "en"


def resolve_avatar_voice_from_env(lang: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Choose avatar_id / voice_id according to DEFAULT_LANG.
    Returns (avatar_id_env, voice_id_env) which may be None.
    """
    avatar_id_env = None
    voice_id_env = None

    if lang == "fa":
        avatar_id_env = os.getenv("FA_AVATAR_ID")
        voice_id_env = os.getenv("FA_VOICE_ID")
    elif lang == "en":
        avatar_id_env = os.getenv("EN_AVATAR_ID")
        voice_id_env = os.getenv("EN_VOICE_ID")
    elif lang == "zh":
        avatar_id_env = os.getenv("ZH_AVATAR_ID")
        voice_id_env = os.getenv("ZH_VOICE_ID")

    # Fallback to generic env vars if language-specific ones are not set
    if not avatar_id_env:
        avatar_id_env = os.getenv("AVATAR_ID")
    if not voice_id_env:
        voice_id_env = os.getenv("VOICE_ID")

    return avatar_id_env, voice_id_env


def build_livekit_viewer_html(livekit_url: str, access_token: str, lang: str) -> str:
    """
    Minimal HTML that connects to LiveKit and shows the avatar video.
    Uses livekit-client UMD build from CDN.
    lang: "fa", "en", or "zh" (for <html lang="..."> tag)
    """
    html_lang = "fa" if lang == "fa" else ("zh" if lang == "zh" else "en")

    if lang == "fa":
        title = "دموی آواتار HeyGen"
        heading = "دموی آواتار استریمینگ"
    elif lang == "zh":
        title = "HeyGen 虚拟形象演示"
        heading = "HeyGen 实时虚拟形象演示"
    else:
        title = "HeyGen Avatar Streaming Demo"
        heading = "HeyGen Streaming Avatar Demo"

    return f"""<!DOCTYPE html>
<html lang="{html_lang}">
<head>
  <meta charset="UTF-8" />
  <title>{title}</title>
  <style>
    body {{
      background: #111;
      color: #eee;
      font-family: sans-serif;
      display: flex;
      flex-direction: column;
      align-items: center;
      padding-top: 20px;
    }}
    video {{
      width: 480px;
      height: 270px;
      background: #000;
    }}
    button {{
      margin-top: 12px;
      padding: 8px 16px;
      font-size: 14px;
      cursor: pointer;
    }}
  </style>
  <script src="https://unpkg.com/livekit-client/dist/livekit-client.umd.js"></script>
</head>
<body>
  <h2>{heading}</h2>
  <video id="avatar-video" autoplay playsinline></video>
  <button id="connect-btn">Connect to Avatar</button>
  <pre id="status"></pre>

  <script>
    const livekitUrl = "{livekit_url}";
    const accessToken = "{access_token}";

    const statusEl = document.getElementById("status");
    const videoEl = document.getElementById("avatar-video");
    const btn = document.getElementById("connect-btn");

    let room = null;
    let mediaStream = new MediaStream();

    async function connect() {{
      try {{
        statusEl.textContent = "Connecting...";
        const {{ Room, RoomEvent }} = LivekitClient;

        room = new Room();

        room.on(RoomEvent.TrackSubscribed, (track, publication, participant) => {{
          console.log("Track subscribed:", track.kind);
          if (!videoEl.srcObject) {{
            videoEl.srcObject = mediaStream;
          }}
          mediaStream.addTrack(track.mediaStreamTrack);
        }});

        room.on(RoomEvent.Disconnected, () => {{
          statusEl.textContent = "Disconnected";
        }});

        await room.connect(livekitUrl, accessToken);
        statusEl.textContent = "Connected. Waiting for avatar media...";
      }} catch (e) {{
        console.error(e);
        statusEl.textContent = "Error: " + e;
      }}
    }}

    btn.addEventListener("click", () => {{
      if (!room) {{
        connect();
      }}
    }});
  </script>
</body>
</html>
"""


def get_demo_text(lang: str) -> str:
    """
    Decide what text the avatar should read.

    Priority:
      1) DEMO_TEXT env var (can be any language)
      2) Default text based on lang ("fa", "en", "zh")
    """
    demo_text_env = os.getenv("DEMO_TEXT")
    if demo_text_env:
        return demo_text_env

    if lang == "fa":
        return (
            "سلام، این یک پیام آزمایشی از یک اسکریپت پایتون است. "
            "من یک آواتار هوشمند هستم که متن تولید شده توسط برنامهٔ شما را می‌خوانم."
        )
    if lang == "zh":
        return (
            "你好，这是一条来自 Python 脚本的演示消息。"
            "我是一个实时虚拟形象，正在朗读你的应用程序生成的文本。"
        )

    # default English
    return (
        "Hello, this is a demo message from a Python script. "
        "I am a streaming AI avatar reading text generated by your application."
    )


def main():
    load_dotenv()

    api_key = os.getenv("HEYGEN_API_KEY")
    raw_default_lang = os.getenv("DEFAULT_LANG", "en")
    lang = normalize_lang(raw_default_lang)

    if not api_key:
        raise RuntimeError("HEYGEN_API_KEY env var is required")

    client = HeyGenStreamingClient(api_key)

    # Resolve avatar/voice based on lang
    avatar_id_env, voice_id = resolve_avatar_voice_from_env(lang)

    # If avatar_id still not set, pick first streaming avatar
    if avatar_id_env:
        avatar_id = avatar_id_env
        print(f"Using avatar from env for lang={lang}: {avatar_id}")
    else:
        print("[*] No language-specific AVATAR_ID set, fetching streaming avatars...")
        avatars = client.list_streaming_avatars()
        if not avatars:
            raise RuntimeError("No streaming avatars returned from HeyGen.")
        first = avatars[0]
        avatar_id = first.get("avatar_id") or first.get("id")
        if not avatar_id:
            raise RuntimeError("Could not find avatar_id in first avatar object.")
        print(f"[+] Using first streaming avatar: {avatar_id}")

    print("=== HeyGen Streaming Avatar Local Demo ===")
    print(f"DEFAULT_LANG={lang} (raw='{raw_default_lang}')")
    print(f"AVATAR_ID={avatar_id}")
    print(f"VOICE_ID={voice_id or 'default'}\n")

    # 1) Create per-session token
    print("[*] Creating streaming session token...")
    session_token = client.create_session_token()
    print(f"[+] Session token: {session_token[:8]}... (hidden)")

    # 2) Create streaming session
    print("[*] Creating streaming session with avatar...")
    session_info = client.new_session(
        session_token=session_token,
        avatar_id=avatar_id,
        voice_id=voice_id,
    )

    session_id = session_info["session_id"]
    livekit_url = session_info["url"]
    access_token = session_info["access_token"]

    print(f"[+] Session created: {session_id}")
    print(f"    LiveKit URL: {livekit_url}")
    print("    Access token: (hidden)")
    print()

    # 3) Start session
    print("[*] Starting streaming session...")
    client.start_session(session_token, session_id)
    print("[+] Streaming started.\n")

    # 4) Create local HTML viewer and open in browser
    html = build_livekit_viewer_html(livekit_url, access_token, lang)
    tmp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".html")
    tmp_file.write(html.encode("utf-8"))
    tmp_file.flush()
    tmp_path = tmp_file.name
    tmp_file.close()

    print(f"[*] Opening LiveKit viewer in browser: {tmp_path}")
    webbrowser.open(f"file://{tmp_path}")

    # Give the browser time to connect (and you time to click "Connect to Avatar")
    wait_for_connect = 5
    print(f"[*] Waiting {wait_for_connect} seconds before sending text to avatar...")
    time.sleep(wait_for_connect)

    # 5) Send demo text based on lang
    demo_text = get_demo_text(lang)
    print("[*] Sending demo text to avatar:")
    print(f'    "{demo_text}"\n')

    resp = client.send_task(
        session_token=session_token,
        session_id=session_id,
        text=demo_text,
        task_type="repeat",
        task_mode="async",
    )
    print(f"[+] Task accepted by HeyGen: {resp}\n")
    print(">>> In the browser, click 'Connect to Avatar' and you should see and hear it reading this text.")

    # Leave the session alive for a bit so you can watch/listen
    try:
        wait_seconds = 60
        print(f"\n[*] Keeping session alive for ~{wait_seconds} seconds...")
        time.sleep(wait_seconds)
    finally:
        print("\n[*] Stopping session...")
        client.stop_session(session_token, session_id)
        print("[+] Session stopped. Demo finished.")


if __name__ == "__main__":
    main()
