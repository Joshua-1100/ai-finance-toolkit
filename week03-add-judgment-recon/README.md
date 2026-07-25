# reconcile-and-flag

Bank-to-ledger reconciliation, built to be run by anyone with a PC and checked
by anyone who knows accounting.

> **Status: working end to end.** Pick two CSVs, get a reconciled Excel
> workbook that proves it is complete.

## Running it

```bash
python run_recon.py
```

Pick the general ledger CSV, then the bank CSV, then where to save the workbook —
all from native file dialogs. Pass `--gl`, `--bank` and `--out` to skip the
dialogs on reruns, or `--no-excel` for the console report alone.

## What you get

[`data/reconciliation_example.xlsx`](data/reconciliation_example.xlsx) is
committed as a worked example — the output of running the tool against the corpus
in this repo. Open it beside
[`data/non_reconciled.xlsx`](data/non_reconciled.xlsx), the same job done by
hand, for the before and after.

Your own runs write to `data/reconciliation.xlsx` by default, which is
gitignored — the Summary tab stamps its generation time, so otherwise every run
would look like a change to a committed file.

| Tab | What it holds |
|---|---|
| **Summary** | Control totals, what each pass claimed, and the proof |
| **Reconciled** | Every matched row, banded by group, with the match quality |
| **Exceptions** | What is still open — the list a Controller actually works |
| **General Ledger** | The source file verbatim, plus the match each row landed in |
| **Bank** | The same for the statement |

An **Ambiguous** tab appears only when a pass declined to choose between
candidates. Its absence means there was nothing to decline, not nothing to say.

Amounts are written as numbers rather than text, so the workbook can be summed
and filtered like any other. That means Excel holds them as floats — fine for
display and totalling at two decimals, and not where any of the matching
happened. Every comparison that decided anything was made in integer cents
before the file existed.

On the corpus:

```
  exact_triple           50 matches
  void_pairs              2 matches
  amount_memo            60 matches
  group_sum              30 matches
  digit_core_dated       10 matches
  digit_core             10 matches
  near_amount             5 matches

  167 match groups covering 202 GL and 202 bank rows
  shapes: 1 x 0:2, 135 x 1:1, 5 x 1:2, 5 x 1:3, 5 x 1:5, 1 x 2:0, 5 x 2:1, 5 x 3:1, 5 x 5:1

  amount   date     identity  groups
  Exact    Close    Exact         50
  Exact    Close    Similar        3
  Exact    Exact    Exact         52
  Exact    Exact    Similar       10
  Exact    Wide     Exact         10
  Exact    Wide     Similar        7
  Near     Exact    Exact          5
  Sum      Exact    Exact         30

STILL OPEN
  GL       3 of 205 rows         1,807.63
  Bank     3 of 205 rows           780.31

PROOF
  unmatched GL less unmatched bank        1,027.21
  drift accepted inside matches              -0.11
  accounted for                           1,027.21
  GL total less bank total                1,027.21
  FOOTS - the reconciliation is complete.
```

Every pass claims exactly the scenario it was built for. The three rows left a
side are Set 8, the genuine non-matches — verified independently, by the fact
that they are the only rows whose memos contain no document number at all.

The proof is the part worth trusting. Whatever the engine claims, the open items
plus the drift it absorbed have to add back to the difference the two files
arrived with, to the cent. That is checkable by anyone who can add.

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

## The matching ladder

Passes run strongest evidence first. Each sees only what earlier passes left, so
the order is a design decision rather than an implementation detail — moving a
pass up gives it first claim on rows it has weaker grounds for.

| # | Pass | Matches on | Shape |
|---|---|---|---|
| 1 | `exact_triple` | date + amount + memo | 1:1 |
| 2 | `void_pairs` | same file: date + memo + equal and opposite | n:0 |
| 3 | `amount_memo` | amount + memo, date graded | 1:1 |
| 4 | `group_sum` | bucket by date + memo, subset sums exactly | n:1, 1:n |
| 5 | `digit_core_dated` | date + amount + document number | 1:1 |
| 6 | `digit_core` | amount + document number, date graded | 1:1 |
| 7 | `near_amount` | date + memo, amount within 0.09 | 1:1 |

Passes propose; the engine claims. A pass reads the rows still available and
returns candidates without mutating anything, so no pass can take a row another
already took, and the proof is re-checked after every one — which localises a
bug to the pass that caused it.

**It refuses rather than guesses.** Where a key does not single out a single
pair, the pass records an ambiguity and moves on. Two ledger rows identical in
date, amount and memo cannot be told apart; two different subsets that both sum
to a deposit give no way to know which settled. A confident wrong match costs
more than an item on a reviewer's list, because the wrong one is never revisited.

**Identity is a rule, not a score.** `Inv 000012345`, `I12345` and a bare
`12345` reduce to the same document number by stripping non-digits and leading
zeros. String-similarity scoring would generalise further, but a reviewer can
check this rule by reading it and cannot check a distance threshold. Numbers
under three digits are ignored as too weak to act on.

**Group matching is bucketed, not brute-forced.** Unconstrained subset-sum over
ten thousand rows is not a computation anyone finishes. Narrowing to the handful
of rows sharing a date and reference makes it immediate. Buckets above twelve
rows are refused rather than allowed to crawl — a reconciliation that hangs is
not a reconciliation.

Measured on synthetic files well past realistic size: 64,000 rows a side in
about three seconds, scaling close to linearly.

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
