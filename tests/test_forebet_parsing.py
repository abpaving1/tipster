"""
Unit tests for sources/forebet.py pure logic functions.
No browser, Redis, or Postgres required — only tests the
conversion and parsing helpers.

Run with:
    python tests/test_forebet_parsing.py
"""

import os
import sys
from datetime import datetime, timezone
from decimal import Decimal

os.environ.setdefault("PROXY_HOST", "fake-host")
os.environ.setdefault("PROXY_PORT", "1234")
os.environ.setdefault("PROXY_USERNAME", "fake-user")
os.environ.setdefault("PROXY_PASSWORD", "fake-pass")

from sources.forebet import _fractional_to_decimal, _parse_forebet_kickoff, _OUTCOME_MAP


# ---------------------------------------------------------------------------
# _fractional_to_decimal
# ---------------------------------------------------------------------------

def test_fraction_home_win():
    # 5/2 = 2.5 + 1 = 3.5
    assert _fractional_to_decimal("5/2") == Decimal("3.500")

def test_fraction_favourite():
    # 3/4 = 0.75 + 1 = 1.75
    assert _fractional_to_decimal("3/4") == Decimal("1.750")

def test_fraction_evens():
    # 1/1 = 1.0 + 1 = 2.0
    assert _fractional_to_decimal("1/1") == Decimal("2.000")

def test_fraction_no_returns_none():
    assert _fractional_to_decimal("no") is None

def test_fraction_down_returns_none():
    assert _fractional_to_decimal("down") is None

def test_fraction_empty_returns_none():
    assert _fractional_to_decimal("") is None

def test_fraction_dash_returns_none():
    assert _fractional_to_decimal("-") is None

def test_fraction_whitespace_stripped():
    assert _fractional_to_decimal("  5/2  ") == Decimal("3.500")

def test_fraction_case_insensitive_no():
    assert _fractional_to_decimal("NO") is None

def test_fraction_verified_from_snapshot():
    # Values verified directly from the saved MHT snapshot
    assert _fractional_to_decimal("29/10") == Decimal("3.900")
    assert _fractional_to_decimal("1/2") == Decimal("1.500")
    assert _fractional_to_decimal("9/2") == Decimal("5.500")


# ---------------------------------------------------------------------------
# _parse_forebet_kickoff
# ---------------------------------------------------------------------------

def test_kickoff_standard_format():
    result = _parse_forebet_kickoff("22/06/2026 17:00")
    assert result == datetime(2026, 6, 22, 17, 0, tzinfo=timezone.utc)

def test_kickoff_midnight():
    result = _parse_forebet_kickoff("01/01/2027 00:00")
    assert result == datetime(2027, 1, 1, 0, 0, tzinfo=timezone.utc)

def test_kickoff_whitespace_stripped():
    result = _parse_forebet_kickoff("  22/06/2026 17:00  ")
    assert result == datetime(2026, 6, 22, 17, 0, tzinfo=timezone.utc)

def test_kickoff_garbage_returns_none():
    assert _parse_forebet_kickoff("not a date") is None

def test_kickoff_wrong_format_returns_none():
    # ISO format — Forebet uses DD/MM/YYYY not YYYY-MM-DD
    assert _parse_forebet_kickoff("2026-06-22T17:00:00") is None

def test_kickoff_empty_returns_none():
    assert _parse_forebet_kickoff("") is None


# ---------------------------------------------------------------------------
# _OUTCOME_MAP completeness
# ---------------------------------------------------------------------------

def test_outcome_map_covers_all_codes():
    for code in ("1", "X", "2"):
        assert code in _OUTCOME_MAP, f"Missing outcome code: {code}"

def test_outcome_map_values():
    assert _OUTCOME_MAP["1"] == "Home"
    assert _OUTCOME_MAP["X"] == "Draw"
    assert _OUTCOME_MAP["2"] == "Away"


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def _run_all():
    tests = [obj for name, obj in globals().items() if name.startswith("test_") and callable(obj)]
    failures = 0
    for test in tests:
        try:
            test()
            print(f"PASS  {test.__name__}")
        except AssertionError as exc:
            failures += 1
            print(f"FAIL  {test.__name__}: {exc}")
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(f"ERROR {test.__name__}: {type(exc).__name__}: {exc}")
    print(f"\n{len(tests) - failures}/{len(tests)} passed")
    if failures:
        sys.exit(1)


if __name__ == "__main__":
    _run_all()
