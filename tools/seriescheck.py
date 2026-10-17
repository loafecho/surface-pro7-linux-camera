#!/usr/bin/env python3
"""seriescheck - offline lint for git format-patch series and plain diffs.

It checks what can be checked without a kernel tree: the structure of every
hunk, the diffstat, the [PATCH n/m] numbering, the mail headers, the trailers
and, on request, a set of banned constructs in the added lines.

Usage:
  seriescheck.py [options] PATH...

PATH is a directory of NNNN-*.patch files (one series) or a single .patch file.

Options:
  --plain              PATHs are plain diffs (no mail headers): only the diff
                       checks run (hunks, add-only, rules).
  --signer NAME        the one person allowed in Signed-off-by (default:
                       "Tony Garcia"). No Signed-off-by at all is reported as
                       NOTE, because only the submitter can add it.
  --allow-email RE     regex an email address in the headers or the commit
                       message must match (default: GitHub noreply addresses).
  --max-subject N      longest allowed subject summary (default 75).
  --no-ai-disclosure   do not require an AI-assistance disclosure.
  --rules d5           FAIL any added line that matches the D5 rules (module
                       pinning, endless loops, lock-loss heuristics, unbounded
                       wait_for_completion, disable_work_sync).
  --add-only           FAIL any patch that removes a line (test-only patches).

Output: one PASS/NOTE/FAIL line per check, then "ALL PASS" (exit 0) or
"RESULT: FAIL ..." (exit 1). Exit 2 on usage errors.
"""
import argparse
import os
import re
import sys

DEFAULT_SIGNER = "Tony Garcia"
DEFAULT_EMAIL_OK = r"^[0-9]+\+[A-Za-z0-9-]+@users\.noreply\.github\.com$"
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
SUBJECT_TAG_RE = re.compile(r"^\[(?P<tag>[^\]]*)\]\s*(?P<summary>.*)$")
NUM_RE = re.compile(r"\b(?P<n>\d+)/(?P<m>\d+)\b")
HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
DIFFSTAT_RE = re.compile(
    r"^ (\d+) files? changed(?:, (\d+) insertions?\(\+\))?(?:, (\d+) deletions?\(-\))?$", re.M)
SIGNOFF_RE = re.compile(r"^Signed-off-by:\s*(.+?)\s*<([^>]*)>\s*$", re.M)
AI_TRAILER_RE = re.compile(r"^Assisted-by:\s*\S", re.M)
AI_BODY_RE = re.compile(r"\bAI coding assistant\b", re.I)
FORBIDDEN_HEADERS = ("To", "Cc", "Bcc")

D5 = [
    ("module pinning", re.compile(r"\b(try_module_get|__module_get)\s*\(")),
    ("endless loop", re.compile(r"\bfor\s*\(\s*;\s*;\s*\)|\bwhile\s*\(\s*(1|true)\s*\)")),
    ("lock-loss heuristic", re.compile(r"\b(lock_lost|stuck_count)\b|\b(lock|msg|message)_owner\b")),
    ("unbounded wait_for_completion", re.compile(r"\bwait_for_completion\s*\(")),
    ("disable_work_sync", re.compile(r"\bdisable_work_sync\s*\(")),
]


class Report:
    def __init__(self, out=sys.stdout):
        self.out = out
        self.failed = []

    def ok(self, check, msg):
        print(f"PASS {check}: {msg}", file=self.out)

    def note(self, check, msg):
        print(f"NOTE {check}: {msg}", file=self.out)

    def bad(self, check, msg):
        self.failed.append(check)
        print(f"FAIL {check}: {msg}", file=self.out)


# ---------------------------------------------------------------- parsing
class Patch:
    """One patch file split into mail headers, commit message and diff."""

    def __init__(self, path, plain=False):
        self.path = path
        self.name = os.path.basename(path)
        with open(path, encoding="utf-8", errors="replace") as f:
            self.text = f.read()
        lines = self.text.splitlines()
        self.headers = {}
        self.header_names = []
        body_start = 0
        if not plain:
            body_start = self._parse_headers(lines)
        diff_start = next((i for i, ln in enumerate(lines) if ln.startswith("diff --git ")
                           or (ln.startswith("--- ") and i + 1 < len(lines) and lines[i + 1].startswith("+++ "))),
                          len(lines))
        rest = lines[body_start:diff_start]
        # The commit message ends at the first "---" separator line.
        sep = next((i for i, ln in enumerate(rest) if ln == "---"), len(rest))
        self.message = "\n".join(rest[:sep])
        self.notes = "\n".join(rest[sep + 1:])
        self.diff_lines = lines[diff_start:]

    def _parse_headers(self, lines):
        i = 0
        if lines and re.match(r"^From [0-9a-f]{40} ", lines[0]):
            i = 1
        last = None
        while i < len(lines):
            ln = lines[i]
            if ln == "":
                return i + 1
            if ln[:1] in (" ", "\t") and last:
                self.headers[last] += " " + ln.strip()
            else:
                m = re.match(r"^([A-Za-z-]+):\s?(.*)$", ln)
                if not m:
                    return i  # no header block (git format-patch output with headers removed)
                last = m.group(1)
                self.header_names.append(last)
                self.headers[last] = m.group(2)
            i += 1
        return i

    @property
    def subject(self):
        return self.headers.get("Subject")

    @property
    def is_cover(self):
        s = self.subject or ""
        m = SUBJECT_TAG_RE.match(s)
        n = NUM_RE.search(m.group("tag")) if m else None
        return bool(n and n.group("n") == "0") or self.name.startswith("0000-")

    def files(self):
        """Return [(filename, [diff lines])], one entry per file in the diff."""
        lines = list(self.diff_lines)
        # Drop the "-- " signature git format-patch appends after the last file.
        for i in range(len(lines) - 1, -1, -1):
            if lines[i] == "-- ":
                lines = lines[:i]
                break
        out = []
        i = 0
        while i < len(lines):
            ln = lines[i]
            git = ln.startswith("diff --git ")
            unified = ln.startswith("--- ") and i + 1 < len(lines) and lines[i + 1].startswith("+++ ")
            if git or (unified and (not out or "+++" in "".join(x[:3] for x in out[-1][1]))):
                if git:
                    name = ln.split(" b/", 1)[-1]
                else:
                    name = re.sub(r"^\+\+\+ (b/)?", "", lines[i + 1]).split("\t")[0]
                out.append([name, []])
                if git:
                    i += 1
                    continue
            if out:
                out[-1][1].append(ln)
            i += 1
        return [(n, b) for n, b in out]


def check_hunks(p, files):
    """Every hunk's line counts must match its header.

    Returns (errors, added lines, removed lines, {file: (added, removed)})."""
    errors, added, removed = [], [], []
    per_file = {}
    for fname, lines in files:
        a = r = 0
        i = 0
        seen = False
        while i < len(lines):
            m = HUNK_RE.match(lines[i])
            if not m:
                if seen and lines[i].strip():
                    errors.append(f"{fname}: line outside any hunk: {lines[i][:60]!r}")
                    break
                i += 1
                continue
            seen = True
            want_old = int(m.group(2)) if m.group(2) is not None else 1
            want_new = int(m.group(4)) if m.group(4) is not None else 1
            old = new = 0
            i += 1
            while i < len(lines) and (old < want_old or new < want_new):
                ln = lines[i]
                tag = ln[:1]
                if tag == "\\":
                    pass
                elif tag == " " or ln == "":
                    old += 1
                    new += 1
                elif tag == "-":
                    old += 1
                    r += 1
                    removed.append(ln[1:])
                elif tag == "+":
                    new += 1
                    a += 1
                    added.append(ln[1:])
                else:
                    break
                i += 1
            while i < len(lines) and lines[i].startswith("\\"):
                i += 1
            if old != want_old or new != want_new:
                errors.append(f"{fname}: hunk '{m.group(0)}' has {old} old / {new} new lines, "
                              f"header says {want_old} / {want_new}")
        if not seen:
            errors.append(f"{fname}: no hunks")
        per_file[fname] = (a, r)
    return errors, added, removed, per_file


def check_series(paths, opts, rep):
    patches = [Patch(p, plain=opts.plain) for p in paths]
    label = os.path.basename(os.path.dirname(paths[0])) if len(paths) > 1 else os.path.basename(paths[0])
    email_ok = re.compile(opts.allow_email)

    if not opts.plain:
        check_numbering(patches, label, rep)

    for p in patches:
        files = list(p.files())
        if not opts.plain:
            check_headers(p, email_ok, opts, rep)
        if p.is_cover and not opts.plain:
            continue
        if not files:
            rep.bad("diff.present", f"{p.name}: no diff found")
            continue
        errors, added, removed, per_file = check_hunks(p, files)
        if errors:
            for e in errors:
                rep.bad("diff.hunks", f"{p.name}: {e}")
        else:
            rep.ok("diff.hunks", f"{p.name}: {len(files)} file(s), +{len(added)} -{len(removed)}, every hunk header matches its body")
        if not opts.plain:
            check_diffstat(p, per_file, rep)
        if opts.add_only:
            if removed:
                rep.bad("diff.add-only", f"{p.name}: removes {len(removed)} line(s); a test-only patch may only add")
            else:
                rep.ok("diff.add-only", f"{p.name}: adds {len(added)} line(s), removes none")
        if opts.rules == "d5":
            hits = [f"{what}: {ln.strip()[:70]}" for ln in added for what, rx in D5 if rx.search(ln)]
            if hits:
                for h in hits:
                    rep.bad("rules.d5", f"{p.name}: adds {h}")
            else:
                rep.ok("rules.d5", f"{p.name}: no D5 construct in the {len(added)} added line(s)")

    if not opts.plain:
        check_signoff(patches, label, opts.signer, rep)


def check_numbering(patches, label, rep):
    nums = []
    for p in patches:
        s = p.subject
        if s is None:
            rep.bad("format.subject", f"{p.name}: no Subject header")
            continue
        m = SUBJECT_TAG_RE.match(s)
        if not m or "PATCH" not in m.group("tag"):
            rep.bad("format.subject", f"{p.name}: subject has no [PATCH] tag: {s[:60]!r}")
            continue
        n = NUM_RE.search(m.group("tag"))
        nums.append((p, int(n.group("n")) if n else None, int(n.group("m")) if n else None))
    if not nums:
        return
    real = [x for x in nums if not x[0].is_cover]
    if len(nums) == 1 and nums[0][1] is None:
        rep.ok("format.numbering", f"{label}: single patch, no n/m needed")
        return
    totals = {m for _, _, m in nums}
    if None in totals or len(totals) != 1:
        rep.bad("format.numbering", f"{label}: subjects disagree on the series length: {sorted(str(t) for t in totals)}")
        return
    total = totals.pop()
    got = sorted(n for _, n, _ in real)
    if got != list(range(1, total + 1)):
        rep.bad("format.numbering", f"{label}: patches numbered {got}, expected 1..{total}")
        return
    for p, n, _ in nums:
        fm = re.match(r"^(\d{4})-", p.name)
        if fm and int(fm.group(1)) != n:
            rep.bad("format.numbering", f"{p.name}: file number {fm.group(1)} but subject says {n}/{total}")
            return
    cover = [p for p, n, _ in nums if n == 0]
    rep.ok("format.numbering", f"{label}: {total} patch(es) numbered 1..{total}" + (", with a 0/{} cover letter".format(total) if cover else ", no cover letter"))


def check_headers(p, email_ok, opts, rep):
    bad_hdr = [h for h in p.header_names if h in FORBIDDEN_HEADERS]
    if bad_hdr:
        rep.bad("format.headers", f"{p.name}: has {', '.join(bad_hdr)} header(s); recipients are chosen at send time")
    else:
        rep.ok("format.headers", f"{p.name}: no To/Cc/Bcc headers")
    scope = "\n".join(f"{k}: {v}" for k, v in p.headers.items()) + "\n" + p.message
    others = sorted({e for e in EMAIL_RE.findall(scope) if not email_ok.match(e)})
    if others:
        rep.bad("format.email", f"{p.name}: {len(others)} address(es) outside the allowed pattern")
    s = p.subject
    if s:
        m = SUBJECT_TAG_RE.match(s)
        summary = m.group("summary") if m else s
        if len(summary) > opts.max_subject:
            rep.bad("format.subject-length", f"{p.name}: subject summary is {len(summary)} chars (max {opts.max_subject})")
        elif not re.match(r"^[A-Za-z0-9_.-]+(: [A-Za-z0-9_.-]+)*: \S", summary) and not p.is_cover:
            rep.bad("format.subject-prefix", f"{p.name}: subject has no 'subsystem: ' prefix: {summary[:50]!r}")
        else:
            rep.ok("format.subject-length", f"{p.name}: {len(summary)} chars")
    if not p.is_cover and not opts.no_ai_disclosure:
        if AI_TRAILER_RE.search(p.message) or AI_BODY_RE.search(p.message):
            rep.ok("format.ai-disclosure", f"{p.name}: discloses AI assistance")
        else:
            rep.bad("format.ai-disclosure", f"{p.name}: no Assisted-by trailer or AI disclosure sentence")


def check_diffstat(p, per_file, rep):
    m = DIFFSTAT_RE.search(p.notes)
    if not m:
        rep.note("diff.diffstat", f"{p.name}: no diffstat")
        return
    files, ins, dels = int(m.group(1)), int(m.group(2) or 0), int(m.group(3) or 0)
    a = sum(x for x, _ in per_file.values())
    r = sum(y for _, y in per_file.values())
    if (files, ins, dels) == (len(per_file), a, r):
        rep.ok("diff.diffstat", f"{p.name}: {files} file(s), {ins}+ {dels}- matches the diff")
    else:
        rep.bad("diff.diffstat", f"{p.name}: diffstat says {files} file(s) {ins}+ {dels}-, diff has "
                                 f"{len(per_file)} file(s) {a}+ {r}-")


def check_signoff(patches, label, signer, rep):
    signers = set()
    for p in patches:
        signers.update(name for name, _ in SIGNOFF_RE.findall(p.message))
    others = sorted(s for s in signers if s != signer)
    if others:
        rep.bad("signoff", f"{label}: Signed-off-by from {', '.join(others)}; only {signer} may sign")
    elif not signers:
        rep.note("signoff", f"{label}: no Signed-off-by yet; only the submitter adds it")
    else:
        rep.ok("signoff", f"{label}: Signed-off-by {signer} only")


def expand(path):
    if os.path.isdir(path):
        found = sorted(os.path.join(path, f) for f in os.listdir(path) if f.endswith(".patch"))
        return [found] if found else []
    return [[path]]


def main(argv=None, out=sys.stdout):
    ap = argparse.ArgumentParser(add_help=True, usage=__doc__)
    ap.add_argument("paths", nargs="+")
    ap.add_argument("--plain", action="store_true")
    ap.add_argument("--signer", default=DEFAULT_SIGNER)
    ap.add_argument("--allow-email", default=DEFAULT_EMAIL_OK)
    ap.add_argument("--max-subject", type=int, default=75)
    ap.add_argument("--no-ai-disclosure", action="store_true")
    ap.add_argument("--rules", choices=["d5"])
    ap.add_argument("--add-only", action="store_true")
    opts = ap.parse_args(argv)
    rep = Report(out)
    groups = []
    for p in opts.paths:
        if not os.path.exists(p):
            print(f"seriescheck: {p}: no such file or directory", file=sys.stderr)
            return 2
        groups += expand(p)
    if not groups:
        print("seriescheck: no .patch files found", file=sys.stderr)
        return 2
    for g in groups:
        check_series(g, opts, rep)
    print(file=out)
    if rep.failed:
        print(f"RESULT: FAIL ({len(rep.failed)} failed checks: {', '.join(sorted(set(rep.failed)))})", file=out)
        return 1
    print("ALL PASS", file=out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
