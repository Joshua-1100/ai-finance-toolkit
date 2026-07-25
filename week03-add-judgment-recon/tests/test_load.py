"""Loading, enumeration and validation, against the real corpus and edge cases."""

from __future__ import annotations

from datetime import date

import pytest

from recon.load import (
    BANK_SPEC,
    GL_SPEC,
    LoadError,
    load_gl,
    map_headers,
    normalize_header,
    parse_date,
)
from recon.model import Side


# --- the real corpus -----------------------------------------------------

def test_loads_corpus(gl, bank):
    assert len(gl) == 205
    assert len(bank) == 205
    assert gl.side is Side.GL
    assert bank.side is Side.BANK


def test_ids_are_sequential_and_padded(gl, bank):
    assert [r.row_id for r in gl.rows[:3]] == ["GL-0001", "GL-0002", "GL-0003"]
    assert bank.rows[0].row_id == "BK-0001"
    assert gl.rows[-1].row_id == "GL-0205"


def test_source_rows_match_spreadsheet_lines(gl):
    """GL-0001 is on line 2 of the file, because line 1 is the header."""
    assert gl.rows[0].source_row == 2
    assert gl.rows[-1].source_row == 206
    assert [r.source_row for r in gl.rows] == list(range(2, 207))


def test_enumeration_is_stable_across_loads(corpus_dir):
    first = load_gl(corpus_dir / "general_ledger.csv")
    second = load_gl(corpus_dir / "general_ledger.csv")
    assert [(r.row_id, r.amount_cents, r.txn_date) for r in first.rows] == \
           [(r.row_id, r.amount_cents, r.txn_date) for r in second.rows]


def test_match_id_starts_empty(gl, bank):
    assert all(r.match_id is None for r in gl.rows)
    assert all(not r.matched for r in bank.rows)
    assert len(gl.unmatched()) == 205


def test_identity_memo_lands_in_memo_field(gl, bank):
    """line_memo and messy_memo play the same role, so they share a field."""
    assert gl.rows[0].memo == gl.rows[0].raw["line_memo"]
    assert bank.rows[0].memo == bank.rows[0].raw["messy_memo"]
    # main_memo is context, present on the GL side only.
    assert gl.rows[0].main_memo == gl.rows[0].raw["main_memo"]
    assert bank.rows[0].main_memo == ""


def test_raw_is_preserved_verbatim(gl):
    """The untouched-data tabs must really be untouched."""
    row = gl.rows[0]
    assert set(row.raw) == {"gl_date", "amount", "main_memo", "line_memo"}
    assert row.raw["amount"] == "444.67"
    assert row.amount_cents == 44467


def test_dates_in_expected_range(gl, bank):
    for f in (gl, bank):
        lo, hi = f.date_range
        assert lo >= date(2026, 5, 1)
        assert hi <= date(2026, 5, 31)


def test_void_pairs_survive_load(gl, bank):
    """Sets 9 and 10 - the negative rows must not be dropped or absolutised."""
    assert sum(1 for r in gl.rows if r.amount_cents == -10000) == 1
    assert sum(1 for r in gl.rows if r.amount_cents == 10000) == 1
    assert sum(1 for r in bank.rows if r.amount_cents == -30000) == 1
    assert sum(1 for r in bank.rows if r.amount_cents == 30000) == 1


def test_totals_lose_no_precision(gl, bank, corpus_dir):
    """The total must equal the same sum taken independently, in Decimal."""
    import csv
    from decimal import Decimal

    for f, filename, col in (
        (gl, "general_ledger.csv", "amount"),
        (bank, "bank.csv", "posted_amount"),
    ):
        with (corpus_dir / filename).open(encoding="utf-8-sig") as fh:
            independent = sum(Decimal(r[col]) for r in csv.DictReader(fh))
        assert isinstance(f.total_cents, int)
        assert Decimal(f.total_cents).scaleb(-2) == independent


def test_group_sums_are_exact_after_load(gl, bank):
    """A set 6 group must sum to its deposit to the cent, post-load."""
    by_key: dict[tuple, list[int]] = {}
    for r in gl.rows:
        by_key.setdefault((r.txn_date, r.memo), []).append(r.amount_cents)
    matched = 0
    for r in bank.rows:
        parts = by_key.get((r.txn_date, r.memo))
        if parts and len(parts) > 1 and sum(parts) == r.amount_cents:
            matched += 1
    assert matched == 15, "expected 15 many-to-one deposits from set 6"


# --- header handling ----------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("Posted Date", "posted_date"),
    ("  posted_date  ", "posted_date"),
    ("POSTED-DATE", "posted_date"),
    ("Posted.Date", "posted_date"),
    ("Amount ($)", "amount"),
])
def test_normalize_header(raw, expected):
    assert normalize_header(raw) == expected


def test_aliases_accept_a_realistic_export():
    cols = map_headers(["Date", "Transaction Amount", "Narrative"], BANK_SPEC)
    assert cols == {
        "posted_date": "Date",
        "posted_amount": "Transaction Amount",
        "messy_memo": "Narrative",
    }


def test_missing_column_names_what_it_saw():
    with pytest.raises(LoadError) as exc:
        map_headers(["gl_date", "amount", "main_memo"], GL_SPEC)
    assert "line_memo" in str(exc.value)
    assert "headers seen" in str(exc.value)


def test_ambiguous_headers_are_an_error_not_a_guess():
    with pytest.raises(LoadError) as exc:
        map_headers(["posted_date", "amount", "amt", "memo"], BANK_SPEC)
    assert "both map to" in str(exc.value)


# --- date handling ------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("2026-05-14", date(2026, 5, 14)),
    ("05/14/2026", date(2026, 5, 14)),
    ("5/14/26", date(2026, 5, 14)),
    ("2026/05/14", date(2026, 5, 14)),
    ("14-May-2026", date(2026, 5, 14)),
    ("May 14, 2026", date(2026, 5, 14)),
])
def test_parse_date_formats(raw, expected):
    assert parse_date(raw) == expected


@pytest.mark.parametrize("raw", ["", "not a date", "2026-13-01", "05-14-2026x"])
def test_parse_date_rejects_junk(raw):
    with pytest.raises(ValueError):
        parse_date(raw)


def test_day_first_dates_are_rejected_not_guessed():
    """13/05/2026 is unambiguous to a human but the format is not supported.

    Accepting it would mean accepting 05/06/2026, which is genuinely ambiguous,
    and guessing wrong shifts a transaction by months.
    """
    with pytest.raises(ValueError):
        parse_date("13/05/2026")


# --- validation ---------------------------------------------------------

def test_all_bad_rows_reported_at_once(tmp_path):
    """Forty bad dates should not mean forty rounds of trial and error."""
    bad = tmp_path / "bad.csv"
    bad.write_text(
        "gl_date,amount,main_memo,line_memo\n"
        "2026-05-01,10.00,ok,Inv 1\n"
        "nonsense,10.00,bad date,Inv 2\n"
        "2026-05-02,abc,bad amount,Inv 3\n"
        "alsononsense,xyz,both bad,Inv 4\n",
        encoding="utf-8",
    )
    with pytest.raises(LoadError) as exc:
        load_gl(bad)
    problems = exc.value.problems
    assert len(problems) == 3
    assert any("row 3" in p for p in problems)
    assert any("row 4" in p for p in problems)
    assert any("row 5" in p for p in problems)


def test_blank_rows_warn_and_are_skipped(tmp_path):
    f = tmp_path / "gaps.csv"
    f.write_text(
        "gl_date,amount,main_memo,line_memo\n"
        "2026-05-01,10.00,ok,Inv 1\n"
        ",,,\n"
        "2026-05-02,20.00,ok,Inv 2\n",
        encoding="utf-8",
    )
    loaded = load_gl(f)
    assert len(loaded) == 2
    # Ids stay contiguous - the skipped line does not leave a hole.
    assert [r.row_id for r in loaded.rows] == ["GL-0001", "GL-0002"]
    assert loaded.rows[1].source_row == 4  # but the trace still points at line 4
    assert any("blank" in w for w in loaded.warnings)


def test_blank_memo_warns_without_failing(tmp_path):
    f = tmp_path / "nomemo.csv"
    f.write_text(
        "gl_date,amount,main_memo,line_memo\n"
        "2026-05-01,10.00,ok,\n",
        encoding="utf-8",
    )
    loaded = load_gl(f)
    assert len(loaded) == 1
    assert any("identity matching" in w for w in loaded.warnings)


def test_excel_bom_does_not_break_headers(tmp_path):
    """Excel writes a BOM on CSV export; it must not ride along on header one."""
    f = tmp_path / "bom.csv"
    f.write_bytes(
        b"\xef\xbb\xbfgl_date,amount,main_memo,line_memo\n2026-05-01,10.00,ok,Inv 1\n"
    )
    assert len(load_gl(f)) == 1


def test_missing_file_is_a_clean_error(tmp_path):
    with pytest.raises(LoadError) as exc:
        load_gl(tmp_path / "nope.csv")
    assert "not found" in str(exc.value)


def test_empty_file_is_a_clean_error(tmp_path):
    f = tmp_path / "empty.csv"
    f.write_text("", encoding="utf-8")
    with pytest.raises(LoadError):
        load_gl(f)


def test_header_only_file_is_a_clean_error(tmp_path):
    f = tmp_path / "headeronly.csv"
    f.write_text("gl_date,amount,main_memo,line_memo\n", encoding="utf-8")
    with pytest.raises(LoadError) as exc:
        load_gl(f)
    assert "no data rows" in str(exc.value)


def test_wrong_file_on_wrong_side_fails_clearly(corpus_dir):
    """Selecting the bank file when asked for the GL should say so plainly."""
    with pytest.raises(LoadError) as exc:
        load_gl(corpus_dir / "bank.csv")
    assert "gl_date" in str(exc.value)
