# Davud's Telegram buddy 🤖

A simple one-file AI agent that:
- chats like a friendly human and calls the user **Davud**
- reacts to **photos**
- answers **price** questions (from the `PRICES` list in `bot.py`)
- sends a human-sounding **weather heads-up** each morning (`/testweather` to try now)
- **relays messages** to a friend and brings their reply back (`/ask`)
- **sends email** on request, with a confirm step (`/email`)

## Keys (Secrets / .env)
**Required:** `TELEGRAM_TOKEN`, `GEMINI_API_KEY`
**Optional — only for the email feature:** `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`,
`SMTP_PASSWORD`, `EMAIL_FROM`, `ALLOWED_EMAILS`
- For **Gmail**: turn on 2-Step Verification, create an **App Password**, and use that as
  `SMTP_PASSWORD` (a normal password won't work).
- `ALLOWED_EMAILS` (optional) limits who the bot may email — leave blank to allow any.

## Run it
Cloud (recommended): see **REPLIT-SETUP.md**.
Local:
```
pip install -r requirements.txt     # then copy .env.example to .env and fill it in
python bot.py
```
You'll see `Ready!`, then message the bot in Telegram.

## Commands
- `/help` — list everything
- `/who` — who the bot knows (people who've opened it)
- `/ask Name | message` — message a friend; their reply comes back to you
- `/email address | subject | message` — draft an email, then `/yes` to send or `/no` to cancel
- `/testweather` — the morning weather message, now

## How the relay works
Everyone uses the **same bot**. When someone opens it and presses Start, the bot remembers their
name. `/ask Deniz | ...` sends Deniz the message; **Deniz's next reply is passed straight back to
you**. (Telegram rule: the bot can only message people who have opened it first — so your friend
must press Start once.)

## Change it
Edit the top of `bot.py`: `CITY`, `PRICES`, `TIMEZONE`.

## Notes
- Free stack: Gemini `gemini-2.5-flash` (free tier), Telegram Bot API, keyless Open-Meteo, and
  (optional) email via your own SMTP. Telegram relay + email are free; SMS/WhatsApp are not.
- 🔒 Keep all keys in Secrets / `.env` — never in the code or shared. `.env`, `people.json` and
  `chats.json` are gitignored.
