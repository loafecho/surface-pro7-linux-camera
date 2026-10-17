#!/usr/bin/env python3
"""evidencecheck - recompute the verdict of ipts fault-campaign evidence files.

The campaign scripts in fault-injection/host/ write "ipts-evidence v1" files: a
header, one CYCLE line per cycle and a SUMMARY line. This checker never trusts
the SUMMARY. It recomputes every cycle's outcome from the raw fields and fails
when the summary disagrees, when a boot ID is not in the device's boot journal,
or when the fault campaign shows a task stuck in the HID core.

Usage:
  evidencecheck.py [--boots FILE] EVIDENCE...

EVIDENCE is an evidence file or a directory of *.txt evidence files.
--boots FILE  a `journalctl --list-boots` listing. Without it, the boot IDs are
              taken from the LIST-BOOTS lines of the device-check evidence.

Checks (one PASS/FAIL line each):
  header   first line "# ipts-evidence v1", with kind, phase, script,
           script-sha256, boot-id and srcversion
  counts   CYCLE lines numbered 1..n; SUMMARY cycles= and pass= equal the
           recomputed values (and hidcore= for f3-rmmod)
  boot-id  the header boot ID and every per-cycle boot ID are in the listing
  f3       f3-rmmod: every cycle has fault_fired=yes, hidraw_stuck=0,
           rmmod_rc=0, 0 <= rmmod_s <= 30 and blocked_in != hidcore; a
           TOUCH-CHECK line, when present, says PASS
  restore  device-check: manifest=OK and listboots_has_boot=yes

Ends with "ALL PASS" (exit 0) or "RESULT: FAIL ..." (exit 1); 2 on usage errors.
"""
import argparse
import os
import re
import sys

MAGIC = "# ipts-evidence v1"
REQUIRED = ("kind", "phase", "script", "script-sha256", "boot-id", "srcversion")
RMMOD_MAX = 30
BOOT_RE = re.compile(r"^\s*(?:LIST-BOOTS\s+)?-?\d+\s+([0-9a-f]{32})\s", re.M)
CYCLE_BOOT_KEYS = ("boot", "after_boot", "cleared_by_boot")


def parse(path):
    with open(path, encoding="utf-8", errors="replace") as f:
        lines = f.read().splitlines()
    ev = {"path": path, "magic": bool(lines) and lines[0] == MAGIC, "head": {}, "cycles": [],
          "summary": None, "touch": None, "text": "\n".join(lines)}
    for ln in lines:
        m = re.match(r"^# ([a-z0-9-]+): (.*)$", ln)
        if m:
            ev["head"].setdefault(m.group(1), m.group(2).strip())
            continue
        m = re.match(r"^CYCLE (\d+) (.*)$", ln)
        if m:
            ev["cycles"].append((int(m.group(1)), dict(re.findall(r"(\w+)=(\S+)", m.group(2)))))
            continue
        m = re.match(r"^SUMMARY (.*)$", ln)
        if m:
            ev["summary"] = dict(re.findall(r"(\w+)=(\S+)", m.group(1)))
            continue
        m = re.match(r"^TOUCH-CHECK result=(\S+)", ln)
        if m:
            ev["touch"] = m.group(1)
    return ev


def num(v, default=-1):
    return int(v) if v is not None and re.fullmatch(r"\d+", v) else default


def f3_outcome(c):
    g = c.get
    passed = (g("fault_fired") == "yes" and g("hidraw_stuck") == "0" and g("rmmod_rc") == "0"
              and 0 <= num(g("rmmod_s")) <= RMMOD_MAX and g("blocked_in") != "hidcore")
    return "pass" if passed else "fail"


def device_outcome(c):
    return "pass" if c.get("manifest") == "OK" and c.get("listboots_has_boot") == "yes" else "fail"


OUTCOME = {"f3-rmmod": f3_outcome, "device-check": device_outcome}


class Checker:
    def __init__(self, out):
        self.out = out
        self.failed = []

    def ok(self, check, msg):
        print(f"PASS {check}: {msg}", file=self.out)

    def bad(self, check, msg):
        self.failed.append(check)
        print(f"FAIL {check}: {msg}", file=self.out)

    def run(self, files, boots):
        for path in files:
            self.one(parse(path), boots)
        print(file=self.out)
        if self.failed:
            print(f"RESULT: FAIL ({len(self.failed)} failed checks: {', '.join(sorted(set(self.failed)))})",
                  file=self.out)
            return 1
        print("ALL PASS", file=self.out)
        return 0

    def one(self, ev, boots):
        name = os.path.basename(ev["path"])
        h = ev["head"]
        missing = [k for k in REQUIRED if k not in h]
        if not ev["magic"] or missing:
            self.bad("header", f"{name}: not an ipts-evidence v1 file with a full header"
                               + (f" (missing {', '.join(missing)})" if missing else ""))
            return
        kind = h["kind"]
        if kind not in OUTCOME:
            self.bad("header", f"{name}: unknown kind {kind!r}")
            return
        self.ok("header", f"{name}: {kind}/{h['phase']} written by {h['script']} ({h['script-sha256'][:12]}...)")

        nums = [n for n, _ in ev["cycles"]]
        outcomes = [OUTCOME[kind](c) for _, c in ev["cycles"]]
        npass = outcomes.count("pass")
        s = ev["summary"] or {}
        counts_ok = (bool(nums) and nums == list(range(1, len(nums) + 1))
                     and num(s.get("cycles")) == len(nums) and num(s.get("pass")) == npass)
        hidcore = sum(1 for _, c in ev["cycles"] if c.get("blocked_in") == "hidcore")
        if kind == "f3-rmmod" and num(s.get("hidcore")) != hidcore:
            counts_ok = False
        if counts_ok:
            self.ok("counts", f"{name}: {npass}/{len(nums)} cycles pass, recomputed from the CYCLE lines")
        else:
            self.bad("counts", f"{name}: SUMMARY says cycles={s.get('cycles')} pass={s.get('pass')}"
                               f"{' hidcore=' + str(s.get('hidcore')) if kind == 'f3-rmmod' else ''}; "
                               f"recomputed cycles={len(nums)} pass={npass}"
                               f"{' hidcore=' + str(hidcore) if kind == 'f3-rmmod' else ''}")

        ids = [h["boot-id"]] + [c[k] for _, c in ev["cycles"] for k in CYCLE_BOOT_KEYS if k in c]
        unknown = sorted({i for i in ids if i not in boots})
        if not boots:
            self.bad("boot-id", f"{name}: no boot listing to check against")
        elif unknown:
            self.bad("boot-id", f"{name}: boot ID(s) {', '.join(unknown)} not in the boot listing")
        else:
            self.ok("boot-id", f"{name}: {len(set(ids))} boot ID(s), all in the boot listing")

        if kind == "f3-rmmod":
            if hidcore:
                self.bad("f3", f"{name}: {hidcore} cycle(s) blocked in the HID core")
            elif npass != len(outcomes) or not outcomes:
                self.bad("f3", f"{name}: {outcomes.count('fail')}/{len(outcomes)} cycles failed the F3 check")
            elif ev["touch"] not in (None, "PASS"):
                self.bad("f3", f"{name}: touchscreen check after the campaign says {ev['touch']}")
            else:
                self.ok("f3", f"{name}: every cycle fired the fault, unloaded in <= {RMMOD_MAX} s "
                              f"and left no task in the HID core")
        else:
            if outcomes and all(o == "pass" for o in outcomes):
                self.ok("restore", f"{name}: manifest OK and the boot is in the journal")
            else:
                self.bad("restore", f"{name}: device check did not report manifest OK with the boot in the journal")


def collect(paths):
    files = []
    for p in paths:
        if os.path.isdir(p):
            files += sorted(os.path.join(p, f) for f in os.listdir(p) if f.endswith(".txt"))
        elif os.path.isfile(p):
            files.append(p)
        else:
            raise FileNotFoundError(p)
    return files


def boot_listing(files, boots_file):
    if boots_file:
        with open(boots_file, encoding="utf-8", errors="replace") as f:
            return set(BOOT_RE.findall(f.read()))
    ids = set()
    for p in files:
        ev = parse(p)
        if ev["head"].get("kind") == "device-check":
            ids |= set(BOOT_RE.findall("\n".join(ln for ln in ev["text"].splitlines()
                                                 if ln.startswith("LIST-BOOTS "))))
    return ids


def main(argv=None, out=sys.stdout):
    ap = argparse.ArgumentParser(usage=__doc__)
    ap.add_argument("paths", nargs="+")
    ap.add_argument("--boots")
    opts = ap.parse_args(argv)
    try:
        files = collect(opts.paths)
    except FileNotFoundError as e:
        print(f"evidencecheck: {e}: no such file or directory", file=sys.stderr)
        return 2
    if not files:
        print("evidencecheck: no evidence files found", file=sys.stderr)
        return 2
    return Checker(out).run(files, boot_listing(files, opts.boots))


if __name__ == "__main__":
    sys.exit(main())
