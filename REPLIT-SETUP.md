# ☁️ Run the bot in the cloud with Replit (no install for the student)

Goal: the student clicks **Run** in a browser and watches his bot come alive — then messages it
on his phone. No Python, no pip, nothing installed on his computer.

---

## One-time setup (a teacher/grown-up does this, ~5 min)

### 1. Get the two free keys first
- **Telegram token:** in Telegram, message **@BotFather** → `/newbot` → pick a name → copy the
  **token**. BotFather also gives the bot's link (e.g. `t.me/your_bot`) — that's what the student opens.
- **Gemini key:** go to **aistudio.google.com** → "Get API key" → copy it.

### 2. Make the Repl
1. Go to **replit.com** and sign in (free).
2. Click **＋ Create Repl** → choose the **Python** template → create it.
3. In the file list, delete the default `main.py`, then **drag in these files** from the
   `davud-bot` folder:
   - `bot.py`
   - `requirements.txt`
   - `.replit`   *(this one may be hidden — turn on "Show hidden files" in the three-dots menu, and let it overwrite the existing `.replit`)*

   *(Skip `.env`, `.env.example` and `.gitignore` — not needed on Replit.)*

### 3. Add the keys as Secrets (not in the code!)
1. In the left sidebar, open the **Secrets** tool (🔒 lock icon).
2. Add two secrets:
   - key `TELEGRAM_TOKEN` → value: your BotFather token
   - key `GEMINI_API_KEY` → value: your Gemini key
3. That's it — the code reads these automatically.

### 4. Press ▶ Run
The first run installs the libraries (takes ~30–60 sec, you'll see it in the console), then prints
**`Ready!`**. The bot is now live.

---

## What the student does 🎉
1. Open the Repl page and press the big green **▶ Run** button.
2. On his phone, open the bot's link from BotFather and tap **Start**.
3. Watch it work — he sees the console light up as he:
   - chats with it 💬
   - sends a **photo** 📷
   - asks **"how much is a haircut?"**
   - types **/testweather** 🌦️ for the morning-style weather message

He built an agent, and it's running in the cloud. ✨

---

## 🎓 Lesson day — give the student his OWN copy (don't share your account)

You could log the student into your account, but then he'd see your private keys and your whole
account. The clean way is **Remix** (fork): he gets his own copy, with his own keys, and your keys
stay private (Replit does **not** copy Secrets into a remix).

**Before the lesson, make your Repl remixable:** open it → **Publish** it (or just set it public /
turn on "Allow forks") so the student can open and remix the link.

**In the lesson, the student:**
1. Makes a **free Replit account**, his own **Telegram bot** (@BotFather) and **Gemini key**
   (~5–8 min of signups — easiest to do these together right before).
2. Opens your Repl link and clicks **Remix / Fork** → he now has his own private copy.
3. Opens the **Secrets** 🔒 tool and adds his own `TELEGRAM_TOKEN` and `GEMINI_API_KEY`.
   *(His copy starts with no keys — that's expected.)*
4. Edits `SYSTEM_PROMPT` at the top of `bot.py` — pastes the personality he designed in Lesson 1.
5. Presses **▶ Run** and messages his bot on his phone. It's his. 🎉

That's the whole lesson: **Remix → add 2 Secrets → tweak the persona → Run.**

## Good to know
- **While the Run tab is open, the bot stays up** — perfect for the lesson.
- **For 24/7** (so the 7:30 AM weather message fires every day on its own), Replit needs an
  always-on **Deployment** (a small paid plan). For the lesson, keeping it running during class +
  the `/testweather` command shows the feature without needing that.
- **Change the city or prices:** edit the `CITY` and `PRICES` lines at the top of `bot.py`, then
  press Run again.
- 🔒 The keys live only in **Secrets** — never paste them into the code or share them.

> Prefer GitHub? You can also push this folder to a GitHub repo and use Replit's **Import from
> GitHub** instead of dragging files. Ask and I'll set that up.
