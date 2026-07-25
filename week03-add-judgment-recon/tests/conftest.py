from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Make the package importable without an install step, so `pytest` works on a
# fresh clone.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from recon.load import load_bank, load_gl  # noqa: E402


@pytest.fixture(scope="session")
def corpus_dir() -> Path:
    return ROOT / "data"


# Function-scoped on purpose. Some tests tamper with rows to prove the engine
# catches it, and a shared instance would leak that damage into other tests.
# Loading the corpus costs about two milliseconds.
@pytest.fixture
def gl(corpus_dir):
    return load_gl(corpus_dir / "general_ledger.csv")


@pytest.fixture
def bank(corpus_dir):
    return load_bank(corpus_dir / "bank.csv")
