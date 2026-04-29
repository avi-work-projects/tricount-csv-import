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

- EXPENSES: each entry is a dict with date, description, category, cost, and
  EITHER:
    * "payer" + "participants"  (compact form: 1 payer, equal split)
    * "paid_by" + "owed_by"     (general form: dicts with per-person amounts)
  Optional: "currency" overrides the default for that row.

- SETTLEMENTS: prior cash transfers from one person to another. They appear
  in the CSV as rows with category "Pago".

Negative costs are valid — they model vendor refunds (e.g., a hotel returns
money to the group). The script handles them transparently.

VALIDATION
----------
After computing all rows, the script verifies that each row sums to 0 and
prints the final per-person balance. Any mismatch raises an AssertionError.
"""

from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

# ============================================================
# EDIT THIS SECTION WITH YOUR DATA
# ============================================================
#
# Example: 4-friend weekend road trip with various split scenarios that this
# script supports. Replace with your own data.

PEOPLE = ["Alice", "Bob", "Charlie", "Dana"]

CURRENCY = "EUR"  # default currency for all rows; override per expense if needed

EXPENSES = [
    # Compact form: 1 payer, equal split among participants
    {
        "date": "2026-07-04",
        "desc": "Hotel - 2 nights",
        "cat": "Hotel",
        "cost": "320.00",
        "payer": "Alice",
        "participants": ["Alice", "Bob", "Charlie", "Dana"],
    },
    # Compact form: equal split among a subset (Bob skipped)
    {
        "date": "2026-07-05",
        "desc": "Museum tickets",
        "cat": "General",
        "cost": "60.00",
        "payer": "Alice",
        "participants": ["Alice", "Charlie", "Dana"],
    },
    # Compact form: payer covers a single person (Bob's airport taxi)
    {
        "date": "2026-07-05",
        "desc": "Airport taxi for Bob",
        "cat": "General",
        "cost": "35.00",
        "payer": "Alice",
        "participants": ["Bob"],
    },
    # GENERAL form: multiple payers (Alice paid 60, Bob paid 40), equal split among 4
    {
        "date": "2026-07-04",
        "desc": "Dinner Friday",
        "cat": "Restaurantes",
        "cost": "100.00",
        "paid_by": {"Alice": "60.00", "Bob": "40.00"},
        "owed_by": {"Alice": "25.00", "Bob": "25.00", "Charlie": "25.00", "Dana": "25.00"},
    },
    # GENERAL form: unequal split (Alice ate more, Dana ate less)
    {
        "date": "2026-07-05",
        "desc": "Lunch Saturday",
        "cat": "Restaurantes",
        "cost": "78.00",
        "paid_by": {"Dana": "78.00"},
        "owed_by": {"Alice": "30.00", "Bob": "20.00", "Charlie": "20.00", "Dana": "8.00"},
    },
    # NEGATIVE cost: vendor refund (hotel refunded 30€ for a broken AC, split among 4)
    {
        "date": "2026-07-06",
        "desc": "Refund hotel AC issue",
        "cat": "Hotel",
        "cost": "-30.00",
        "paid_by": {"Alice": "-30.00"},  # Alice received the refund
        "owed_by": {"Alice": "-7.50", "Bob": "-7.50", "Charlie": "-7.50", "Dana": "-7.50"},
    },
    # CURRENCY override: a single expense in a different currency
    {
        "date": "2026-07-04",
        "desc": "Gasoline (paid in USD on the road)",
        "cat": "Alquiler de coche",
        "cost": "85.50",
        "currency": "USD",
        "payer": "Bob",
        "participants": ["Alice", "Bob", "Charlie", "Dana"],
    },
]

SETTLEMENTS = [
    # Bob transferred 50 EUR to Alice before the trip
    {"date": "2026-06-15", "payer": "Bob", "recipient": "Alice", "amount": "50.00"},
]

SALDO_DATE = "2026-07-06"
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
    (i.e. 'first name + surname initial' like 'Angel V'), it appends a period
    in the description text -> 'Angel V.'. For names without that pattern
    (e.g. 'Juanma'), it uses the name as-is.
    """
    parts = name.rsplit(" ", 1)
    if len(parts) == 2 and len(parts[1]) == 1 and parts[1].isupper():
        return f"{name}."
    return name


def normalize_expense(exp):
    """Convert any supported expense form to the canonical (paid_by, owed_by) form.

    The canonical form is two dicts {name: Decimal}. Compact-form expenses
    (`payer` + `participants`) are expanded into equal shares with the payer
    covering the full cost. Rounding residuals are absorbed by the payer so
    each row sums to 0 exactly.
    """
    cost = q2(exp["cost"])

    if "paid_by" in exp or "owed_by" in exp:
        paid_by = {k: q2(v) for k, v in exp.get("paid_by", {}).items()}
        owed_by = {k: q2(v) for k, v in exp.get("owed_by", {}).items()}
        # Sanity: payments and shares must each match the cost
        paid_sum = sum(paid_by.values(), Decimal("0"))
        owed_sum = sum(owed_by.values(), Decimal("0"))
        if abs(paid_sum - cost) > Decimal("0.01"):
            raise ValueError(
                f"Row '{exp['desc']}': paid_by sums to {paid_sum}, expected {cost}"
            )
        if abs(owed_sum - cost) > Decimal("0.01"):
            raise ValueError(
                f"Row '{exp['desc']}': owed_by sums to {owed_sum}, expected {cost}"
            )
        return paid_by, owed_by

    # Compact form: 1 payer, equal split among participants
    payer = exp["payer"]
    participants = exp["participants"]
    n = len(participants)
    share = q2(cost / n)

    paid_by = {payer: cost}
    owed_by = {p: share for p in participants}

    # Absorb rounding residual on the payer (or first participant if payer not in list)
    residual = cost - sum(owed_by.values(), Decimal("0"))
    if residual != 0:
        target = payer if payer in owed_by else participants[0]
        owed_by[target] += residual

    return paid_by, owed_by


def expense_row(exp):
    """Build the CSV row for a single expense (any supported form)."""
    cost = q2(exp["cost"])
    paid_by, owed_by = normalize_expense(exp)

    nets = {p: paid_by.get(p, Decimal("0")) - owed_by.get(p, Decimal("0")) for p in PEOPLE}
    total = sum(nets.values(), Decimal("0"))
    assert abs(total) < Decimal("0.01"), f"Row '{exp['desc']}' nets sum to {total}, not 0"

    currency = exp.get("currency", CURRENCY)
    cells = [exp["date"], exp["desc"], exp["cat"], f"{cost:.2f}", currency]
    cells += [f"{nets[p]:.2f}" for p in PEOPLE]
    return cells


def settlement_row(s):
    """Settlement: payer +amount, recipient -amount, others 0. Category 'Pago'."""
    amount = q2(s["amount"])
    nets = {p: Decimal("0") for p in PEOPLE}
    nets[s["payer"]] = amount
    nets[s["recipient"]] = -amount

    desc = f"{display_name(s['payer'])} pagó {display_name(s['recipient'])}"
    currency = s.get("currency", CURRENCY)
    cells = [s["date"], desc, "Pago", f"{amount:.2f}", currency]
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

    # Splitwise's exact format:
    # header\n\n<rows separated by \n>\n\n<saldo>\n\n
    lines = [",".join(header), ""]
    lines += [",".join(row) for row in data_rows]
    lines += ["", ",".join(saldo), ""]
    text = "\n".join(lines) + "\n"

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_bytes(text.encode("utf-8"))

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
    print(f"  {'SUM':10s} {sum(totals.values(), Decimal('0')):.2f}  (must be 0)")


if __name__ == "__main__":
    main()
