# Deploying Bach Bash (free, durable, phone-friendly)

The plan: host the app for free on **Streamlit Community Cloud**, with the data
living in a free **Neon Postgres** database so nothing is lost when the app
restarts. Total cost: **$0**. Updating the app = `git push`.

> Why Postgres? Free hosts have an *ephemeral* filesystem — the local SQLite
> file gets wiped on every reboot/sleep. A managed Postgres keeps the crew's
> votes, availability, and expenses durable for months.

---

## 1. Create a free Postgres database (Neon) — ~3 min

1. Go to <https://neon.tech> and sign up (free tier, no card).
2. Create a project (any name, e.g. `traceybach`). A database is created for you.
3. On the project dashboard, click **Connect** and copy the **connection
   string**. It looks like:
   ```
   postgresql://USER:PASSWORD@ep-xxxx.us-east-2.aws.neon.tech/neondb?sslmode=require
   ```
   Keep `?sslmode=require` on the end. Save this — it's your `DATABASE_URL`.

Neon auto-suspends when idle and auto-resumes on the next visit, so intermittent
planning over months stays on the free tier.

## 2. Deploy on Streamlit Community Cloud — ~3 min

1. Go to <https://share.streamlit.io> and sign in **with GitHub**.
2. Click **Create app** → **Deploy a public app from GitHub**.
3. Fill in:
   - **Repository:** `aaronbunda1/traceybach`
   - **Branch:** `main`
   - **Main file path:** `app.py`
4. Click **Advanced settings → Secrets** and paste this one line (using your
   Neon string from step 1):
   ```toml
   DATABASE_URL = "postgresql://USER:PASSWORD@HOST/neondb?sslmode=require"
   ```
5. Click **Deploy**. First build takes a couple of minutes.

That's it — you'll get a URL like `https://traceybach.streamlit.app`. Text it to
the crew; it works on phones and laptops, no install.

## 3. Day-to-day

- **Anyone with the link can participate** — vote, add expenses, mark dates, etc.
  There's no login and no password.
- **Only GitHub collaborators can change the app** — the city options, costs,
  and copy live in `app.py`. Edit, commit, and push; Streamlit Cloud redeploys
  automatically on every push to `main`.
- **Photos** are committed in `assets/photos/`, so they ship with the deploy.
  Add more by committing files there (or via the in-app uploader during local
  dev — uploads on the hosted app won't persist across reboots, so commit the
  keepers to the repo).

## Notes & limits

- **Google Calendar:** the *embedded* calendar (Schedule tab) works hosted —
  just paste a public calendar's ID in its settings. The *two-way OAuth sync* is
  local-only (it needs a browser on the machine) and is effectively disabled on
  the host; the embed + "add to calendar" links cover the shared-calendar need.
- **Co-planners:** add them as collaborators on the GitHub repo
  (Settings → Collaborators). That's the entire access model.
- **Local development** needs no secrets — without `DATABASE_URL` the app uses a
  local `bach_bash.db` SQLite file. To test against Postgres locally, put
  `DATABASE_URL` in `.streamlit/secrets.toml` (git-ignored) or export it as an
  env var.
