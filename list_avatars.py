import os
import requests
import csv
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


def list_streaming_avatars():
    """
    Calls /v1/streaming/avatar.list and returns the avatar list.
    According to HeyGen docs, response shape is roughly:
      { "code": 100, "message": "success", "data": [ { avatar fields... }, ... ] }
    """
    url = f"{BASE_URL}/v1/streaming/avatar.list"
    resp = requests.get(url, headers=headers, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    return data["data"]


def save_to_csv(avatars, filename="avatars.csv"):
    """
    Save avatar list to CSV.
    We pick a set of common / useful fields. Missing ones become "N/A".
    Adjust fieldnames if you see more interesting keys in your data.
    """
    fieldnames = [
        "avatar_id",
        "default_voice",
        "is_public",
        "normal_preview",
        'pose_name',
        "status",
    ]

    with open(filename, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        for a in avatars:
            writer.writerow({
                "avatar_id": a.get("avatar_id") or a.get("id"),
                "default_voice": a.get("default_voice") or "N/A",
                "is_public": a.get("is_public") or "N/A",
                "normal_preview": a.get("normal_preview") or "N/A",
                "pose_name": a.get("pose_name") or "N/A",
                "status": a.get("status") or "N/A",
            })

    print(f"[+] Saved CSV file: {filename}\n")


def main():
    avatars = list_streaming_avatars()
    print(f"Total streaming avatars: {len(avatars)}\n")

    # Save to CSV
    save_to_csv(avatars)

    # Dump compact view in console
    # for a in avatars:
    #     avatar_id = a.get("avatar_id") or a.get("id")
    #     name = a.get("name") or "N/A"
    #     description = a.get("description") or "N/A"
    #     gender = a.get("gender") or "N/A"
    #     avatar_type = a.get("type") or "N/A"
    #     language = a.get("language") or "N/A"
    #     cover = a.get("cover") or a.get("cover_image") or "N/A"
    #     support_interactive = a.get("support_interactive_avatar", "N/A")

    #     print(f"- avatar_id : {avatar_id}")
    #     print(f"  name      : {name}")
    #     print(f"  type      : {avatar_type}")
    #     print(f"  gender    : {gender}")
    #     print(f"  language  : {language}")
    #     print(f"  cover     : {cover}")
    #     print(f"  support_interactive_avatar : {support_interactive}")
    #     if description and description != "N/A":
    #         print(f"  description: {description}")
    #     print()


if __name__ == "__main__":
    main()
