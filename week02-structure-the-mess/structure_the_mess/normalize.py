"""LLM normalization: messy labels -> canonical keys.

This is the only place a model is allowed to touch the data, and it is
deliberately the narrowest possible job: given a label string and its
context, pick a key from a closed list. The model never sees a number it
could alter and never invents a field, because the tool schema constrains
its output to an enum. If it returns something off-list, the row is
quarantined rather than accepted.

Why a model at all? Because label -> concept is genuinely ambiguous and
open-ended in a way regex is not:

  * "Loss from operations" and "Income from operations" are the same line
    item; which one prints depends on the sign that quarter.
  * The page-3 footnote tables repeat "Cost of revenue", "Sales and
    marketing" and "General and administrative" as *stock-comp* rows. Same
    strings, different meaning, disambiguated only by context.
  * Wrap artifacts leave labels like "PSU settlement Payment of indemnity
    holdback", where two line items have collided.
  * Units shift mid-document: everything is thousands except the RPO row,
    which is millions, and the margin rows, which are percentages.

Every one of those is a judgment call about meaning. That is the part
worth spending a model on.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Optional

from .schema import CANONICAL_KEYS, LineItem, RawRow, Statement, Unit

CACHE_DIR = Path(__file__).resolve().parent.parent / ".cache"

MODEL = "claude-sonnet-4-5"

# Section title -> statement. Deterministic because the titles are clean;
# no reason to spend a model call on it.
SECTION_TO_STATEMENT: list[tuple[str, Statement]] = [
    ("Non-GAAP Consolidated Statements of Operations", Statement.INCOME_STATEMENT_NON_GAAP),
    ("Consolidated Statements of Operations", Statement.INCOME_STATEMENT),
    ("Consolidated Balance Sheets", Statement.BALANCE_SHEET),
    ("Consolidated Statements of Cash Flows", Statement.CASH_FLOW),
    ("GAAP to Non-GAAP Reconciliations", Statement.RECONCILIATION),
    ("Calculations of Key and Other Selected Metrics", Statement.KEY_METRICS),
]


def statement_for(section_title: str) -> Optional[Statement]:
    for needle, stmt in SECTION_TO_STATEMENT:
        if needle.lower() in section_title.lower():
            return stmt
    return None


def _allowed_keys(stmt: Statement) -> list[str]:
    keys = set(CANONICAL_KEYS[stmt])
    # The key-metrics page also carries the revenue disaggregation tables.
    if stmt is Statement.KEY_METRICS:
        keys |= CANONICAL_KEYS[Statement.SEGMENT]
    return sorted(keys)


def _tool_schema(allowed: list[str]) -> dict:
    return {
        "name": "record_mappings",
        "description": (
            "Record the canonical mapping for every raw label supplied. "
            "Return exactly one entry per input row, in the same order."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "mappings": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "row_index": {"type": "integer"},
                            "canonical_key": {
                                "type": "string",
                                "enum": allowed + ["UNKNOWN"],
                                "description": (
                                    "Use UNKNOWN if no listed key is a faithful "
                                    "match. Never force a bad fit."
                                ),
                            },
                            "unit": {
                                "type": "string",
                                "enum": [u.value for u in Unit],
                            },
                            "confidence": {
                                "type": "number",
                                "minimum": 0.0,
                                "maximum": 1.0,
                            },
                            "reasoning": {
                                "type": "string",
                                "description": "One short clause. Why this key.",
                            },
                        },
                        "required": [
                            "row_index",
                            "canonical_key",
                            "unit",
                            "confidence",
                            "reasoning",
                        ],
                    },
                }
            },
            "required": ["mappings"],
        },
    }


SYSTEM_PROMPT = """You map line-item labels from a public company's quarterly \
financial supplement onto a fixed canonical schema.

Rules:
1. Choose only from the provided enum of canonical keys. If nothing fits \
faithfully, return UNKNOWN. A wrong mapping is far worse than an admitted gap, \
because downstream accounting identity checks will silently absorb it.
2. Use the section context to disambiguate repeated labels. A row labelled \
"Cost of revenue" under a stock-based-compensation footnote is \
sbc_cost_of_revenue, not cost_of_revenue.
3. Sign conventions are already handled upstream; do not reason about them.
4. Infer units from the sample values and the label, not from the page header. \
Most rows are thousands of USD, but percentages, per-share amounts, share \
counts, headcounts, customer counts, and millions-of-USD rows all appear.
5. A label may be corrupted by PDF line-wrapping, so two line items can collide \
in one string. Map to the item the values actually belong to - which is \
normally the one whose text comes first."""


def _cache_key(page: int, labels: list[str]) -> str:
    blob = json.dumps({"page": page, "labels": labels, "model": MODEL}, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()[:20]


def _call_model(rows: list[RawRow], stmt: Statement, client) -> list[dict]:
    allowed = _allowed_keys(stmt)
    payload = [
        {
            "row_index": i,
            "label": r.raw_label,
            "section_context": " > ".join(r.section_path) or "(none)",
            "sample_values": [v for v in list(r.values.values())[:3]],
        }
        for i, r in enumerate(rows)
    ]
    msg = client.messages.create(
        model=MODEL,
        max_tokens=8000,
        system=SYSTEM_PROMPT,
        tools=[_tool_schema(allowed)],
        tool_choice={"type": "tool", "name": "record_mappings"},
        messages=[
            {
                "role": "user",
                "content": (
                    f"Statement: {stmt.value}\n"
                    f"Document section: {rows[0].section_title}\n\n"
                    f"Rows:\n{json.dumps(payload, indent=2)}"
                ),
            }
        ],
    )
    for block in msg.content:
        if block.type == "tool_use":
            return block.input["mappings"]
    raise RuntimeError("Model returned no tool_use block")


def normalize(
    rows: list[RawRow],
    use_llm: bool = True,
    cache: bool = True,
) -> tuple[list[LineItem], list[RawRow]]:
    """Map raw rows onto canonical line items.

    Returns (line_items, quarantined_rows). Anything the model could not
    map faithfully lands in the second list. Nothing is dropped.
    """
    from .aliases import deterministic_map

    line_items: list[LineItem] = []
    quarantined: list[RawRow] = []

    client = None
    if use_llm:
        from anthropic import Anthropic
        from dotenv import load_dotenv

        load_dotenv()
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise RuntimeError(
                "ANTHROPIC_API_KEY not set. Copy .env.example to .env and add "
                "your key, or run with --no-llm to use the deterministic "
                "alias table."
            )
        client = Anthropic()
        CACHE_DIR.mkdir(exist_ok=True)

    by_page: dict[int, list[RawRow]] = {}
    for r in rows:
        by_page.setdefault(r.page, []).append(r)

    for page, page_rows in sorted(by_page.items()):
        stmt = statement_for(page_rows[0].section_title)
        if stmt is None:
            quarantined.extend(page_rows)
            continue

        if use_llm:
            labels = [r.raw_label for r in page_rows]
            cache_path = CACHE_DIR / f"page{page}_{_cache_key(page, labels)}.json"
            if cache and cache_path.exists():
                mappings = json.loads(cache_path.read_text())
            else:
                mappings = _call_model(page_rows, stmt, client)
                if cache:
                    cache_path.write_text(json.dumps(mappings, indent=2))
            method = "llm"
        else:
            mappings = [
                {
                    "row_index": i,
                    "canonical_key": deterministic_map(r, stmt) or "UNKNOWN",
                    "unit": _guess_unit(r).value,
                    "confidence": 1.0,
                    "reasoning": "deterministic alias table",
                }
                for i, r in enumerate(page_rows)
            ]
            method = "alias"

        allowed = set(_allowed_keys(stmt))
        seen: set[str] = set()
        for m in mappings:
            idx = m["row_index"]
            if idx >= len(page_rows):
                continue
            row = page_rows[idx]
            key = m["canonical_key"]
            if key == "UNKNOWN" or key not in allowed or key in seen:
                quarantined.append(row)
                continue
            seen.add(key)
            target_stmt = (
                Statement.SEGMENT
                if key in CANONICAL_KEYS[Statement.SEGMENT]
                and stmt is Statement.KEY_METRICS
                else stmt
            )
            for period, value in row.values.items():
                line_items.append(
                    LineItem(
                        statement=target_stmt,
                        canonical_key=key,
                        label=row.raw_label,
                        period=period,
                        value=value,
                        unit=Unit(m["unit"]),
                        page=row.page,
                        source_line=row.source_line,
                        normalization_confidence=float(m["confidence"]),
                        normalization_method=method,
                    )
                )

    return line_items, quarantined


def _guess_unit(row: RawRow) -> Unit:
    """Unit heuristic for the no-LLM path."""
    label = row.raw_label.lower()
    vals = [v for v in row.values.values() if v is not None]
    if "%" in row.source_line or "margin" in label or "growth" in label or "rate" in label:
        return Unit.PERCENT
    if "per share" in label:
        return Unit.USD_PER_SHARE
    if "shares used in computing" in label:
        return Unit.THOUSANDS_SHARES
    if "headcount" in label or "paying customers" in label:
        return Unit.COUNT
    if "remaining performance obligations" in label:
        return Unit.MILLIONS_USD
    if vals and all(abs(v) < 100 for v in vals):
        return Unit.USD_PER_SHARE
    return Unit.THOUSANDS_USD
