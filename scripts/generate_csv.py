"""
Generate a Splitwise-format CSV for bulk-importing into Tricount.

Edit PEOPLE, EXPENSES, and SETTLEMENTS below, then run:
    python generate_csv.py

The output file path is set at the bottom — adjust as needed.

WHY THIS SCRIPT EXISTS
----------------------
Tricount's "Import from Splitwise" feature accepts CSVs in Splitwise's exact
export format. Generating that CSV directly (without ever using a real
Splitwise account) is the fastest way to load many expenses at once. The format
has strict byte-level requirements (no BOM, LF only, specific blank lines) that
this script gets right.

DATA MODEL
----------
- PEOPLE: ordered list of names. The order is the column order in the CSV.
- EXPENSES: each is a dict with date, description, category, cost, payer,
  and participants (subset of PEOPLE who share the cost).
- SETTLEMENTS: prior cash transfers from one person to another. They appear
  in the CSV as rows with category "Pago".
"""

from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

# ============================================================
# EDIT THIS SECTION WITH YOUR DATA
# ============================================================
#
# Example: 4-friend weekend road trip with shared expenses, asymmetric splits,
# and one prior cash settlement. Replace with your own data.

PEOPLE = ["Alice", "Bob", "Charlie", "Dana"]

CURRENCY = "EUR"

# Each expense: date, description, category, cost (€), payer, participants.
# Participants is a subset of PEOPLE — the cost is divided equally among them.
EXPENSES = [
    {
        "date": "2026-07-04",
        "desc": "Hotel - 2 nights",
        "cat": "Hotel",
        "cost": "320.00",
        "payer": "Alice",
        "participants": ["Alice", "Bob", "Charlie", "Dana"],
    },
    {
        "date": "2026-07-04",
        "desc": "Gasoline round trip",
        "cat": "Alquiler de coche",
        "cost": "85.50",
        "payer": "Bob",
        "participants": ["Alice", "Bob", "Charlie", "Dana"],
    },
    {
        "date": "2026-07-04",
        "desc": "Dinner Friday",
        "cat": "General",
        "cost": "112.40",
        "payer": "Charlie",
        "participants": ["Alice", "Bob", "Charlie", "Dana"],
    },
    {
        "date": "2026-07-05",
        "desc": "Museum tickets",
        "cat": "General",
        "cost": "60.00",
        "payer": "Alice",
        # Bob skipped the museum — split among 3 only
        "participants": ["Alice", "Charlie", "Dana"],
    },
    {
        "date": "2026-07-05",
        "desc": "Lunch Saturday",
        "cat": "General",
        "cost": "78.00",
        "payer": "Dana",
        "participants": ["Alice", "Bob", "Charlie", "Dana"],
    },
    {
        "date": "2026-07-05",
        "desc": "Airport taxi for Bob",
        "cat": "General",
        "cost": "35.00",
        "payer": "Alice",
        # Only Bob benefits — payer covers the whole thing for him
        "participants": ["Bob"],
    },
]

# Each settlement: date, payer (sent money), recipient (received money), amount.
# These appear in the CSV as rows with category "Pago" — Tricount will treat
# them as payments rather than expenses.
SETTLEMENTS = [
    # Example: Bob transferred 50 EUR to Alice before the trip to settle a
    # previous unrelated debt.
    {"date": "2026-06-15", "payer": "Bob", "recipient": "Alice", "amount": "50.00"},
]

SALDO_DATE = "2026-07-05"  # any date you want for the Saldo total row

OUTPUT_PATH = Path.home() / "Downloads" / "tricount-import.csv"


# ============================================================
# IMPLEMENTATION (you usually don't need to touch below)
# ============================================================

def q2(x):
    """Round to 2 decimals using ROUND_HALF_UP (matches Splitwise's behavior)."""
    return Decimal(str(x)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def display_name(name):
    """Return the form Splitwise uses in 'X pagó Y' descriptions.

    Splitwise convention: if a name ends in a single capital letter
    (i.e. 'first name + surname initial' like 'Alice S'), it appends a period
    in the description text -> 'Alice S.'. For names without that pattern
    (e.g. 'Alice'), it uses the name as-is.
    """
    parts = name.rsplit(" ", 1)
    if len(parts) == 2 and len(parts[1]) == 1 and parts[1].isupper():
        return f"{name}."
    return name


def expense_row(exp):
    """Compute the per-person net amounts for an expense and return the CSV row.

    Logic: each participant owes their rounded share. The payer ALSO
    covered the full cost out of pocket, which we add back to their balance.
    Any rounding residual is absorbed by the payer to make the row sum to 0.
    Works whether the payer is in the participants list or not.
    """
    cost = q2(exp["cost"])
    n = len(exp["participants"])
    share = q2(cost / n)
    payer = exp["payer"]

    nets = {p: Decimal("0") for p in PEOPLE}
    # Each participant "consumes" their share
    for p in exp["participants"]:
        nets[p] = -share
    # Payer paid the whole cost out of pocket
    nets[payer] += cost
    # Absorb rounding residual on the payer so the row sums to exactly 0
    residual = sum(nets.values())
    if residual != 0:
        nets[payer] -= residual

    # Sanity: row must sum to 0
    total = sum(nets.values())
    assert abs(total) < Decimal("0.01"), f"Row {exp['desc']} sums to {total}, not 0"

    cells = [exp["date"], exp["desc"], exp["cat"], f"{cost:.2f}", CURRENCY]
    cells += [f"{nets[p]:.2f}" for p in PEOPLE]
    return cells


def settlement_row(s):
    """Settlement: payer +amount, recipient -amount, others 0. Category 'Pago'."""
    amount = q2(s["amount"])
    nets = {p: Decimal("0") for p in PEOPLE}
    nets[s["payer"]] = amount
    nets[s["recipient"]] = -amount

    desc = f"{display_name(s['payer'])} pagó {display_name(s['recipient'])}"
    cells = [s["date"], desc, "Pago", f"{amount:.2f}", CURRENCY]
    cells += [f"{nets[p]:.2f}" for p in PEOPLE]
    return cells


def saldo_total(rows):
    """Sum the per-person columns across all data rows."""
    totals = {p: Decimal("0") for p in PEOPLE}
    for row in rows:
        for i, p in enumerate(PEOPLE):
            totals[p] += Decimal(row[5 + i])
    cells = [SALDO_DATE, "Saldo total", " ", " ", CURRENCY]
    cells += [f"{totals[p]:.2f}" for p in PEOPLE]
    return cells, totals


def main():
    header = ["Fecha", "Descripción", "Categoría", "Coste", "Moneda"] + PEOPLE
    data_rows = [expense_row(e) for e in EXPENSES] + [settlement_row(s) for s in SETTLEMENTS]
    saldo, totals = saldo_total(data_rows)

    # Build the CSV with the EXACT Splitwise format:
    # header\n\n<rows separated by \n>\n\n<saldo>\n\n
    lines = [",".join(header), ""]                 # header + blank line
    lines += [",".join(row) for row in data_rows]
    lines += ["", ",".join(saldo), ""]             # blank, saldo, trailing blank
    text = "\n".join(lines) + "\n"                  # final \n so file ends with \n\n

    # Binary write to guarantee LF and no BOM, regardless of OS
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_bytes(text.encode("utf-8"))

    # Validation report
    encoded = text.encode("utf-8")
    bom = b"\xef\xbb\xbf"
    has_bom = encoded[:3] == bom
    has_crlf = "\r\n" in text
    print(f"Wrote {OUTPUT_PATH} ({len(encoded)} bytes)")
    print(f"Has BOM: {has_bom}")
    print(f"Has CRLF: {has_crlf}")
    print(f"Rows: {len(data_rows)} ({len(EXPENSES)} expenses + {len(SETTLEMENTS)} settlements)")
    print()
    print("Final balance per person:")
    for p in PEOPLE:
        sign = "+" if totals[p] >= 0 else ""
        print(f"  {p:10s} {sign}{totals[p]:.2f} {CURRENCY}")
    print(f"  {'SUM':10s} {sum(totals.values()):.2f}  (must be 0)")


if __name__ == "__main__":
    main()
