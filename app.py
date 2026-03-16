import os
import re
import requests
from fastapi import FastAPI, Request, HTTPException

app = FastAPI()

BOT_TOKEN = os.getenv("BOT_TOKEN")
AWIN_TOKEN = os.getenv("AWIN_TOKEN")
PUBLISHER_ID = os.getenv("PUBLISHER_ID", "731446")
ADVERTISER_ID = int(os.getenv("ADVERTISER_ID", "11640"))
TARGET_CHAT_ID = os.getenv("TARGET_CHAT_ID", "@solochollos10")
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL") or (
    f"https://{os.getenv('RAILWAY_PUBLIC_DOMAIN')}"
    if os.getenv("RAILWAY_PUBLIC_DOMAIN")
    else None
)

TG_API = f"https://api.telegram.org/bot{BOT_TOKEN}"
AWIN_API = f"https://api.awin.com/publishers/{PUBLISHER_ID}/linkbuilder/generate"

URL_RE = re.compile(r"https?://[^\s<>\"]+")

def telegram(method, data):
    r = requests.post(f"{TG_API}/{method}", json=data, timeout=30)
    r.raise_for_status()
    return r.json()

def extract_urls(text):
    if not text:
        return []
    return URL_RE.findall(text)

def is_aliexpress_url(url):
    u = url.lower()
    return (
        "aliexpress.com/" in u
        or "es.aliexpress.com/" in u
        or "a.aliexpress.com/" in u
    )

def is_affiliate_or_short(url):
    u = url.lower()
    return "tidd.ly/" in u or "awin1.com/" in u

def generate_awin_short_url(destination_url):
    headers = {
        "Authorization": f"Bearer {AWIN_TOKEN}",
        "Content-Type": "application/json",
    }
    params = {
        "accessToken": AWIN_TOKEN
    }
    payload = {
        "advertiserId": ADVERTISER_ID,
        "destinationUrl": destination_url,
        "shorten": True
    }

    r = requests.post(AWIN_API, headers=headers, params=params, json=payload, timeout=30)
    r.raise_for_status()
    data = r.json()

    short_url = data.get("shortUrl")
    long_url = data.get("url")

    if not short_url and not long_url:
        raise ValueError(f"No se pudo generar enlace Awin: {data}")

    return short_url or long_url

def replace_aliexpress_links(text):
    urls = extract_urls(text)
    if not urls:
        return text, False

    changed = False
    new_text = text

    for url in urls:
        if is_affiliate_or_short(url):
            continue
        if is_aliexpress_url(url):
            short_url = generate_awin_short_url(url)
            new_text = new_text.replace(url, short_url)
            changed = True

    return new_text, changed

def set_webhook():
    if not PUBLIC_BASE_URL:
        return
    webhook_url = f"{PUBLIC_BASE_URL}/telegram/webhook"
    telegram("setWebhook", {"url": webhook_url})

@app.on_event("startup")
def on_startup():
    if BOT_TOKEN and PUBLIC_BASE_URL:
        try:
            set_webhook()
        except Exception as e:
            print("Webhook error:", e)

@app.get("/")
def health():
    return {"ok": True}

@app.post("/telegram/webhook")
async def telegram_webhook(request: Request):
    update = await request.json()

    post = update.get("channel_post") or update.get("message")
    if not post:
        return {"ok": True}

    chat = post.get("chat", {})
    chat_id = str(chat.get("id"))
    chat_username = f"@{chat.get('username')}" if chat.get("username") else None
    message_id = post.get("message_id")
    text = post.get("text") or post.get("caption") or ""

    target_ok = TARGET_CHAT_ID in {chat_id, chat_username}
    if not target_ok:
        return {"ok": True}

    if not text:
        return {"ok": True}

    if "tidd.ly/" in text or "awin1.com/" in text:
        return {"ok": True}

    try:
        new_text, changed = replace_aliexpress_links(text)
        if not changed:
            return {"ok": True}

        telegram("deleteMessage", {
            "chat_id": TARGET_CHAT_ID,
            "message_id": message_id
        })

        telegram("sendMessage", {
            "chat_id": TARGET_CHAT_ID,
            "text": new_text,
            "disable_web_page_preview": False
        })

        return {"ok": True}
    except Exception as e:
        print("Processing error:", e)
        return {"ok": False, "error": str(e)}
