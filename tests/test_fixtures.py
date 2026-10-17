"""Every fixture must give its expected verdict, and the committed fixtures must
match their generator."""
import filecmp
import io
import os
import shlex
import sys

import pytest

import evidencecheck
import seriescheck

parametrize = pytest.mark.parametrize  # alias keeps decorator lines short

HERE = os.path.dirname(os.path.abspath(__file__))
FIX = os.path.join(HERE, "fixtures")
sys.path.insert(0, FIX)
import make_fixtures  # noqa: E402


def fixtures(kind):
    root = os.path.join(FIX, kind)
    return sorted(os.path.join(root, d) for d in os.listdir(root) if os.path.isdir(os.path.join(root, d)))


def read(path):
    with open(path) as f:
        return f.read().strip()


def run(main, d):
    args = shlex.split(read(os.path.join(d, "ARGS"))) if os.path.exists(os.path.join(d, "ARGS")) else []
    out = io.StringIO()
    rc = main(args + [d], out=out)
    return rc, out.getvalue()


def verdict(rc, out, expect):
    lines = out.splitlines()
    if expect == "PASS":
        assert rc == 0, out
        assert lines[-1] == "ALL PASS", out
        assert not any(ln.startswith("FAIL ") for ln in lines), out
    else:
        assert rc == 1, out
        assert any(ln.startswith(f"FAIL {expect}:") for ln in lines), out
        # A bad fixture breaks one thing: no other check may fail.
        others = {ln.split(":")[0][5:] for ln in lines if ln.startswith("FAIL ")} - {expect}
        allowed = {"format.email"} if expect == "format.headers" else set()
        assert others <= allowed, out


@parametrize("d", fixtures("series"), ids=os.path.basename)
def test_series_fixture(d):
    rc, out = run(seriescheck.main, d)
    verdict(rc, out, read(os.path.join(d, "EXPECT")))


@parametrize("d", fixtures("evidence"), ids=os.path.basename)
def test_evidence_fixture(d):
    rc, out = run(evidencecheck.main, d)
    verdict(rc, out, read(os.path.join(d, "EXPECT")))


def test_fixture_set_covers_every_check():
    want_series = {"diff.hunks", "diff.diffstat", "diff.add-only", "rules.d5", "format.numbering",
                   "format.headers", "format.email", "format.ai-disclosure", "format.subject-length", "signoff"}
    want_evidence = {"header", "counts", "boot-id", "f3", "restore"}
    got_series = {read(os.path.join(d, "EXPECT")) for d in fixtures("series")}
    got_evidence = {read(os.path.join(d, "EXPECT")) for d in fixtures("evidence")}
    assert want_series <= got_series
    assert want_evidence <= got_evidence
    assert "PASS" in got_series and "PASS" in got_evidence


def test_committed_fixtures_match_generator(tmp_path):
    make_fixtures.main(str(tmp_path))
    for kind in ("series", "evidence"):
        cmp = filecmp.dircmp(os.path.join(FIX, kind), str(tmp_path / kind))
        stack = [cmp]
        while stack:
            c = stack.pop()
            assert not (c.left_only or c.right_only or c.diff_files), (c.left, c.left_only, c.right_only, c.diff_files)
            stack.extend(c.subdirs.values())
