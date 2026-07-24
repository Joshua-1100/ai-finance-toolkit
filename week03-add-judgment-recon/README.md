# reconcile-and-flag

Bank-to-ledger reconciliation, built to be run by anyone with a PC and checked
by anyone who knows accounting.

> **Status: in progress.** The synthetic test corpus is built and verified. The
> reconciliation engine itself is next.

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

## Design constraints

- **Portable.** Anyone with a stock Python install should be able to clone,
  run, and get output. Dependencies are a cost paid by every user.
- **Deterministic where there's a right answer.** Whether 1,204.55 equals
  1,204.55 is arithmetic. It gets arithmetic, not a model.
- **Judgment where judgment is genuinely required.** Whether `I12345` and
  `Inv 000012345` are the same invoice is a call, and calls get explained.
- **Every match auditable.** A reconciliation nobody can check is worse than no
  reconciliation, because it's trusted.
