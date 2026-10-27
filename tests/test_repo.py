"""Run the checkers on the real patch series, patches and evidence in this repo."""
import io
import os

import pytest

import evidencecheck
import seriescheck

parametrize = pytest.mark.parametrize  # alias keeps decorator lines short

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERIES = ["series/ipts-rfc", "series/ipts-rfc/on-pr178", "series/ipu4p", "series/libcamera"]
PLAIN = ["patches/kernel", "patches/libcamera", "patches/pipewire"]


def run(main, args):
    out = io.StringIO()
    rc = main(args, out=out)
    return rc, out.getvalue()


@parametrize("series", SERIES)
def test_series_lint(series):
    rc, out = run(seriescheck.main, [os.path.join(ROOT, series)])
    assert rc == 0, out


@parametrize("d", PLAIN)
def test_plain_patches_have_consistent_hunks(d):
    rc, out = run(seriescheck.main, ["--plain", os.path.join(ROOT, d)])
    assert rc == 0, out


def test_fault_patch_is_add_only_and_d5_clean():
    rc, out = run(seriescheck.main, ["--plain", "--add-only", "--rules=d5",
                                     os.path.join(ROOT, "fault-injection/ipts-fault-inject.patch")])
    assert rc == 0, out


def test_ipts_patch_2_is_flagged_by_d5():
    """Patch 2/2 is on hold because it pins the module and uses a lock-loss
    heuristic; the D5 rules must see that."""
    rc, out = run(seriescheck.main, ["--rules=d5", os.path.join(ROOT, "series/ipts-rfc")])
    assert rc == 1
    assert "FAIL rules.d5: 0002-" in out
    assert "module pinning" in out and "lock-loss heuristic" in out
    assert "FAIL rules.d5: 0001-" not in out


def test_recorded_evidence():
    rc, out = run(evidencecheck.main, [os.path.join(ROOT, "evidence/ipts-f3")])
    assert rc == 0, out
    assert "3/3 cycles pass" in out
