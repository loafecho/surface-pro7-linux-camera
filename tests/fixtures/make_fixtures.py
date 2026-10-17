#!/usr/bin/env python3
"""Write the checker fixtures under tests/fixtures/{series,evidence}/.

Each fixture is a folder with an EXPECT file: "PASS" for a fixture that must
pass, otherwise the check name that must FAIL. An optional ARGS file holds extra
checker arguments. Every bad fixture is the good one with one thing broken, so a
FAIL can only come from that one change.

Run it after changing a fixture on purpose; tests/test_fixtures.py fails when the
committed fixtures and this generator disagree.
"""
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
AUTHOR = "Demo Author <1+demo@users.noreply.github.com>"
SIG = "-- "  # git format-patch signature separator (with its trailing space)

COVER = f"""From 1111111111111111111111111111111111111111 Mon Sep 17 00:00:00 2001
From: {AUTHOR}
Date: Mon, 26 Oct 2026 10:00:00 +0000
Subject: [RFC PATCH 0/2] demo: bound a wait and fix a list race

Two small fixes to a demo driver, used as checker fixtures.

Demo Author (2):
  demo: unlink the entry under one lock
  demo: bound the stop wait

 drivers/misc/demo.c | 9 +++++----
 1 file changed, 5 insertions(+), 4 deletions(-)

{SIG}
2.43.0
"""

P1 = f"""From 2222222222222222222222222222222222222222 Mon Sep 17 00:00:00 2001
From: {AUTHOR}
Date: Mon, 26 Oct 2026 10:00:00 +0000
Subject: [RFC PATCH 1/2] demo: unlink the entry under one lock

Find and unlink the entry under one write lock, so two waiters can never
take the same entry.

Assisted-by: LLM
{{signoff}}---
 drivers/misc/demo.c | 6 ++----
 1 file changed, 2 insertions(+), 4 deletions(-)

diff --git a/drivers/misc/demo.c b/drivers/misc/demo.c
index 1111111..2222222 100644
--- a/drivers/misc/demo.c
+++ b/drivers/misc/demo.c
@@ -10,10 +10,8 @@ static int demo_search(struct demo *d, int code)
 {{
 	struct demo_msg *e;

-	down_read(&d->lock);
+	down_write(&d->lock);
 	e = demo_find(d, code);
-	up_read(&d->lock);
-	down_write(&d->lock);
 	list_del(&e->list);
-	up_write(&d->lock);
+	up_write(&d->lock);
 	return 0;
{SIG}
2.43.0
"""

P2 = f"""From 3333333333333333333333333333333333333333 Mon Sep 17 00:00:00 2001
From: {AUTHOR}
Date: Mon, 26 Oct 2026 10:00:00 +0000
Subject: [RFC PATCH 2/2] demo: bound the stop wait

Wait at most 20 s for the thread to stop instead of forever.

Assisted-by: LLM
---
 drivers/misc/demo.c | 3 ++-
 1 file changed, 2 insertions(+), 1 deletion(-)

diff --git a/drivers/misc/demo.c b/drivers/misc/demo.c
index 2222222..3333333 100644
--- a/drivers/misc/demo.c
+++ b/drivers/misc/demo.c
@@ -30,4 +30,5 @@ static void demo_stop(struct demo *d)
 {{
 	kthread_stop(d->thread);
-	{{wait}}
+	if (!wait_for_completion_timeout(&d->done, 20 * HZ))
+		pr_err("demo: thread did not stop\\n");
 }}
{SIG}
2.43.0
"""

FAULT = """diff --git a/fault.c b/fault.c
new file mode 100644
index 0000000..4444444
--- /dev/null
+++ b/fault.c
@@ -0,0 +1,4 @@
+// SPDX-License-Identifier: GPL-2.0
+/* Test-only: compiled in only with -DDEMO_FAULT_INJECT. */
+static int fault;
+module_param(fault, int, 0644);
"""


def series_good():
    return {
        "0000-cover-letter.patch": COVER,
        "0001-demo-unlink-the-entry-under-one-lock.patch": P1.replace("{signoff}", ""),
        "0002-demo-bound-the-stop-wait.patch": P2.replace("{wait}", "wait_for_completion(&d->done);"),
    }


def series_fixtures():
    fx = {}
    fx["good"] = ("PASS", "", series_good())

    f = series_good()
    f["0002-demo-bound-the-stop-wait.patch"] = f["0002-demo-bound-the-stop-wait.patch"].replace(
        "@@ -30,4 +30,5 @@", "@@ -30,4 +30,6 @@")
    fx["bad-hunk-count"] = ("diff.hunks", "", f)

    f = series_good()
    f["0001-demo-unlink-the-entry-under-one-lock.patch"] = f["0001-demo-unlink-the-entry-under-one-lock.patch"].replace(
        " 1 file changed, 2 insertions(+), 4 deletions(-)", " 1 file changed, 3 insertions(+), 4 deletions(-)")
    fx["bad-diffstat"] = ("diff.diffstat", "", f)

    f = series_good()
    f["0002-demo-bound-the-stop-wait.patch"] = f["0002-demo-bound-the-stop-wait.patch"].replace("2/2]", "3/3]")
    fx["bad-numbering"] = ("format.numbering", "", f)

    f = series_good()
    f.pop("0001-demo-unlink-the-entry-under-one-lock.patch")
    fx["bad-missing-patch"] = ("format.numbering", "", f)

    f = series_good()
    f["0001-demo-unlink-the-entry-under-one-lock.patch"] = f["0001-demo-unlink-the-entry-under-one-lock.patch"].replace(
        "Date: Mon, 26 Oct 2026", "To: list@example.org\nCc: maintainer@example.org\nDate: Mon, 26 Oct 2026")
    fx["bad-cc-header"] = ("format.headers", "", f)

    f = series_good()
    f["0001-demo-unlink-the-entry-under-one-lock.patch"] = P1.replace("{signoff}", "Reviewed-by: Someone Else <someone@example.org>\n")
    fx["bad-email"] = ("format.email", "", f)

    f = series_good()
    f["0001-demo-unlink-the-entry-under-one-lock.patch"] = P1.replace("{signoff}", "Signed-off-by: Someone Else <1+else@users.noreply.github.com>\n")
    fx["bad-signoff-other"] = ("signoff", "--signer=\"Demo Author\"", f)

    f = series_good()
    f["0001-demo-unlink-the-entry-under-one-lock.patch"] = P1.replace("{signoff}", "Signed-off-by: Demo Author <1+demo@users.noreply.github.com>\n")
    fx["good-signoff-own"] = ("PASS", "--signer=\"Demo Author\"", f)

    f = series_good()
    f["0002-demo-bound-the-stop-wait.patch"] = f["0002-demo-bound-the-stop-wait.patch"].replace("\nAssisted-by: LLM\n", "\n")
    fx["bad-no-ai-disclosure"] = ("format.ai-disclosure", "", f)

    f = series_good()
    f["0002-demo-bound-the-stop-wait.patch"] = f["0002-demo-bound-the-stop-wait.patch"].replace(
        "demo: bound the stop wait\n", "demo: bound the stop wait so that a receiver thread which died can never hang a reboot\n", 1)
    fx["bad-subject-long"] = ("format.subject-length", "", f)

    f = series_good()
    f["0002-demo-bound-the-stop-wait.patch"] = f["0002-demo-bound-the-stop-wait.patch"].replace(
        "+\tif (!wait_for_completion_timeout(&d->done, 20 * HZ))", "+\tif (!try_module_get(THIS_MODULE))")
    fx["bad-d5-module-pin"] = ("rules.d5", "--rules=d5", f)

    fx["good-fault-add-only"] = ("PASS", "--plain --add-only --rules=d5", {"fault-inject.patch": FAULT})
    fx["bad-fault-removes"] = ("diff.add-only", "--plain --add-only", {
        "fault-inject.patch": FAULT.replace("@@ -0,0 +1,4 @@", "@@ -1,1 +1,4 @@").replace(
            "+// SPDX-License-Identifier: GPL-2.0\n", "-// old line\n+// SPDX-License-Identifier: GPL-2.0\n")})
    fx["bad-fault-d5"] = ("rules.d5", "--plain --rules=d5", {
        "fault-inject.patch": FAULT.replace("@@ -0,0 +1,4 @@", "@@ -0,0 +1,5 @@").replace(
            "+module_param(fault, int, 0644);\n", "+module_param(fault, int, 0644);\n+static void f(void) { for (;;) ; }\n")})
    return fx


BOOTS = ["%032x" % (0xA1 + i) for i in range(6)]


def device_check(boot, manifest="OK", has_boot="yes", passed=1):
    rows = "\n".join(f"LIST-BOOTS {i - len(BOOTS) + 1:3d} {b} Mon 2026-10-26 10:0{i}:00 PDT Mon 2026-10-26 10:0{i}:30 PDT"
                     for i, b in enumerate(BOOTS))
    return f"""# ipts-evidence v1
# kind: device-check
# phase: check
# script: device-check-v2.sh
# script-sha256: {'1' * 64}
# host: (redacted)
# boot-id: {boot}
# srcversion: 0123456789ABCDEF0123456
# started: 2026-10-26T17:10:00+00:00
LIST-BOOTS IDX BOOT ID                          FIRST ENTRY                 LAST ENTRY
{rows}
SRCVERSION 0123456789ABCDEF0123456
MANIFEST OK 4 items
MANIFEST-STATUS {manifest} 4 items
MANIFEST-RC 0
CYCLE 1 boot={boot} src=0123456789ABCDEF0123456 manifest={manifest} listboots_has_boot={has_boot}
SUMMARY kind=device-check cycles=1 pass={passed}
# finished: 2026-10-26T17:10:01+00:00
"""


def f3(cycles=None, summary=None, touch="PASS", magic="# ipts-evidence v1", head_boot=BOOTS[1]):
    if cycles is None:
        cycles = [dict(fault_fired="yes", hidraw_stuck="0", rmmod_s="1", rmmod_rc="0", blocked_in="none",
                       boot=BOOTS[i + 1], t_back="32", after_boot=BOOTS[i + 2]) for i in range(3)]
    lines = [f"CYCLE {n} src=FEDCBA9876543210FEDCBA9 " + " ".join(f"{k}={v}" for k, v in c.items())
             for n, c in enumerate(cycles, 1)]
    hidcore = sum(1 for c in cycles if c.get("blocked_in") == "hidcore")
    if summary is None:
        npass = sum(1 for c in cycles if c["fault_fired"] == "yes" and c["hidraw_stuck"] == "0"
                    and c["rmmod_rc"] == "0" and int(c["rmmod_s"]) <= 30 and c["blocked_in"] != "hidcore")
        summary = f"cycles={len(cycles)} pass={npass} hidcore={hidcore}"
    body = "\n".join(lines)
    return f"""{magic}
# kind: f3-rmmod
# phase: red
# script: campaign-v2.sh
# script-sha256: {'2' * 64}
# host: (redacted)
# boot-id: {head_boot}
# srcversion: FEDCBA9876543210FEDCBA9
# ko: /var/tmp/ipts-fault.ko
# safety: deadman=1 panic=10 pstore=0
# started: 2026-10-26T17:00:00+00:00
{body}
TOUCH-CHECK result={touch} touch=ok
SUMMARY kind=f3-rmmod phase=red {summary}
# finished: 2026-10-26T17:05:00+00:00
"""


def evidence_fixtures():
    dc = device_check(BOOTS[-1])
    fx = {"good": ("PASS", "", {"device-check-2026-10-26.txt": dc, "f3-rmmod-red-2026-10-26.txt": f3()})}
    fx["bad-forged-count"] = ("counts", "", {"device-check-2026-10-26.txt": dc,
                                             "f3-rmmod-red-2026-10-26.txt": f3(summary="cycles=4 pass=4 hidcore=0")})
    c = [dict(fault_fired="yes", hidraw_stuck="0", rmmod_s="1", rmmod_rc="0", blocked_in="none",
              boot=BOOTS[1], t_back="32", after_boot="f" * 32)]
    fx["bad-boot-id"] = ("boot-id", "", {"device-check-2026-10-26.txt": dc, "f3-rmmod-red-2026-10-26.txt": f3(cycles=c)})
    c = [dict(fault_fired="yes", hidraw_stuck="1", rmmod_s="41", rmmod_rc="hang", blocked_in="hidcore",
              boot=BOOTS[1], t_back="95", after_boot=BOOTS[2])]
    fx["bad-f3-hidcore"] = ("f3", "", {"device-check-2026-10-26.txt": dc, "f3-rmmod-red-2026-10-26.txt": f3(cycles=c)})
    c = [dict(fault_fired="no", hidraw_stuck="0", rmmod_s="0", rmmod_rc="0", blocked_in="none",
              boot=BOOTS[1], t_back="31", after_boot=BOOTS[2])]
    fx["bad-f3-fault-not-fired"] = ("f3", "", {"device-check-2026-10-26.txt": dc,
                                               "f3-rmmod-red-2026-10-26.txt": f3(cycles=c)})
    fx["bad-touch"] = ("f3", "", {"device-check-2026-10-26.txt": dc, "f3-rmmod-red-2026-10-26.txt": f3(touch="FAIL")})
    fx["bad-header"] = ("header", "", {"device-check-2026-10-26.txt": dc,
                                       "f3-rmmod-red-2026-10-26.txt": f3(magic="# evidence")})
    fx["bad-restore"] = ("restore", "", {"device-check-2026-10-26.txt": device_check(BOOTS[-1], manifest="MISMATCH", passed=0),
                                         "f3-rmmod-red-2026-10-26.txt": f3()})
    return fx


def write(root, fixtures):
    if os.path.isdir(root):
        shutil.rmtree(root)
    for name, (expect, args, files) in sorted(fixtures.items()):
        d = os.path.join(root, name)
        os.makedirs(d)
        with open(os.path.join(d, "EXPECT"), "w") as f:
            f.write(expect + "\n")
        if args:
            with open(os.path.join(d, "ARGS"), "w") as f:
                f.write(args + "\n")
        for fn, text in files.items():
            with open(os.path.join(d, fn), "w") as f:
                f.write(text)


def main(root=HERE):
    write(os.path.join(root, "series"), series_fixtures())
    write(os.path.join(root, "evidence"), evidence_fixtures())
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else HERE))
