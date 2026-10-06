# Working patches (Surface Pro 7, kernel 6.19.8 era)

These are the patches that first made the Surface Pro 7's three cameras and its
touchscreen usable on a 6.19.8 linux-surface kernel with the out-of-tree IPU4
driver. They are working patches, not submissions: plain diffs, some with
module parameters that were only there to find the right settings. The cleaned
up, upstream-shaped versions of the parts that survived are in `../series/`.

| File | What it changes |
|---|---|
| `kernel/ipts-mei-search-atomic.patch` | Touchscreen driver (`drivers/hid/ipts/mei.c`): find and unlink a reply under one write lock. The first form of `series/ipts-rfc` patch 1. |
| `kernel/ipu4p-isys-sp7-ir-source6.patch` | Out-of-tree IPU4P ISYS driver: bring-up switches for the IR camera on CSI-2 firmware source 6 (PHY building block 8 setup, receiver timing, re-arm per stream). Scoped to source 6; the RGB cameras are untouched. |
| `kernel/ov5693-sp7-hflip.patch` | Front sensor: treat HFLIP as relative to the module's natural readout, so a 180-degree rotation gives an unmirrored image, and keep the Bayer order BGGR. |
| `kernel/ov7251-sp7-reg-override-led.patch` | IR sensor: extra register writes at stream start and a delayed IR emitter switch-on, as module parameters. |
| `kernel/sp7-rear-fixed-focus-dw9719-ov8865.patch` | Rear lens and sensor: an option to leave the lens out of the media graph at a fixed focus position, so the sensor gets the real power cycles the IPU's link-start recovery needs. |
| `libcamera/libcamera-simple-lazy-video-open.patch` | libcamera simple pipeline: open the video nodes when a camera is acquired, not at match time. |
| `libcamera/libcamera-softisp-param-defaults-and-tuned-adjust.patch` | libcamera SoftISP: default values for every debayer parameter, a black-level clamp, and tuning-file defaults for gamma, contrast and saturation. |
| `pipewire/pipewire-1.0.5-libcamera-0.7-model-string.patch` | PipeWire 1.0.5 camera plugin: build against libcamera 0.7. |
| `pipewire/pipewire-1.4.10-libcamera-mono-formats.patch` | PipeWire 1.4.10 camera plugin: expose the monochrome R8/R10/R12/R16 formats the IR camera produces. |
| `build/libcamera-build.sh`, `build/pipewire-spa-build.sh` | Container build steps for the libcamera and PipeWire plugin builds above (sources mounted at `/src`, output at `/out`). |

`tools/seriescheck.py --plain` checks every hunk in these files for internal
consistency. It does not prove they still apply to any current tree.
