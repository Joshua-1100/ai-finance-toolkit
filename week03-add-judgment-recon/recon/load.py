"""Read a GL or bank CSV into enumerated, validated rows.

Two principles here:

Fail loudly, and all at once. A file with forty bad dates should report forty
bad dates, not the first one - otherwise fixing an export becomes forty rounds
of trial and error.

Never silently reinterpret data. Headers are matched against a small alias
table so a real-world export works without editing, but anything genuinely
ambiguous is an error the user resolves, not a guess the program makes.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from .model import LedgerFile, LedgerRow, Side
from .money import AmountError, parse_cents

# ISO first, because that is what a well-behaved export produces. Day-first
# formats (13/05/2026) are deliberately absent: 05/06/2026 is genuinely
# ambiguous, and guessing wrong silently shifts a transaction by months.
DATE_FORMATS = ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%Y/%m/%d", "%d-%b-%Y", "%b %d, %Y")

MAX_MEMO_REPORTED = 60  # truncation for console display only


class LoadError(Exception):
    """A file could not be loaded. Carries every problem found, not just one."""

    def __init__(self, path: str, problems: list[str]) -> None:
        self.path = path
        self.problems = problems
        shown = "\n  ".join(problems[:25])
        extra = f"\n  ... and {len(problems) - 25} more" if len(problems) > 25 else ""
        super().__init__(f"{Path(path).name}: {len(problems)} problem(s)\n  {shown}{extra}")


@dataclass(frozen=True)
class FileSpec:
    """What one side of the reconciliation looks like on disk."""

    side: Side
    id_prefix: str
    date_col: str
    amount_col: str
    memo_col: str
    main_memo_col: str | None
    aliases: dict[str, str]

    @property
    def required(self) -> tuple[str, ...]:
        cols = (self.date_col, self.amount_col, self.memo_col)
        return cols + ((self.main_memo_col,) if self.main_memo_col else ())


GL_SPEC = FileSpec(
    side=Side.GL,
    id_prefix="GL",
    date_col="gl_date",
    amount_col="amount",
    memo_col="line_memo",
    main_memo_col="main_memo",
    aliases={
        "date": "gl_date", "posting_date": "gl_date", "post_date": "gl_date",
        "transaction_date": "gl_date", "entry_date": "gl_date", "gl_dt": "gl_date",
        "amt": "amount", "gl_amount": "amount", "net_amount": "amount",
        "line_amount": "amount",
        "memo": "main_memo", "description": "main_memo", "header_memo": "main_memo",
        "je_memo": "main_memo",
        "detail": "line_memo", "reference": "line_memo", "ref": "line_memo",
        "line_description": "line_memo", "invoice": "line_memo",
    },
)

BANK_SPEC = FileSpec(
    side=Side.BANK,
    id_prefix="BK",
    date_col="posted_date",
    amount_col="posted_amount",
    memo_col="messy_memo",
    main_memo_col=None,
    aliases={
        "date": "posted_date", "post_date": "posted_date", "posting_date": "posted_date",
        "transaction_date": "posted_date", "value_date": "posted_date",
        "amount": "posted_amount", "amt": "posted_amount",
        "transaction_amount": "posted_amount",
        "memo": "messy_memo", "description": "messy_memo", "details": "messy_memo",
        "narrative": "messy_memo", "transaction_description": "messy_memo",
    },
)


def normalize_header(name: str) -> str:
    """'Posted Date ' -> 'posted_date'. Punctuation and case are noise."""
    cleaned = re.sub(r"[^a-z0-9]+", "_", name.strip().lower())
    return cleaned.strip("_")


def map_headers(headers: list[str], spec: FileSpec) -> dict[str, str]:
    """Map the file's headers onto canonical names.

    Returns {canonical_name: actual_header}. Raises if a required column is
    missing or if two headers both claim one canonical name.
    """
    resolved: dict[str, str] = {}
    collisions: list[str] = []

    for actual in headers:
        norm = normalize_header(actual)
        canonical = norm if norm in spec.required else spec.aliases.get(norm)
        if canonical is None:
            continue
        if canonical in resolved:
            collisions.append(
                f"columns {resolved[canonical]!r} and {actual!r} both map to "
                f"{canonical!r} - rename one"
            )
            continue
        resolved[canonical] = actual

    missing = [c for c in spec.required if c not in resolved]
    problems = collisions + [
        f"required column {c!r} not found (headers seen: {', '.join(headers)})"
        for c in missing
    ]
    if problems:
        raise LoadError(spec.side.value, problems)
    return resolved


def parse_date(raw: str) -> date:
    """Parse a date, trying the accepted formats in order of trustworthiness."""
    text = str(raw).strip()
    if not text:
        raise ValueError("date is blank")
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"unrecognized date format: {raw!r}")


def load_side(path: str | Path, spec: FileSpec) -> LedgerFile:
    """Load one file into enumerated rows.

    Row ids are assigned in file order before any sorting or filtering, so
    GL-0007 always means the same line of the same file across every run.
    """
    path = Path(path)
    if not path.exists():
        raise LoadError(str(path), [f"file not found: {path}"])

    problems: list[str] = []
    warnings: list[str] = []
    rows: list[LedgerRow] = []

    # utf-8-sig: Excel prefixes a BOM on CSV export, which would otherwise ride
    # along on the first header and break the mapping.
    with path.open("r", newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames is None:
            raise LoadError(str(path), ["file is empty - no header row"])
        headers = [h for h in reader.fieldnames if h is not None]
        cols = map_headers(headers, spec)

        seq = 0
        for offset, raw_row in enumerate(reader):
            source_row = offset + 2  # +1 for zero-index, +1 for the header line

            if not any((v or "").strip() for v in raw_row.values()):
                warnings.append(f"row {source_row}: blank, skipped")
                continue

            try:
                txn_date = parse_date(raw_row[cols[spec.date_col]])
            except ValueError as exc:
                problems.append(f"row {source_row}: {exc}")
                continue

            try:
                cents = parse_cents(raw_row[cols[spec.amount_col]])
            except AmountError as exc:
                problems.append(f"row {source_row}: {exc}")
                continue

            memo = (raw_row[cols[spec.memo_col]] or "").strip()
            if not memo:
                warnings.append(
                    f"row {source_row}: {spec.memo_col} is blank - identity "
                    f"matching will not be possible for this row"
                )

            main_memo = ""
            if spec.main_memo_col:
                main_memo = (raw_row[cols[spec.main_memo_col]] or "").strip()

            seq += 1
            rows.append(LedgerRow(
                side=spec.side,
                row_id=f"{spec.id_prefix}-{seq:04d}",
                source_row=source_row,
                txn_date=txn_date,
                amount_cents=cents,
                memo=memo,
                main_memo=main_memo,
                # Originals kept verbatim so the untouched-data tabs really are
                # untouched, whatever we derive downstream.
                raw={k: (v or "") for k, v in raw_row.items() if k is not None},
            ))

    if problems:
        raise LoadError(str(path), problems)
    if not rows:
        raise LoadError(str(path), ["no data rows found"])

    return LedgerFile(
        side=spec.side, path=str(path), headers=headers, rows=rows, warnings=warnings,
    )


def load_gl(path: str | Path) -> LedgerFile:
    return load_side(path, GL_SPEC)


def load_bank(path: str | Path) -> LedgerFile:
    return load_side(path, BANK_SPEC)
