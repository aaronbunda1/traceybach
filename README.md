# 🥂 Bach Bash Planner

A one-stop bachelorette party planner — a colorful Streamlit app for picking
the weekend, voting on the city, and splitting the costs. Local-first (SQLite),
with a clean path to free durable hosting (Postgres).

## Tabs

| Tab | What it does |
|-----|--------------|
| 🏠 **Home** | Hype landing page — banner, photo gallery of the bride-to-be, and live stats (crew size, leading city, front-runner weekend). |
| 👯 **Crew** | Manage the guest list. |
| 📅 **Availability** | Everyone marks the **Fri–Sun weekends in Feb & March 2027** ✅/🤔/❌; a ranked table surfaces the best weekend. |
| 🌆 **City** | Vote on the destination. A sub-tab per city (Puerto Rico, Cartagena, Las Vegas) with the vibe, **cost estimates that scale with guest count** (Airbnb, activities, food, flights), and **travel time from NYC, Bay Area & South Florida**, plus a vote tally. |
| 💰 **Budget** | Planned spend by category, per-head total vs a target. |
| 🧾 **Expenses** | Splitwise-style logging + minimized "who pays whom" settle-up. |
| 🗓️ **Schedule** | Embedded Google Calendar (read-only month view) + add-to-calendar links + optional two-way sync (local only). |
| 💡 **Ideas** | Suggest activities and vote. |
| ✅ **Checklist** | Shared to-do / packing list. |

## Run it locally

```bash
cd ~/Code/bach-bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

Locally, data is stored in `bach_bash.db` (SQLite) — delete that file to reset.

## Photos

Photos of the guest of honor live in `assets/photos/` and show on the Home page
(sorted by filename). Add or remove them by editing that folder, or use the
in-app **📸 Add / manage photos** uploader during local dev.

## Access model

The hosted app is **open** — anyone with the link can vote, add expenses, mark
availability, and so on. There's no login or password. The only thing that's
restricted is the app itself (this code, including the city templates in
`app.py`): change it by editing and pushing to the repo, so **only GitHub
collaborators can change the app**. Add co-planners under the repo's
Settings → Collaborators.

## Storage

`db.py` is dual-mode:

- **No `DATABASE_URL`** (local dev / tests) → a local **SQLite** file.
- **`DATABASE_URL` set** → **Postgres** (e.g. a free Neon database when hosted),
  so the crew's data survives restarts.

## Deploying (free)

See **[DEPLOY.md](DEPLOY.md)** for the full step-by-step: a free Neon Postgres
database + Streamlit Community Cloud, deployed straight from this GitHub repo.

## Google Calendar (optional)

The Schedule tab works with no setup via the embedded calendar and
"Add to Google Calendar" links. Two-way sync (read/write a shared calendar from
inside the app) uses an OAuth desktop flow and is **local-only** — it isn't
available on the hosted app. To use it locally:

1. Create a project at <https://console.cloud.google.com> and enable the
   **Google Calendar API**.
2. Create an **OAuth client ID** of type **Desktop app**.
3. Download the JSON as `credentials.json` in this folder.
4. In the Schedule tab, click **Connect Google Calendar**.

`credentials.json`, `token.json`, `bach_bash.db`, and `.streamlit/secrets.toml`
are git-ignored.

## Tests

```bash
pip install pytest
pytest -q
```

Covers settle-up math, DB round-trips, and a Streamlit `AppTest` smoke test.
The suite always runs on a throwaway SQLite DB.
