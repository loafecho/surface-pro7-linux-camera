#!/bin/bash
# Surface Pro 7 camera regression suite. One PASS/FAIL line per check, INFO for metrics.
#   sp7-camcheck            everything
#   sp7-camcheck quick      skip browsers and Snapshot
#   sp7-camcheck ir         IR check only
# Frames for eyeballing land in /tmp/sp7-camcheck/ (front.jpg, rear.jpg, ir.png).
# Helpers live in /usr/local/share/sp7-camcheck/.
set -u
MODE=${1:-all}
H=/usr/local/share/sp7-camcheck
OUT=/tmp/sp7-camcheck
mkdir -p "$OUT"
XDG_RUNTIME_DIR=/run/user/$(id -u)
export XDG_RUNTIME_DIR
export DBUS_SESSION_BUS_ADDRESS=unix:path=$XDG_RUNTIME_DIR/bus
FRONT=libcamera_input.__SB_.PCI0.I2C2.CAMF
REAR=libcamera_input.__SB_.PCI0.I2C3.CAMR
IPU=/sys/bus/pci/devices/0000:00:05.0/power/runtime_status
NPASS=0 NFAIL=0
pass() { echo "PASS  $*"; NPASS=$((NPASS + 1)); }
fail() { echo "FAIL  $*"; NFAIL=$((NFAIL + 1)); }
info() { echo "INFO  $*"; }
check() { local name=$1; shift; if "$@"; then pass "$name"; else fail "$name"; fi; }
# PipeWire may have only just started (no desktop login: the user manager starts with the ssh session)
wait_nodes() { for _ in $(seq 1 40); do pw-cli ls Node 2>/dev/null | grep -q "$FRONT" && pw-cli ls Node 2>/dev/null | grep -q "$REAR" && return 0; sleep 0.5; done; return 1; }
wait_suspend() { for _ in $(seq 1 60); do [ "$(cat $IPU)" = suspended ] && return 0; sleep 0.5; done; return 1; }

# The rest of a pipewiresrc capture: settle AE for $3 frames, keep the last one.
grab() {
	local node=$1 file=$2 frames=${3:-90}
	rm -f "$file"
	timeout -s INT 30 gst-launch-1.0 -q pipewiresrc target-object="$node" num-buffers="$frames" \
		! video/x-raw,width=1280,height=720 ! videoconvert ! jpegenc quality=92 \
		! multifilesink location="$file" max-files=1 >/dev/null 2>&1
	[ -s "$file" ]
}

echo "== sp7-camcheck $(date '+%Y-%m-%d %I:%M %p')  kernel $(uname -r)"
# Every mode: the installed custom pieces match the manifest (sp7-manifest, R9).
MANIFEST=$(sudo -n /usr/local/sbin/sp7-manifest check 2>&1)
while read -r l; do [[ "$l" == MISMATCH\ * ]] && [[ "$l" != MISMATCH\ [0-9]* ]] && info "manifest: $l"; done <<<"$MANIFEST"
check "custom pieces match manifest ($(tail -1 <<<"$MANIFEST"))" grep -q '^OK' <<<"$(tail -1 <<<"$MANIFEST")"

if [ "$MODE" != ir ]; then
	check "kernel is 6.19.8-surface-ipu4cf" [ "$(uname -r)" = 6.19.8-surface-ipu4cf ]
	check "GRUB default is ipu4cf" sudo -n grep -q '^GRUB_DEFAULT=.*surface-ipu4cf-advanced' /etc/default/grub
	check "ov7251 bound (IR sensor powers up)" bash -c 'ls /sys/bus/i2c/drivers/ov7251/ | grep -q INT347E'
	check "pipewire + wireplumber active" systemctl --user -q is-active pipewire wireplumber
	check "PipeWire camera nodes present" wait_nodes
	check "sp7-howdy-relay active" systemctl --user -q is-active sp7-howdy-relay
	check "IPU suspended when idle" wait_suspend
	DMESG0=$(sudo -n journalctl -k -b --no-pager | grep -ciE "power cycle required|stream close time out")

	# 1. Stress: 24 back-to-back streams, front/rear, four resolutions.
	ok=0
	for _round in 1 2 3; do
		for m in F:640x480 R:800x600 F:1280x720 R:640x480 F:1920x1080 R:1280x720 F:640x480 R:1920x1080; do
			[ "${m%%:*}" = F ] && t=$FRONT || t=$REAR
			r=${m##*:}
			timeout -s INT 20 gst-launch-1.0 -q pipewiresrc target-object=$t num-buffers=30 \
				! video/x-raw,width=${r%x*},height=${r#*x} ! fakesink >/dev/null 2>&1 && ok=$((ok + 1))
		done
	done
	check "stress front+rear $ok/24" [ $ok = 24 ]
	check "IPU suspends after stress" wait_suspend

	# 2. Frames + metrics (for the eye; numbers are INFO).
	if grab $FRONT "$OUT/front.jpg"; then pass "front frame captured"; info "front $(python3 $H/metrics.py $OUT/front.jpg)"; else fail "front frame captured"; fi
	if grab $REAR "$OUT/rear.jpg"; then pass "rear frame captured"; info "rear  $(python3 $H/metrics.py $OUT/rear.jpg)"; else fail "rear frame captured"; fi
	info "rear lens: dw9719 $(readlink /sys/bus/i2c/devices/i2c-INT347A:00-VCM/driver >/dev/null && echo bound || echo UNBOUND), default_focus=$(cat /sys/module/dw9719/parameters/default_focus 2>/dev/null), async_register=$(cat /sys/module/dw9719/parameters/async_register 2>/dev/null)"
	check "rear lens + sensor suspended when idle" bash -c 'sleep 1; [ "$(cat /sys/bus/i2c/devices/i2c-INT347A:00-VCM/power/runtime_status)" = suspended ] && [ "$(cat /sys/bus/i2c/devices/i2c-INT347A:00/power/runtime_status)" = suspended ]'

	# 3. Howdy loopback /dev/video61 (front via relay), OpenCV like Howdy.
	out=$(python3 $H/devcheck.py /dev/video61 3 4 10 2>/dev/null | tail -1)
	check "/dev/video61 relay 3 cycles ($out)" [ "$out" = "RESULT 3/3" ]

	if [ "$MODE" = all ]; then
		# The relay keeps the front camera for a few seconds after its client
		# stops; the cameras share one capture path, so wait until it is idle.
		wait_suspend
		# 4. Browsers: headless getUserMedia, 30 frames from each camera.
		for b in google-chrome brave-browser; do
			P=$(mktemp -d)
			res=$(timeout 90 $b --headless=new --user-data-dir=$P --no-first-run --enable-features=WebRtcPipeWireCamera \
				--use-fake-ui-for-media-stream --enable-logging=stderr --v=0 file://$H/camtest.html 2>&1 |
				grep -oE 'CAMTEST \{[^}]*\}' | sed 's/CAMTEST //')
			sleep 1; rm -rf "$P" 2>/dev/null
			nf=$(echo "$res" | grep -c '"label":"Built-in Front Camera","frames":30')
			nr=$(echo "$res" | grep -c '"label":"Built-in Back Camera","frames":30')
			check "$b front 30/30" [ "$nf" = 1 ]
			check "$b rear 30/30" [ "$nr" = 1 ]
		done
		# 5. GNOME Snapshot on the live session.
		if [ -S "$XDG_RUNTIME_DIR/wayland-0" ]; then
			(WAYLAND_DISPLAY=wayland-0 snapshot >/dev/null 2>&1 &)
			sleep 10
			out=$(python3 $H/snapcheck.py 2>&1)
			pkill -x snapshot
			check "Snapshot streaming ($out)" bash -c "echo '$out' | grep -q 'state=running'"
		else
			fail "Snapshot (no wayland session)"
		fi
		check "IPU suspends after browsers/Snapshot" wait_suspend
	fi
	DMESG1=$(sudo -n journalctl -k -b --no-pager | grep -ciE "power cycle required|stream close time out")
	check "no new IPU errors in dmesg ($((DMESG1 - DMESG0)))" [ "$DMESG1" = "$DMESG0" ]
fi

# 6. IR: /dev/video62, 20 open/stream/close cycles, >=15 fps of changing frames.
if [ -e /dev/video62 ]; then
	# The IR link locks on a random sensor restart: allow up to 30 s for the
	# first frame of each cycle, then require >=15 fps of changing frames for 2 s;
	# 5 s between cycles so the relay really stops and restarts the camera.
	out=$(python3 $H/devcheck.py /dev/video62 20 2 15 30 5 2>/dev/null)
	echo "$out" | grep -E "BAD|failed" | head -3 | sed 's/^/INFO  ir /'
	echo "$out" | grep "first-frame times" | sed 's/^/INFO  ir /'
	check "IR /dev/video62 $(echo "$out" | tail -1 | sed 's/RESULT //') cycles >=15 fps" bash -c "echo '$out' | tail -1 | grep -qx 'RESULT 20/20'"
	timeout 40 python3 -c "
import cv2,time; c=cv2.VideoCapture('/dev/video62',cv2.CAP_V4L2); t=time.time(); f=None; n=0
while time.time()-t<30 and n<45:
    r,x=c.read()
    if r and x.mean()>3: f=x; n+=1
f is not None and cv2.imwrite('$OUT/ir.png',f)" 2>/dev/null
	[ -s $OUT/ir.png ] && info "ir $(python3 $H/metrics.py $OUT/ir.png)"
else
	fail "IR /dev/video62 missing"
fi
[ "$MODE" = ir ] || check "IPU suspended at end" wait_suspend
echo "== $NPASS PASS, $NFAIL FAIL   frames: $OUT/"
[ $NFAIL = 0 ]
