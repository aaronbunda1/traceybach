"""Tests: settle-up math + DB round-trips + Streamlit AppTest smoke.

Run:  pytest -q
"""

import os
import sys
import tempfile
from datetime import date

# Use a throwaway DB before importing the app modules.
_TMP = tempfile.mkdtemp()
os.environ["BACH_DB_PATH"] = os.path.join(_TMP, "test.db")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import db  # noqa: E402
from settle import net_balances, settle  # noqa: E402


def setup_function(_):
    # Fresh DB per test.
    if os.path.exists(db.DB_PATH):
        os.remove(db.DB_PATH)
    db.init_db()


def test_participants_roundtrip():
    a = db.add_participant("Alice", "a@x.com")
    b = db.add_participant("Bea")
    names = {p["name"] for p in db.list_participants()}
    assert names == {"Alice", "Bea"}
    db.remove_participant(a)
    assert {p["name"] for p in db.list_participants()} == {"Bea"}
    assert b  # id returned


def test_expense_shares_sum_to_total():
    a = db.add_participant("A")
    b = db.add_participant("B")
    c = db.add_participant("C")
    # $100 split 3 ways doesn't divide evenly; shares must still total 100.
    db.add_expense("Dinner", 100.0, a, [a, b, c])
    shares = db.get_expense_shares()
    assert round(sum(float(s["share"]) for s in shares), 2) == 100.0


def test_settle_simple():
    # A pays $90 for A,B,C → B and C each owe $30.
    bal = {1: 60.0, 2: -30.0, 3: -30.0}
    transfers = settle(bal)
    assert len(transfers) == 2
    assert all(t.to == 1 for t in transfers)
    assert round(sum(t.amount for t in transfers), 2) == 60.0


def test_net_balances_from_db():
    a = db.add_participant("A")
    b = db.add_participant("B")
    db.add_expense("Lunch", 50.0, a, [a, b])  # B owes A 25
    bal = net_balances(db.list_expenses(), db.get_expense_shares())
    assert round(bal[a], 2) == 25.0
    assert round(bal[b], 2) == -25.0
    transfers = settle(bal)
    assert len(transfers) == 1
    assert transfers[0].frm == b and transfers[0].to == a
    assert round(transfers[0].amount, 2) == 25.0


def test_availability_and_settings():
    a = db.add_participant("A")
    db.set_availability(a, date(2026, 7, 4), "yes")
    db.set_availability(a, date(2026, 7, 4), "no")  # overwrite
    avail = db.get_availability()
    assert len(avail) == 1 and avail[0]["status"] == "no"
    db.set_setting("party_name", "Vegas")
    assert db.get_setting("party_name") == "Vegas"


def test_ideas_votes_and_checklist():
    a = db.add_participant("A")
    i = db.add_idea("Spa day", "http://x")
    db.toggle_vote(i, a)
    assert db.vote_counts()[i] == 1
    db.toggle_vote(i, a)  # toggle off
    assert db.vote_counts().get(i, 0) == 0
    ci = db.add_checklist_item("Sunscreen", a)
    db.set_checklist_done(ci, True)
    assert db.list_checklist()[0]["done"] == 1


def test_streamlit_apptest_smoke():
    from streamlit.testing.v1 import AppTest

    app_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "app.py")
    at = AppTest.from_file(app_path, default_timeout=30).run()
    assert not at.exception
    # All 9 top-level tabs render (plus the City tab's nested city sub-tabs).
    labels = {t.label for t in at.tabs}
    for expected in (
        "🏠 Home",
        "👯 Crew",
        "📅 Availability",
        "🌆 City",
        "💰 Budget",
        "🧾 Expenses",
        "🗓️ Schedule",
        "💡 Ideas",
        "✅ Checklist",
    ):
        assert expected in labels, f"missing tab: {expected}"
