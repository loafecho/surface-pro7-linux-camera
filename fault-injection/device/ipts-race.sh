#!/bin/bash
# Touchscreen driver race test. Runs as root on the Surface, detached from ssh.
#   ipts-race.sh <ipts.ko> <cycles> <logfile>
# Each cycle: stop iptsd, let udev finish, unload ipts, load the given build, and the moment its
# hidraw node exists fire HID requests from 4 processes for 1.5 s (the start-up window where the
# poll thread and userspace both wait for the same reply). Nothing opens hidraw during an unload.
KO=$1; N=$2; LOG=$3
exec >>"$LOG" 2>&1
echo "== ipts race test $(date '+%F %T') ko=$KO srcversion=$(modinfo -F srcversion "$KO") cycles=$N"
oops0=$(dmesg | grep -c "Oops")
ipts_hidraw() { local h; for h in /sys/class/hidraw/hidraw*; do grep -qs "IPTS" "$h/device/uevent" && { echo "/dev/${h##*/}"; return 0; }; done; return 1; }
hammer() {
	local t0 h n=0 end
	t0=$(date +%s%N)
	while :; do h=$(ipts_hidraw) && break; (( $(date +%s%N) - t0 > 3000000000 )) && return 1; done
	end=$(( $(date +%s%N) + 1500000000 ))
	while (( $(date +%s%N) < end )); do /usr/bin/iptsd-check-device "$h" >/dev/null 2>&1; n=$((n+1)); done
	echo "$n" > /run/sp7-hammer.$BASHPID
}
i=0
while [ $i -lt "$N" ]; do
	i=$((i+1))
	systemctl stop 'iptsd@*' 2>/dev/null
	udevadm settle --timeout=10; sleep 0.3
	if lsmod | grep -q '^ipts '; then rmmod ipts || { echo "cycle $i: rmmod failed"; break; }; fi
	udevadm settle --timeout=10
	rm -f /run/sp7-hammer.*
	for _ in 1 2 3 4; do hammer & done
	insmod "$KO" || { echo "cycle $i: insmod failed"; break; }
	sleep 2.6
	o=$(dmesg | grep -c "Oops")
	if [ "$o" != "$oops0" ]; then
		echo "cycle $i: KERNEL OOPS"; dmesg | grep -E "Oops:|BUG:|RIP: 0010|Comm:|last unloaded" | tail -5
		echo "stuck tasks: $(ps -eo stat,comm | awk '$1 ~ /^D/ {print $2}' | tr '\n' ' ')"
		break
	fi
	wait
	if [ -z "$(pgrep -x ipts_poll)" ] || ! ipts_hidraw >/dev/null; then
		echo "cycle $i: no hidraw node after load (driver not running)"
		dmesg | grep ipts | tail -3
		break
	fi
	echo "cycle $i: requests=$(cat /run/sp7-hammer.* 2>/dev/null | paste -sd+ | bc) new_oops=0 poll=$(pgrep -x ipts_poll | head -1)"
	udevadm settle --timeout=10
done
echo "RESULT cycles_run=$i new_oops=$(( $(dmesg | grep -c "Oops") - oops0 )) loaded=$(cat /sys/module/ipts/srcversion 2>/dev/null)"
echo "DONE"
