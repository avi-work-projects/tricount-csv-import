---
name: tricount-csv-import
description: Generate a Splitwise-format CSV to bulk-import many group expenses (with asymmetric splits, multiple payers, prior settlements) directly into Tricount via its official "Import from Splitwise" feature. Use this skill whenever the user wants to set up a Tricount with many expenses at once, migrate accumulated group expenses, convert a list of trip/event expenses into Tricount, bypass Splitwise's 3-5 expenses/day free-tier limit, or export their accounting from any tool into Tricount. Triggers include phrases like "import expenses to Tricount", "create a Tricount with X expenses", "bulk-load Tricount", "migrate to Tricount", "Splitwise to Tricount", "CSV para Tricount", "tengo muchos gastos del viaje para meter en Tricount", "importar gastos a Tricount", or any situation where the user has compiled a list of group expenses and needs them in Tricount efficiently. The Splitwise CSV format has strict byte-level requirements that this skill encodes — failing any of them causes Tricount to reject the file with the error "No se puede importar el CSV. Por favor, sube un archivo con gastos."
---

# Tricount Bulk Import

## Why this skill exists

Tricount has an official **"Import from Splitwise"** feature that accepts CSVs in Splitwise's exact export format. Generating that CSV directly (without going through a real Splitwise group) is the fastest way to load many expenses into Tricount, because:

- **Splitwise's free plan limits to 3-5 expenses/day** with a 10-second cooldown — useless for large groups (a typical trip has 15-30 expenses).
- **Splitwise Pro is $4.99/month** — works but costs money for one-time use.
- **Tricount's manual entry is tedious** for asymmetric splits (different participants per expense, settlements, etc.).

The trick: Tricount's importer doesn't validate that the CSV came from a real Splitwise account — it only validates the **format**. So we generate the CSV directly. This was discovered by reverse-engineering the format and testing iteratively until Tricount accepted it.

## The exact CSV format (byte-level)

Tricount is **strict** about format. Any deviation triggers the error: *"No se puede importar el CSV. Por favor, sube un archivo con gastos."*

### Encoding and line endings

- **UTF-8 without BOM** (no `EF BB BF` prefix)
- **LF line endings only** (`\n`) — never CRLF (`\r\n`). This matters on Windows where text-mode file writes auto-convert.

### Structure

```
<header line>\n
\n                         ← blank line REQUIRED after header
<expense row 1>\n
<expense row 2>\n
...
<settlement row 1>\n       ← settlements are just rows with category "Pago"
...
\n                         ← blank line REQUIRED before saldo total
<saldo total row>\n
\n                         ← trailing blank line REQUIRED (file ends with \n\n)
```

### Header

```
Fecha,Descripción,Categoría,Coste,Moneda,<Person1>,<Person2>,...,<PersonN>
```

Person names go in the order you want columns. They'll be the participants in the resulting Tricount.

### Expense row

```
<YYYY-MM-DD>,<description>,<category>,<cost>,EUR,<net person1>,<net person2>,...
```

Where each person's `net` is:
- **Payer (participates):** `cost - their_share` → positive
- **Non-payer participant:** `-their_share` → negative
- **Non-participant:** `0.00` → zero

Each row's nets must sum to **exactly 0**. The payer absorbs any rounding cents (compute their net last as `-sum(other nets)`).

Categories that Splitwise uses (kept in CSV): `Avión`, `General`, `Alquiler de coche`, `Hotel`, `Pago`, plus many others. Tricount ignores unknown categories (treats as default), so you can use any string.

### Settlement / payment row

For prior cash transfers (e.g., person paid the organizer months ago):

```
<date>,<X> pagó <Y>,Pago,<amount>,EUR,...
```

- **Description format is literal**: `"X pagó Y"` (verb "pagó" between names). E.g., `"Juanma pagó Angel V."`
- **Category MUST be `Pago`** (singular). Not "Pagos", not "Settlement". Tricount detects this and treats the row as a payment, not an expense.
- **Net for the payer (X):** `+amount`
- **Net for the recipient (Y):** `-amount`
- **All others:** `0.00`

Note this is the **opposite sign** of an expense — for a settlement, the person who **transferred money out** has a positive net. Why? Splitwise treats a settlement as "X paid Y directly" which reduces X's debt to Y. The CSV models this as X giving more credit to the group ledger and Y receiving cash.

### Saldo total row

```
<any date>,Saldo total, , ,EUR,<sum col 1>,<sum col 2>,...
```

Note the **literal spaces** in the empty Categoría and Coste fields: `"Saldo total, , ,EUR,..."`. This is how Splitwise exports it.

The values are the column-wise sums of all data rows. They tell Tricount the final balance per person and serve as a checksum.

## Procedure

### 1. Collect the data

You need:
- **List of expenses**: date, description, category, cost, payer name, list of participants (subset of all people)
- **List of prior settlements** (optional): date, payer, recipient, amount

### 2. Generate the CSV

Use the script in `scripts/generate_csv.py`. It handles:
- Computing nets per person per expense (with correct rounding)
- Generating settlement rows
- Writing the file in **binary mode** with proper LF endings and no BOM
- Computing the Saldo total row as column sums

Adapt the `PEOPLE`, `EXPENSES`, and `SETTLEMENTS` constants at the top of the script.

### 3. Validate

Before handing the CSV to the user, run the validation block at the bottom of the script. It checks:
- Every data row sums to 0 (within 1 cent)
- Saldo total values match the column-wise sums
- Total trip cost is reasonable

If a row doesn't sum to 0, recompute the payer's net as `cost - sum(other_participants_shares)` to absorb rounding.

### 4. Import into Tricount

In the Tricount mobile app:
1. Tap "Add a Tricount"
2. Choose **"Import from Splitwise"**
3. Pick the generated `.csv` file
4. Review and confirm

If Tricount accepts the file, the new Tricount appears with all members, expenses, and the correct balances.

## When format goes wrong

If Tricount shows *"No se puede importar el CSV. Por favor, sube un archivo con gastos"*, it's almost always one of these:

| Symptom | Likely cause | Fix |
|---|---|---|
| Hard reject, no expenses imported | Missing blank line after header | Add `\n` after header |
| Same | Missing blank line before Saldo total | Add `\n` before Saldo total |
| Same | File doesn't end with `\n\n` | Append a final blank line |
| Same | UTF-8 BOM present | Write file with explicit `bytes` (binary mode) |
| Same | CRLF line endings | Write with `\n` only (binary mode bypasses Windows auto-conversion) |
| Imports but wrong amounts | Row doesn't sum to 0 | Recompute payer's net as `-sum(others)` |
| Settlements appear as expenses | Category not exactly `Pago` | Check spelling (no "Pagos", no plural) |

The single most common failure is the blank lines. The script writes them correctly; if you hand-edit the CSV, preserve them.

## Verifying the byte format

To confirm a generated CSV matches Splitwise's real format, fetch a real Splitwise export from your own group and compare bytes:

```javascript
// In the browser console at secure.splitwise.com:
fetch('/api/v3.0/export_group/<your_group_id>.csv', {credentials: 'include'})
  .then(r => r.arrayBuffer())
  .then(buf => {
    const bytes = new Uint8Array(buf);
    const text = new TextDecoder('utf-8').decode(bytes);
    return {bytes_len: bytes.length, has_bom: bytes[0]===0xEF, has_crlf: text.includes('\r\n'), full: text};
  });
```

The returned `full` text is the canonical reference. Match its empty-line pattern exactly.

## Fallback options if format-only approach fails

If for some reason Tricount rejects every iteration of the CSV (rare — should not happen with the procedure above), the fallbacks are:

1. **Splitwise Pro 1 month ($4.99):** removes the daily limit. Use Splitwise's API or UI to add the expenses, then export the canonical CSV from Splitwise itself, and import that to Tricount.
2. **Splitwise free with patience:** 3-5 expenses/day. For a 21-expense trip this takes ~5 days.
3. **Manual entry in Tricount:** tedious for asymmetric splits but always works. Use a printed list of computed shares.

## Example data and full reference

A worked example with 15 expenses + 6 settlements (for a Costa Rica + Dominican Republic trip with 8 people, multiple payers, 4 different participation patterns) is in `scripts/generate_csv.py` as the default constants. Use it as a template — replace the people, expenses, and settlements with your own data and run the script.