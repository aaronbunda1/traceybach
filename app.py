"""Bach Bash — a one-stop bachelorette party planner.

Tabs:
  Home        party basics + at-a-glance stats
  Crew        manage the guest list
  Availability everyone marks the Feb/Mar 2027 weekends that work
  City        vote on the destination; hype + dynamic cost/logistics per city
  Budget      planned spend by category vs per-head target
  Expenses    Splitwise-style logging + minimized settle-up
  Schedule    embedded Google Calendar + two-way sync
  Ideas       suggest activities and vote
  Checklist   shared to-do / packing list

Access model:
  The app is fully open — anyone with the link can vote, add expenses, mark
  availability, and so on. Only people with access to the GitHub repo can change
  the app itself (this code, including the city templates).

Run:  streamlit run app.py
"""

from __future__ import annotations

import os
import urllib.parse
from datetime import date, datetime, time, timedelta

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

import db
import gcal
from settle import net_balances, settle

st.set_page_config(page_title="Bach Bash Planner", page_icon="🥂", layout="wide")

# On Streamlit Cloud the DATABASE_URL lives in st.secrets; expose it as an env
# var so db.py connects to Postgres. Locally (no secret) db.py uses SQLite.
try:
    if "DATABASE_URL" in st.secrets and not os.environ.get("DATABASE_URL"):
        os.environ["DATABASE_URL"] = str(st.secrets["DATABASE_URL"])
except Exception:
    pass

db.init_db()


# --------------------------------------------------------------- helpers ---
def participant_map() -> dict[int, str]:
    return {p["id"]: p["name"] for p in db.list_participants()}


def gcal_add_link(summary: str, start: datetime, end: datetime, location: str = "", details: str = "") -> str:
    """Build a 'Add to Google Calendar' URL (no API needed, works for everyone)."""
    fmt = "%Y%m%dT%H%M%S"
    params = {
        "action": "TEMPLATE",
        "text": summary,
        "dates": f"{start.strftime(fmt)}/{end.strftime(fmt)}",
        "location": location,
        "details": details,
    }
    return "https://calendar.google.com/calendar/render?" + urllib.parse.urlencode(params)


def money(x: float) -> str:
    return f"${x:,.2f}"


HERE = os.path.dirname(__file__)
PHOTOS_DIR = os.path.join(HERE, "assets", "photos")
_PHOTO_EXTS = (".jpg", ".jpeg", ".png", ".gif", ".webp")


def list_photos() -> list[str]:
    """Absolute paths of guest-of-honor photos, sorted by filename."""
    if not os.path.isdir(PHOTOS_DIR):
        return []
    return sorted(
        os.path.join(PHOTOS_DIR, f)
        for f in os.listdir(PHOTOS_DIR)
        if f.lower().endswith(_PHOTO_EXTS)
    )


def save_uploaded_photos(files) -> int:
    os.makedirs(PHOTOS_DIR, exist_ok=True)
    saved = 0
    for f in files:
        dest = os.path.join(PHOTOS_DIR, f.name)
        with open(dest, "wb") as out:
            out.write(f.getbuffer())
        saved += 1
    return saved


def feb_mar_2027_weekends() -> list[date]:
    """Fridays of every Fri–Sun weekend in Feb & March 2027 (the candidate dates)."""
    out: list[date] = []
    d = date(2027, 2, 1)
    end = date(2027, 3, 31)
    while d <= end:
        if d.weekday() == 4:  # Friday
            out.append(d)
        d += timedelta(days=1)
    return out


def weekend_label(friday: date) -> str:
    sunday = friday + timedelta(days=2)
    if friday.month == sunday.month:
        return f"{friday.strftime('%b %-d')}–{sunday.strftime('%-d')}"
    return f"{friday.strftime('%b %-d')} – {sunday.strftime('%b %-d')}"


# --------------------------------------------------- destination templates ---
# Placeholder estimates — tweak the numbers freely. Costs are computed live
# against the guest count below, so per-person figures update as the crew grows.
HUBS = ["NYC", "Bay Area", "South Florida"]

CITIES: dict[str, dict] = {
    "puerto_rico": {
        "name": "Puerto Rico",
        "emoji": "🌴",
        "tagline": "Rainforest, bioluminescent bays, and zero-passport Caribbean.",
        "hype": (
            "Picture this: **no passport, no currency exchange, all Caribbean.** "
            "Days in Old San Juan's blue cobblestones, frozen piña coladas at the "
            "bar that invented them, and a midnight kayak through a **glowing "
            "bioluminescent bay** that lights up with every paddle. El Yunque "
            "rainforest waterfalls by morning, rooftop salsa by night. February "
            "is dry-season perfect — high 70s–low 80s, blue skies, warm water."
        ),
        "lodging_total": 4200,          # whole villa for the weekend
        "food_pp": 240,                 # food + drinks per person for the weekend
        "activities": [
            ("Bioluminescent bay night kayak", 65),
            ("El Yunque rainforest + waterfall day", 55),
            ("Old San Juan food + rum walking tour", 70),
            ("Catamaran beach day w/ snorkel", 110),
        ],
        "flights": {"NYC": 260, "Bay Area": 470, "South Florida": 180},
        "travel_time": {"NYC": "~4h nonstop", "Bay Area": "~9h (1 stop)", "South Florida": "~2.5h nonstop"},
        "best_for": "Beach + adventure mix, no-passport ease.",
    },
    "cartagena": {
        "name": "Cartagena",
        "emoji": "💃",
        "tagline": "Walled-city color, rooftop sunsets, island day-trips.",
        "hype": (
            "The most **photogenic** weekend on the board. A 500-year-old walled "
            "city dripping in bougainvillea, candy-colored balconies, and "
            "horse-drawn-carriage sunsets. Days on the white sand of the Rosario "
            "Islands, nights on rooftop terraces with the whole old town glowing "
            "below. Incredible food, unreal exchange rate (your dollar goes "
            "*far*), and a nightlife scene built for exactly this trip. Late "
            "Feb / March is warm, dry, and golden."
        ),
        "lodging_total": 3600,          # luxe walled-city villa, lower $/night
        "food_pp": 180,
        "activities": [
            ("Rosario Islands private boat day", 95),
            ("Walled-city food + chiva party bus night", 75),
            ("Rooftop sunset + salsa lesson", 45),
            ("Cooking class + market tour", 60),
        ],
        "flights": {"NYC": 360, "Bay Area": 520, "South Florida": 240},
        "travel_time": {"NYC": "~5.5h nonstop", "Bay Area": "~9–10h (1 stop)", "South Florida": "~3.5h nonstop"},
        "best_for": "Best value + best photos; passport required.",
    },
    "las_vegas": {
        "name": "Las Vegas",
        "emoji": "🎰",
        "tagline": "Pools, shows, dinners, dancing — turnkey and domestic.",
        "hype": (
            "The **no-logistics** option that still goes all out. One flight, no "
            "passport, everyone lands within an hour of each other. Dayclub pool "
            "cabana, a blow-out group dinner, a show, and a table at night — all "
            "within a 10-minute walk. Spa mornings, brunch that doesn't end, and "
            "a suite big enough for the whole crew. February is cool and "
            "comfortable (highs in the 60s) — perfect for walking the Strip."
        ),
        "lodging_total": 3000,          # big Strip suite, 2 nights
        "food_pp": 320,                 # Vegas dinners + drinks add up
        "activities": [
            ("Dayclub pool cabana (split)", 90),
            ("Headliner show tickets", 120),
            ("Group tasting-menu dinner", 150),
            ("Nightclub table (split)", 110),
        ],
        "flights": {"NYC": 320, "Bay Area": 130, "South Florida": 300},
        "travel_time": {"NYC": "~5.5h nonstop", "Bay Area": "~1.5h nonstop", "South Florida": "~5h nonstop"},
        "best_for": "Zero hassle, all domestic, everything walkable.",
    },
}


def city_cost_breakdown(city: dict, guests: int) -> dict:
    """Per-person cost estimate for a city, given the guest count."""
    guests = max(1, guests)
    lodging_pp = city["lodging_total"] / guests
    activities_pp = sum(c for _, c in city["activities"])
    food_pp = city["food_pp"]
    avg_flight = sum(city["flights"].values()) / len(city["flights"])
    total_pp = lodging_pp + activities_pp + food_pp + avg_flight
    return {
        "lodging_pp": lodging_pp,
        "activities_pp": activities_pp,
        "food_pp": food_pp,
        "avg_flight": avg_flight,
        "total_pp": total_pp,
    }


# The app is fully open: anyone with the link can vote, add expenses, mark
# availability, etc. Only people with access to the GitHub repo can change the
# app itself (this code and the city templates below).
with st.sidebar:
    st.header("🥂 Bach Bash")
    st.caption("Plan together — everyone with the link can pitch in: vote, "
               "add expenses, mark dates, and more.")

    with st.expander("⚙️ Party settings"):
        s_name = st.text_input(
            "Party name", value=db.get_setting("party_name", "Bachelorette Bash")
        )
        s_goh = st.text_input(
            "Guest of honor", value=db.get_setting("guest_of_honor", "")
        )
        s_loc = st.text_input(
            "Destination / city", value=db.get_setting("location", "")
        )
        s_target = st.number_input(
            "Target budget per person ($)",
            min_value=0.0,
            step=50.0,
            value=float(db.get_setting("target_pp", "0") or 0),
        )
        s_notes = st.text_area(
            "Notes / vibe", value=db.get_setting("notes", ""), height=80
        )
        if st.button("💾 Save settings", type="primary"):
            db.set_setting("party_name", s_name)
            db.set_setting("guest_of_honor", s_goh)
            db.set_setting("location", s_loc)
            db.set_setting("target_pp", str(s_target))
            db.set_setting("notes", s_notes)
            st.success("Saved!")
            st.rerun()


# ----------------------------------------------------------------- header ---
party_name = db.get_setting("party_name", "Bachelorette Bash")
st.title(f"🥂 {party_name}")

tabs = st.tabs(
    [
        "🏠 Home",
        "👯 Crew",
        "📅 Availability",
        "🌆 City",
        "💰 Budget",
        "🧾 Expenses",
        "🗓️ Schedule",
        "💡 Ideas",
        "✅ Checklist",
    ]
)

# ================================================================= HOME ===
with tabs[0]:
    goh = db.get_setting("guest_of_honor", "") or "Tracey"
    location = db.get_setting("location", "")
    notes = db.get_setting("notes", "")

    # Confetti, but only once per session so it doesn't fire on every rerun.
    if not st.session_state.get("_welcomed"):
        st.balloons()
        st.session_state["_welcomed"] = True

    # --- Colorful hero banner ---
    sub = "She said YES to Brian 💍 — now let's have some Fung! 🎉"
    tagline = "Tracey Fung is tying the knot — time for one un-Fung-ettable send-off."
    loc_line = f"📍 {location} · " if location else ""
    st.markdown(
        f"""
        <div style="
            font-family: -apple-system, system-ui, sans-serif;
            border-radius: 22px;
            padding: 42px 28px;
            text-align: center;
            color: #fff;
            background: linear-gradient(135deg,#ff5fa2 0%,#ff8fb1 25%,#ffa6c9 45%,#c86dd7 75%,#7873f5 100%);
            box-shadow: 0 12px 32px rgba(200,90,160,0.35);
        ">
            <div style="font-size: 15px; letter-spacing: 4px; text-transform: uppercase; opacity:.9;">
                {loc_line}February / March 2027
            </div>
            <div style="font-size: 52px; font-weight: 800; margin: 8px 0 4px; text-shadow: 0 2px 10px rgba(0,0,0,.15);">
                🥂 {goh}'s Bachelorette 🥂
            </div>
            <div style="font-size: 22px; font-weight: 600; opacity:.97;">{sub}</div>
            <div style="font-size: 15px; font-weight: 500; opacity:.92; margin-top: 6px;">{tagline}</div>
            <div style="font-size: 30px; margin-top: 14px;">💃🪩🍾🌴✨👯‍♀️🎉</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.write("")

    # --- Photo gallery of the bride-to-be ---
    photos = list_photos()
    if photos:
        st.markdown("#### 💖 The Fung-to-be")
        cols = st.columns(min(3, len(photos)))
        for i, path in enumerate(photos):
            with cols[i % len(cols)]:
                st.image(path, use_container_width=True)
    else:
        st.info(
            "📸 No photos yet! Drop a few pics of the bride-to-be in below "
            "(or add them to `assets/photos/`) and this turns into her gallery."
        )

    with st.expander("📸 Add / manage photos"):
        ups = st.file_uploader(
            "Upload photos of the guest of honor",
            type=["jpg", "jpeg", "png", "gif", "webp"],
            accept_multiple_files=True,
        )
        if ups and st.button("Add to gallery", type="primary"):
            n = save_uploaded_photos(ups)
            st.success(f"Added {n} photo{'s' if n != 1 else ''}! 🎉")
            st.rerun()
        if photos:
            st.caption("Remove a photo:")
            for path in photos:
                if st.button(f"🗑 {os.path.basename(path)}", key=f"rmphoto_{path}"):
                    os.remove(path)
                    st.rerun()

    st.divider()

    # --- Fun, dynamic hype stats (everything here flows from real data) ---
    parts = db.list_participants()
    counts = db.city_vote_counts()
    avail = {(a["participant_id"], a["day"]): a["status"] for a in db.get_availability()}
    weekends = feb_mar_2027_weekends()

    # Leading city, if anyone has voted.
    lead_city = "TBD 🤔"
    if counts:
        lk = max(counts.items(), key=lambda kv: kv[1])[0]
        if lk in CITIES:
            lead_city = f"{CITIES[lk]['emoji']} {CITIES[lk]['name']}"

    # Best weekend so far by yes/maybe score.
    best_weekend = "Voting open 📅"
    score = {"yes": 1.0, "maybe": 0.5, "no": 0.0}
    scored = []
    for fri in weekends:
        s = [score[avail[(p["id"], fri.isoformat())]] for p in parts
             if (p["id"], fri.isoformat()) in avail]
        if s:
            scored.append((sum(s), fri))
    if scored:
        best_weekend = weekend_label(max(scored, key=lambda x: x[0])[1]) + " '27"

    m1, m2, m3 = st.columns(3)
    m1.metric("👯 Crew assembled", len(parts))
    m2.metric("🌆 Leading destination", lead_city)
    m3.metric("📅 Front-runner weekend", best_weekend)

    st.markdown(
        "#### 🎀 The mission\n"
        "One weekend. Zero chill. All Fung. Before Tracey becomes a Mrs., we're sending "
        "her off with sun, sips, and shenanigans. Use the tabs up top to **lock the crew**, "
        "**pick the weekend**, **vote on the city**, and **split the damage** — "
        "let's make it Fung-forgettable. ✨ _#FungAndGames · #LastFlingBeforeTheRing_"
    )
    if notes:
        st.success(f"💌 {notes}")

# ================================================================= CREW ===
with tabs[1]:
    st.subheader("Who's coming")
    with st.form("add_crew", clear_on_submit=True):
        cc1, cc2, cc3 = st.columns([2, 3, 1])
        name = cc1.text_input("Name")
        email = cc2.text_input("Email (optional)")
        cc3.markdown("<br>", unsafe_allow_html=True)
        if cc3.form_submit_button("Add"):
            if name.strip():
                db.add_participant(name, email)
                st.rerun()
            else:
                st.warning("Name required.")

    parts = db.list_participants()
    if not parts:
        st.info("Add your crew above to get started.")
    for p in parts:
        col1, col2, col3 = st.columns([3, 4, 1])
        col1.write(f"**{p['name']}**")
        col2.write(p["email"] or "—")
        if col3.button("Remove", key=f"rm_part_{p['id']}"):
            db.remove_participant(p["id"])
            st.rerun()

# ========================================================= AVAILABILITY ===
with tabs[2]:
    st.subheader("Which weekend works?")
    st.caption("We're choosing between the **Fri–Sun weekends in February & March 2027**.")
    parts = db.list_participants()
    weekends = feb_mar_2027_weekends()
    if not parts:
        st.info("Add crew members first (Crew tab).")
    else:
        who = st.selectbox("I am…", parts, format_func=lambda p: p["name"])
        existing = {
            (a["participant_id"], a["day"]): a["status"] for a in db.get_availability()
        }
        st.caption("Mark each weekend. ✅ Yes · 🤔 Maybe · ❌ No")
        with st.form("avail_form"):
            picks = {}
            for i in range(0, len(weekends), 4):
                cols = st.columns(min(4, len(weekends) - i))
                for j, fri in enumerate(weekends[i : i + 4]):
                    cur = existing.get((who["id"], fri.isoformat()), "maybe")
                    picks[fri] = cols[j].radio(
                        weekend_label(fri),
                        ["yes", "maybe", "no"],
                        index=["yes", "maybe", "no"].index(cur),
                        key=f"av_{who['id']}_{fri.isoformat()}",
                        format_func=lambda s: {"yes": "✅", "maybe": "🤔", "no": "❌"}[s],
                        horizontal=True,
                    )
            if st.form_submit_button("💾 Save my availability", type="primary"):
                for fri, status in picks.items():
                    db.set_availability(who["id"], fri, status)
                st.success("Saved!")
                st.rerun()

        st.divider()
        st.subheader("Best weekend (everyone)")
        score = {"yes": 1.0, "maybe": 0.5, "no": 0.0}
        rows = []
        for fri in weekends:
            day_scores = []
            for p in parts:
                s = existing.get((p["id"], fri.isoformat()), None)
                if s is not None:
                    day_scores.append(score[s])
            if day_scores:
                rows.append(
                    {
                        "Weekend": weekend_label(fri),
                        "Score": round(sum(day_scores), 2),
                        "✅": sum(1 for p in parts if existing.get((p["id"], fri.isoformat())) == "yes"),
                        "🤔": sum(1 for p in parts if existing.get((p["id"], fri.isoformat())) == "maybe"),
                        "❌": sum(1 for p in parts if existing.get((p["id"], fri.isoformat())) == "no"),
                    }
                )
        if rows:
            df = pd.DataFrame(rows).sort_values("Score", ascending=False)
            st.dataframe(df, use_container_width=True, hide_index=True)
            best = df.iloc[0]
            st.success(f"🏆 Top pick: **{best['Weekend']} 2027** (score {best['Score']})")
        else:
            st.info("No availability logged yet.")

# ================================================================= CITY ===
with tabs[3]:
    st.subheader("🌆 Where are we going?")
    st.caption("Read the vibe, check the damage, then cast your vote. "
               "Costs update live with the guest count.")

    parts = db.list_participants()
    votes = db.get_city_votes()
    counts = db.city_vote_counts()

    gc1, gc2 = st.columns([1, 2])
    guests = gc1.number_input(
        "Guest count (for cost estimates)",
        min_value=1,
        step=1,
        value=max(1, len(parts)),
    )
    voter = None
    if parts:
        voter = gc2.selectbox(
            "Voting as…", parts, format_func=lambda p: p["name"], key="city_voter"
        )
        cur_vote = votes.get(voter["id"]) if voter else None
        if cur_vote in CITIES:
            gc2.caption(f"Your current vote: **{CITIES[cur_vote]['emoji']} {CITIES[cur_vote]['name']}**")
    else:
        gc2.caption("Add crew members to enable voting.")

    city_keys = list(CITIES.keys())
    city_tabs = st.tabs([f"{CITIES[k]['emoji']} {CITIES[k]['name']}" for k in city_keys])
    for key, ctab in zip(city_keys, city_tabs):
        city = CITIES[key]
        with ctab:
            st.markdown(f"### {city['emoji']} {city['name']}")
            st.markdown(f"*{city['tagline']}*")
            st.markdown(city["hype"])
            st.caption(f"💖 Best for: {city['best_for']}")

            costs = city_cost_breakdown(city, guests)
            st.markdown("#### 💸 Estimated cost per person")
            cm1, cm2, cm3, cm4, cm5 = st.columns(5)
            cm1.metric("🏠 Airbnb", money(costs["lodging_pp"]), help=f"{money(city['lodging_total'])} total ÷ {guests} guests")
            cm2.metric("🎉 Activities", money(costs["activities_pp"]))
            cm3.metric("🍽️ Food/drinks", money(costs["food_pp"]))
            cm4.metric("✈️ Flights (avg)", money(costs["avg_flight"]))
            cm5.metric("**Total / person**", money(costs["total_pp"]))
            st.caption(
                f"For {guests} guests, that's about **{money(costs['total_pp'] * guests)}** "
                "all-in for the group. Airbnb is split across the crew, so the per-person "
                "lodging drops as more people join."
            )

            ac1, ac2 = st.columns(2)
            with ac1:
                st.markdown("**🎉 Activities (per person)**")
                act_df = pd.DataFrame(
                    [{"Activity": n, "Est. $": money(c)} for n, c in city["activities"]]
                )
                st.dataframe(act_df, use_container_width=True, hide_index=True)
            with ac2:
                st.markdown("**🧭 Getting there**")
                log_df = pd.DataFrame(
                    [
                        {
                            "From": hub,
                            "Flight time": city["travel_time"][hub],
                            "Est. airfare": money(city["flights"][hub]),
                        }
                        for hub in HUBS
                    ]
                )
                st.dataframe(log_df, use_container_width=True, hide_index=True)

            st.divider()
            n_here = counts.get(key, 0)
            vc1, vc2 = st.columns([1, 2])
            already = voter is not None and votes.get(voter["id"]) == key
            if vc1.button(
                "✅ Voted!" if already else f"🗳️ Vote for {city['name']}",
                key=f"vote_city_{key}",
                type="primary" if not already else "secondary" or voter is None or already,
            ):
                db.set_city_vote(voter["id"], key)
                st.rerun()
            vc2.markdown(f"**{n_here}** vote{'s' if n_here != 1 else ''} so far")

    st.divider()
    st.subheader("🏆 Vote tally")
    if counts:
        tally = pd.DataFrame(
            [
                {"City": f"{CITIES[k]['emoji']} {CITIES[k]['name']}", "Votes": counts.get(k, 0)}
                for k in city_keys
            ]
        )
        st.bar_chart(tally.set_index("City")["Votes"])
        leader = max(counts.items(), key=lambda kv: kv[1])
        if leader[0] in CITIES:
            st.success(f"🥇 Leading: **{CITIES[leader[0]]['emoji']} {CITIES[leader[0]]['name']}** "
                       f"with {leader[1]} vote{'s' if leader[1] != 1 else ''}")
    else:
        st.info("No votes yet — be the first above.")

# =============================================================== BUDGET ===
with tabs[4]:
    st.subheader("Budget summary")
    parts = db.list_participants()
    target_pp = float(db.get_setting("target_pp", "0") or 0)
    with st.form("add_budget", clear_on_submit=True):
        b1, b2, b3 = st.columns([2, 1, 3])
        cat = b1.text_input("Category", placeholder="Airbnb, dinner, activities…")
        amt = b2.number_input("Planned $", min_value=0.0, step=25.0)
        bnotes = b3.text_input("Notes")
        if st.form_submit_button("Add line item"):
            if cat.strip():
                db.add_budget_item(cat, amt, bnotes)
                st.rerun()

    items = db.list_budget_items()
    if items:
        df = pd.DataFrame([dict(i) for i in items])[["category", "planned", "notes"]]
        df.columns = ["Category", "Planned $", "Notes"]
        st.dataframe(df, use_container_width=True, hide_index=True)
        total = sum(float(i["planned"]) for i in items)
        c1, c2, c3 = st.columns(3)
        c1.metric("Total planned", money(total))
        c2.metric("Per person", money(total / len(parts)) if parts else "$0.00")
        if target_pp and parts:
            delta = total / len(parts) - target_pp
            c3.metric("vs target / person", money(target_pp), delta=money(-delta), delta_color="inverse")
        st.bar_chart(df.set_index("Category")["Planned $"])
        with st.expander("Remove a line item"):
            for i in items:
                if st.button(f"Remove · {i['category']} ({money(i['planned'])})", key=f"rmb_{i['id']}"):
                    db.remove_budget_item(i["id"])
                    st.rerun()
    else:
        st.info("Add budget line items above.")

# ============================================================= EXPENSES ===
with tabs[5]:
    st.subheader("Expenses — Splitwise style")
    parts = db.list_participants()
    pmap = participant_map()
    if len(parts) < 1:
        st.info("Add crew members first (Crew tab).")
    else:
        with st.form("add_expense", clear_on_submit=True):
            e1, e2 = st.columns([3, 1])
            desc = e1.text_input("What was it?", placeholder="Dinner at …")
            amount = e2.number_input("Amount $", min_value=0.0, step=5.0)
            e3, e4 = st.columns(2)
            payer = e3.selectbox("Paid by", parts, format_func=lambda p: p["name"])
            spent_on = e4.date_input("Date", value=date.today())
            split_among = st.multiselect(
                "Split among",
                parts,
                default=parts,
                format_func=lambda p: p["name"],
            )
            if st.form_submit_button("Add expense", type="primary"):
                if desc.strip() and amount > 0 and split_among:
                    db.add_expense(
                        desc, amount, payer["id"], [p["id"] for p in split_among], spent_on
                    )
                    st.rerun()
                else:
                    st.warning("Need a description, amount, and at least one person to split with.")

        expenses = db.list_expenses()
        shares = db.get_expense_shares()
        if expenses:
            rows = [
                {
                    "Date": e["spent_on"],
                    "Description": e["description"],
                    "Amount": money(float(e["amount"])),
                    "Paid by": e["payer_name"],
                }
                for e in expenses
            ]
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
            st.caption(f"Total logged: **{money(sum(float(e['amount']) for e in expenses))}**")

            st.divider()
            st.subheader("⚖️ Settle up")
            balances = net_balances(expenses, shares)
            bal_rows = [
                {
                    "Person": pmap.get(pid, f"#{pid}"),
                    "Net": money(v),
                    "Status": "is owed" if v > 0.005 else ("owes" if v < -0.005 else "even"),
                }
                for pid, v in sorted(balances.items(), key=lambda kv: -kv[1])
            ]
            st.dataframe(pd.DataFrame(bal_rows), use_container_width=True, hide_index=True)
            transfers = settle(balances)
            if transfers:
                st.markdown("**Suggested payments to settle everything:**")
                for t in transfers:
                    st.write(
                        f"💸 **{pmap.get(t.frm, t.frm)}** → **{pmap.get(t.to, t.to)}**: "
                        f"{money(t.amount)}"
                    )
            else:
                st.success("All settled — nobody owes anything! 🎉")

            with st.expander("Remove an expense"):
                for e in expenses:
                    if st.button(
                        f"Remove · {e['description']} ({money(float(e['amount']))})",
                        key=f"rme_{e['id']}",
                    ):
                        db.remove_expense(e["id"])
                        st.rerun()
        else:
            st.info("No expenses logged yet.")

# ============================================================= SCHEDULE ===
with tabs[6]:
    st.subheader("🗓️ Schedule")

    # --- Pretty embedded Google Calendar (read-only month view) ---
    embed_id = db.get_setting("gcal_embed_id", "") or ""
    if embed_id:
        if embed_id.startswith("http"):
            src = embed_id
        else:
            src = (
                "https://calendar.google.com/calendar/embed?"
                + urllib.parse.urlencode({"src": embed_id, "ctz": "America/New_York"})
            )
        components.iframe(src, height=600, scrolling=True)
    else:
        st.info("Add a shared Google Calendar below to show a live embedded calendar here.")

    with st.expander("⚙️ Embedded calendar settings"):
        st.caption(
            "Paste the **calendar ID** of a *public* (or 'see all event details' "
            "shared) Google Calendar — find it under the calendar's Settings → "
            "*Integrate calendar → Calendar ID* (looks like `…@group.calendar.google.com`). "
            "You can also paste a full embed `src` URL."
        )
        new_embed = st.text_input("Calendar ID or embed URL", value=embed_id)
        sc1, sc2 = st.columns(2)
        if sc1.button("Save calendar", type="primary"):
            db.set_setting("gcal_embed_id", new_embed.strip())
            st.rerun()
        if embed_id and sc2.button("Remove embed"):
            db.set_setting("gcal_embed_id", "")
            st.rerun()

    st.divider()
    st.markdown("**Two-way sync** — add an event here and it lands on the shared calendar.")

    if not gcal.libs_available() or not gcal.credentials_present():
        st.warning(gcal.setup_hint())
        st.info(
            "While Google sync isn't set up, use the **Add to Google Calendar** links "
            "below — those work for everyone with no setup."
        )
        local_only = True
    else:
        local_only = False
        cc1, cc2 = st.columns([1, 1])
        if not gcal.is_connected():
            if cc1.button("🔗 Connect Google Calendar", type="primary"):
                with st.spinner("Opening Google sign-in in your browser…"):
                    try:
                        gcal.connect()
                        st.success("Connected!")
                        st.rerun()
                    except Exception as exc:
                        st.error(f"Connection failed: {exc}")
        else:
            if cc2.button("Disconnect"):
                gcal.disconnect()
                st.rerun()

    if not local_only and gcal.is_connected():
        try:
            cals = gcal.list_calendars()
            cal_choice = st.selectbox(
                "Calendar",
                cals,
                format_func=lambda c: c["summary"] + (" (primary)" if c["primary"] else ""),
            )
            cal_id = cal_choice["id"]

            with st.form("add_event", clear_on_submit=True):
                st.markdown("**Add an event**")
                ev_title = st.text_input("Title", placeholder="Brunch reservation")
                d1, d2, d3 = st.columns(3)
                ev_date = d1.date_input("Date", value=date.today())
                ev_start = d2.time_input("Start", value=time(12, 0))
                ev_end = d3.time_input("End", value=time(14, 0))
                ev_loc = st.text_input("Location")
                ev_desc = st.text_area("Details", height=80)
                if st.form_submit_button("➕ Add to shared calendar", type="primary"):
                    start_dt = datetime.combine(ev_date, ev_start)
                    end_dt = datetime.combine(ev_date, ev_end)
                    try:
                        gcal.create_event(cal_id, ev_title, start_dt, end_dt, ev_loc, ev_desc)
                        st.success("Added to Google Calendar!")
                        st.rerun()
                    except Exception as exc:
                        st.error(f"Couldn't add event: {exc}")

            st.divider()
            st.markdown("**Upcoming events**")
            now = datetime.now()
            events = gcal.list_events(cal_id, now - timedelta(days=1), now + timedelta(days=120))
            if events:
                for e in events:
                    c1, c2 = st.columns([5, 1])
                    when = e["start"]
                    c1.write(
                        f"**{e['summary']}** — {when}"
                        + (f" · 📍 {e['location']}" if e["location"] else "")
                    )
                    if c2.button("Delete", key=f"del_ev_{e['id']}"):
                        gcal.delete_event(cal_id, e["id"])
                        st.rerun()
            else:
                st.info("No upcoming events on this calendar.")
        except Exception as exc:
            st.error(f"Google Calendar error: {exc}")

    # Local schedule builder + add-to-calendar links (always available).
    st.divider()
    st.markdown("**Quick add-to-calendar link generator** (no Google setup needed)")
    with st.form("ics_event", clear_on_submit=True):
        q1, q2, q3, q4 = st.columns(4)
        qt = q1.text_input("Event")
        qd = q2.date_input("Date ", value=date.today(), key="qdate")
        qs = q3.time_input("Start ", value=time(18, 0), key="qstart")
        qe = q4.time_input("End ", value=time(20, 0), key="qend")
        qloc = st.text_input("Location ", key="qloc")
        if st.form_submit_button("Generate link"):
            if qt.strip():
                link = gcal_add_link(
                    qt,
                    datetime.combine(qd, qs),
                    datetime.combine(qd, qe),
                    qloc,
                )
                st.markdown(f"[➕ Add **{qt}** to Google Calendar]({link})")
                st.caption("Share this link with the crew — each person taps it to add the event.")

# ================================================================ IDEAS ===
with tabs[7]:
    st.subheader("💡 Ideas & polls")
    parts = db.list_participants()
    with st.form("add_idea", clear_on_submit=True):
        i1, i2 = st.columns([2, 3])
        it = i1.text_input("Idea / activity")
        iu = i2.text_input("Link (optional)")
        inotes = st.text_input("Notes")
        if st.form_submit_button("Add idea"):
            if it.strip():
                db.add_idea(it, iu, inotes)
                st.rerun()

    ideas = db.list_ideas()
    counts = db.vote_counts()
    if ideas:
        voter = None
        if parts:
            voter = st.selectbox("Vote as…", parts, format_func=lambda p: p["name"], key="voter")
        for idea in sorted(ideas, key=lambda x: -counts.get(x["id"], 0)):
            c1, c2, c3 = st.columns([5, 1, 1])
            label = f"**{idea['title']}**"
            if idea["url"]:
                label += f"  ·  [link]({idea['url']})"
            if idea["notes"]:
                label += f"  \n_{idea['notes']}_"
            c1.markdown(f"{label}  \n👍 {counts.get(idea['id'], 0)} votes")
            if voter and c2.button("👍 Vote", key=f"vote_{idea['id']}"):
                db.toggle_vote(idea["id"], voter["id"])
                st.rerun()
            if c3.button("🗑", key=f"rmi_{idea['id']}"):
                db.remove_idea(idea["id"])
                st.rerun()
    else:
        st.info("Drop some activity ideas and let the crew vote.")

# ============================================================ CHECKLIST ===
with tabs[8]:
    st.subheader("✅ Checklist")
    parts = db.list_participants()
    pmap = participant_map()
    with st.form("add_check", clear_on_submit=True):
        c1, c2 = st.columns([4, 2])
        lbl = c1.text_input("To-do / packing item")
        owner = c2.selectbox(
            "Owner", [None] + parts, format_func=lambda p: "—" if p is None else p["name"]
        )
        if st.form_submit_button("Add"):
            if lbl.strip():
                db.add_checklist_item(lbl, owner["id"] if owner else None)
                st.rerun()

    items = db.list_checklist()
    if items:
        done_n = sum(1 for i in items if i["done"])
        st.progress(done_n / len(items), text=f"{done_n}/{len(items)} done")
        for i in items:
            c1, c2, c3 = st.columns([6, 2, 1])
            checked = c1.checkbox(
                i["label"], value=bool(i["done"]), key=f"chk_{i['id']}"
            )
            if checked != bool(i["done"]):
                db.set_checklist_done(i["id"], checked)
                st.rerun()
            c2.caption(f"👤 {i['owner_name']}" if i["owner_name"] else "")
            if c3.button("🗑", key=f"rmc_{i['id']}"):
                db.remove_checklist_item(i["id"])
                st.rerun()
    else:
        st.info("Build your shared packing / to-do list here.")
