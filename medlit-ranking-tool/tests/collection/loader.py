"""Load and validate the live search testing collection."""

import json
from pathlib import Path

from .models import CollectionFile, LiveSearchCase, default_cases_path


def load_collection(path: Path | None = None) -> CollectionFile:
    """Parse cases.json and validate every case (including SearchRequest)."""
    p = path or default_cases_path()
    raw = json.loads(p.read_text(encoding="utf-8"))
    return CollectionFile.model_validate(raw)


def load_cases(path: Path | None = None) -> list[LiveSearchCase]:
    """Return the list of cases in file order."""
    return load_collection(path).cases


def get_case(case_id: str, path: Path | None = None) -> LiveSearchCase | None:
    for c in load_cases(path):
        if c.id == case_id:
            return c
    return None
