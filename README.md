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
| 03 | [**reconcile-and-flag**](week03-add-judgment-recon/) | Bank-to-ledger reconciliation that proves it is complete, and refuses to guess | 🔨 Engine working |
| 04 | **standards-assistant** | RAG assistant over accounting standards, answering with citations | 📋 Planned |

---

## Featured: structure-the-mess

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
