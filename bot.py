# Davud's Telegram buddy — a simple AI agent in one file.
#
# WHAT IT CAN DO:
#   • chat like a friendly human (and call the user "Davud")
#   • look at photos you send
#   • answer price questions (from the PRICES list below)
#   • send you a human-sounding weather heads-up each morning  (/testweather to try now)
#   • relay a message to a friend and bring their reply back    (/ask  Name | message)
#   • send an email on your behalf, with a confirm step         (/email to | subject | body)
#
# HOW TO RUN (locally):
#   1) pip install -r requirements.txt
#   2) copy .env.example to .env and fill in your keys
#   3) python bot.py
# On Replit: just add the Secrets (below) and press Run.
#
# SECRETS / .env keys:
#   TELEGRAM_TOKEN, GEMINI_API_KEY            (required)
#   Email (optional) — pick ONE way:
#     easy:  RESEND_API_KEY  (+ EMAIL_FROM on a verified domain)
#     or:    SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, EMAIL_FROM
#   ALLOWED_EMAILS  (optional allowlist; blank = send to anyone)

import os
import json
import asyncio
import smtplib
import datetime
from email.message import EmailMessage
from zoneinfo import ZoneInfo

import requests
from dotenv import load_dotenv
from google import genai
from google.genai import types
from telegram import Update
from telegram.ext import (
    Application, CommandHandler, MessageHandler, ContextTypes, filters,
)

# ---------- things you can edit ----------
CITY = "Istanbul"                         # city for the morning weather heads-up
TIMEZONE = "Europe/Istanbul"              # so the morning message fires at local 07:30
PRICES = {                                # the bot answers "how much...?" from this list
    "haircut": "300 TL",
    "hair coloring": "800 TL",
}
MODEL = "gemini-3.8-flash"                # the AI brain (free tier is fine)
# -----------------------------------------

load_dotenv()
TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]

# Email settings (optional — the bot still works without them).
# Two ways to send: the Resend API (easiest — one key) OR SMTP (needs an app password).
RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "")
SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
# Who the email is "from". For Resend you need a verified-domain address (e.g. bot@yourdomain);
# the shared tester "onboarding@resend.dev" only delivers to your own Resend account email.
EMAIL_FROM = (os.environ.get("EMAIL_FROM", "").strip()
              or SMTP_USER
              or ("onboarding@resend.dev" if RESEND_API_KEY else ""))
ALLOWED_EMAILS = [e.strip().lower() for e in os.environ.get("ALLOWED_EMAILS", "").split(",") if e.strip()]
EMAIL_READY = bool(RESEND_API_KEY or (SMTP_USER and SMTP_PASSWORD))

client = genai.Client(api_key=GEMINI_API_KEY)

# The agent's personality and rules (its "system prompt").
price_lines = "\n".join(f"- {name}: {price}" for name, price in PRICES.items())
SYSTEM_PROMPT = f"""You are a warm, friendly assistant texting with a person named Davud.
Talk in a natural, human way: short messages, casual, at most one emoji. Always address him
as "Davud". Be kind and encouraging.

If Davud asks whether you are an AI or a real person, answer honestly that you are an AI helper.

You know these prices and can answer "how much does it cost?" questions:
{price_lines}
If he asks about something not on the list, say you're not sure of that price.

You have tools you can use:
- draft_email: when Davud asks you to send or write an email to someone, call draft_email with
  the recipient's address, a short subject, and the message. It does NOT send right away — after
  drafting, show Davud the recipient, subject and message, and ask him to reply "yes" to send or
  "no" to cancel.
- send_to_friend: when Davud asks you to message or ask a friend something, call send_to_friend
  with the friend's name and the message. It sends on Telegram right away (if that friend has
  opened the bot), and their reply comes back to Davud.
- check_weather: when Davud asks about the weather or what to wear, call check_weather with the city.

Keep replies brief and friendly, like a real text conversation."""

# ---------- saved data (survives restarts) ----------
PEOPLE_FILE = "people.json"   # everyone who has opened the bot: name -> chat id


def load_people() -> dict:
    try:
        with open(PEOPLE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_people() -> None:
    try:
        with open(PEOPLE_FILE, "w", encoding="utf-8") as f:
            json.dump(people, f, ensure_ascii=False)
    except OSError:
        pass


people: dict = load_people()   # { "<chat_id>": {"name": "...", "username": "..."} }

# ---------- in-memory state (fine to lose on restart) ----------
history: dict[int, list] = {}          # short chat memory per person
awaiting_reply: dict[int, tuple] = {}  # recipient_chat_id -> (sender_chat_id, sender_name)
pending_email: dict[int, dict] = {}    # chat_id -> {"to","subject","body"} waiting for /yes
pending_relay: dict[int, dict] = {}    # chat_id -> {"target","name","message"} queued by the AI


def register_person(update: Update) -> None:
    """Remember anyone who talks to the bot, so we can find them by name later."""
    user = update.effective_user
    cid = str(update.effective_chat.id)
    name = (user.first_name or user.username or "friend").strip()
    people[cid] = {"name": name, "username": (user.username or "")}
    save_people()


def find_chat_by_name(name: str):
    """Look up a person's chat id by their first name or @username (case-insensitive)."""
    key = name.strip().lstrip("@").lower()
    for cid, info in people.items():
        if info["name"].lower() == key or info["username"].lower() == key:
            return int(cid)
    return None


# ---------- the AI + network calls (blocking, so we run them in a thread) ----------

def ask_gemini(chat_id: int, user_text: str) -> str:
    """Reply to a text message, remembering recent turns and letting the AI use tools."""
    turns = history.setdefault(chat_id, [])
    turns.append({"role": "user", "text": user_text})
    turns[:] = turns[-10:]
    contents = [
        types.Content(role=t["role"], parts=[types.Part.from_text(text=t["text"])])
        for t in turns
    ]

    # ----- tools the AI can choose to call (they capture THIS chat's id) -----
    def draft_email(to: str, subject: str, body: str) -> str:
        """Draft an email for Davud to send. Use this whenever he asks to send or write an
        email to someone. The email is NOT sent yet — it is staged for Davud to confirm."""
        if not EMAIL_READY:
            return "Email is not set up, so you can't send one. Let Davud know."
        if ALLOWED_EMAILS and to.lower() not in ALLOWED_EMAILS:
            return f"Not allowed to email {to}. You may only email: {', '.join(ALLOWED_EMAILS)}."
        pending_email[chat_id] = {"to": to, "subject": subject, "body": body}
        return (f"Email drafted to {to}, subject '{subject}'. Now show Davud the recipient, "
                f"subject and message, then ask him to reply 'yes' to send or 'no' to cancel.")

    def send_to_friend(name: str, message: str) -> str:
        """Send a Telegram message to one of Davud's friends by name. Use when Davud asks to
        message or ask a friend something. It sends right away and the friend's reply returns."""
        target = find_chat_by_name(name)
        if target is None:
            return (f"{name} hasn't opened the bot yet, so you can't message them. Tell Davud that "
                    f"{name} needs to open the bot and press Start first.")
        if target == chat_id:
            return "That's Davud himself — ask him which friend he means."
        pending_relay[chat_id] = {"target": target, "name": name, "message": message}
        return f"Message queued for {name}. Tell Davud you've sent it and will bring the reply back."

    def check_weather(city: str) -> str:
        """Get today's weather for a city. Use when Davud asks about the weather or what to wear."""
        try:
            d = get_weather(city)
            return f"{d['city']}: high {d['temp_max']}C, low {d['temp_min']}C, rain chance {d['rain_chance']}%."
        except Exception:
            return "Couldn't get the weather right now."

    config = types.GenerateContentConfig(
        system_instruction=SYSTEM_PROMPT, temperature=0.8,
        tools=[draft_email, send_to_friend, check_weather],
    )
    resp = client.models.generate_content(model=MODEL, contents=contents, config=config)
    reply = (resp.text or "").strip() or "Hmm, I didn't catch that — say it again?"
    turns.append({"role": "model", "text": reply})
    return reply


def ask_gemini_about_photo(image_bytes: bytes, caption: str) -> str:
    question = caption.strip() or "Davud sent you this photo. React warmly and briefly, and say what you see."
    contents = [types.Content(role="user", parts=[
        types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"),
        types.Part.from_text(text=question),
    ])]
    resp = client.models.generate_content(
        model=MODEL, contents=contents,
        config=types.GenerateContentConfig(system_instruction=SYSTEM_PROMPT, temperature=0.7),
    )
    return (resp.text or "").strip() or "Nice photo, Davud! 📷"


def get_weather(city: str) -> dict:
    """Today's weather for a city, from the free Open-Meteo API (no key needed)."""
    geo = requests.get("https://geocoding-api.open-meteo.com/v1/search",
                       params={"name": city, "count": 1}, timeout=15).json()
    place = geo["results"][0]
    fc = requests.get("https://api.open-meteo.com/v1/forecast", params={
        "latitude": place["latitude"], "longitude": place["longitude"],
        "daily": "precipitation_probability_max,temperature_2m_max,temperature_2m_min",
        "timezone": "auto",
    }, timeout=15).json()
    d = fc["daily"]
    return {"city": city, "temp_max": d["temperature_2m_max"][0],
            "temp_min": d["temperature_2m_min"][0], "rain_chance": d["precipitation_probability_max"][0]}


def human_weather_line(data: dict) -> str:
    prompt = (f"Write ONE short, warm, human text to Davud about today's weather in {data['city']}. "
              f"High {data['temp_max']}°C, low {data['temp_min']}°C, rain chance {data['rain_chance']}%. "
              f"Mention taking an umbrella only if rain chance is 50% or more. "
              f"Under 25 words, casual, at most one emoji.")
    try:
        resp = client.models.generate_content(model=MODEL, contents=prompt,
                                               config=types.GenerateContentConfig(temperature=0.9))
        line = (resp.text or "").strip()
        if line:
            return line
    except Exception:
        pass
    umbrella = " Take an umbrella ☔" if data["rain_chance"] >= 50 else ""
    return f"Morning Davud! Around {data['temp_max']}°C today in {data['city']}.{umbrella}"


def send_email_resend(to: str, subject: str, body: str) -> None:
    """Send email via the Resend API — just needs RESEND_API_KEY (no app password)."""
    r = requests.post(
        "https://api.resend.com/emails",
        headers={"Authorization": f"Bearer {RESEND_API_KEY}", "Content-Type": "application/json"},
        json={"from": EMAIL_FROM, "to": [to], "subject": subject, "text": body},
        timeout=20,
    )
    if r.status_code >= 300:
        raise RuntimeError(f"Resend error {r.status_code}: {r.text}")


def send_email_smtp(to: str, subject: str, body: str) -> None:
    """Send a plain-text email over SMTP (e.g. Gmail/Yandex with an App Password)."""
    msg = EmailMessage()
    msg["From"] = EMAIL_FROM
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    if SMTP_PORT == 465:
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=20) as s:
            s.login(SMTP_USER, SMTP_PASSWORD)
            s.send_message(msg)
    else:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=20) as s:
            s.starttls()
            s.login(SMTP_USER, SMTP_PASSWORD)
            s.send_message(msg)


def send_email(to: str, subject: str, body: str) -> None:
    """Send using whatever is configured: Resend if a key is set, otherwise SMTP."""
    if RESEND_API_KEY:
        send_email_resend(to, subject, body)
    elif SMTP_USER and SMTP_PASSWORD:
        send_email_smtp(to, subject, body)
    else:
        raise RuntimeError("No email method configured")


# ---------- Telegram command handlers ----------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    register_person(update)
    await update.message.reply_text(
        "Hey Davud! 👋 I'm here whenever you need me. Ask me anything, send a photo, "
        "or type /help to see what I can do.")


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    register_person(update)
    await update.message.reply_text(
        "Here's what I can do:\n"
        "• Just chat with me 💬\n"
        "• Send me a photo 📷\n"
        "• Ask about prices (e.g. \"how much is a haircut?\")\n"
        "• Ask me to email someone (e.g. \"email pat@x.com that I'll be late\") — I draft it and you confirm 📧\n"
        "• Ask about the weather or what to wear 🌦️\n"
        "• Ask me to message a friend (e.g. \"ask Ayten if she's free\") — I send it and bring back the reply 📨\n"
        "• /who  — see which friends I know\n"
        "• /ask Name | message  — the manual way to message a friend\n"
        "• /email address | subject | message  — the manual way to draft an email\n"
        "• /testweather  — get the morning-style weather now")


async def who(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    register_person(update)
    names = sorted({info["name"] for info in people.values()})
    if names:
        await update.message.reply_text("People who've opened me:\n• " + "\n• ".join(names) +
                                        "\n\nMessage one with:  /ask Name | your message")
    else:
        await update.message.reply_text("No one yet — ask your friend to open me and press Start first.")


async def ask(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Relay a message to a friend. Their next reply comes back to the sender."""
    register_person(update)
    chat_id = update.effective_chat.id
    payload = update.message.text.partition(" ")[2]
    if "|" not in payload:
        await update.message.reply_text("Try:  /ask Name | your message\n(See /who for who I know.)")
        return
    name, _, message = payload.partition("|")
    name, message = name.strip(), message.strip()
    target = find_chat_by_name(name)
    if target is None:
        await update.message.reply_text(
            f"I don't know anyone called \"{name}\" yet. They need to open me and press Start first. "
            f"(Type /who to see who I know.)")
        return
    if target == chat_id:
        await update.message.reply_text("That's you 😄 — pick a friend who has opened me.")
        return
    sender_name = people[str(chat_id)]["name"]
    try:
        await context.bot.send_message(
            target,
            f"📩 {sender_name} asks:\n\n{message}\n\n(Just reply here and I'll send your answer back.)")
    except Exception:
        await update.message.reply_text(f"Hmm, I couldn't reach {name} right now 😕")
        return
    awaiting_reply[target] = (chat_id, sender_name)
    await update.message.reply_text(f"Sent to {name}. I'll bring their reply back to you. 📨")


async def email_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Draft an email and ask the user to confirm before sending."""
    register_person(update)
    chat_id = update.effective_chat.id
    if not EMAIL_READY:
        await update.message.reply_text("Email isn't set up yet — ask the teacher to add the SMTP secrets.")
        return
    payload = update.message.text.partition(" ")[2]
    parts = [p.strip() for p in payload.split("|", 2)]
    if len(parts) < 3 or not all(parts):
        await update.message.reply_text("Try:  /email address | subject | message")
        return
    to, subject, body = parts
    if ALLOWED_EMAILS and to.lower() not in ALLOWED_EMAILS:
        await update.message.reply_text(f"I'm only allowed to email: {', '.join(ALLOWED_EMAILS)}")
        return
    pending_email[chat_id] = {"to": to, "subject": subject, "body": body}
    await update.message.reply_text(
        f"📧 Ready to send:\n\nTo: {to}\nSubject: {subject}\n\n{body}\n\n"
        f"Reply /yes to send, or /no to cancel.")


async def yes(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    e = pending_email.pop(chat_id, None)
    if not e:
        await update.message.reply_text("Nothing to confirm right now.")
        return
    try:
        await asyncio.to_thread(send_email, e["to"], e["subject"], e["body"])
        await update.message.reply_text(f"Sent to {e['to']} ✅")
    except Exception as ex:
        print("EMAIL ERROR:", repr(ex))   # shows the real reason in the Replit console
        await update.message.reply_text("Couldn't send that one 😕 — check the console for the reason (often the mail server blocking SMTP login).")


async def no(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if pending_email.pop(update.effective_chat.id, None):
        await update.message.reply_text("Okay, cancelled. 👍")
    else:
        await update.message.reply_text("Nothing to cancel.")


async def testweather(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    register_person(update)
    await send_morning(context)


# ---------- message handlers ----------

async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    register_person(update)
    text = update.message.text

    # If this person owes a reply to a relayed message, pass it back to the sender.
    if chat_id in awaiting_reply:
        sender_id, sender_name = awaiting_reply.pop(chat_id)
        my_name = people[str(chat_id)]["name"]
        try:
            await context.bot.send_message(sender_id, f"💬 {my_name} replied:\n\n{text}")
            await update.message.reply_text(f"Got it — I passed your reply back to {sender_name}. ✅")
        except Exception:
            await update.message.reply_text("I couldn't deliver that reply 😕")
        return

    # If an email draft is waiting, a plain "yes"/"no" sends or cancels it.
    if chat_id in pending_email:
        low = text.strip().lower()
        if low in ("yes", "y", "yep", "yeah", "send", "send it", "ok", "okay", "go", "do it", "evet"):
            e = pending_email.pop(chat_id)
            await context.bot.send_chat_action(chat_id, "typing")
            try:
                await asyncio.to_thread(send_email, e["to"], e["subject"], e["body"])
                await update.message.reply_text(f"Sent to {e['to']} ✅")
            except Exception as ex:
                print("EMAIL ERROR:", repr(ex))
                await update.message.reply_text("Couldn't send that one 😕 — check the console for the reason.")
            return
        if low in ("no", "n", "nope", "cancel", "stop", "hayır"):
            pending_email.pop(chat_id, None)
            await update.message.reply_text("Okay, cancelled. 👍")
            return

    # Otherwise it's a normal chat with the AI (which may use tools).
    await context.bot.send_chat_action(chat_id, "typing")
    try:
        reply = await asyncio.to_thread(ask_gemini, chat_id, text)
    except Exception as ex:
        print("CHAT ERROR:", repr(ex))   # shows the real reason (e.g. bad Gemini key) in the console
        reply = "Oops, my brain hiccuped 😅 try again?"

    # If the AI queued a message to a friend, actually send it now.
    relay = pending_relay.pop(chat_id, None)
    if relay:
        sender_name = people[str(chat_id)]["name"]
        try:
            await context.bot.send_message(
                relay["target"],
                f"📩 {sender_name} asks:\n\n{relay['message']}\n\n(Just reply here and I'll send your answer back.)")
            awaiting_reply[relay["target"]] = (chat_id, sender_name)
        except Exception as ex:
            print("RELAY ERROR:", repr(ex))
            reply += "\n\n(Hmm, I couldn't reach them just now 😕)"

    await update.message.reply_text(reply)


async def on_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    register_person(update)
    await context.bot.send_chat_action(chat_id, "typing")
    try:
        photo = update.message.photo[-1]
        tg_file = await photo.get_file()
        img_bytes = bytes(await tg_file.download_as_bytearray())
        reply = await asyncio.to_thread(ask_gemini_about_photo, img_bytes, update.message.caption or "")
    except Exception as ex:
        print("PHOTO ERROR:", repr(ex))
        reply = "Hmm, I couldn't open that photo 😅 mind sending it again?"
    await update.message.reply_text(reply)


async def send_morning(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Runs automatically each morning (and from /testweather)."""
    try:
        data = await asyncio.to_thread(get_weather, CITY)
        line = await asyncio.to_thread(human_weather_line, data)
    except Exception:
        line = "Morning Davud! Couldn't check the weather right now 😅"
    for cid in list(people.keys()):
        try:
            await context.bot.send_message(int(cid), line)
        except Exception:
            pass


def main() -> None:
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("who", who))
    app.add_handler(CommandHandler("ask", ask))
    app.add_handler(CommandHandler("email", email_cmd))
    app.add_handler(CommandHandler("yes", yes))
    app.add_handler(CommandHandler("no", no))
    app.add_handler(CommandHandler("testweather", testweather))
    app.add_handler(MessageHandler(filters.PHOTO, on_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))

    app.job_queue.run_daily(send_morning,
                            time=datetime.time(hour=7, minute=30, tzinfo=ZoneInfo(TIMEZONE)))

    print("Ready!")
    app.run_polling()


if __name__ == "__main__":
    main()
