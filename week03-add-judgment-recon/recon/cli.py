"""Entry point.

Step 1: choose the two files, load them, enumerate them, and report what came
in. Matching and the Excel workbook arrive in the steps that follow.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .engine import reconcile
from .excel import OutputLocked, write_workbook
from .load import LoadError, load_bank, load_gl
from .pick import choose_csv, choose_save_path
from .report import load_report, match_report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="recon",
        description="Reconcile a general ledger against a bank statement.",
    )
    # Optional so a first-time user can just run it and get a file dialog, and
    # so repeat runs and tests can skip the dialog entirely.
    parser.add_argument("--gl", type=Path, help="path to the general ledger CSV")
    parser.add_argument("--bank", type=Path, help="path to the bank CSV")
    parser.add_argument(
        "--out", type=Path,
        help="where to write the workbook (default: alongside the ledger)",
    )
    parser.add_argument(
        "--no-excel", action="store_true",
        help="report to the console only, write nothing",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    start_dir = Path.cwd() / "data"
    if not start_dir.is_dir():
        start_dir = Path.cwd()

    gl_path = args.gl or choose_csv("Select the GENERAL LEDGER csv", start_dir)
    # Default the bank dialog to wherever the GL came from - the two files are
    # almost always kept together.
    bank_path = args.bank or choose_csv("Select the BANK csv", Path(gl_path).parent)

    if Path(gl_path).resolve() == Path(bank_path).resolve():
        print("The same file was selected twice.", file=sys.stderr)
        return 2

    try:
        gl = load_gl(gl_path)
        bank = load_bank(bank_path)
    except LoadError as exc:
        print(f"\nCould not load the files.\n\n{exc}\n", file=sys.stderr)
        return 1

    print(load_report(gl, bank))

    result = reconcile(gl, bank)
    print(match_report(result))

    if args.no_excel:
        return 0

    out_path = args.out
    if out_path is None:
        default = Path(gl_path).parent / "reconciliation.xlsx"
        # Only ask when the run was interactive to begin with. A scripted run
        # that passed --gl and --bank should not stop for a dialog.
        interactive = args.gl is None or args.bank is None
        out_path = choose_save_path(default) if interactive else default

    try:
        written = write_workbook(result, out_path)
    except OutputLocked as exc:
        print(f"\n{exc}\n", file=sys.stderr)
        return 3

    print(f"  Workbook written to {written}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
