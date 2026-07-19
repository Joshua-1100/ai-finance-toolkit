import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

PDF_ENV = "SUPPLEMENT_PDF"


@pytest.fixture(scope="session")
def pdf_path() -> str:
    path = os.environ.get(PDF_ENV) or str(
        Path(__file__).resolve().parent.parent / "data" / "supplement.pdf"
    )
    if not Path(path).exists():
        pytest.skip(f"Source PDF not found. Set ${PDF_ENV} to run integration tests.")
    return path


@pytest.fixture(scope="session")
def rows(pdf_path):
    from structure_the_mess.extract import extract_pdf
    return extract_pdf(pdf_path)[0]


@pytest.fixture(scope="session")
def filing(pdf_path):
    from structure_the_mess.cli import build_filing
    return build_filing(pdf_path, use_llm=False, company="Cloudflare, Inc.", ticker="NET")[0]
