"""Optional: validate the real PRE_SEED package (not committed to the repo).

HELLOMYME_PRESEED_CSV_DIR=/path/to/csv HELLOMYME_PRESEED_VERSION=v1.2 uv run pytest tests/test_real_preseed.py
"""
import os
from datetime import date

import pytest

from hellomyme.importer.preseed import load_package, validate

CSV_DIR = os.environ.get("HELLOMYME_PRESEED_CSV_DIR")


@pytest.mark.skipif(not CSV_DIR, reason="HELLOMYME_PRESEED_CSV_DIR not set")
def test_real_package_passes_critical_validation():
    v = validate(load_package(CSV_DIR), date.fromisoformat(
        os.environ.get("HELLOMYME_PRESEED_AS_OF", "2026-10-07")))
    assert not v.critical()
    assert not v.rejects()
    assert len(v.persons) == v.staged_counts["persons"]
