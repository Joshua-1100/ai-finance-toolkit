"""Deterministic extraction: PDF -> RawRow objects.

No LLM here, on purpose. Pulling numbers off a page is a task with a
correct answer, and a language model is both slower and less trustworthy
at it than geometry is. Everything in this module is reproducible and
unit-testable. The model gets involved only in normalize.py, where the
task genuinely has judgment in it.

The layout problem: this deck has no ruled table borders, so pdfplumber's
table finder collapses each row into one string. Instead we work at the
word level, cluster words into rows by their y-coordinate, find the
"Q2 2024 ... Q1 2026" header to learn the column anchors, and split each
row into a label region and a value region by x-coordinate.
"""
from __future__ import annotations

import collections
import re
from pathlib import Path
from typing import Optional

import pdfplumber

from .schema import RawRow


class ExtractionError(RuntimeError):
    """Raised when the page geometry cannot be resolved into labelled rows."""

# A value token: optional $, optional parens (negative), digits with
# separators, optional decimals, optional trailing %. Or an em/en dash,
# which in financial statements means "nil" - importantly NOT zero, though
# for arithmetic we treat it as absent.
VALUE_RE = re.compile(
    r"^\$?\(?-?[\d,]+(?:\.\d+)?\)?%?$|^[—–]$|^\$$"
)
NIL_TOKENS = {"—", "–", "-"}

# Footnote markers glued to a label, e.g. "revenue(1)(2)" or
# "General and administrative(1)(3)(5)(6)". Single digits in parens
# immediately following a word character - never a real value, because
# real values in this deck always carry a comma or decimal.
FOOTNOTE_RE = re.compile(r"(?<=\w)(?:\(\d\))+")

HEADER_QUARTER_RE = re.compile(r"^Q([1-4])$")
HEADER_YEAR_RE = re.compile(r"^(20\d{2})$")

# Vertical clustering tolerance, in points. This is load-bearing and was
# the source of the pipeline's first real bug. Ordinary rows put the label
# and its values ~1pt apart, so 3.0 looked generous. But when a label wraps
# onto two lines, the renderer vertically CENTERS the values between them -
# 4pt from each label line. At tolerance 3.0 those values formed their own
# label-less row and were dropped on the floor, silently losing the
# "Current portion of convertible senior notes, net" and "Total liabilities
# and stockholders' equity" rows. 5.0 captures the centered case while
# staying well under the ~12pt line pitch. See tests/test_extract.py.
ROW_TOLERANCE = 5.0

FOOTER_BAND = 45.0  # points from the bottom edge reserved for the page number


def clean_number(token: str) -> Optional[float]:
    """Convert a financial-statement token to a float.

    Handles the three conventions that break naive float() calls:
    parentheses for negatives, comma thousands separators, and the em dash
    used for nil. Returns None for nil so that "no value" is distinguishable
    from "zero" - a distinction that matters when you later compute deltas.
    """
    t = token.strip()
    if not t or t in NIL_TOKENS or t == "$":
        return None
    # Strip the percent sign BEFORE testing for parentheses. Negative margins
    # print as "(8.7)%", so checking endswith(")") first misses the negative
    # and then fails to parse at all - silently nulling every negative GAAP
    # operating margin in the document.
    t = t.replace("%", "").replace("$", "").strip()
    negative = t.startswith("(") and t.endswith(")")
    t = t.strip("()").replace(",", "").strip()
    if not t or t in NIL_TOKENS:
        return None
    try:
        val = float(t)
    except ValueError:
        return None
    return -val if negative else val


def clean_label(text: str) -> str:
    """Strip footnote markers and normalize whitespace, keeping meaning intact."""
    text = FOOTNOTE_RE.sub("", text)
    text = text.replace("’", "'")
    return " ".join(text.split()).strip(" :.")


def _group_words_into_rows(words: list[dict]) -> list[list[dict]]:
    buckets: dict[float, list[dict]] = collections.defaultdict(list)
    for w in words:
        key = next(
            (k for k in buckets if abs(k - w["top"]) <= ROW_TOLERANCE), w["top"]
        )
        buckets[key].append(w)
    return [
        sorted(buckets[k], key=lambda w: w["x0"]) for k in sorted(buckets)
    ]


def _find_period_header(rows: list[list[dict]]) -> tuple[list[str], list[float], int]:
    """Locate the quarter header row and return labels, x-anchors, and its index."""
    for idx, row in enumerate(rows):
        toks = [w["text"] for w in row]
        quarters = [t for t in toks if HEADER_QUARTER_RE.match(t)]
        if len(quarters) < 4:
            continue
        periods: list[str] = []
        anchors: list[float] = []
        i = 0
        while i < len(row) - 1:
            a, b = row[i]["text"], row[i + 1]["text"]
            if HEADER_QUARTER_RE.match(a) and HEADER_YEAR_RE.match(b):
                periods.append(f"{a} {b}")
                # Right edge of the header pair; values are right-aligned
                # to roughly this position.
                anchors.append(row[i + 1]["x1"])
                i += 2
            else:
                i += 1
        if len(periods) >= 4:
            return periods, anchors, idx
    return [], [], -1


def _section_title(rows: list[list[dict]], header_idx: int) -> str:
    """The lines above the period header describe what table this is."""
    parts: list[str] = []
    for row in rows[:header_idx]:
        text = " ".join(w["text"] for w in row).strip()
        if text and not text.startswith("CLOUDFLARE"):
            parts.append(text)
    return " | ".join(parts) if parts else "unknown"


def _assign_values(
    value_words: list[dict], anchors: list[float]
) -> dict[int, Optional[float]]:
    """Map value tokens to column indices.

    Fast path: if the row has exactly one value per column, assign
    positionally - unambiguous and immune to alignment drift. Slow path:
    some rows genuinely omit cells, so fall back to nearest-anchor matching
    on the token's right edge, which is where right-aligned numbers agree.
    """
    tokens = [w for w in value_words if w["text"] != "$"]
    out: dict[int, Optional[float]] = {}
    if len(tokens) == len(anchors):
        for i, w in enumerate(tokens):
            out[i] = clean_number(w["text"])
        return out
    for w in tokens:
        col = min(range(len(anchors)), key=lambda i: abs(anchors[i] - w["x1"]))
        if col not in out or out[col] is None:
            out[col] = clean_number(w["text"])
    return out


def _is_heading(orphan_x0: float, next_label_x0: float | None, raw_text: str) -> bool:
    """Distinguish a section heading from a wrapped label fragment.

    Geometry settles it. In this deck headings sit at x0 = 38.6 while the
    line items beneath them are indented to x0 = 44.6, and a wrapped
    continuation always shares its parent's exact indentation. A trailing
    colon is a second, independent signal.
    """
    if raw_text.rstrip().endswith(":"):
        return True
    if next_label_x0 is None:
        return False
    return orphan_x0 < next_label_x0 - 1.0


def extract_page(page: pdfplumber.page.Page, page_no: int) -> list[RawRow]:
    words = page.extract_words(use_text_flow=False, keep_blank_chars=False)
    # Drop the footer band. The centered page number is a bare integer sitting
    # to the right of the label boundary, so it reads as a stray value and
    # trips the label-less-value guard.
    words = [w for w in words if w["top"] < page.height - FOOTER_BAND]
    if not words:
        return []
    rows = _group_words_into_rows(words)
    periods, anchors, header_idx = _find_period_header(rows)
    if not periods:
        return []  # prose page, no tabular data

    section = _section_title(rows, header_idx)
    label_boundary = min(anchors) - 45.0

    # Pass 1: classify every line as a valued row or a label-only orphan,
    # recording indentation so pass 2 can resolve wraps.
    lines: list[dict] = []
    orphan_values: list[dict] = []
    for row in rows[header_idx + 1 :]:
        # A token is a value only if it BOTH sits past the label boundary and
        # parses as a number - that conjunction keeps "2030" inside "issuance
        # of 2030 convertible senior notes" from being read as a data point.
        # But a token that fails either test is label text, wherever it sits.
        # Requiring label words to stay left of the boundary silently ate the
        # tail of long labels on the cash-flow page, turning "restricted cash,
        # beginning" into "restricted cash," and collapsing the beginning- and
        # end-of-period rows onto one indistinguishable label.
        value_words = [
            w
            for w in row
            if w["x1"] > label_boundary and VALUE_RE.match(w["text"])
        ]
        value_ids = {id(w) for w in value_words}
        label_words = [w for w in row if id(w) not in value_ids]
        raw_text = " ".join(w["text"] for w in label_words)
        label_text = clean_label(raw_text)
        if label_text.startswith("_"):
            continue  # footnote rule separator
        if not label_text:
            if value_words:
                # Values with no label mean the row clustering failed. Never
                # drop these silently - that is exactly how a balance sheet
                # ends up quietly not balancing.
                orphan_values.append(
                    {
                        "page": page_no,
                        "source": " ".join(w["text"] for w in row),
                    }
                )
            continue
        lines.append(
            {
                "label": label_text,
                "raw_text": raw_text,
                "x0": label_words[0]["x0"] if label_words else 0.0,
                "values": _assign_values(value_words, anchors) if value_words else None,
                "source": " ".join(w["text"] for w in row),
            }
        )

    # Pass 2: attach orphans. A lowercase orphan is the tail of the label
    # above it ("notes, net", "income (loss)", "equity"). A capitalized
    # orphan at the same indent as the row below is that row's head
    # ("Prepaid expenses and other current" + "assets"). Anything less
    # indented than the row below is a heading and becomes context, not label.
    heading_stack: list[dict] = []
    pending_prefix: list[str] = []
    out: list[RawRow] = []

    for i, line in enumerate(lines):
        if line["values"] is None:
            # Order matters. A lowercase fragment is always the tail of the
            # label above it ("notes, net", "income (loss)", "equity") - never
            # a heading, since headings are title-cased. Test this first,
            # otherwise the indentation rule misreads the tail as a heading
            # because the row below it happens to be indented further.
            if line["label"][:1].islower() and out:
                out[-1].raw_label = clean_label(
                    f"{out[-1].raw_label} {line['label']}"
                )
                continue
            next_valued = next(
                (l for l in lines[i + 1 :] if l["values"] is not None), None
            )
            next_x0 = next_valued["x0"] if next_valued else None
            if _is_heading(line["x0"], next_x0, line["raw_text"]):
                # Headings nest by indentation: entering "Liabilities and
                # Stockholders' Equity" at x0=38.6 must discard the stale
                # "Current assets" at x0=38.6 rather than accumulate it.
                heading_stack = [
                    h for h in heading_stack if h["x0"] < line["x0"]
                ]
                heading_stack.append({"x0": line["x0"], "label": line["label"]})
                continue
            pending_prefix.append(line["label"])
            continue

        label = " ".join(pending_prefix + [line["label"]]).strip()
        pending_prefix = []
        out.append(
            RawRow(
                page=page_no,
                section_title=section,
                section_path=[h["label"] for h in heading_stack],
                raw_label=clean_label(label),
                values={
                    periods[j]: line["values"].get(j) for j in range(len(periods))
                },
                source_line=line["source"],
            )
        )

    if orphan_values:
        raise ExtractionError(
            f"Page {page_no}: {len(orphan_values)} row(s) carried values but no "
            f"label after wrap resolution. Row clustering is wrong; fix it "
            f"rather than accepting partial data. First: "
            f"{orphan_values[0]['source'][:90]!r}"
        )
    return out


def extract_pdf(path: str | Path) -> tuple[list[RawRow], list[str]]:
    """Extract every tabular row in the document.

    Returns the rows plus the ordered list of fiscal periods found.
    """
    rows: list[RawRow] = []
    periods: list[str] = []
    with pdfplumber.open(str(path)) as pdf:
        for i, page in enumerate(pdf.pages, start=1):
            page_rows = extract_page(page, i)
            rows.extend(page_rows)
            if page_rows and not periods:
                periods = list(page_rows[0].values.keys())
    return rows, periods
