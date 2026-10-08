# Davud's Telegram buddy 🤖

A simple one-file AI agent: it chats like a friendly human, calls the user **Davud**, reacts to
photos, answers price questions, and sends a human-sounding weather heads-up each morning.

## Run it (both keys are free)
1. In Telegram, message **@BotFather** → `/newbot` → copy the **token**. That also gives you the
   bot's link (its "Telegram number") to open and chat with.
2. Get a **Gemini API key** at **aistudio.google.com** → "Get API key".
3. Copy `.env.example` to a new file called **`.env`** and paste both keys in.
4. Install and run:
   ```
   pip install -r requirements.txt
   python bot.py
   ```
   You should see `Ready!`. Now open your bot in Telegram and say hi.

## Try it
- Say hi, chat normally.
- Ask **"how much is a haircut?"**
- Send a **photo** 📷 — it reacts to what it sees.
- Type **/testweather** 🌦️ to get the morning-style heads-up right now.

## Change it
Open `bot.py` and edit the lines near the top:
- `CITY` — your city for the weather.
- `PRICES` — your own list, e.g. `{"lesson": "500 TL"}`.
- `TIMEZONE` — so the 07:30 morning message fires at your local time.

## Notes
- Uses `gemini-2.5-flash` (free tier), `python-telegram-bot` (with its scheduler), and the free
  keyless **Open-Meteo** weather API.
- 🔒 Keep `.env` and both keys secret — they're like passwords. Don't commit `.env` or share it.
