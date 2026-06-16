# Individual IKR

A personal monthly goals dashboard (IKR = Individual Key Results). Track targets, weightage, and progress in a Streamlit app, with optional Telegram reminders and progress updates.

Each person runs their own copy. Data stays in a local SQLite database on your machine — nothing personal is stored in this repository.

## Quick start

### 1. Clone and install

```bash
git clone <your-repo-url>
cd individual_ikr
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Run the app

```bash
streamlit run streamlit_app/app.py
```

Open the URL shown in the terminal (usually http://localhost:8501).

### 3. First login

On first run the app creates `ikr.db` automatically.

| Field    | Default |
|----------|---------|
| Username | `admin` |
| Password | `admin` |

Sign in, then go to **Account** and change your password.

### 4. Set up your month

1. **Config** — Add goals for the current month (name, target, weightage). Weightage should total 100% across goals.
2. **Progress** — Enter how far you are on each goal. The dashboard shows completion % and weighted score.

That’s enough to use the app without Telegram.

---

## Tabs

| Tab | Who | Purpose |
|-----|-----|---------|
| **Progress** | Everyone | View and update progress for the selected month |
| **Config** | Everyone | Add, edit, or remove goals for a month |
| **Account** | Everyone | Change password; connect Telegram (optional) |
| **Users** | Admin only | Create or delete user accounts |

---

## Multi-user setup

The default `admin` account can create additional users under **Users**.

- Each user has their own goals and progress (data is isolated by user).
- Share the app URL with others on the same network, or deploy it to a server everyone can reach.
- Each user should change their password after first login.

---

## Telegram (optional)

Telegram is optional. Use it for daily reminders and updating progress from your phone.

### One-time bot setup (whoever hosts the app)

1. Create a bot with [@BotFather](https://t.me/BotFather) on Telegram.
2. Copy the token into either:
   - `telegram_bot_token.txt` (copy from `telegram_bot_token.txt.example`), or
   - environment variable `TELEGRAM_BOT_TOKEN`

### Per-user connect

1. Sign in → **Account** → **Connect Telegram**.
2. Tap the link, press **Start** in Telegram.
3. The app links your chat id automatically.

### Update progress from Telegram

Message your bot:

| Message | Meaning |
|---------|---------|
| `/status` | Show current month goals and progress |
| `/help` | List commands |
| `1 3.5` | Set goal #1 progress to 3.5 |
| `Read: 3` | Set progress for goal named “Read” to 3 |

### In-app background scheduler

While the Streamlit app is **running** (even on the login screen), it automatically:

1. **Polls Telegram every 1 minute** — picks up progress updates and connect messages
2. **Sends daily reminders at 11:30 AM** (your computer’s local time) — missing goals or stale progress summaries

Configure the reminder time in the admin **Settings** tab (default 11:30 AM local time).

### When the app is closed

For Telegram updates and reminders when Streamlit is not running, use Task Scheduler (Windows) or cron (Mac/Linux):

```bash
python notifiers/poll_telegram.py      # every 1–2 minutes
python notifiers/send_reminders.py     # once daily (backup for 11:30 reminders)
```

Example cron (Mac/Linux):

```cron
0 11 * * * cd /path/to/individual_ikr && .venv/bin/python notifiers/send_reminders.py
*/2 * * * * cd /path/to/individual_ikr && .venv/bin/python notifiers/poll_telegram.py
```

---

## What stays on your machine (not in Git)

| File | Purpose |
|------|---------|
| `ikr.db` | All users, goals, progress (auto-created on first run) |
| `telegram_bot_token.txt` | Your bot token (copy from `.example`) |
| `progress.json`, `goals_config.json` | Legacy import only (optional); ignored by Git |

---

## Legacy JSON import (optional)

**You do not need these files.** The app stores everything in `ikr.db` and runs fine without any JSON files.

These files are only for one-time migration from an older JSON-based version:

1. Copy `goals_config.json.example` → `goals_config.json` (and/or `progress.json.example` → `progress.json`).
2. Edit with your data. Use month keys like `2026-06` (YYYY-MM). Goal `id` values in `progress.json` must match those in `goals_config.json`.
3. Start the app **before** you have goals in the database — data is imported once for the admin user, then SQLite is used going forward.

If the files are missing or empty, nothing happens and the app works normally.

---

## Troubleshooting

**App won’t start / database errors**  
Delete `ikr.db` and restart — a fresh database is created. Corrupt files are renamed to `ikr.corrupt_<timestamp>.db`.

**Telegram SSL errors (macOS)**  
Set `TELEGRAM_SSL_VERIFY=0` only if needed for local development.

**Reminders not sending**  
Check the bot token, that the user connected Telegram in **Account**, and that `poll_telegram.py` or the app is running.

---

## Project layout

```
individual_ikr/
├── streamlit_app/     # UI (Progress, Config, Account, Users)
├── notifiers/         # Telegram poll & daily reminders
├── auth.py            # Users & passwords
├── data.py            # Goals & progress (SQLite)
├── config.py          # Paths & scoring helpers
└── requirements.txt
```
