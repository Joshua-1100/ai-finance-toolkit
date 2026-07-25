"""Memo comparison.

The ledger's `line_memo` and the statement's `messy_memo` are supposed to name
the same document. They rarely do so identically, which is where the judgment in
this tool lives.
"""

from __future__ import annotations

import re

_WHITESPACE = re.compile(r"\s+")


def normalize_memo(memo: str) -> str:
    """Fold away differences that carry no information.

    Case and internal spacing are artifacts of whichever system exported the
    row, so 'INV  123' and 'Inv 123' are treated as the same string. Anything
    beyond that - punctuation, prefixes, leading zeros - is a real difference
    and is left for the fuzzier passes to judge.

        >>> normalize_memo("  Inv   6060842 ")
        'INV 6060842'
    """
    return _WHITESPACE.sub(" ", memo.strip()).upper()
