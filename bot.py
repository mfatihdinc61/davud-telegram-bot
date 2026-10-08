# Davud's Telegram buddy — a simple AI agent in one file.
#
# HOW TO RUN:
#   1) pip install -r requirements.txt
#   2) copy .env.example to .env and paste in your two keys
#   3) python bot.py   ->  then message your bot in Telegram
#
# To change things: edit PRICES and CITY just below.

import os
import json
import asyncio
import datetime
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
TIMEZONE = "Europe/Istanbul"              # used so the morning message fires at local 07:30
PRICES = {                                # the bot answers "how much...?" from this list
    "haircut": "300 TL",
    "hair coloring": "800 TL",
}
MODEL = "gemini-2.5-flash"                # the AI brain (free tier is fine)
# -----------------------------------------

load_dotenv()
TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]

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

Keep replies brief and friendly, like a real text conversation."""

# Remember chat ids so the morning message can reach everyone, even after a restart.
CHATS_FILE = "chats.json"


def load_chats() -> set:
    try:
        with open(CHATS_FILE, "r", encoding="utf-8") as f:
            return set(json.load(f))
    except (FileNotFoundError, json.JSONDecodeError):
        return set()


def save_chats(chats: set) -> None:
    try:
        with open(CHATS_FILE, "w", encoding="utf-8") as f:
            json.dump(list(chats), f)
    except OSError:
        pass


known_chats = load_chats()
# Short per-chat conversation memory (kept in RAM): { chat_id: [ {role, text}, ... ] }
history: dict[int, list] = {}


def remember_chat(chat_id: int) -> None:
    if chat_id not in known_chats:
        known_chats.add(chat_id)
        save_chats(known_chats)


# ---------- the AI calls (these are blocking, so we run them in a thread) ----------

def ask_gemini(chat_id: int, user_text: str) -> str:
    """Reply to a text message, remembering the last few turns of the chat."""
    turns = history.setdefault(chat_id, [])
    turns.append({"role": "user", "text": user_text})
    turns[:] = turns[-10:]  # keep only the last 10 messages

    contents = [
        types.Content(role=t["role"], parts=[types.Part.from_text(text=t["text"])])
        for t in turns
    ]
    resp = client.models.generate_content(
        model=MODEL,
        contents=contents,
        config=types.GenerateContentConfig(system_instruction=SYSTEM_PROMPT, temperature=0.8),
    )
    reply = (resp.text or "").strip() or "Hmm, I didn't catch that — say it again?"
    turns.append({"role": "model", "text": reply})
    return reply


def ask_gemini_about_photo(image_bytes: bytes, caption: str) -> str:
    """Look at a photo Davud sent and react to it."""
    question = caption.strip() or "Davud sent you this photo. React warmly and briefly, and say what you see."
    contents = [
        types.Content(role="user", parts=[
            types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"),
            types.Part.from_text(text=question),
        ])
    ]
    resp = client.models.generate_content(
        model=MODEL,
        contents=contents,
        config=types.GenerateContentConfig(system_instruction=SYSTEM_PROMPT, temperature=0.7),
    )
    return (resp.text or "").strip() or "Nice photo, Davud! 📷"


def get_weather(city: str) -> dict:
    """Today's weather for a city, using the free Open-Meteo API (no key needed)."""
    geo = requests.get(
        "https://geocoding-api.open-meteo.com/v1/search",
        params={"name": city, "count": 1}, timeout=15,
    ).json()
    place = geo["results"][0]
    fc = requests.get(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude": place["latitude"], "longitude": place["longitude"],
            "daily": "precipitation_probability_max,temperature_2m_max,temperature_2m_min",
            "timezone": "auto",
        }, timeout=15,
    ).json()
    daily = fc["daily"]
    return {
        "city": city,
        "temp_max": daily["temperature_2m_max"][0],
        "temp_min": daily["temperature_2m_min"][0],
        "rain_chance": daily["precipitation_probability_max"][0],
    }


def human_weather_line(data: dict) -> str:
    """Ask the AI to phrase a short, human-sounding weather heads-up for Davud."""
    prompt = (
        f"Write ONE short, warm, human text to Davud about today's weather in {data['city']}. "
        f"High {data['temp_max']}°C, low {data['temp_min']}°C, rain chance {data['rain_chance']}%. "
        f"Mention taking an umbrella only if rain chance is 50% or more. "
        f"Under 25 words, casual, at most one emoji."
    )
    try:
        resp = client.models.generate_content(
            model=MODEL, contents=prompt,
            config=types.GenerateContentConfig(temperature=0.9),
        )
        line = (resp.text or "").strip()
        if line:
            return line
    except Exception:
        pass
    # Fallback if the AI call fails
    umbrella = " Take an umbrella ☔" if data["rain_chance"] >= 50 else ""
    return f"Morning Davud! Around {data['temp_max']}°C today in {data['city']}.{umbrella}"


# ---------- Telegram handlers ----------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    remember_chat(update.effective_chat.id)
    await update.message.reply_text("Hey Davud! 👋 I'm here whenever you need me — ask me anything, "
                                    "send me a photo, or just say hi.")


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    remember_chat(chat_id)
    await context.bot.send_chat_action(chat_id, "typing")
    try:
        reply = await asyncio.to_thread(ask_gemini, chat_id, update.message.text)
    except Exception:
        reply = "Oops, my brain hiccuped 😅 try again?"
    await update.message.reply_text(reply)


async def on_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    remember_chat(chat_id)
    await context.bot.send_chat_action(chat_id, "typing")
    try:
        photo = update.message.photo[-1]                 # biggest size
        tg_file = await photo.get_file()
        img_bytes = bytes(await tg_file.download_as_bytearray())
        caption = update.message.caption or ""
        reply = await asyncio.to_thread(ask_gemini_about_photo, img_bytes, caption)
    except Exception:
        reply = "Hmm, I couldn't open that photo 😅 mind sending it again?"
    await update.message.reply_text(reply)


async def send_morning(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Runs automatically each morning (and from /testweather)."""
    try:
        data = await asyncio.to_thread(get_weather, CITY)
        line = await asyncio.to_thread(human_weather_line, data)
    except Exception:
        line = f"Morning Davud! Couldn't check the weather right now 😅"
    for chat_id in list(known_chats):
        try:
            await context.bot.send_message(chat_id, line)
        except Exception:
            pass


async def testweather(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    remember_chat(update.effective_chat.id)
    await send_morning(context)


def main() -> None:
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("testweather", testweather))
    app.add_handler(MessageHandler(filters.PHOTO, on_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))

    # Morning heads-up at 07:30 local time.
    app.job_queue.run_daily(
        send_morning,
        time=datetime.time(hour=7, minute=30, tzinfo=ZoneInfo(TIMEZONE)),
    )

    print("Ready!")
    app.run_polling()


if __name__ == "__main__":
    main()
