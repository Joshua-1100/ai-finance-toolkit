# structure-the-mess

Turns a company's quarterly financial supplement PDF into clean, validated,
queryable data — and then proves the numbers are right by checking them
against the accounting identities the source document must already satisfy.

Built against Cloudflare's Q1 FY26 supplemental (8 quarters, 9 pages).

```
214 raw rows  ->  1,128 validated line items  ->  118/118 identity checks pass
```

## The accounting problem

Quarterly financial data is published for humans to read, not for machines to
use. If you want to answer something as basic as *how much of this company's
growth was funded by operations versus debt versus issuing stock*, you need
the balance sheet, income statement, and cash flow statement lined up across
many quarters. That data exists — in PDFs, laid out for the eye.

So the analysis never happens, or it happens in a hand-keyed spreadsheet
nobody trusts and nobody can rebuild next quarter.

The specific mess in these documents:

- **No table borders.** Off-the-shelf table extraction collapses each row into
  a single string. The structure has to be recovered from word geometry.
- **Wrapped labels.** When a label spans two lines, the values are rendered
  *centred between them*. Naive row clustering assigns them to neither.
- **Footnote markers inside labels.** `Cost of revenue(1)(2)` — and `(1)` looks
  exactly like a negative number.
- **Parentheses mean negative.** `(34,698)` is −34,698. `(8.7)%` is −8.7%.
- **Em dash means nil, not zero.** Collapsing the two corrupts every delta.
- **Labels repeat with different meanings.** "Cost of revenue" appears three
  times on page 3: the real line item, the stock-comp inside it, and the
  intangible amortization inside it. Only context distinguishes them.
- **Units shift mid-document.** The page header says thousands. The RPO row is
  millions. Margin rows are percentages. Share counts are counts.

## Approach: deterministic where there's a right answer, model where there's judgment

The pipeline splits at the point where the task stops having a single correct
answer.

```
PDF ──[pdfplumber + geometry]──> raw rows ──[Claude tool-use]──> canonical keys
                                                                      │
                       DuckDB <── validated ──[accounting identities]─┘
```

**`extract.py` — no model.** Pulling numbers off a page has a right answer, and
geometry is faster and more trustworthy at it than a language model. Words are
clustered into rows by y-coordinate, the `Q2 2024 … Q1 2026` header supplies
the column anchors, and each row is split into label and value regions by
x-coordinate. Fully reproducible and unit-tested.

**`normalize.py` — model, narrowly scoped.** The model's entire job is: given a
label and its context, pick a key from a closed list. It is constrained by a
tool-use schema whose `canonical_key` field is an *enum*, so it cannot invent a
field. It never sees a number it could alter. If it returns `UNKNOWN` or an
off-list key, the row is **quarantined, not dropped**.

This is the part rules genuinely cannot do. "Loss from operations" and "Income
from operations" are the same concept, printed differently depending on the
sign that quarter. A row labelled "Cost of revenue" under a stock-comp footnote
means something different from the identical string 20 rows above it. Wrap
artifacts produce labels like `PSU settlement Payment of indemnity holdback`,
where two line items have collided. These are judgments about meaning.

**`validate.py` — no model.** Fifteen families of accounting identity, checked
across every period:

| Check | Assertion |
|---|---|
| `balance_sheet_balances` | Assets = Liabilities + Equity |
| `delta_identity` | ΔAssets = ΔLiabilities + ΔEquity |
| `clean_surplus` | Δ accumulated deficit = net income |
| `gross_profit` | Revenue − COGS |
| `total_opex` | S&M + R&D + G&A |
| `operating_result` | Gross profit − opex |
| `pretax_result` / `net_result` | full income statement articulation |
| `sbc_components_foot` | stock-comp footnote foots to its own total |
| `net_change_in_cash` | operating + investing + financing |
| `cash_rollforward` | beginning + change = end |
| `free_cash_flow` | OCF − capex − capitalized software |
| `revenue_by_region_foots` | regional revenue = total revenue |
| `revenue_by_customer_type_foots` | channel + direct = total revenue |

None of these depend on hand-labelled expected values. They depend on
double-entry bookkeeping, which means they are cheap to write and impossible to
fudge. **A wrong number cannot pass them.**

## Verifying the model

`aliases.py` is a hand-built deterministic label→key table for this issuer. It
exists so the tool runs without an API key — and so the model's output has
something to be measured against:

```bash
python -m structure_the_mess.cli supplement.pdf --compare
```

reports every row where the model and the alias table disagree, plus the rows
only the model could map. That turns "the LLM seems fine" into a number.

## Bugs this build actually hit

Each is now a regression test in `tests/test_extract.py`. They're listed here
because they're the substance of the work — the parser looked correct at every
one of these points.

1. **Silent row loss from row-clustering tolerance.** Wrapped labels centre
   their values between the two label lines, 4pt from each. At a 3pt tolerance
   those values formed a label-less row and were discarded — losing
   *Current portion of convertible senior notes* and *Total liabilities and
   stockholders' equity* entirely. The balance sheet still appeared to parse
   fine. Fixed, plus a guard that now raises on any label-less value row rather
   than continuing.
2. **Truncated long labels.** Requiring label words to sit left of the value
   boundary silently ate the tails of long labels, collapsing
   *cash, beginning of period* and *cash, end of period* into one identical
   label.
3. **Negative percentages parsed as nil.** `(8.7)%` failed the
   `endswith(")")` test, so every negative GAAP operating margin came through
   as `None`. Caught by a unit test, not by looking at the output.
4. **Footer page numbers read as data.** A centred bare integer sits right of
   the value boundary and parses cleanly.
5. **Substring collision in label matching.** The weighted-average share-count
   label *ends with* the full text of the EPS label, so longest-match mapped it
   to `eps_diluted`.

Bug 1 and bug 3 are the interesting ones: both produced output that looked
entirely reasonable. Neither would have been caught by reading the results.
That's the argument for validating against identities rather than eyeballing.

## Usage

```bash
pip install -r requirements.txt
cp .env.example .env          # add ANTHROPIC_API_KEY

# Full pipeline
python -m structure_the_mess.cli supplement.pdf --db data/net.duckdb

# No API key needed - deterministic alias table
python -m structure_the_mess.cli supplement.pdf --no-llm

# Compare the two normalizers
python -m structure_the_mess.cli supplement.pdf --compare

# Fail the build if any accounting identity breaks
python -m structure_the_mess.cli supplement.pdf --strict

# Trace one figure back to the page it came from
python -m structure_the_mess.cli supplement.pdf --trace convertible_notes_noncurrent

# Tests
SUPPLEMENT_PDF=path/to/supplement.pdf pytest tests/ -q
```

Model calls are cached to `.cache/` by page-content hash, so reruns are free.

## Crosschecking a figure

Every value keeps its provenance — source page, original label, and the
verbatim PDF line — so any number can be traced without re-parsing:

```
TRACE  convertible_notes_noncurrent
  statement(s): balance_sheet
  unit(s):      thousands_usd

  period                value  page  label
  Q2 2024           1,285,342     5  Convertible senior notes, net
  Q3 2024           1,286,332     5  Convertible senior notes, net

  verbatim source line(s) from the PDF:
    Convertible senior notes, net 1,285,342 1,286,332 1,287,321 ...

  derived metrics built from this key:
    funding_mix.delta_debt
      Q2 2024=—, Q3 2024=990, Q4 2024=989, ... Q2 2025=1,972,195
```

That last line answers a question worth asking: the 990 in Q3 2024 is not
borrowing. Convertible notes are carried net of issuance costs, and each
quarter a slice of that discount unwinds — the same 990 appears independently
on the cash flow statement as a non-cash add-back. `delta_debt` measures the
change in *carrying value*, which is what makes the balance sheet tie. For cash
actually raised, read the financing section instead. The only real financing
event in this window is Q2 2025.

## What comes out

`line_items` in long format — one row per (statement, key, period), so adding
next quarter is an INSERT, not a schema change. Plus three views:

**`funding_mix`** — the equity roll-forward made queryable. Where did the
change in the asset base actually come from?

```
 period   delta_assets  delta_debt  delta_deferred_rev  delta_apic  retained_earnings
 Q1 2025      420,097         990              35,789     410,222           (38,454)
 Q2 2025    1,841,102   1,972,195              46,854    (148,681)          (50,446)
 Q3 2025      224,034       2,492              62,375     110,902            (1,290)
 Q4 2025      249,861       2,403              80,417     126,227           (12,077)
 Q1 2026      127,721       2,426              69,676     108,553           (22,927)
```

Q2 2025 is the $2B convertible note issuance; the negative APIC that quarter is
the $283M capped-call purchase charged against equity. Every other quarter,
asset growth is roughly 85% paid-in capital plus deferred revenue — and since
option proceeds were only $5.7M against $114M of stock comp in Q1 2026, that
"equity funding" is overwhelmingly dilution rather than cash raised.

**`growth_efficiency`** — asset turnover (gross and ex-cash), YoY revenue and
asset growth, incremental vs. current operating margin, gross margin, stock
comp as a percentage of revenue.

Gross asset turnover appears to collapse from 0.55 to 0.42 across the window.
Ex-cash it is flat at ~1.28 — the entire apparent decline is the $2B raise
sitting in securities. Meanwhile incremental operating margin ran
13.8% → 17.0% → 14.5% → 10.6% while gross margin slid 77.8% → 71.2%: growth is
getting more expensive at the margin.

**`facts`** — a tidy wide view of the keys the growth analysis needs.

## Limitations

- **Single-issuer.** Tuned to this deck's layout and line items. Another
  issuer's supplemental would need schema additions and would likely surface
  new geometry bugs. Generalizing is the honest next step, not a claim this
  already makes.
- The deterministic alias table doesn't cover the non-GAAP reconciliation
  pages, so `--no-llm` quarantines those rows by design.
- `section_path` nests headings by indentation alone, so same-indent siblings
  like *Assets* → *Current assets* replace rather than nest. Cosmetic; the
  canonical key is what's load-bearing.
- No cost-of-capital data, so ROIC-vs-WACC needs an external market data source.
