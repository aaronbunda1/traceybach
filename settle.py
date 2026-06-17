"""Splitwise-style balance + settle-up math.

Pure functions over plain dicts/lists so they're trivial to unit test without
touching the database or Streamlit.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Transfer:
    frm: int  # participant id who pays
    to: int   # participant id who receives
    amount: float


def net_balances(expenses, shares) -> dict[int, float]:
    """Return {participant_id: net} where net > 0 means they are owed money.

    expenses: rows with keys id, amount, paid_by
    shares:   rows with keys expense_id, participant_id, share
    """
    bal: dict[int, float] = {}
    for e in expenses:
        bal[e["paid_by"]] = bal.get(e["paid_by"], 0.0) + float(e["amount"])
    for s in shares:
        pid = s["participant_id"]
        bal[pid] = bal.get(pid, 0.0) - float(s["share"])
    # Round to cents to avoid float dust.
    return {pid: round(v, 2) for pid, v in bal.items()}


def settle(balances: dict[int, float]) -> list[Transfer]:
    """Greedily minimize the number of transfers to settle all balances.

    Classic creditor/debtor matching: repeatedly match the largest debtor to
    the largest creditor. Produces at most n-1 transfers.
    """
    creditors = sorted(
        [[pid, amt] for pid, amt in balances.items() if amt > 0.005],
        key=lambda x: -x[1],
    )
    debtors = sorted(
        [[pid, -amt] for pid, amt in balances.items() if amt < -0.005],
        key=lambda x: -x[1],
    )
    transfers: list[Transfer] = []
    i = j = 0
    while i < len(debtors) and j < len(creditors):
        d_pid, d_amt = debtors[i]
        c_pid, c_amt = creditors[j]
        pay = round(min(d_amt, c_amt), 2)
        if pay > 0:
            transfers.append(Transfer(frm=d_pid, to=c_pid, amount=pay))
        debtors[i][1] = round(d_amt - pay, 2)
        creditors[j][1] = round(c_amt - pay, 2)
        if debtors[i][1] <= 0.005:
            i += 1
        if creditors[j][1] <= 0.005:
            j += 1
    return transfers
