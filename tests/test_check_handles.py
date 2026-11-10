import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "check_handles", Path(__file__).parent.parent / "scripts" / "check_handles.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def test_parses_all_twenty_shortlist_rows():
    rows = mod.parse_shortlist(mod.SHORTLIST.read_text())
    assert len(rows) == 20
    assert rows[0] == ("Cold Save", "coldsavefiles")


def test_verdict():
    assert mod.verdict(404) == "free"
    assert mod.verdict(200) == "taken"
    assert mod.verdict(-1).startswith("unknown")
