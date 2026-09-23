import os
import httpx
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import PlainTextResponse
import anthropic

app = FastAPI()

WEBHOOK_VERIFY_TOKEN = os.environ.get("WEBHOOK_VERIFY_TOKEN", "digsm2026")
WHATSAPP_ACCESS_TOKEN = os.environ.get("WHATSAPP_ACCESS_TOKEN", "")
WHATSAPP_PHONE_NUMBER_ID = os.environ.get("WHATSAPP_PHONE_NUMBER_ID", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-5")

anthropic_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

SYSTEM_PROMPT = """Tu es l'assistant IA de DigSM (Digital Success Method), une plateforme d'accompagnement académique pour les étudiants et chercheurs francophones africains.

Ton rôle est de :
1. Accueillir chaleureusement les prospects
2. Répondre aux questions sur l'accompagnement DigSM (aide à la rédaction de thèses, mémoires et articles scientifiques)
3. Qualifier les prospects en posant ces questions clés :
   - Quel est votre niveau d'études ? (Master ou Doctorat)
   - Quelle est votre discipline ?
   - Quelle est votre deadline de soutenance ?
   - Quel est votre principal blocage en ce moment ?
4. Une fois qualifié, informer le prospect que Nestor (le fondateur) va le contacter personnellement.

Sois chaleureux, professionnel et toujours en français. Garde tes réponses concises (2-3 phrases max par message WhatsApp)."""


@app.get("/webhook")
async def verify_webhook(request: Request):
    """Meta webhook verification endpoint"""
    mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")

    if mode == "subscribe" and token == WEBHOOK_VERIFY_TOKEN:
        return PlainTextResponse(content=challenge)

    raise HTTPException(status_code=403, detail="Forbidden")


@app.post("/webhook")
async def receive_message(request: Request):
    """Receive and process incoming WhatsApp messages"""
    body = await request.json()

    try:
        entry = body.get("entry", [{}])[0]
        changes = entry.get("changes", [{}])[0]
        value = changes.get("value", {})
        messages = value.get("messages", [])

        if not messages:
            return {"status": "ok"}

        message = messages[0]
        if message.get("type") != "text":
            return {"status": "ok"}

        sender_id = message["from"]
        text = message["text"]["body"]

        print(f"Message from {sender_id}: {text}")

        # Generate AI response
        response = anthropic_client.messages.create(
            model=ANTHROPIC_MODEL,
            max_tokens=500,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": text}]
        )

        ai_reply = response.content[0].text
        print(f"AI reply: {ai_reply}")

        # Send reply
        await send_whatsapp_message(sender_id, ai_reply)

    except Exception as e:
        print(f"Error: {e}")

    return {"status": "ok"}


async def send_whatsapp_message(to: str, text: str):
    """Send a WhatsApp message via Meta Cloud API"""
    url = f"https://graph.facebook.com/v18.0/{WHATSAPP_PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": text}
    }

    async with httpx.AsyncClient() as client:
        r = await client.post(url, headers=headers, json=payload)
        print(f"WhatsApp send status: {r.status_code}")


@app.get("/")
async def health():
    return {"status": "ok", "service": "DigSM WhatsApp Agent"}
