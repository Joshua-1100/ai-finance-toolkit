"""Money as integer cents. No float ever touches an amount.

Reconciliation turns on exact equality - and on sums of 2 to 5 rows equalling
one deposit. In float64, 444.67 + 879.52 + 755.75 is not the number you wrote
down, so those group matches would silently fail. Amounts are parsed to int
cents on the way in and formatted only on the way out.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

# Characters that routinely decorate an exported amount and carry no meaning.
_STRIP = str.maketrans({"$": None, ",": None, " ": None, " ": None, "'": None})


class AmountError(ValueError):
    """An amount field could not be read as money."""


def parse_cents(raw: object) -> int:
    """Parse an exported amount into integer cents.

    Handles the shapes finance exports actually produce: '1,204.55', '$1204.55',
    '(123.45)' for negative, a trailing minus, and stray whitespace.

        >>> parse_cents("1,204.55")
        120455
        >>> parse_cents("(123.45)")
        -12345
    """
    text = str(raw).strip()
    if not text:
        raise AmountError("amount is blank")

    negative = False
    # Accounting parentheses, e.g. (123.45)
    if text.startswith("(") and text.endswith(")"):
        negative = True
        text = text[1:-1].strip()

    text = text.translate(_STRIP)

    # Leading or trailing sign; trailing is common in mainframe-era exports.
    if text.startswith("-"):
        negative = not negative
        text = text[1:]
    elif text.endswith("-"):
        negative = not negative
        text = text[:-1]
    elif text.startswith("+"):
        text = text[1:]

    if not text:
        raise AmountError("amount has a sign but no digits")

    try:
        value = Decimal(text)
    except InvalidOperation:
        raise AmountError(f"not a number: {raw!r}") from None

    if value != value.quantize(Decimal("0.01")):
        raise AmountError(f"more precision than cents: {raw!r}")

    cents = int(value.scaleb(2))
    return -cents if negative else cents


def format_cents(cents: int) -> str:
    """Render cents for display: -12345 -> '-123.45'."""
    sign = "-" if cents < 0 else ""
    whole, part = divmod(abs(cents), 100)
    return f"{sign}{whole}.{part:02d}"


def format_cents_grouped(cents: int) -> str:
    """Render cents with thousands separators, for console and summary tabs."""
    sign = "-" if cents < 0 else ""
    whole, part = divmod(abs(cents), 100)
    return f"{sign}{whole:,}.{part:02d}"
