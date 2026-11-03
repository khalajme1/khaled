"""الإرسال على واتساب عن طريق Green API (green-api.com).

تربط رقمك بمسح QR من لوحة Green API (مثل واتساب ويب)، وبعدها نرسل الصورة.
"""
import os
from pathlib import Path

import requests


def send_photo(path: Path, caption: str = "") -> None:
    media_url = os.environ.get("GREEN_API_MEDIA_URL", "https://media.green-api.com").rstrip("/")
    instance = os.environ["GREEN_API_INSTANCE_ID"]
    token = os.environ["GREEN_API_TOKEN"]
    chat_ids = [c.strip() for c in os.environ["WHATSAPP_CHAT_ID"].split(",") if c.strip()]

    url = f"{media_url}/waInstance{instance}/sendFileByUpload/{token}"
    for chat_id in chat_ids:
        if "@" not in chat_id:  # رقم فقط مثل 96512345678
            chat_id = f"{chat_id.lstrip('+')}@c.us"
        with open(path, "rb") as f:
            r = requests.post(
                url,
                data={"chatId": chat_id, "caption": caption, "fileName": path.name},
                files={"file": (path.name, f, "image/png")},
                timeout=60,
            )
        r.raise_for_status()
        print(f"sent to WhatsApp {chat_id}: {r.text}")
