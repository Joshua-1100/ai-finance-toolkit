"""Packaging regressions.

The pipeline can be entirely correct and still fail on someone else's
machine because of a dependency that only exists on the author's. That is
its own class of bug and deserves its own test.
"""
import builtins
import sys

import pytest


@pytest.fixture
def no_pandas(monkeypatch):
    """Make pandas and numpy unimportable for the duration of a test."""
    real_import = builtins.__import__

    def guard(name, *args, **kwargs):
        if name.split(".")[0] in ("pandas", "numpy"):
            raise ModuleNotFoundError(f"No module named '{name}'")
        return real_import(name, *args, **kwargs)

    for mod in [m for m in sys.modules if m.split(".")[0] in ("pandas", "numpy")]:
        monkeypatch.delitem(sys.modules, mod, raising=False)
    monkeypatch.setattr(builtins, "__import__", guard)


def test_html_report_needs_no_pandas(no_pandas, pdf_path, tmp_path):
    # BUG: the report path used DuckDB's .df() helper, which quietly requires
    # pandas and numpy. Neither was in requirements.txt, so the HTML step
    # crashed on a clean install after the rest of the pipeline had already
    # succeeded and written its output.
    from structure_the_mess.cli import main

    exit_code = main([
        pdf_path,
        "--no-llm",
        "--html", str(tmp_path / "report.html"),
        "--db", str(tmp_path / "f.duckdb"),
        "--json", str(tmp_path / "f.json"),
    ])
    assert exit_code == 0
    report = (tmp_path / "report.html").read_text(encoding="utf-8")
    assert "118/118" in report
    assert "<svg" in report


def test_declared_requirements_cover_imports():
    """Every third-party package the pipeline imports must be declared."""
    from pathlib import Path

    req_text = (Path(__file__).resolve().parent.parent / "requirements.txt").read_text()
    declared = {
        line.split(">=")[0].split("==")[0].strip().lower()
        for line in req_text.splitlines()
        if line.strip() and not line.startswith("#")
    }
    assert {"pdfplumber", "duckdb", "pydantic", "anthropic"} <= declared
    # pandas must NOT be needed - if someone reintroduces .df(), the test
    # above fails and this comment explains why.
    assert "pandas" not in declared


class TestTrace:
    """--trace is the crosschecking path: it must show provenance, not just values."""

    def _run(self, pdf_path, tmp_path, key):
        from structure_the_mess.cli import main

        return main([
            pdf_path, "--no-llm", "--trace", key,
            "--db", str(tmp_path / "t.duckdb"),
            "--json", str(tmp_path / "t.json"),
        ])

    def test_trace_shows_source_page_and_verbatim_line(
        self, pdf_path, tmp_path, capsys
    ):
        assert self._run(pdf_path, tmp_path, "convertible_notes_noncurrent") == 0
        out = capsys.readouterr().out
        assert "TRACE  convertible_notes_noncurrent" in out
        assert "balance_sheet" in out
        assert "Convertible senior notes, net" in out   # original label
        assert "1,285,342" in out                        # Q2 2024 value
        # The verbatim PDF line is the actual audit trail.
        assert "1,285,342 1,286,332" in out

    def test_trace_shows_derived_metrics(self, pdf_path, tmp_path, capsys):
        assert self._run(pdf_path, tmp_path, "convertible_notes_noncurrent") == 0
        out = capsys.readouterr().out
        assert "facts.total_debt" in out
        assert "funding_mix.delta_debt" in out
        # The 990 in Q3 2024 is issuance-cost amortization, not new borrowing.
        assert "Q3 2024=990" in out
        assert "(query failed)" not in out

    def test_unknown_key_suggests_near_matches(self, pdf_path, tmp_path, capsys):
        assert self._run(pdf_path, tmp_path, "convertable_notes") == 0
        out = capsys.readouterr().out
        assert "No canonical key" in out
        assert "convertible_notes_noncurrent" in out

    def test_every_dependency_target_is_queryable(self, pdf_path, tmp_path, capsys):
        """Every key in VIEW_DEPENDENCIES must resolve against a real view column.

        The map is hand-maintained alongside the SQL, so it can drift. This
        catches a renamed column before a user hits '(query failed)'.
        """
        from structure_the_mess.cli import build_filing
        from structure_the_mess.load import VIEW_DEPENDENCIES, load

        filing, _ = build_filing(pdf_path, use_llm=False,
                                 company="Cloudflare, Inc.", ticker="NET")
        con = load(filing, tmp_path / "dep.duckdb")
        for target in VIEW_DEPENDENCIES:
            view, column = target.split(".")
            con.sql(f"SELECT period, {column} FROM {view} ORDER BY period_sort")
        con.close()
