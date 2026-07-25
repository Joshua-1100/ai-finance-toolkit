# ai-finance-toolkit

Working tools at the intersection of accounting controls and AI — built by a
Controller, not a demo engineer.

The premise: the scarce skill in AI-assisted finance isn't getting a model to
produce an answer. It's knowing whether the answer is right, and being able to
prove it. Every tool here is built to be *checkable* — validated against
accounting identities, tested, and traceable back to its source.

---

## Tools

| | Tool | What it does | Status |
|---|---|---|---|
| 01 | [**first-integration**](week01-first-integration/) | OAuth into a live accounting system, pull real ledger data into pandas | ✅ Shipped |
| 02 | [**structure-the-mess**](week02-structure-the-mess/) | Turn a quarterly financial PDF into clean, validated, queryable data | ✅ Shipped |
| 03 | [**reconcile-and-flag**](week03-add-judgment-recon/) | Bank-to-ledger reconciliation that proves it is complete, refuses to guess, and explains what it refused | ✅ Shipped |
| 04 | **standards-assistant** | RAG assistant over accounting standards, answering with citations | 📋 Planned |

---

## Featured: reconcile-and-flag

Every Controller has done a bank reconciliation. The clean matches are a
spreadsheet formula. The job is the judgment calls — the payment that posted
three days late, the one deposit covering five invoices, the memo that reads
`Inv 000012345` on one side and `I12345` on the other, the entry and its
reversal that cancel each other and belong to nothing.

```
205 ledger + 205 bank rows  →  167 match groups, 6 open items  →  1,027.21 difference, explained to the cent
```

**The test data comes before the tool.** You cannot tell whether a
reconciliation handles the hard cases by pointing it at real bank data, because
with real data you don't know the right answer either. So the corpus is
synthetic and every hard case is planted deliberately — eleven scenarios, from
exact matches through wide date shifts, fuzzy invoice references, many-to-one
settlement groups, one-sided voids and penny differences. The engine finds all
eleven, and the only rows it leaves open are the three a side that genuinely
don't match. Those get confirmed independently, by the fact that they're the
only rows whose memos contain no document number at all.

**Deterministic where there's a right answer, model where there's judgment.**
Whether 1,204.55 equals 1,204.55 is arithmetic, so seven ordered rules do all
the deciding — no model is consulted about any match. Where a rule cannot single
out one answer, a model explains what the candidates probably are and what to go
check. It cannot do more than that, and not because it's asked nicely: the tool
schema it must answer through has three fields — a sentence and two closed
enums. There is no field for a row id, a pairing, or a verdict, so no response
it could produce would change a reconciliation. A test asserts that absence,
because it is the entire argument. (That path is opt-in, and so far exercised
only against a stubbed client — see the
[tool README](week03-add-judgment-recon/README.md).)

**It refuses rather than guesses.** Two ledger rows identical in date, amount and
memo cannot be told apart. Two different subsets that both sum to a deposit give
no way to know which one settled. In those cases the engine records the
candidates and moves on. That's a controls judgment, not a technical one: a
confident wrong match costs more than an item on a reviewer's list, because the
wrong one never gets revisited.

**The proof is the deliverable, not the output.** Whatever the engine claims, the
open items plus any penny difference it absorbed have to add back to the
difference the two files arrived with — to the cent, in integer arithmetic, and
re-proved after every single pass so a bug lands on the pass that caused it. A
reconciliation nobody can check is worse than none, because it gets trusted.

**One bug worth reading about.** Sets 6 and 7 require summing two to five ledger
rows and testing equality against a deposit. In float64, `730.03 + 46.80` is
`776.8299999999999` — and 5 of the 30 group matches planted in this corpus fail
that comparison. They fail *silently*: a correct many-to-one match gets reported
as two unmatched items while the reconciliation still looks entirely reasonable.
Amounts are integer cents end to end, and the specific failing values are pinned
in a test. It's the same lesson as week 2's three bugs — the dangerous output is
the plausible kind.

Open [`data/reconciliation_example.xlsx`](week03-add-judgment-recon/data/reconciliation_example.xlsx)
next to [`data/non_reconciled.xlsx`](week03-add-judgment-recon/data/non_reconciled.xlsx),
the same job worked by hand, for the before and after.

---

## Also featured: structure-the-mess

Financial data is published for humans to read, not for machines to use. Want
to know how much of a company's growth was funded by operations versus debt
versus issuing stock? That requires the balance sheet, income statement, and
cash flow statement aligned across many quarters — data that exists only in
PDFs laid out for the eye.

This tool extracts it, and then proves the extraction is correct.

```
214 raw rows  →  1,128 validated line items  →  118/118 identity checks pass
```

**Deterministic where there's a right answer, model where there's judgment.**
Pulling numbers off a page has a correct answer, so that's geometry — fully
reproducible, no model involved. Mapping a messy label like
`General and administrative(1)(3)(5)(6)` to a canonical concept is a judgment
call, so that's the model — constrained by a tool-use schema whose output is a
closed enum, so it cannot invent a field, and never shown a number it could
alter.

**Validated against double-entry, not eyeballs.** Assets = Liabilities +
Equity. Change in accumulated deficit = net income. Regional revenue foots to
total revenue. Fifteen families of check across every period. None of these
depend on hand-labelled expected values — they depend on identities the source
statements must already satisfy, which makes them impossible to fudge. A wrong
number cannot pass them.

**Every figure is traceable.** `--trace` returns the source page, the original
label, the verbatim PDF line, and every derived metric built from that value.

**Three bugs worth reading about.** The [README](week02-structure-the-mess/README.md)
documents each one, because all three produced output that looked entirely
reasonable: a row-clustering tolerance that silently dropped two balance sheet
lines, a parenthesis check that nulled every negative margin, and a dependency
that only existed on my machine. None would have been caught by reading the
results. That's the argument for validation over inspection, and it's the
whole thesis of this repo in miniature.

---

## Why a Controller is building this

Most tooling in this space is built by engineers who then have to learn what a
deferred revenue balance means. I came the other way. The controls instinct —
tie it out, flag what doesn't reconcile, show your work — turns out to be a
technical feature, not a soft skill, once you're asking whether a model's
output can be trusted.

That's the gap this repo is meant to demonstrate: not "I can call an LLM API,"
but "I can tell you when it's wrong, and prove it."

---

## Getting started

```bash
git clone https://github.com/Joshua-1100/ai-finance-toolkit.git
cd ai-finance-toolkit

python -m venv .venv
.venv\Scripts\Activate.ps1        # Windows
# source .venv/bin/activate       # macOS / Linux

cp .env.example .env              # add your API keys
```

Each tool has its own README and requirements. The fastest way to see something
real:

```bash
cd week02-structure-the-mess
pip install -r requirements.txt
python -m structure_the_mess.cli data/supplement.pdf --no-llm --html
```

No API key needed for that run — it uses the deterministic path. You should see
118/118 checks pass and get a standalone HTML report.

Or, for the shortest path to something you can open in Excel:

```bash
cd week03-add-judgment-recon
pip install -r requirements.txt
python run_recon.py --gl data/general_ledger.csv --bank data/bank.csv
```

One small dependency, no API key, no source PDF. It reconciles 205 ledger rows
against 205 bank rows, resolves every one but the three that genuinely do not
match, and proves the result foots to the cent.

---

## Layout

```
ai-finance-toolkit/
├── week01-first-integration/     # live accounting system → pandas
├── week02-structure-the-mess/    # messy PDF → validated structured data
├── week03-add-judgment-recon/    # ledger + bank → reconciled Excel workbook
├── .env.example
└── README.md
```

---

## Stack

Python · pandas · DuckDB · pdfplumber · Pydantic · openpyxl · Anthropic API · pytest

---

**Joshua Fairbanks** — Controller building AI-native finance tooling.
[LinkedIn](#) · [Email](#)
