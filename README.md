# 🥂 Bach Bash Planner

A one-stop bachelorette party planner. Local-first Streamlit app with two-way
Google Calendar sync.

## Tabs

| Tab | What it does |
|-----|--------------|
| 🏠 **Home** | Party basics + at-a-glance stats (crew size, budget, spend). |
| 👯 **Crew** | Manage the guest list. |
| 📅 **Availability** | Everyone marks dates ✅/🤔/❌; a ranked table surfaces the best weekend. |
| 💰 **Budget** | Planned spend by category, per-head total vs a target. |
| 🧾 **Expenses** | Splitwise-style logging + minimized "who pays whom" settle-up. |
| 🗓️ **Schedule** | Two-way Google Calendar sync (+ no-setup add-to-calendar links). |
| 💡 **Ideas** | Suggest activities and vote. |
| ✅ **Checklist** | Shared to-do / packing list. |

## Run it

```bash
cd ~/Code/bach-bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

Data is stored locally in `bach_bash.db` (SQLite). Delete that file to reset.

## Google Calendar sync (optional)

The Schedule tab works without any setup via "Add to Google Calendar" links.
For full two-way sync (read/write a shared party calendar from inside the app):

1. Create a project at <https://console.cloud.google.com> and enable the
   **Google Calendar API**.
2. Create an **OAuth client ID** of type **Desktop app**.
3. Download the JSON as `credentials.json` in this folder.
4. In the Schedule tab, click **Connect Google Calendar** — a browser window
   opens once to grant access; the token is cached in `token.json`.

`credentials.json`, `token.json`, and `bach_bash.db` are git-ignored.

## Sharing with participants (local-first)

Right now this runs on your machine and data is local. To let the whole crew
use the same instance, the simplest path is to run it and expose it
temporarily, e.g.:

```bash
pip install streamlit && streamlit run app.py --server.address 0.0.0.0
# then share your LAN IP, or tunnel with `ngrok http 8501` / `cloudflared`.
```

When you're ready for a permanently-hosted shared version with accounts, the
SQLite layer (`db.py`) swaps cleanly for a hosted Postgres/Supabase.

## Tests

```bash
pip install pytest
pytest -q
```

Covers settle-up math, DB round-trips, and a Streamlit `AppTest` smoke test.
```
