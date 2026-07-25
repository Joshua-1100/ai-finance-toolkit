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


# A one or two digit core is weak evidence - plenty of unrelated documents
# share the number 7. Three is the shortest run worth acting on, and even then
# only alongside an exact amount.
MIN_DIGIT_CORE = 3


def memo_digit_core(memo: str) -> str | None:
    """The document number inside a memo, stripped of everything decorative.

    'Inv 000012345', 'I12345', '#12345' and a bare '12345' all name the same
    invoice. Pulling out the digits and dropping leading zeros reduces them to
    one comparable string.

        >>> memo_digit_core("Inv 000012345")
        '12345'
        >>> memo_digit_core("I12345")
        '12345'

    Returns None when there is nothing worth comparing, which keeps memos with
    no number - or only a short one - out of the fuzzy passes entirely. Chosen
    over string-similarity scoring because a reviewer can check this rule by
    reading it, and cannot check a distance threshold.
    """
    digits = "".join(c for c in memo if c.isdigit())
    if not digits:
        return None
    core = digits.lstrip("0")
    if len(core) < MIN_DIGIT_CORE:
        return None
    return core
