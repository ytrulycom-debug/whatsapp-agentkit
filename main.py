import os
import asyncio
import random
import httpx
from fastapi import FastAPI, Request, HTTPException, BackgroundTasks
from fastapi.responses import PlainTextResponse
import anthropic

app = FastAPI()

WEBHOOK_VERIFY_TOKEN = os.environ.get("WEBHOOK_VERIFY_TOKEN", "digsm2026")
WHATSAPP_ACCESS_TOKEN = os.environ.get("WHATSAPP_ACCESS_TOKEN", "")
WHATSAPP_PHONE_NUMBER_ID = os.environ.get("WHATSAPP_PHONE_NUMBER_ID", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-5")

anthropic_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

# Conversation history per user (in-memory)
conversation_store: dict[str, list] = {}

# Deduplication: track processed message IDs to avoid double processing
processed_message_ids: set = set()

SYSTEM_PROMPT = """Tu es l'assistant WhatsApp officiel de DigSM (Digital Success Method), la plateforme d'accompagnement académique de Nestor, fondateur de DigSM.

## QUI EST DIGSM
DigSM accompagne les étudiants et chercheurs francophones d'Afrique (et de la diaspora) dans la rédaction de leurs mémoires de Master, thèses de Doctorat et articles scientifiques. DigSM a déjà accompagné plus de 100 étudiants au Burkina Faso, Côte d'Ivoire, Sénégal, Niger, Togo, Bénin, Mali, RDC et en Europe. L'accompagnement est 100% en ligne.

## CE QUE FAIT DIGSM
- Accompagnement à la rédaction de mémoires de Master (toutes disciplines)
- Accompagnement à la rédaction de thèses de Doctorat
- Méthodologie de rédaction d'articles scientifiques (programme en 8 modules)
- Revue de littérature structurée (workflow DigSM avec outils IA : Zotero, ResearchRabbit, Elicit, Consensus, SciSpace)
- Intégration d'outils IA dans le processus de recherche académique

## RÈGLE ABSOLUE
Tu ne dois JAMAIS utiliser les expressions "clé en main", "rédaction complète" ou "on rédige à votre place". DigSM propose uniquement un ACCOMPAGNEMENT qui préserve le rôle d'auteur actif de l'étudiant. Si quelqu'un demande "est-ce que vous rédigez à ma place ?", réponds clairement que non : DigSM accompagne, guide et structure — mais l'étudiant reste l'auteur.

## TON RÔLE
Tu gères les conversations WhatsApp en 5 phases :

**PHASE 1 — ACCUEIL**
Accueille chaleureusement, présente DigSM en 2 phrases et demande ce qui amène le prospect.

**PHASE 2 — QUALIFICATION**
Pose ces 4 questions UNE PAR UNE (pas toutes en même temps) :
1. Quel est votre niveau d'études ? (Master ou Doctorat)
2. Quelle est votre discipline / domaine de recherche ?
3. Quelle est votre date de soutenance (ou deadline) ?
4. Quel est votre principal blocage en ce moment ? (rédaction, méthodologie, revue de littérature, manque de temps, autre ?)

**PHASE 3 — PRÉSENTATION CIBLÉE**
Une fois les 4 réponses obtenues, présente brièvement l'accompagnement DigSM adapté à leur profil. Sois concis et percutant. Mets en avant : la méthode structurée, les résultats concrets (100+ étudiants accompagnés), et le suivi personnalisé.

**PHASE 4 — ENGAGEMENT**
Invite le prospect à une consultation gratuite avec Nestor. Dis-leur que Nestor va les contacter personnellement pour discuter de leur situation et voir comment DigSM peut les aider.

**PHASE 5 — TRANSFERT**
Quand le prospect est qualifié (niveau Master ou Doctorat + discipline + deadline + blocage identifié) ET intéressé, dis exactement ceci :
"Parfait ! J'ai transmis votre profil à Nestor, le fondateur de DigSM. Il vous contactera très prochainement pour un échange personnalisé. En attendant, vous pouvez visiter notre site : academy.dsmethod.site 🎓"

## FAQ COURANTES
- "C'est quoi DigSM ?" → Digital Success Method : accompagnement académique pour étudiants francophones africains
- "Vous rédigez à ma place ?" → Non, DigSM accompagne — vous restez l'auteur de votre travail
- "Pour quelles disciplines ?" → Toutes les disciplines (sciences sociales, gestion, santé, droit, éducation, sciences, etc.)
- "C'est payant ?" → Oui, DigSM propose des formules d'accompagnement personnalisées. Nestor vous présentera les options lors de votre consultation.
- "Vous êtes où ?" → 100% en ligne — nous accompagnons des étudiants partout en Afrique francophone et en Europe
- "Ça dure combien de temps ?" → Dépend de votre situation. Nestor évaluera avec vous lors de la consultation gratuite.

## STYLE DE COMMUNICATION
- Toujours en français
- Ton chaleureux, professionnel et encourageant
- Messages courts (2-4 phrases max par message WhatsApp)
- Utilise des emojis sobrement (🎓 📚 ✅)
- Tutoiement ou vouvoiement selon le ton du prospect
- Ne réponds qu'à ce qui est demandé — ne surcharge pas le prospect d'informations"""


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
async def receive_message(request: Request, background_tasks: BackgroundTasks):
    """Receive WhatsApp messages — return 200 immediately, process in background"""
    body = await request.json()
    # Return 200 immediately so Meta doesn't retry and cause duplicate messages
    background_tasks.add_task(process_message, body)
    return {"status": "ok"}


async def process_message(body: dict):
    """Process incoming WhatsApp message and send AI reply"""
    try:
        entry = body.get("entry", [{}])[0]
        changes = entry.get("changes", [{}])[0]
        value = changes.get("value", {})
        messages = value.get("messages", [])

        if not messages:
            return

        message = messages[0]
        if message.get("type") != "text":
            return

        # Deduplication: skip if we already processed this message
        message_id = message.get("id", "")
        if message_id and message_id in processed_message_ids:
            print(f"Duplicate message ignored: {message_id}")
            return
        if message_id:
            processed_message_ids.add(message_id)
            # Keep the set from growing forever (keep last 1000 IDs)
            if len(processed_message_ids) > 1000:
                processed_message_ids.clear()

        sender_id = message["from"]
        text = message["text"]["body"]

        print(f"Message from {sender_id}: {text}")

        # Step 1: Mark message as read (shows blue checkmarks ✓✓ — like a human reading)
        if message_id:
            await mark_as_read(message_id)

        # Step 2: Human-like reading delay (2–5 sec, slightly longer for longer messages)
        reading_delay = random.uniform(2, 5) + min(len(text) / 150, 2)
        await asyncio.sleep(reading_delay)

        # Step 3: Generate AI response with conversation history
        history = conversation_store.get(sender_id, [])
        history.append({"role": "user", "content": text})

        response = anthropic_client.messages.create(
            model=ANTHROPIC_MODEL,
            max_tokens=400,
            system=SYSTEM_PROMPT,
            messages=history
        )

        ai_reply = response.content[0].text
        print(f"AI reply: {ai_reply}")

        # Update conversation history (keep last 30 messages)
        history.append({"role": "assistant", "content": ai_reply})
        conversation_store[sender_id] = history[-30:]

        # Step 4: Typing delay — proportional to reply length (simulates real typing)
        # ~40 characters per second typing speed, with some randomness
        typing_delay = random.uniform(1, 3) + len(ai_reply) / 40
        typing_delay = min(typing_delay, 8)  # cap at 8 seconds max
        await asyncio.sleep(typing_delay)

        # Step 5: Send reply
        await send_whatsapp_message(sender_id, ai_reply)

    except Exception as e:
        print(f"Error processing message: {e}")


async def mark_as_read(message_id: str):
    """Mark incoming message as read (shows blue checkmarks to the user)"""
    url = f"https://graph.facebook.com/v18.0/{WHATSAPP_PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "status": "read",
        "message_id": message_id
    }
    try:
        async with httpx.AsyncClient() as client:
            r = await client.post(url, headers=headers, json=payload)
            print(f"Mark as read: {r.status_code}")
    except Exception as e:
        print(f"Mark as read error: {e}")


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
        print(f"WhatsApp send status: {r.status_code} - {r.text}")


@app.get("/")
async def health():
    return {"status": "ok", "service": "DigSM WhatsApp Agent"}
