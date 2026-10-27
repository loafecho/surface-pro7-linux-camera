# Upstream-shaped patch series

Each folder is `git format-patch` output (mail recipients removed). None of the
patches carries a Signed-off-by yet: that line is the submitter's own
certification and is added only at submission time. As of the notes these were
prepared with (2026-10-27), none of the series below had been posted to a
mailing list or opened as a pull request.

## `ipts-rfc/` - touchscreen driver (linux-surface/kernel, `drivers/hid/ipts`)

| Patch | Status |
|---|---|
| `0000-cover-letter.patch` | RFC cover letter: what was tested, what was not, known issues, AI disclosure. |
| `0001-hid-ipts-find-and-unlink-a-reply-under-one-lock.patch` | Same fix as linux-surface/kernel PR #178 (not merged as of 2026-10-27). Kept for reference; the plan was to support that PR, not duplicate it. |
| `0002-hid-ipts-bound-the-stop-path-and-never-unload-with-a.patch` | On hold. A review found a use-after-free on its "message lock lost" path, and it pins the module with `try_module_get()`. A rework that drops both was planned. |
| `on-pr178/0001-...patch` | Patch 2 rebased on top of PR #178 instead of patch 1. Built, not run. |
| `build-results.txt` | External-module build of every prefix of the series: return code, warning count, srcversion. |
| `checkpatch-results.txt` | `checkpatch.pl --strict` per patch. The only error is the missing Signed-off-by. |

Base: linux-surface/kernel `v7.2-surface-devel` (`2dfd333c3af7`); the
`drivers/hid/ipts` tree is identical on `v7.3-surface-devel`.

`tools/seriescheck.py --rules d5 series/ipts-rfc` fails on patch 2 on purpose:
the D5 rules ban exactly the constructs that put it on hold, and the test suite
checks that they are found.

## `libcamera/` - libcamera

Two patches checked against libcamera `master` at `2c4b67c0792f`
(`checks.txt`): `git apply --check` is clean for both, and `utils/checkstyle.py`
reports only the missing Signed-off-by. They were built and used on the Surface
Pro 7 on libcamera v0.7.0; they were not built or run on `master`.

- `0001` closes the simple pipeline's video nodes while no camera is acquired.
- `0002` lets the SoftISP `Adjust` algorithm take its gamma, contrast and
  saturation defaults from the tuning file. Two other changes from the original
  working patch were dropped because upstream had already fixed them.

## `ipu4p/` - IPU4P support in the mainline `intel-ipu6` driver

Two fixes written on top of a public, not yet merged IPU4P-on-IPU6 RFC series
(not included here), tested on linux-surface 7.3.0-rc7 with that series and the
IPU7 v4 series applied.

- `0001` holds CPU latency at 100 us while the ISYS is powered (IPU4P only). On
  this machine the IR camera delivered frames on 0 of 10 starts at the 300 us
  default and on 10 of 10 starts at 200 us or less.
- `0002` sends the iwake watermark update after `set_streaming(0)` instead of
  before the stream flush (IPU4P only): 0 stop/close timeouts in 12 stops,
  against a timeout on every full-resolution front camera stop before.

The runtime numbers come from the full tested tree (base, both series and the
local Surface Pro 7 patches), not from these two patches alone.
