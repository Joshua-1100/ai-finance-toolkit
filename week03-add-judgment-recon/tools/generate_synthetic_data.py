#!/usr/bin/env python3
"""Generate the synthetic GL and bank files used to test the reconciliation.

Implements data/synthetic_requirements.txt. Standard library only - no pandas,
no installs, no network. The seed is fixed, so every run on every machine
produces byte-identical CSVs.

    python tools/generate_synthetic_data.py

Because there is no separate answer key, this file IS the specification of what
"correct" looks like. Each build_set_NN function below documents the match
scenario it plants, and the recon engine's tests should be readable against it.
"""

from __future__ import annotations

import argparse
import csv
import random
from datetime import date, timedelta
from pathlib import Path

DATE_MIN = date(2026, 5, 1)
DATE_MAX = date(2026, 5, 31)
SEED = 20260503

GL_HEADERS = ["gl_date", "amount", "main_memo", "line_memo"]
BANK_HEADERS = ["posted_date", "posted_amount", "messy_memo"]
MEMO_LIMITS = {"main_memo": 100, "line_memo": 150, "messy_memo": 250}

# Amounts are carried as integer cents everywhere and only formatted to two
# decimals on write, so group sums stay exact.
AMOUNT_MIN_CENTS = 500
AMOUNT_MAX_CENTS = 999_99

PRESIDENT_FIRST = [
    "George", "John", "Thomas", "James", "Andrew", "Martin", "William",
    "Zachary", "Millard", "Franklin", "Abraham", "Ulysses", "Rutherford",
    "Chester", "Grover", "Benjamin", "Theodore", "Woodrow", "Warren",
    "Calvin", "Herbert", "Harry", "Dwight", "Lyndon", "Richard", "Gerald",
    "Ronald", "Barack", "Joseph",
]

PRESIDENT_LAST = [
    "Washington", "Adams", "Jefferson", "Madison", "Monroe", "Jackson",
    "Harrison", "Tyler", "Polk", "Taylor", "Fillmore", "Pierce", "Buchanan",
    "Lincoln", "Grant", "Hayes", "Garfield", "Arthur", "Cleveland",
    "McKinley", "Roosevelt", "Taft", "Wilson", "Harding", "Coolidge",
    "Hoover", "Truman", "Eisenhower", "Kennedy", "Nixon", "Ford", "Carter",
    "Reagan", "Bush", "Clinton", "Obama", "Biden",
]

# One theme per set, so a human reading a row can tell which scenario it came
# from without an answer key.
VEGETABLES = [
    "Celery", "Carrot", "Parsnip", "Radish", "Turnip", "Spinach", "Cabbage",
    "Leek", "Shallot", "Endive", "Fennel", "Kale", "Okra", "Artichoke",
    "Rutabaga",
]
FRUITS = [
    "Apple", "Banana", "Cherry", "Damson", "Elderberry", "Fig", "Guava",
    "Honeydew", "Kiwi", "Mango", "Nectarine", "Papaya", "Quince",
    "Raspberry", "Tangerine",
]
LEMONS = [
    "Meyer", "Eureka", "Lisbon", "Ponderosa", "Femminello", "Verna",
    "Primofiori", "Bearss", "Villafranca", "Genoa", "Avalon", "Harvey",
    "Interdonato", "Sorrento", "Yen Ben",
]
ADJECTIVES = [
    "Happy", "Restless", "Curious", "Brittle", "Solemn", "Nimble", "Radiant",
    "Stubborn", "Gentle", "Vivid", "Anxious", "Prudent", "Jagged", "Mellow",
    "Somber",
]
ADVERBS = [
    "Quickly", "Softly", "Rarely", "Gladly", "Sternly", "Openly", "Wearily",
    "Boldly", "Faintly", "Neatly", "Loosely", "Bravely", "Calmly", "Sharply",
    "Plainly",
]
ANGELS = [
    "Gabriel", "Michael", "Raphael", "Uriel", "Ariel", "Azrael", "Camael",
    "Jophiel", "Zadkiel", "Metatron", "Sandalphon", "Raguel", "Remiel",
    "Barachiel", "Selaphiel",
]
# Set 7 is "like Set 6" in the spec, which would repeat the angel theme. Given
# its own theme instead so the two many-to-one directions stay distinguishable.
TREES = [
    "Willow", "Cedar", "Maple", "Birch", "Aspen", "Cypress", "Juniper",
    "Magnolia", "Sycamore", "Hawthorn", "Alder", "Hemlock", "Poplar",
    "Spruce", "Rowan",
]


class Gen:
    """Random helpers bound to one seeded Random instance."""

    def __init__(self, seed: int) -> None:
        self.rng = random.Random(seed)

    # -- primitives ------------------------------------------------------
    def amount(self) -> int:
        """A random amount, in cents."""
        return self.rng.randint(AMOUNT_MIN_CENTS, AMOUNT_MAX_CENTS)

    def date_between(self, lo: date = DATE_MIN, hi: date = DATE_MAX) -> date:
        return lo + timedelta(days=self.rng.randint(0, (hi - lo).days))

    def digits(self, lo: int, hi: int) -> str:
        """A digit string of random length in [lo, hi], no leading zero."""
        n = self.rng.randint(lo, hi)
        first = self.rng.choice("123456789")
        rest = "".join(self.rng.choice("0123456789") for _ in range(n - 1))
        return first + rest

    # -- memo builders ---------------------------------------------------
    def themed_memo(self, theme: list[str]) -> str:
        """e.g. 'Celery Washington' - the main_memo pattern for most sets."""
        return f"{self.rng.choice(theme)} {self.rng.choice(PRESIDENT_LAST)}"

    def default_memo(self) -> str:
        """The spec's fallback for any memo a set does not pin down."""
        return f"{self.rng.choice(PRESIDENT_FIRST)}{self.digits(2, 14)}"

    def invoice_memo(self) -> str:
        """e.g. 'Inv 6060842' - matched on both sides in the clean sets."""
        return f"Inv {self.digits(2, 10)}"

    def fuzzy_invoice_pair(self) -> tuple[str, str]:
        """A GL/bank memo pair that refers to one invoice but does not match.

        'Inv 000012345' on the GL side against 'I12345' or bare '12345' on the
        bank side - same core number, different dress.
        """
        core = self.digits(3, 8)
        gl = f"Inv {core.zfill(len(core) + self.rng.randint(2, 5))}"
        bank = self.rng.choice([f"I{core}", core, f"INV{core}", f"#{core}"])
        return gl, bank

    def backwards_president(self) -> str:
        """'Bush' -> 'Hsub'."""
        return self.rng.choice(PRESIDENT_LAST)[::-1].capitalize()


def gl_row(d: date, cents: int, main_memo: str, line_memo: str) -> dict:
    return {
        "gl_date": d.isoformat(),
        "amount": cents,
        "main_memo": main_memo,
        "line_memo": line_memo,
    }


def bank_row(d: date, cents: int, messy_memo: str) -> dict:
    return {
        "posted_date": d.isoformat(),
        "posted_amount": cents,
        "messy_memo": messy_memo,
    }


# ---------------------------------------------------------------------------
# Sets. Each returns (gl_rows, bank_rows).
# ---------------------------------------------------------------------------

def build_set_01(g: Gen) -> tuple[list, list]:
    """LowHangingFruit: 50 exact matches on amount, date and memo."""
    gl, bank = [], []
    for _ in range(50):
        d, cents, memo = g.date_between(), g.amount(), g.invoice_memo()
        gl.append(gl_row(d, cents, g.themed_memo(VEGETABLES), memo))
        bank.append(bank_row(d, cents, memo))
    return gl, bank


def build_set_02(g: Gen) -> tuple[list, list]:
    """Dateshifts slight: amount and memo match, GL date off by 1-3 days.

    25 rows where the GL is ahead of the bank, 25 where it is behind.
    """
    gl, bank = [], []
    # Keep the bank date away from the month edges so the shifted GL date
    # still lands inside the required range.
    lo, hi = DATE_MIN + timedelta(days=3), DATE_MAX - timedelta(days=3)
    for i in range(50):
        direction = 1 if i < 25 else -1
        posted = g.date_between(lo, hi)
        shifted = posted + timedelta(days=direction * g.rng.randint(1, 3))
        cents, memo = g.amount(), g.invoice_memo()
        gl.append(gl_row(shifted, cents, g.themed_memo(FRUITS), memo))
        bank.append(bank_row(posted, cents, memo))
    return gl, bank


def build_set_03(g: Gen) -> tuple[list, list]:
    """Dateshifts widely: amount and memo match, dates >= 14 days apart."""
    gl, bank = [], []
    for _ in range(10):
        early = g.date_between(DATE_MIN, DATE_MAX - timedelta(days=14))
        gap = g.rng.randint(14, (DATE_MAX - early).days)
        late = early + timedelta(days=gap)
        gl_date, posted = (early, late) if g.rng.random() < 0.5 else (late, early)
        cents, memo = g.amount(), g.invoice_memo()
        gl.append(gl_row(gl_date, cents, g.themed_memo(LEMONS), memo))
        bank.append(bank_row(posted, cents, memo))
    return gl, bank


def build_set_04(g: Gen) -> tuple[list, list]:
    """Imperfect Identity: amount and date match, memos only resemble."""
    gl, bank = [], []
    for _ in range(10):
        d, cents = g.date_between(), g.amount()
        gl_memo, bank_memo = g.fuzzy_invoice_pair()
        gl.append(gl_row(d, cents, g.themed_memo(ADJECTIVES), gl_memo))
        bank.append(bank_row(d, cents, bank_memo))
    return gl, bank


def build_set_05(g: Gen) -> tuple[list, list]:
    """Imperfect Date_Identity: amount matches, date and memo both differ."""
    gl, bank = [], []
    for _ in range(10):
        posted = g.date_between()
        gl_date = posted
        while gl_date == posted:
            offset = g.rng.choice([-1, 1]) * g.rng.randint(1, 20)
            candidate = posted + timedelta(days=offset)
            if DATE_MIN <= candidate <= DATE_MAX:
                gl_date = candidate
        cents = g.amount()
        gl_memo, bank_memo = g.fuzzy_invoice_pair()
        gl.append(gl_row(gl_date, cents, g.themed_memo(ADVERBS), gl_memo))
        bank.append(bank_row(posted, cents, bank_memo))
    return gl, bank


def build_set_06(g: Gen) -> tuple[list, list]:
    """GLmany Bankone: groups of 2, 3 and 5 GL rows summing to one bank row.

    Five groups at each size - 50 GL rows against 15 bank rows. Date and memo
    match across the whole group.
    """
    gl, bank = [], []
    for size in (2, 3, 5):
        for _ in range(5):
            d, memo = g.date_between(), g.invoice_memo()
            parts = [g.amount() for _ in range(size)]
            for cents in parts:
                gl.append(gl_row(d, cents, g.themed_memo(ANGELS), memo))
            bank.append(bank_row(d, sum(parts), memo))
    return gl, bank


def build_set_07(g: Gen) -> tuple[list, list]:
    """GLone Bankmany: set 6 mirrored - 15 GL rows against 50 bank rows."""
    gl, bank = [], []
    for size in (2, 3, 5):
        for _ in range(5):
            d, memo = g.date_between(), g.invoice_memo()
            parts = [g.amount() for _ in range(size)]
            for cents in parts:
                bank.append(bank_row(d, cents, memo))
            gl.append(gl_row(d, sum(parts), g.themed_memo(TREES), memo))
    return gl, bank


def build_set_08(g: Gen) -> tuple[list, list]:
    """NoMatch: 3 rows a side that agree on nothing. Memos run backwards."""
    gl, bank = [], []
    used_cents: set[int] = set()

    def unique_amount() -> int:
        while True:
            cents = g.amount()
            if cents not in used_cents:
                used_cents.add(cents)
                return cents

    for _ in range(3):
        gl.append(gl_row(
            g.date_between(), unique_amount(),
            f"{g.backwards_president()} {g.backwards_president()}",
            g.backwards_president(),
        ))
    for _ in range(3):
        bank.append(bank_row(
            g.date_between(), unique_amount(), g.backwards_president(),
        ))
    return gl, bank


def build_set_09(g: Gen) -> tuple[list, list]:
    """GLvoid: a +100.00 / -100.00 GL pair that nets to zero.

    One-sided by design - there is no bank counterpart. The two rows share a
    date and memo, which is the signal that they cancel each other out.
    """
    d, main_memo, line_memo = g.date_between(), g.default_memo(), g.invoice_memo()
    return [
        gl_row(d, 100_00, main_memo, line_memo),
        gl_row(d, -100_00, main_memo, line_memo),
    ], []


def build_set_10(g: Gen) -> tuple[list, list]:
    """Bankvoid: a +300.00 / -300.00 bank pair that nets to zero, GL silent."""
    d, memo = g.date_between(), g.invoice_memo()
    return [], [
        bank_row(d, 300_00, memo),
        bank_row(d, -300_00, memo),
    ]


def build_set_11(g: Gen) -> tuple[list, list]:
    """CloseToMatch: date and memo match, amount off by 1 to 9 cents."""
    gl, bank = [], []
    for _ in range(5):
        d, cents, memo = g.date_between(), g.amount(), g.invoice_memo()
        drift = g.rng.choice([-1, 1]) * g.rng.randint(1, 9)
        gl.append(gl_row(d, cents, g.default_memo(), memo))
        bank.append(bank_row(d, cents + drift, memo))
    return gl, bank


BUILDERS = [
    build_set_01, build_set_02, build_set_03, build_set_04, build_set_05,
    build_set_06, build_set_07, build_set_08, build_set_09, build_set_10,
    build_set_11,
]


def validate(gl_rows: list[dict], bank_rows: list[dict]) -> None:
    """Fail loudly if a set has drifted outside the spec's rules."""
    for rows, headers in ((gl_rows, GL_HEADERS), (bank_rows, BANK_HEADERS)):
        date_key, amount_key = headers[0], headers[1]
        for row in rows:
            assert set(row) == set(headers), f"bad columns: {sorted(row)}"
            d = date.fromisoformat(row[date_key])
            assert DATE_MIN <= d <= DATE_MAX, f"{d} outside test range"
            assert isinstance(row[amount_key], int), "amounts must stay in cents"
            for field, limit in MEMO_LIMITS.items():
                if field in row:
                    assert len(row[field]) <= limit, f"{field} over {limit} chars"


def write_csv(path: Path, headers: list[str], rows: list[dict]) -> None:
    amount_key = headers[1]
    path.parent.mkdir(parents=True, exist_ok=True)
    # newline="" per the csv docs, so Windows does not double the line endings.
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=headers)
        writer.writeheader()
        for row in rows:
            out = dict(row)
            out[amount_key] = f"{row[amount_key] / 100:.2f}"
            writer.writerow(out)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=SEED)
    parser.add_argument(
        "--outdir", type=Path,
        default=Path(__file__).resolve().parent.parent / "data",
    )
    args = parser.parse_args()

    g = Gen(args.seed)
    gl_rows: list[dict] = []
    bank_rows: list[dict] = []
    for build in BUILDERS:
        gl_part, bank_part = build(g)
        gl_rows.extend(gl_part)
        bank_rows.extend(bank_part)

    validate(gl_rows, bank_rows)

    # Shuffle so the scenarios are interleaved rather than arriving in tidy
    # blocks - a recon that only works on sorted input is not a recon.
    g.rng.shuffle(gl_rows)
    g.rng.shuffle(bank_rows)

    write_csv(args.outdir / "general_ledger.csv", GL_HEADERS, gl_rows)
    write_csv(args.outdir / "bank.csv", BANK_HEADERS, bank_rows)
    print(f"general_ledger.csv: {len(gl_rows)} rows")
    print(f"bank.csv:           {len(bank_rows)} rows")


if __name__ == "__main__":
    main()
