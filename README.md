# tricount-csv-import

Bulk-import many shared expenses into [Tricount](https://tricount.com) by generating a Splitwise-format CSV that Tricount's official "Import from Splitwise" feature accepts — without ever touching a real Splitwise account.

> **TL;DR**: Tricount lets you import a CSV from Splitwise. We reverse-engineered the exact byte-level format, so you can generate it directly and skip Splitwise entirely (and skip its 3–5 expenses/day free-tier limit).

## The problem this solves

- **Tricount** doesn't have a bulk-import feature for arbitrary CSVs — only the Splitwise importer.
- **Splitwise free** caps you at 3–5 expenses/day with a 10-second cooldown. Useless for trips with 15+ expenses.
- **Splitwise Pro** is $4.99/month — works, but feels excessive for a one-off migration.
- **Manual entry** in Tricount is tedious for asymmetric splits (different participants per expense, prior cash settlements, etc.).

This script generates the CSV directly. Tricount accepts it. Done in 30 seconds.

## How it works

Tricount's importer doesn't validate that the CSV came from a real Splitwise account — it only validates the **format**. The format has strict byte-level requirements:

- UTF-8 **without BOM**
- **LF line endings only** (no CRLF)
- A blank line **after the header**
- A blank line **before the "Saldo total" row**
- File must end with `\n\n`

Any deviation triggers Tricount's generic error: *"No se puede importar el CSV. Por favor, sube un archivo con gastos."* This script handles all of that correctly.

## Usage

1. Open `scripts/generate_csv.py` and edit the three constants near the top:
   - `PEOPLE` — ordered list of names (the column order in the CSV).
   - `EXPENSES` — list of dicts: `{date, desc, cat, cost, payer, participants}`.
   - `SETTLEMENTS` — list of dicts for prior cash transfers: `{date, payer, recipient, amount}`.

2. Run it:
   ```bash
   python scripts/generate_csv.py
   ```

3. The script writes the CSV to `~/Downloads/tricount-import.csv` (configurable via `OUTPUT_PATH`) and prints a balance summary.

4. In the Tricount mobile app: **Add a Tricount → Import from Splitwise → pick the CSV → confirm**.

## Asymmetric splits

Each expense's `participants` is a subset of `PEOPLE`. The cost is divided equally among participants only. Use this for cases like:
- Some people skipped an activity
- Someone paid for one specific person's airfare
- Different subsets of the group at different stages of a trip

## Settlements

Prior cash transfers (e.g. one person paid the organizer back two weeks before) appear in the CSV with category `Pago` and a description in the form `"X pagó Y"`. Tricount recognizes these as settlements rather than expenses.

## Format details

If you want to understand or extend the format, the long-form spec is in [`SKILL.md`](SKILL.md). Highlights:
- Each row's per-person columns are **net amounts** (positive if paid more than their share, negative if owes).
- Each row must sum to exactly 0.
- The script absorbs rounding cents on the payer.

## Why "skill"?

This repo is also a [Claude Code skill](https://docs.claude.com/en/docs/claude-code/skills). If you use Claude Code, drop the `tricount-csv-import/` folder into `~/.claude/skills/` and Claude will auto-trigger it whenever you ask anything related to importing many expenses into Tricount. The script becomes invokable from natural-language requests like "I have 20 trip expenses to put in Tricount, here are the data".

## License

MIT — see [LICENSE](LICENSE).

## Contributing

Issues and PRs welcome. If Tricount changes its accepted format, please open an issue with the rejection error and a sample of the new official Splitwise export so we can update the spec.
