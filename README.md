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

**Optional — email, pick ONE way:**
- **Resend (easiest):** `RESEND_API_KEY` + `EMAIL_FROM`. One key from [resend.com](https://resend.com),
  no app password. To email **anyone**, verify a domain in Resend and set `EMAIL_FROM=bot@yourdomain`.
  (The shared tester `onboarding@resend.dev` only delivers to your own Resend inbox.)
- **SMTP (Gmail/Yandex):** `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `EMAIL_FROM` —
  needs an **App Password** (a normal password won't work).

`ALLOWED_EMAILS` (optional) limits who the bot may email — **leave blank to allow anyone**.

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

## 🚚 Fleet PTI mode (truck pre-trip inspections)
The bot also tracks daily **Pre-Trip Inspections** for truck drivers, in a Telegram **group**:
- A driver posts a **photo or video of their truck** in the group.
- The AI **verifies it's really a truck** (rejects random/fake photos), then logs that driver's
  inspection, updates their **streak/total**, and replies *"✅ PTI logged — cleared to load."*
- **Milestones** (7-day streak, 30 inspections…) get a 🏅 shout-out.
- Each morning it **reminds** anyone who hasn't done it; at a cutoff time it **DMs the manager**
  a did/didn't report and flags no-shows.

**One-time Telegram setup (important):** a bot can't read group photos until you turn its
**privacy mode OFF**:
1. In **@BotFather** → `/setprivacy` → choose your bot → **Disable**.
2. **Add the bot to your drivers' group** (if it was already in the group, remove and re-add so the
   privacy change takes effect).
3. In a **private** chat with the bot, send **`/iammanager`** → you now receive the reports.
4. Drivers post a truck photo in the group to start their streaks.

Manager commands (private): `/report` · `/leaderboard` · `/ptihelp`.
Times are set by `PTI_REMINDER_HOUR` / `PTI_REPORT_HOUR` at the top of `bot.py`.
*(Both photos and short videos get the AI truck-check. Telegram caps bot video downloads at ~20MB, so keep clips short.)*

## Change it
Edit the top of `bot.py`: `CITY`, `PRICES`, `TIMEZONE`, `PTI_REMINDER_HOUR`, `PTI_REPORT_HOUR`.

## Notes
- Free stack: Gemini `gemini-3.8-flash` (free tier), Telegram Bot API, keyless Open-Meteo, and
  (optional) email via your own SMTP. Telegram relay + email are free; SMS/WhatsApp are not.
- 🔒 Keep all keys in Secrets / `.env` — never in the code or shared. `.env`, `people.json` and
  `chats.json` are gitignored.
