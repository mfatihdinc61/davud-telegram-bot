# 🎓 Student guide — build this Telegram agent

Two ways to end up with your own copy of the bot (companion chat + email/friend/weather tools + the
fleet **PTI** truck-inspection system).

---

## First: the free accounts/keys you'll need (both paths)
- **Telegram bot token** — in Telegram, message **@BotFather** → `/newbot` → copy the token.
- **Gemini API key** — **aistudio.google.com** → *Get API key* → copy it (starts with `AIza`).
- **Replit account** (to host it) — free.
- *(Optional, for email)* a **Resend** API key + a domain you've verified in Resend. If you don't have
  one, just skip email — everything else works without it.

---

## Scenario 1 — pull my repo and configure it (fastest)

1. **Import the code into Replit:** replit.com → **＋ Create** → **Import from GitHub** →
   `https://github.com/mfatihdinc61/davud-telegram-bot` → Import.
2. **Add your keys** in the **Secrets** 🔒 tool:
   - `TELEGRAM_TOKEN` = your BotFather token
   - `GEMINI_API_KEY` = your `AIza…` key
   - *(optional)* `RESEND_API_KEY` + `EMAIL_FROM=you@yourdomain`
3. **Press ▶ Run.** First run builds a venv and installs libs, then prints **`Ready!`**.
   - ⚠️ If you see **`externally-managed-environment`**, the Replit Agent changed `.replit`. Open the
     **Shell** and run `git checkout .replit`, then Run again.
4. **Make it yours:** open `bot.py` (Build → ＋ → Files → `bot.py`) and edit the top:
   `SYSTEM_PROMPT` (personality), `CITY`, `PRICES`, `PTI_REMINDER_HOUR`, `PTI_REPORT_HOUR`.
   *(Or just tell the Replit **Agent** chat: "change the persona to …")*
5. **Chat features:** DM your bot — talk to it, send a photo, ask *"email … "*, *"ask <friend> …"*,
   *"what should I wear?"*.
6. **Turn on the PTI group feature:**
   - **@BotFather → `/setprivacy` → `@yourbot` → Disable** (so it can read group photos).
   - **Add the bot to a group** (if it was already in, remove & re-add it).
   - In a **private** chat with the bot, send **`/iammanager`** → you'll get the reports.
   - Drivers post a **truck photo/video** in the group → it verifies & logs their streak.
7. **Keep the Repl tab open** — on the free plan the bot runs only while a workspace is open.

**Gotchas:** one bot token = one running copy (don't run it twice); the model is already
`gemini-3.8-flash`; email only sends from a **verified** Resend domain.

---

## Scenario 2 — build it from scratch with Claude Code

Install Claude Code, open an **empty folder**, run `claude`, and paste the prompt below. It will
create `bot.py` and the support files. Then add your keys and run it (locally with
`pip install -r requirements.txt && python bot.py`, or import the folder into Replit as in
Scenario 1). **The full build prompt is in `BUILD-PROMPT.md`** in this repo (copy it whole).

Tip: you can also build it **step by step** — start with "a Telegram bot that chats using Gemini",
get that running, then ask Claude Code to add photos, then tools (email/weather/friend), then the
PTI group feature. Smaller steps are easier to test.
