#!/bin/bash
# Crash B reproducer, as first hit on 2026-10-04 11:32 am: run the sleep hook's wake reload in a
# loop while other processes open every /dev/hidraw* node without pause. Root, detached.
#   ipts-hook-stress.sh <hook script> <cycles> <logfile>
HOOK=$1; N=$2; LOG=$3
exec >>"$LOG" 2>&1
echo "== hook stress $(date '+%F %T') hook=$HOOK sha=$(sha256sum < "$HOOK" | cut -c1-16) ipts=$(modinfo -F srcversion ipts) cycles=$N"
oops() { dmesg | grep -cE "Oops|BUG: unable|general protection|kernel BUG"; }
o0=$(oops)
stop=/run/sp7-hook-stress.stop; rm -f $stop
hammer() { while [ ! -e $stop ]; do for h in /dev/hidraw*; do /usr/bin/iptsd-check-device "$h" >/dev/null 2>&1; done; done; }
for _ in 1 2 3 4; do hammer & done
i=0; res=PASS
while [ $i -lt "$N" ]; do
	i=$((i+1))
	timeout 120 "$HOOK" post; rc=$?
	sleep 1
	o=$(oops)
	echo "cycle $i: hook_rc=$rc new_oops=$((o-o0)) src=$(cat /sys/module/ipts/srcversion 2>/dev/null) initstate=$(cat /sys/module/ipts/initstate 2>/dev/null) poll=$(pgrep -x ipts_poll | head -1) iptsd=$(systemctl list-units 'iptsd@*' --no-legend --state=running | wc -l)"
	if [ "$o" != "$o0" ]; then
		res=FAIL; echo "cycle $i: KERNEL OOPS"
		dmesg | grep -E "Oops|BUG:|RIP: 0010|Comm:|last unloaded" | tail -6
		break
	fi
	[ $rc -ne 0 ] && { res=FAIL; echo "cycle $i: hook timed out or failed"; break; }
	if [ -z "$(pgrep -x ipts_poll)" ] || [ "$(systemctl list-units 'iptsd@*' --no-legend --state=running | wc -l)" = 0 ]; then
		res=FAIL; echo "cycle $i: driver not running after the reload (no poll thread or no iptsd)"
		dmesg | grep -E "ipts" | tail -4
		break
	fi
done
touch $stop; sleep 3
echo "stuck tasks: $(ps -eo stat,comm | awk '$1 ~ /^D/ {print $2}' | tr '\n' ' ')"
echo "RESULT result=$res cycles_run=$i"
echo "DONE"
