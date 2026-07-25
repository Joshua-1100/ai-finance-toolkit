# reconcile-and-flag

Bank-to-ledger reconciliation, built to be run by anyone with a PC and checked
by anyone who knows accounting.

> **Status: in progress.** The synthetic corpus is built and verified, and the
> load stage runs. Matching passes and the Excel workbook are next.

## Running it

```bash
python run_recon.py
```

Pick the general ledger CSV, then the bank CSV, from a native file dialog. Pass
`--gl` and `--bank` to skip the dialog on reruns.

Right now this loads, validates, and enumerates both files, then reports the one
number that matters before any matching happens:

```
  GL total                      125,223.99
  Bank total                    124,196.78
  Difference to explain           1,027.21
```

Every unmatched item the finished reconciliation reports has to add back to
exactly that figure. That is the completeness proof, and it is checkable by
anyone who can add.

### Install

```bash
pip install -r requirements.txt
```

One runtime dependency, `openpyxl`, for writing the workbook. Reading CSVs,
parsing money, matching, and the file dialog are all standard library. No
pandas: this workload is combinatorial group matching and string similarity
rather than vectorized arithmetic, so pandas and numpy would cost every user a
~60MB install for no gain.

---

## Why the test data comes first

A reconciliation that only handles clean matches is a spreadsheet formula. The
work is in the judgment calls — the payment that posted three days late, the
one bank deposit that covers five invoices, the memo that reads `Inv 000012345`
on one side and `I12345` on the other.

You cannot tell whether an engine handles those cases by pointing it at real
bank data, because with real data you don't know the right answer either. So
the corpus is synthetic and every hard case is planted deliberately, one
scenario at a time.

`data/general_ledger.csv` and `data/bank.csv` — 205 rows a side — contain
eleven scenarios:

| Set | Scenario | Rows (GL / bank) | What it tests |
|---|---|---|---|
| 1 | LowHangingFruit | 50 / 50 | Exact match on amount, date and memo |
| 2 | Dateshifts slight | 50 / 50 | GL date off by 1–3 days (25 ahead, 25 behind) |
| 3 | Dateshifts widely | 10 / 10 | Dates ≥ 14 days apart — match or leave open? |
| 4 | Imperfect Identity | 10 / 10 | Amount and date agree, memos only resemble |
| 5 | Imperfect Date_Identity | 10 / 10 | Amount agrees; date *and* memo both differ |
| 6 | GLmany Bankone | 50 / 15 | Groups of 2, 3 and 5 GL rows summing to one deposit |
| 7 | GLone Bankmany | 15 / 50 | The mirror — one GL row against a split settlement |
| 8 | NoMatch | 3 / 3 | Genuinely unmatched both ways |
| 9 | GLvoid | 2 / 0 | +100.00 / −100.00 GL pair netting to zero |
| 10 | Bankvoid | 0 / 2 | +300.00 / −300.00 bank pair netting to zero |
| 11 | CloseToMatch | 5 / 5 | Amounts off by 1–9 cents |

Sets 9 and 10 are one-sided on purpose. A void pair has no counterparty — the
signal is that two rows on the *same* side share a date and memo and cancel
out. An engine that reports them as two unmatched items has missed the point.

Each set carries its own `main_memo` theme (vegetables, fruits, lemon
varieties, angels, trees…), so any row can be traced back to its scenario by
eye without a separate answer key.

## Regenerating the data

Standard library only. No pandas, no installs, no network.

```bash
python tools/generate_synthetic_data.py
```

The seed is fixed, so this produces byte-identical files on every machine — a
diff in `data/` means the generator changed, never the weather. Pass `--seed`
for an independent corpus to check the engine isn't overfitting to this one.

Because there's no separate answer key,
[`tools/generate_synthetic_data.py`](tools/generate_synthetic_data.py) is the
specification of what "correct" means. Each `build_set_NN` function documents
the scenario it plants, and the engine's tests should read against it.

## How a match is described

A `match_id` names a match **group**, not a pair. Every row that participates
carries the same id, so one mechanism covers all the shapes in the corpus:
one-to-one, three-to-one, one-to-five, and the one-sided void pairs that resolve
with no counterparty at all.

Each group is graded on three independent axes, because "matched" on its own
tells a reviewer nothing about whether to trust it:

| | Values | Meaning |
|---|---|---|
| **Amount** | Exact / Sum / Near / None | equal to the cent · a group total · within tolerance · no |
| **Date** | Exact / Close / Wide / None | same day · settlement lag · far enough to look at · no |
| **Identity** | Exact / Similar / None | identical memo · same invoice, different dress · no |

Quality lives on the group rather than on the rows. Five ledger rows summing to
one deposit share one verdict, and storing that verdict five times invites the
copies drifting apart.

## Money is never a float

Amounts are parsed to integer cents at load and formatted only on output. This
is not fastidiousness. Sets 6 and 7 require summing 2–5 rows and testing
equality against a deposit, and **5 of the 30 group matches planted in this
corpus fail naive float64 equality** — `730.03 + 46.80` is `776.8299999999999`,
not `776.83`. Those failures are silent: a correct many-to-one match would
simply be reported as two unmatched items, and the recon would look plausible
while being wrong. `tests/test_money.py` pins the specific cases.

## Design constraints

- **Portable.** Anyone with a stock Python install should be able to clone,
  run, and get output. Dependencies are a cost paid by every user.
- **Deterministic where there's a right answer.** Whether 1,204.55 equals
  1,204.55 is arithmetic. It gets arithmetic, not a model.
- **Judgment where judgment is genuinely required.** Whether `I12345` and
  `Inv 000012345` are the same invoice is a call, and calls get explained.
- **Every match auditable.** A reconciliation nobody can check is worse than no
  reconciliation, because it's trusted.
