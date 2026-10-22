# Davud's Telegram buddy — a simple AI agent in one file.
#
# WHAT IT CAN DO:
#   • chat like a friendly fleet dispatcher ("Dispatch"); edit SYSTEM_PROMPT to re-skin it
#   • look at photos you send
#   • answer price questions (from the PRICES list below)
#   • send you a human-sounding weather heads-up each morning  (/testweather to try now)
#   • relay a message to a friend and bring their reply back    (/ask  Name | message)
#   • send an email on your behalf, with a confirm step         (/email to | subject | body)
#   • FLEET PTI: in a drivers' group, drivers post a daily truck photo (quick proof) or a VIDEO
#     walkaround — the AI runs the video against an editable inspection checklist (tyres, lights,
#     plate, mirrors… see PTI_CRITERIA) and only logs it if the key items are visible. It tracks
#     each driver's streak, rewards milestones, and DMs the manager a daily report.
#     Manager: /iammanager (in private) · /report · /leaderboard · /ptihelp
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
PTI_REMINDER_HOUR = 8     # local time: nudge drivers who haven't done their truck PTI yet
PTI_REPORT_HOUR = 11      # local time: DM the manager the daily did/didn't PTI report

# PTI VIDEO CHECKLIST — when a driver posts a VIDEO walkaround, the AI checks it for each
# item below and only logs the inspection if enough items are actually visible. Edit this
# list for your fleet (keep each item short and specific — things the camera can SEE).
PTI_CRITERIA = [
    "front tyres look properly inflated and undamaged",
    "rear tyres look properly inflated and undamaged",
    "headlights and front indicators are present / intact",
    "rear lights and brake lights are present / intact",
    "number plate is visible and readable",
    "both side mirrors are present and not broken",
]
PTI_REQUIRE_ALL = True            # True = every item must be visible to pass the inspection
PTI_MIN_PASS = len(PTI_CRITERIA)  # if REQUIRE_ALL is False: how many items are enough to pass
PTI_FAIL_OPEN = True              # on an AI/network error, accept the clip so a glitch never
                                  # blocks a driver. Set False for a stricter, fail-closed check.
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
SYSTEM_PROMPT = f"""You are "Dispatch", a friendly, professional assistant for a trucking fleet,
texting with drivers and the fleet manager. Talk like a helpful human dispatcher: short, clear
messages, warm but to the point, at most one emoji. Address people naturally and use a person's
first name if you know it — never invent or assume a name.

If someone asks whether you are an AI or a real person, answer honestly that you are an AI assistant.

Your main job is the daily Pre-Trip Inspection (PTI): in the drivers' group, each driver posts a
photo or a short walkaround video of their truck; the bot checks it against the inspection
checklist and logs their streak. If a driver asks how PTI works or what to send, explain it simply
and point them to /ptihelp.

The company gave you this price/rate list; answer "how much…?" questions from it, and say you're
not sure if something isn't on it:
{price_lines}

You have tools you can use:
- check_weather: when someone asks about the weather or road/driving conditions, call check_weather
  with the city.
- draft_email: if someone asks you to send or write an email, call draft_email with the recipient's
  address, a short subject, and the message. It does NOT send right away — show the recipient,
  subject and message, and ask them to reply "yes" to send or "no" to cancel.
- send_to_friend: if someone asks you to pass a message to a colleague by name, call send_to_friend
  with the name and the message; it sends on Telegram right away (if they've opened the bot) and
  their reply comes back to the sender.

Keep replies brief and professional, like a real dispatcher texting back."""

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

# ---------- PTI (Pre-Trip Inspection) tracking ----------
PTI_FILE = "pti.json"     # drivers + streaks + the group chat id + the manager chat id


def load_pti() -> dict:
    try:
        with open(PTI_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        data = {}
    data.setdefault("group_chat_id", None)
    data.setdefault("manager_chat_id", None)
    data.setdefault("drivers", {})     # "<user_id>": {"name","last_pti","streak","total"}
    return data


def save_pti() -> None:
    try:
        with open(PTI_FILE, "w", encoding="utf-8") as f:
            json.dump(pti, f, ensure_ascii=False)
    except OSError:
        pass


pti: dict = load_pti()


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
        """Draft an email for the user to send. Use this whenever they ask to send or write an
        email to someone. The email is NOT sent yet — it is staged for the user to confirm."""
        if not EMAIL_READY:
            return "Email is not set up, so you can't send one. Let the user know."
        if ALLOWED_EMAILS and to.lower() not in ALLOWED_EMAILS:
            return f"Not allowed to email {to}. You may only email: {', '.join(ALLOWED_EMAILS)}."
        pending_email[chat_id] = {"to": to, "subject": subject, "body": body}
        return (f"Email drafted to {to}, subject '{subject}'. Now show the user the recipient, "
                f"subject and message, then ask them to reply 'yes' to send or 'no' to cancel.")

    def send_to_friend(name: str, message: str) -> str:
        """Relay a Telegram message to a colleague by name. Use when the user asks to message or
        ask a colleague something. It sends right away and the colleague's reply returns."""
        target = find_chat_by_name(name)
        if target is None:
            return (f"{name} hasn't opened the bot yet, so you can't message them. Tell the user that "
                    f"{name} needs to open the bot and press Start first.")
        if target == chat_id:
            return "That's the user themselves — ask which colleague they mean."
        pending_relay[chat_id] = {"target": target, "name": name, "message": message}
        return f"Message queued for {name}. Tell the user you've sent it and will bring the reply back."

    def check_weather(city: str) -> str:
        """Get today's weather for a city. Use when the user asks about weather or driving conditions."""
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
    question = caption.strip() or "Someone sent you this photo. React briefly and professionally, and say what you see."
    contents = [types.Content(role="user", parts=[
        types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"),
        types.Part.from_text(text=question),
    ])]
    resp = client.models.generate_content(
        model=MODEL, contents=contents,
        config=types.GenerateContentConfig(system_instruction=SYSTEM_PROMPT, temperature=0.7),
    )
    return (resp.text or "").strip() or "Thanks for the photo. 📷"


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
    prompt = (f"Write ONE short, friendly dispatcher text to the drivers about today's weather and "
              f"driving conditions in {data['city']}. "
              f"High {data['temp_max']}°C, low {data['temp_min']}°C, rain chance {data['rain_chance']}%. "
              f"Mention wet roads / taking care only if rain chance is 50% or more. "
              f"Under 25 words, professional but warm, at most one emoji.")
    try:
        resp = client.models.generate_content(model=MODEL, contents=prompt,
                                               config=types.GenerateContentConfig(temperature=0.9))
        line = (resp.text or "").strip()
        if line:
            return line
    except Exception:
        pass
    umbrella = " Wet roads — drive safe ☔" if data["rain_chance"] >= 50 else ""
    return f"Morning, team! Around {data['temp_max']}°C today in {data['city']}.{umbrella}"


# ---------- PTI helpers ----------

def _today() -> str:
    return datetime.datetime.now(ZoneInfo(TIMEZONE)).date().isoformat()


def _yesterday() -> str:
    return (datetime.datetime.now(ZoneInfo(TIMEZONE)).date() - datetime.timedelta(days=1)).isoformat()


def _parse_json(text: str) -> dict:
    """Pull a JSON object out of the model's reply, even if it's wrapped in ```json fences."""
    t = (text or "").strip()
    if t.startswith("```"):
        t = t.strip("`")
        if t[:4].lower() == "json":
            t = t[4:]
    start, end = t.find("{"), t.rfind("}")
    if start != -1 and end != -1:
        t = t[start:end + 1]
    return json.loads(t)


def pti_need() -> int:
    """How many checklist items must be visible to pass."""
    return len(PTI_CRITERIA) if PTI_REQUIRE_ALL else max(1, min(PTI_MIN_PASS, len(PTI_CRITERIA)))


def inspect_pti_media(media_bytes: bytes, mime_type: str, only_idxs: list = None) -> dict:
    """Check a PTI photo OR walkaround video against the checklist.

    Works for both images and videos (detected from mime_type). only_idxs = the 1-based
    PTI_CRITERIA indices to look for (default: all). On a re-send we pass just the items still
    missing, so the driver can send a short clip — or a photo — of only those.

    Returns: {"error": bool, "found_idxs": set(indices seen), "notes": {idx: why-missing}}.
    """
    is_video = (mime_type or "").startswith("video")
    idxs = only_idxs or list(range(1, len(PTI_CRITERIA) + 1))
    checklist = "\n".join(f"{i}. {PTI_CRITERIA[i - 1]}" for i in idxs)
    if is_video:
        lead = ("You are inspecting a truck driver's daily pre-trip inspection (PTI) WALKAROUND "
                "VIDEO. The driver pans the camera around the truck. Go through the WHOLE clip and, "
                "for each checklist item below, decide whether you can actually SEE it clearly.")
    else:
        lead = ("You are inspecting a truck driver's daily pre-trip inspection (PTI) PHOTO. For each "
                "checklist item below, decide whether you can actually SEE it clearly in this image. "
                "A single photo usually shows only one or two items — that is fine: mark what is "
                "genuinely visible and mark the rest not present.")
    prompt = (
        f"{lead}\n\n"
        f"CHECKLIST (the number before each item is its id):\n{checklist}\n\n"
        "Reply with ONLY a JSON object (no markdown, no commentary) shaped exactly like:\n"
        '{\"items\": [{\"n\": <the item id>, \"present\": true, \"note\": \"short reason\"}]}\n'
        "Give one entry per checklist item above, reusing its id as \"n\". Set present=true ONLY "
        "if the item is genuinely visible; if it is not shown, blurry, or you are unsure, set "
        "present=false and say why in the note (under 8 words)."
    )
    try:
        resp = client.models.generate_content(
            model=MODEL,
            contents=[types.Part.from_bytes(data=media_bytes, mime_type=mime_type or "image/jpeg"),
                      types.Part.from_text(text=prompt)],
            config=types.GenerateContentConfig(temperature=0),
        )
        data = _parse_json(resp.text or "")
        by_n = {int(it.get("n", 0)): it for it in data.get("items", []) if isinstance(it, dict)}
        found, notes = set(), {}
        for i in idxs:
            it = by_n.get(i, {})
            if bool(it.get("present", False)):
                found.add(i)
            else:
                notes[i] = str(it.get("note", "")).strip()
        return {"error": False, "found_idxs": found, "notes": notes}
    except Exception as ex:
        print("PTI VISION ERROR:", repr(ex))
        # fail open (accept the checked items) or closed, per PTI_FAIL_OPEN
        return {"error": True, "found_idxs": set(idxs) if PTI_FAIL_OPEN else set(), "notes": {}}


def pti_checklist_text(passed_idxs: set, carried_idxs: set = frozenset(), notes: dict = None) -> str:
    """Pretty ✅/❌ list; items verified on an earlier clip today are tagged 'already verified'."""
    notes = notes or {}
    lines = []
    for i, crit in enumerate(PTI_CRITERIA, start=1):
        if i in passed_idxs:
            tag = " — already verified earlier" if i in carried_idxs else ""
            lines.append(f"✅ {crit}{tag}")
        else:
            extra = f" — {notes[i]}" if notes.get(i) else ""
            lines.append(f"❌ {crit}{extra}")
    return "\n".join(lines)


# --- same-day inspection progress, so a driver can re-film only the missing items ---

def get_pti_progress(user_id: int) -> set:
    """Indices this driver already passed TODAY (empty if none / a new day)."""
    d = pti["drivers"].get(str(user_id))
    if not d:
        return set()
    p = d.get("pti_progress")
    if not p or p.get("date") != _today():
        return set()
    return set(p.get("passed", []))


def set_pti_progress(user_id: int, name: str, passed_idxs: set) -> None:
    d = pti["drivers"].setdefault(str(user_id), {"name": name, "last_pti": None, "streak": 0, "total": 0})
    d["name"] = name
    d["pti_progress"] = {"date": _today(), "passed": sorted(passed_idxs)}
    save_pti()


def clear_pti_progress(user_id: int) -> None:
    d = pti["drivers"].get(str(user_id))
    if d and "pti_progress" in d:
        d.pop("pti_progress", None)
        save_pti()


def record_pti(user_id: int, name: str) -> dict:
    """Log today's PTI for a driver and update their streak/total. Returns a small summary."""
    d = pti["drivers"].setdefault(str(user_id), {"name": name, "last_pti": None, "streak": 0, "total": 0})
    d["name"] = name
    if d["last_pti"] == _today():
        return {"status": "already", "streak": d["streak"], "total": d["total"], "milestone": None}
    d["streak"] = d["streak"] + 1 if d["last_pti"] == _yesterday() else 1
    d["total"] += 1
    d["last_pti"] = _today()
    save_pti()
    milestone = None
    if d["streak"] in (7, 30, 100):
        milestone = f"{d['streak']}-day streak"
    elif d["total"] in (30, 100, 250):
        milestone = f"{d['total']} inspections done"
    return {"status": "ok", "streak": d["streak"], "total": d["total"], "milestone": milestone}


def pti_report_text() -> str:
    """Build the manager's daily did / didn't report."""
    drivers = pti["drivers"]
    if not drivers:
        return "No drivers have done a PTI yet. Ask them to post a truck photo in the group."
    t = _today()
    done = [d for d in drivers.values() if d["last_pti"] == t]
    missed = [d for d in drivers.values() if d["last_pti"] != t]
    lines = [f"📋 PTI report — {t}", "", f"✅ Done ({len(done)}):"]
    lines += ([f"   • {d['name']} — 🔥{d['streak']} (total {d['total']})"
               for d in sorted(done, key=lambda x: -x["streak"])] or ["   —"])
    lines += ["", f"❌ Missed today ({len(missed)}):"]
    lines += ([f"   • {d['name']} — last: {d['last_pti'] or 'never'}" for d in missed] or ["   —"])
    return "\n".join(lines)


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
        "👋 Dispatch here. I handle daily truck pre-trip inspections and quick questions. "
        "Send a truck photo/video for your PTI, ask me anything, or type /help · /ptihelp.")


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


# ---------- PTI commands ----------

async def iammanager(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_chat.type != "private":
        await update.message.reply_text("Please send /iammanager to me in a private chat, not the group.")
        return
    pti["manager_chat_id"] = update.effective_chat.id
    save_pti()
    await update.message.reply_text(
        "👔 You're set as the fleet manager. You'll get the daily PTI report and no-show alerts here.\n"
        "Commands: /report (today's status) · /leaderboard · /ptihelp")


async def report(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    mid = pti.get("manager_chat_id")
    if mid and update.effective_chat.id != mid:
        await update.message.reply_text("Only the manager can see the full report. (Try /leaderboard.)")
        return
    await update.message.reply_text(pti_report_text())


async def leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    drivers = sorted(pti["drivers"].values(), key=lambda d: (-d["streak"], -d["total"]))
    if not drivers:
        await update.message.reply_text("No drivers yet — post a truck photo in the group to start.")
        return
    medals = ["🥇", "🥈", "🥉"]
    lines = ["🏆 PTI leaderboard (by streak):", ""]
    for i, d in enumerate(drivers[:10]):
        tag = medals[i] if i < 3 else f"{i + 1}."
        lines.append(f"{tag} {d['name']} — 🔥{d['streak']} · total {d['total']}")
    await update.message.reply_text("\n".join(lines))


async def ptihelp(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "🚚 PTI (Pre-Trip Inspection) bot\n\n"
        "Drivers, each day in the group:\n"
        "• 🎥 Best: post a VIDEO walkaround of the truck. I check it against the inspection "
        "checklist (tyres, lights, plate, mirrors…) and only log it if the key items are "
        "clearly visible — you'll get a ✅/❌ list back.\n"
        "• 📸 Or send PHOTOS of the items — each photo is checked against the same list.\n"
        "I log your inspection + streak once enough items are verified. If a video only passes "
        "some checks, just send a short clip OR photos of the missing items — the ones you "
        "already passed today still count.\n\n"
        "Manager (private chat):\n"
        "• /iammanager — set yourself as the manager\n"
        "• /report — who did / didn't do PTI today\n"
        "• /leaderboard — streak rankings")


# ---------- message handlers ----------

GROUP_GREETINGS = {
    "hi", "hii", "hiii", "hey", "heyy", "hello", "helo", "yo", "sup", "hallo", "hiya",
    "selam", "selamlar", "merhaba", "mrb", "slm", "naber", "gunaydin", "günaydın",
    "iyi gunler", "iyi günler", "iyi aksamlar", "iyi akşamlar", "hola",
    "good morning", "good evening", "morning",
}


async def handle_group_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """In a group the bot keeps out of normal driver chatter, but DOES reply when someone greets
    it or addresses it (mention / reply) — so it never looks broken."""
    msg = update.message
    text = (msg.text or "").strip()
    bot_un = (context.bot.username or "").lower()
    low = text.lower()
    mentioned = bool(bot_un) and ("@" + bot_un) in low
    reply_to_bot = bool(msg.reply_to_message and msg.reply_to_message.from_user
                        and msg.reply_to_message.from_user.id == context.bot.id)
    stripped = (low.replace("@" + bot_un, "") if bot_un else low).strip(" !.,?؟")
    greeting = stripped in GROUP_GREETINGS
    if not (mentioned or reply_to_bot or greeting):
        return   # ordinary chatter — stay quiet

    chat_id = update.effective_chat.id
    clean = (text.replace("@" + context.bot.username, "").strip() if (mentioned and context.bot.username) else text)
    await context.bot.send_chat_action(chat_id, "typing")
    try:
        reply = await asyncio.to_thread(ask_gemini, chat_id, clean or "hi")
    except Exception as ex:
        print("GROUP CHAT ERROR:", repr(ex))
        reply = f"👋 Hey {(update.effective_user.first_name or 'there').strip()}!"
    # Group chats shouldn't trigger the email/relay tools — drop anything they queued.
    pending_relay.pop(chat_id, None)
    pending_email.pop(chat_id, None)
    await msg.reply_text(reply)


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # In a group the bot only replies to greetings / when addressed (PTI itself is photos+videos).
    if update.effective_chat.type in ("group", "supergroup"):
        await handle_group_text(update, context)
        return
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
    # In a group, a photo is a driver's daily PTI submission.
    if update.effective_chat.type in ("group", "supergroup"):
        await handle_pti_photo(update, context)
        return
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


async def on_video(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # A video in the group is a PTI submission too — the AI checks it shows a truck.
    if update.effective_chat.type in ("group", "supergroup"):
        await handle_pti_video(update, context)


def _logged_today(user_id: int) -> dict:
    """The driver's record if they've already fully logged PTI today, else None."""
    d = pti["drivers"].get(str(user_id))
    return d if (d and d.get("last_pti") == _today()) else None


async def handle_pti_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat, user = update.effective_chat, update.effective_user
    name = (user.first_name or user.username or "driver").strip()
    pti["group_chat_id"] = chat.id          # remember the drivers' group for reminders/reports
    save_pti()
    done = _logged_today(user.id)
    if done:
        await update.message.reply_text(f"✅ {name}, today's PTI is already logged. 🔥 streak {done['streak']}")
        return
    try:
        photo = update.message.photo[-1]
        tg_file = await photo.get_file()
        img = bytes(await tg_file.download_as_bytearray())
    except Exception as ex:
        print("PTI PHOTO ERROR:", repr(ex))
        await update.message.reply_text(f"{name}, I couldn't open that photo — please send it again.")
        return
    await _process_pti_media(update, user.id, name, img, "image/jpeg")


async def handle_pti_video(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat, user = update.effective_chat, update.effective_user
    name = (user.first_name or user.username or "driver").strip()
    pti["group_chat_id"] = chat.id
    save_pti()
    done = _logged_today(user.id)
    if done:
        await update.message.reply_text(f"✅ {name}, today's PTI is already logged. 🔥 streak {done['streak']}")
        return
    try:
        video = update.message.video
        tg_file = await video.get_file()
        vid = bytes(await tg_file.download_as_bytearray())
    except Exception as ex:
        print("PTI VIDEO ERROR:", repr(ex))
        await update.message.reply_text(
            f"{name}, I couldn't open that video (Telegram caps bot downloads at ~20MB) — "
            f"send it normally (not 'as file'), keep it ~20s at 1080p/720p, or send photos of each item.")
        return
    await _process_pti_media(update, user.id, name, vid, video.mime_type or "video/mp4")


async def _process_pti_media(update: Update, user_id: int, name: str,
                             media_bytes: bytes, mime_type: str) -> None:
    """Shared PTI flow for a photo OR a video: check the still-missing checklist items against
    the media, merge into today's progress, and log the PTI once enough items are covered.
    Photos and videos feed the SAME daily progress, so a driver can finish a partial video by
    sending photos of just the missing parts."""
    kind = "clip" if (mime_type or "").startswith("video") else "photo"
    need = pti_need()
    all_idxs = list(range(1, len(PTI_CRITERIA) + 1))
    prev = await asyncio.to_thread(get_pti_progress, user_id)   # items already passed earlier today
    to_check = [i for i in all_idxs if i not in prev] or all_idxs

    if prev:
        await update.message.reply_text(
            f"🔎 Thanks {name} — the {len(prev)} item(s) you already verified today still count; "
            f"checking this {kind} for the {len(to_check)} still missing…")
    else:
        await update.message.reply_text(f"🔎 Got it, {name} — running the inspection checklist…")

    res = await asyncio.to_thread(inspect_pti_media, media_bytes, mime_type, to_check)
    passed = prev | res["found_idxs"]

    if len(passed) >= need:
        if res["error"]:
            await update.message.reply_text(f"🔎 Couldn't fully check this {kind} (too big / AI hiccup) — accepted.")
        else:
            await update.message.reply_text(
                f"🔎 Inspection complete ({len(passed)}/{need} passed):\n"
                f"{pti_checklist_text(passed, carried_idxs=prev)}")
        await asyncio.to_thread(clear_pti_progress, user_id)
        await _confirm_pti(update, user_id, name)
        return

    # Not enough yet — save progress so the next photo/clip only needs the missing items.
    await asyncio.to_thread(set_pti_progress, user_id, name, passed)
    missing = [PTI_CRITERIA[i - 1] for i in all_idxs if i not in passed]
    body = (f"⚠️ {name}, {len(passed)}/{need} checks passed so far.\n\n"
            f"{pti_checklist_text(passed, carried_idxs=prev, notes=res['notes'])}\n\n"
            f"📸 No need to redo everything — just send a short clip, or photos, of: "
            + ", ".join(missing) + ".")
    await update.message.reply_text(body)


async def _confirm_pti(update: Update, user_id: int, name: str) -> None:
    res = await asyncio.to_thread(record_pti, user_id, name)
    if res["status"] == "already":
        await update.message.reply_text(f"✅ {name}, today's PTI is already logged. 🔥 streak {res['streak']}")
        return
    msg = f"✅ PTI logged for {name} — cleared to load. 🔥 streak {res['streak']} · total {res['total']}"
    if res["milestone"]:
        msg += f"\n🏅 {res['milestone']} — great work, keep it up!"
    await update.message.reply_text(msg)


async def send_morning(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Runs automatically each morning (and from /testweather)."""
    try:
        data = await asyncio.to_thread(get_weather, CITY)
        line = await asyncio.to_thread(human_weather_line, data)
    except Exception:
        line = "Morning, team! Couldn't check the weather right now 😅"
    for cid in list(people.keys()):
        try:
            await context.bot.send_message(int(cid), line)
        except Exception:
            pass


async def pti_reminder(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Nudge the group about drivers who still haven't done today's PTI."""
    gid = pti.get("group_chat_id")
    if not gid:
        return
    pending = [d["name"] for d in pti["drivers"].values() if d["last_pti"] != _today()]
    if pending:
        msg = ("🚚 Good morning, drivers! Time for today's Pre-Trip Inspection — post a clear "
               "photo of your truck here.\n\nStill pending: " + ", ".join(pending))
    else:
        msg = "🚚 Morning! Everyone's PTI is already in. Nice work. ✅"
    try:
        await context.bot.send_message(gid, msg)
    except Exception as ex:
        print("PTI REMINDER ERROR:", repr(ex))


async def pti_report_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """DM the manager the daily did/didn't report."""
    mid = pti.get("manager_chat_id")
    if not mid:
        return
    try:
        await context.bot.send_message(mid, pti_report_text())
    except Exception as ex:
        print("PTI REPORT ERROR:", repr(ex))


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
    # PTI (truck pre-trip inspection) commands
    app.add_handler(CommandHandler("iammanager", iammanager))
    app.add_handler(CommandHandler("report", report))
    app.add_handler(CommandHandler("leaderboard", leaderboard))
    app.add_handler(CommandHandler("ptihelp", ptihelp))
    app.add_handler(MessageHandler(filters.PHOTO, on_photo))
    app.add_handler(MessageHandler(filters.VIDEO, on_video))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))

    tz = ZoneInfo(TIMEZONE)
    app.job_queue.run_daily(send_morning, time=datetime.time(hour=7, minute=30, tzinfo=tz))
    app.job_queue.run_daily(pti_reminder, time=datetime.time(hour=PTI_REMINDER_HOUR, minute=0, tzinfo=tz))
    app.job_queue.run_daily(pti_report_job, time=datetime.time(hour=PTI_REPORT_HOUR, minute=0, tzinfo=tz))

    print("Ready!")
    app.run_polling()


if __name__ == "__main__":
    main()
