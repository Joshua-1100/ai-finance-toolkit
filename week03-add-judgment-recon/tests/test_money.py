"""Amount parsing. The float trap is the bug this module exists to prevent."""

from __future__ import annotations

import pytest

from recon.money import AmountError, format_cents, format_cents_grouped, parse_cents


@pytest.mark.parametrize("raw,expected", [
    ("0.00", 0),
    ("1204.55", 120455),
    ("1,204.55", 120455),
    ("$1,204.55", 120455),
    (" 1204.55 ", 120455),
    ("-123.45", -12345),
    ("(123.45)", -12345),
    ("($123.45)", -12345),
    ("123.45-", -12345),
    ("+123.45", 12345),
    ("100", 10000),
    ("100.5", 10050),
    ("-0.01", -1),
])
def test_parses_export_shapes(raw, expected):
    assert parse_cents(raw) == expected


@pytest.mark.parametrize("raw", ["", "   ", "abc", "1.2.3", "-", "$", "12,3x.00"])
def test_rejects_junk(raw):
    with pytest.raises(AmountError):
        parse_cents(raw)


def test_strips_a_non_breaking_space_separator():
    """European exports use U+00A0 as a thousands separator.

    Pinned because the escape for it in money.py is easy to mangle when editing
    - and if it ever becomes a literal invisible character again, or gets lost,
    this is the test that notices.
    """
    assert parse_cents("1" + chr(0xa0) + "204.55") == 120455


def test_money_source_has_no_invisible_characters():
    """An invisible character in source is a trap for the next reader."""
    from pathlib import Path

    import recon.money

    src = Path(recon.money.__file__).read_text(encoding="utf-8")
    offenders = {hex(ord(c)) for c in src if ord(c) > 126}
    assert not offenders, f"non-ASCII in money.py: {sorted(offenders)}"


def test_rejects_sub_cent_precision():
    """Silently rounding a third decimal would hide a real data problem."""
    with pytest.raises(AmountError):
        parse_cents("10.005")



# Real amounts lifted from data/general_ledger.csv. Each group sums exactly to
# its total in decimal, and inexactly in float64 - which is how a correct
# many-to-one match gets silently reported as two unmatched items. 5 of the 30
# group matches planted in the corpus fail naive float equality.
FLOAT_TRAP_GROUPS = [
    (("730.03", "46.80"), "776.83"),
    (("472.66", "708.63", "27.83"), "1209.12"),
    (("93.55", "350.41", "444.67", "964.67", "838.94"), "2692.24"),
]


@pytest.mark.parametrize("parts,total", FLOAT_TRAP_GROUPS)
def test_group_sums_are_exact_in_cents(parts, total):
    assert sum(parse_cents(p) for p in parts) == parse_cents(total)


@pytest.mark.parametrize("parts,total", FLOAT_TRAP_GROUPS)
def test_the_same_groups_break_in_float(parts, total):
    """Guards the claim above: if this ever passes, the examples went stale."""
    assert sum(float(p) for p in parts) != float(total)


@pytest.mark.parametrize("cents,plain,grouped", [
    (0, "0.00", "0.00"),
    (5, "0.05", "0.05"),
    (-5, "-0.05", "-0.05"),
    (120455, "1204.55", "1,204.55"),
    (-120455, "-1204.55", "-1,204.55"),
    (100000000, "1000000.00", "1,000,000.00"),
])
def test_formatting(cents, plain, grouped):
    assert format_cents(cents) == plain
    assert format_cents_grouped(cents) == grouped


def test_round_trip():
    for raw in ("0.00", "1204.55", "-98.76", "999999.99"):
        assert format_cents(parse_cents(raw)) == raw.lstrip("+")
