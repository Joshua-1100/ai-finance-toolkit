# contract-rag

Retrieval-augmented research over a contract, ending in an audit-ready technical
memorandum that cites the passage behind every fact it asserts.

> **Status: working end to end.** Point it at a contract, get a memo whose
> factual claims each trace to a numbered chunk of the source.

## Running it

```bash
pip install scikit-learn numpy
python rag_pipeline.py
```

Reads every `.txt` in `data/`, reads the research questions from
`RAGprompts.txt`, and writes `retrieved_context.md`. Pass `--k` to change how
many chunks come back per question, `--chunk-tokens` and `--overlap` to retune
the splitter, and `--backend openai` to swap lexical retrieval for dense
embeddings (needs `OPENAI_API_KEY`).

## What you get

| File | What it holds |
|---|---|
| [`retrieved_context.md`](retrieved_context.md) | The evidence file — every retrieved chunk, with its ID and cosine score, grouped by question |
| [`ASC340-40_Pooled_Commissions_Technical_Memo.docx`](ASC340-40_Pooled_Commissions_Technical_Memo.docx) | The deliverable — an 11-page memo on the pooled commission plan |
| [`data/PooledCommissions.txt`](data/PooledCommissions.txt) | The corpus: a synthetic SaaS pooled commission plan |
| [`RAGprompts.txt`](RAGprompts.txt) | The four research questions posed to the corpus |

Chunk IDs read `<source>#S<section>.<window>`, so a claim in the memo can be
walked back to a specific passage of the plan without rereading the contract.

## How the pipeline is built

**Chunking is section-aware.** The splitter breaks on numbered contract
headings first, because a contract already tells you what its citation units
are, and only then applies a 160-word sliding window inside sections that are
too long. The window overlaps by 40 words. That overlap is the whole point: the
operative facts here — 3.5%, 0.5%, twelve months, 15% — sit in adjacent
sentences, and a hard split between a rate and its qualifying clause strands the
number from its meaning.

**Embedding is hybrid and lexical by default.** Word 1–2 grams catch phrases
like "renewal option"; character 3–5 grams keep `3.5%` and `0.5%` matchable when
the query tokenizes them differently. Both are L2-normalised, so the dot product
against the index is cosine similarity directly. TF-IDF over a dense model is a
deliberate choice, not a shortcut — it is deterministic and offline, and a
workpaper that cannot be reproduced next quarter is not a workpaper. The dense
backend is there when you want recall over precision.

## What the retrieval scores actually showed

| Question | Top chunk | Score |
|---|---|---|
| Q1 material right / amortization period | `#S8.1` | 0.406 |
| Q2 commensurate renewal commission | `#S8.1` | 0.348 |
| Q3 practical expedient eligibility | `#S8.1` | 0.312 |
| Q4 draft footnote disclosure | `#S5.1` | 0.149 |

Three of the four questions land on the same chunk, which is the correct
result — Section 3 of the addendum carries all four operative facts at once.

Q4 is the interesting failure. Its scores are uniformly low because it asks for
disclosure language that appears nowhere in the corpus, and no amount of
retuning will fix that: the answer lives in the Codification, not in the
contract. Retrieval supplies the *facts* of an arrangement. It does not supply
the accounting. Worth recording rather than hiding, because a RAG system that
returned a confident chunk for Q4 would be telling you something false.

Indexing the relevant ASC guidance alongside the contract is the obvious next
iteration.

## The accounting, briefly

The memo answers four questions about a pooled commission plan on 12-month SaaS
contracts carrying a 15% contractual renewal discount. Three findings are worth
surfacing here:

**There is a threshold problem the questions did not ask about.** The plan says
its funds are "not tied to any single, specific customer contract," splits 60%
by base salary and 40% by discretionary MBO scores, and pays nothing below 85%
regional quota attainment. That fails the incremental-cost test in
ASC 340-40-25-1 — there may be no asset to amortize at all. The memo answers the
four questions anyway, but leads with this, because it governs.

**The plan drafts against itself.** It cuts renewal funding to 0.5% "because
this renewal requires minimal sales friction." That sentence is a written
admission that the 3.5% initial commission buys a multi-year relationship, which
is close to dispositive under the level-of-effort view of the commensurate test.

**The math is not close.** 0.5% ÷ 3.5% is 14.3% on rates, but only 12.1% on
absolute dollars once the 15% price discount compounds against the renewal base.
Not commensurate under either accepted view.

The corpus is synthetic. The memo applies real guidance to it — ASC 340-40,
ASC 606-10-55-41 through 55-45, ASU 2014-09 BC309, and the TRG papers on
contract costs — but it is a practice artifact, not advice.
