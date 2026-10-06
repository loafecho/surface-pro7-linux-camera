#!/bin/bash
# Crash B reproducer: the touch device is opened and used while the driver unloads.
# Root, on the Surface, detached from ssh.
#   ipts-unload-race.sh <ipts.ko> <cycles> <logfile> [insmod parameters, e.g. fault=4]
# Each cycle (timing of the sleep hook's reload): load the build; from the moment its hidraw node
# exists 4 processes open it and send HID requests in a loop (re-opening the last known node path
# too); after a random 0.2-2.5 s, rmmod runs while they continue. After the
# unload: FAIL if a kernel oops appeared, if an IPTS hidraw node survived the unload (the HID
# device outlived the module), or if rmmod did not finish within 60 s.
KO=$1; N=$2; LOG=$3; PARAMS=$4
exec >>"$LOG" 2>&1
echo "== ipts unload race $(date '+%F %T') ko=$KO srcversion=$(modinfo -F srcversion "$KO") build=$(modinfo -F ipts_build "$KO") cycles=$N params=${PARAMS:-none}"
oops() { dmesg | grep -cE "Oops|BUG: unable|general protection|kernel BUG"; }
o0=$(oops)
ipts_hidraw() { local h; for h in /sys/class/hidraw/hidraw*; do grep -qs "IPTS" "$h/device/uevent" && { echo "/dev/${h##*/}"; return 0; }; done; return 1; }
hammer() {
	local end=$(( $(date +%s%N) + $1 )) h last=$2
	while (( $(date +%s%N) < end )); do
		h=$(ipts_hidraw) || h=$last
		/usr/bin/iptsd-check-device "$h" >/dev/null 2>&1
	done
}
i=0; fail=""
while [ $i -lt "$N" ]; do
	i=$((i+1))
	systemctl stop 'iptsd@*' 2>/dev/null
	udevadm settle --timeout=10
	if lsmod | grep -q '^ipts '; then
		timeout 60 rmmod ipts || { fail="cycle $i: pre-rmmod failed"; break; }
	fi
	udevadm settle --timeout=10
	insmod "$KO" $PARAMS || { fail="cycle $i: insmod failed"; break; }
	node=""; for _ in $(seq 60); do node=$(ipts_hidraw) && break; sleep 0.05; done
	[ -z "$node" ] && { fail="cycle $i: no hidraw node after load"; break; }
	for _ in 1 2 3 4; do hammer 5000000000 "$node" & done
	d=$(( 200 + RANDOM % 2300 ))
	sleep "$(printf '%d.%03d' $((d/1000)) $((d%1000)))"
	t0=$(date +%s%N)
	timeout 60 rmmod ipts; rc=$?
	ms=$(( ($(date +%s%N) - t0) / 1000000 ))
	wait
	left=$(ipts_hidraw)
	o=$(oops)
	echo "cycle $i: delay_ms=$d node=$node rmmod_rc=$rc rmmod_ms=$ms leftover=${left:-none} new_oops=$((o-o0))"
	if [ "$o" != "$o0" ]; then
		fail="cycle $i: KERNEL OOPS"
		dmesg | grep -E "Oops|BUG:|RIP: 0010|Comm:|last unloaded" | tail -6
		break
	fi
	[ -n "$left" ] && { fail="cycle $i: HID device $left outlived the module"; break; }
	[ $rc -ne 0 ] && { fail="cycle $i: rmmod rc=$rc"; break; }
done
echo "stuck tasks: $(ps -eo stat,comm | awk '$1 ~ /^D/ {print $2}' | tr '\n' ' ')"
if [ -n "$fail" ]; then echo "$fail"; echo "RESULT result=FAIL cycles_run=$i"; else echo "RESULT result=PASS cycles_run=$i"; fi
echo "DONE"
