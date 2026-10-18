# 🛠️ Claude Code build prompt (Scenario 2)

Open an **empty folder**, run `claude`, and paste everything in the box below. When it's done, add
your keys (`.env` or Replit Secrets) and run it.

```
Build a Telegram "AI agent" bot in Python, in ONE file `bot.py`, plus `requirements.txt`,
`.env.example`, `.replit`, `.gitignore`, and a short `README.md`. Clean, well-commented code that
runs on Replit and locally. Don't over-explain — just create the files.

TECH (use exactly these):
- python-telegram-bot v21+ (async) WITH JobQueue:  pip install "python-telegram-bot[job-queue]"
- Google Gemini via the "google-genai" SDK, model "gemini-3.8-flash":
    from google import genai
    from google.genai import types
    client = genai.Client(api_key=GEMINI_API_KEY)
    client.models.generate_content(model=MODEL, contents=..., config=types.GenerateContentConfig(...))
- Weather: the FREE Open-Meteo API (no key), via "requests".
- Email: the Resend API (via "requests") using RESEND_API_KEY and EMAIL_FROM (a verified-domain
  address). Email is optional — if RESEND_API_KEY is missing, the email feature just stays off.
- Config via python-dotenv. Read all secrets from the environment (Replit Secrets / .env):
  TELEGRAM_TOKEN, GEMINI_API_KEY (required); RESEND_API_KEY, EMAIL_FROM, ALLOWED_EMAILS (optional).

CONFIG block at the very top (easy to edit): CITY, TIMEZONE, PRICES (a dict),
MODEL = "gemini-3.8-flash", PTI_REMINDER_HOUR, PTI_REPORT_HOUR.

PART A — personal assistant (private 1-to-1 chats):
- A friendly persona in a SYSTEM_PROMPT. Remember the last ~10 messages per chat.
- Use Gemini AUTOMATIC FUNCTION CALLING with these tools the model can choose to call:
  * draft_email(to, subject, body): stage an email (do NOT send yet); the bot shows the draft and
    asks the user to reply "yes" to send or "no" to cancel. A plain "yes" (or /yes) sends it via
    Resend; "no" (or /no) cancels. Respect the optional ALLOWED_EMAILS allowlist.
  * send_to_friend(name, message): relay a Telegram message to another user, found by first name or
    @username among people who have started the bot; route that friend's next reply back to the sender.
  * check_weather(city): Open-Meteo forecast.
- React to PHOTOS in private: send the image to Gemini vision and reply about it in character.
- A daily morning weather message via JobQueue, plus a /testweather command.
- Remember everyone who messages the bot (name + chat id) in people.json.

PART B — FLEET PTI (Pre-Trip Inspection), which happens in a Telegram GROUP:
- When a driver posts a PHOTO or a VIDEO of a truck in the group, use Gemini vision to verify it
  clearly shows a truck/lorry/heavy goods vehicle. If not, reject with a friendly message. If yes,
  log that driver's PTI for today.
- Track per-driver streak and total in pti.json. Reply "✅ PTI logged — cleared to load. 🔥 streak N".
  Give a 🏅 shout-out at milestones (7-day streak; 30 inspections).
- Stay quiet to ordinary group text (no companion chit-chat in groups).
- Manager flow (in a private chat): /iammanager sets the caller as the fleet manager; /report shows
  today's did/didn't list; /leaderboard shows streak rankings; /ptihelp explains it.
- Scheduled jobs: a morning reminder posted in the group naming who hasn't submitted, and a
  cutoff-time report DMed to the manager.
- Vision checks must FAIL OPEN (accept) on any API error so a glitch never blocks a driver; print
  errors to the console (e.g. "PTI VISION ERROR:").

ROBUSTNESS: wrap all network/Gemini calls in try/except and print clear errors ("CHAT ERROR:",
"EMAIL ERROR:", "PTI VISION ERROR:") so the console shows the real reason. Run the blocking
Gemini/requests calls in threads with asyncio.to_thread. Print "Ready!" on startup.

FILES:
- .replit — IMPORTANT: on Replit the system Python is read-only (Nix) and sets PIP_USER=1, so install
  into a venv with --no-user. Use:
    run = "test -d .venv || python -m venv .venv; . .venv/bin/activate && pip install --no-user -q -r requirements.txt && python bot.py"
    entrypoint = "bot.py"
    modules = ["python-3.12"]
- requirements.txt — python-telegram-bot[job-queue], google-genai, requests, python-dotenv, tzdata
- .env.example — the env keys above with placeholders
- .gitignore — .env, .venv/, *.json data files (people.json, pti.json), __pycache__/, *.pyc
- README.md — how to get the Telegram token (@BotFather) and Gemini key (aistudio.google.com), how
  to run, and — crucial for the PTI group feature — that you must DISABLE the bot's privacy mode in
  @BotFather (/setprivacy → Disable) and then (re-)add the bot to the group so it can read group photos.

Keep it to the single bot.py, comment each section, and make the persona, city, prices and PTI times
easy to change at the top.
```

After it builds: add `TELEGRAM_TOKEN` and `GEMINI_API_KEY` (and optional Resend keys), then run.
For the PTI group feature, remember: **BotFather → /setprivacy → Disable → re-add the bot to the group.**
