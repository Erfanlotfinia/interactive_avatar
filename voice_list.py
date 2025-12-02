# list_voices.py
import os
import requests
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("HEYGEN_API_KEY")
BASE_URL = "https://api.heygen.com"

if not API_KEY:
    raise RuntimeError("Set HEYGEN_API_KEY in your environment or .env file")

headers = {
    "X-Api-Key": API_KEY,
    "Content-Type": "application/json",
}

def list_voices():
    url = f"{BASE_URL}/v2/voices"
    resp = requests.get(url, headers=headers, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    # print('---------------- >>>', data)
    return data['data']['voices'] # according to docs

def main():
    voices = list_voices()
    print(f"Total voices: {len(voices)}\n")

    # Dump a compact view
    for v in voices:
        vid = v.get("voice_id")
        name = v.get("name") or v.get("display_name") or "N/A"
        language = v.get("language") or "N/A"
        supports_locale = v.get("support_locale")
        gender = v.get("gender") or "N/A"
        preview_audio = v.get("preview_audio") or "N/A"
        support_interactive_avatar = v.get("support_interactive_avatar") or "N/A"


        print(f"- voice_id: {vid}")
        print(f"  name    : {name}")
        print(f"  language  : {language}")
        print(f"  gender  : {gender}")
        print(f"preview_audio : {preview_audio}")
        print(f"support_interactive_avatar : {support_interactive_avatar}")
        if supports_locale:
            print(f"  support_locale: {supports_locale}")
        print()

if __name__ == "__main__":
    main()
