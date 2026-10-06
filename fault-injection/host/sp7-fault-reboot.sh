#!/bin/bash
# R4 prevention test, run from a separate machine. Loads the fault-injection build of the final driver,
# turns the safety net OFF for this boot, injects a fault, checks that a sleep request still
# completes and wakes, then times `systemctl reboot` (must be back in <=120 s).
#   sp7-fault-reboot.sh <fault 1|2> <run label> <evidence dir>
# fault 1: the receiver thread dies holding the message lock (BUG in the kthread)
# fault 2: a userspace HID request keeps the message lock (triggered by one iptsd-check-device)
HERE=$(cd "$(dirname "$0")" && pwd)
F=$1; L=$2; D=$3; H=${SP7_HOST:?set SP7_HOST=user@host of the test device}
s() { timeout 60 ssh -o BatchMode=yes -o ConnectTimeout=8 $H "$@"; }
mkdir -p "$D"; OUT=$D/$L.txt
{
echo "== R4 fault=$F label=$L $(date '+%F %T')"
s 'sudo -n sh -c "
	echo 0 > /sys/module/sp7_deadman/parameters/mode
	systemctl stop iptsd@\\* ; udevadm settle; rmmod ipts && insmod /var/tmp/sp7-build/v2fi/ipts.ko
	sleep 6; udevadm settle; systemctl start iptsd@\$(basename \$(for h in /sys/class/hidraw/hidraw*; do grep -qs IPTS \$h/device/uevent && echo \$h; done)) ; sleep 3
	echo deadman_mode=\$(cat /sys/module/sp7_deadman/parameters/mode) build=\$(modinfo -F ipts_build /var/tmp/sp7-build/v2fi/ipts.ko) srcversion=\$(cat /sys/module/ipts/srcversion) fault_param_present=\$(test -e /sys/module/ipts/parameters/fault && echo yes || echo no)
"'
s "sudo -n sh -c 'echo $F > /sys/module/ipts/parameters/fault && echo fault_set=\$(cat /sys/module/ipts/parameters/fault)'"
if [ "$F" = 2 ]; then
	s 'sudo -n sh -c "for h in /sys/class/hidraw/hidraw*; do grep -qs IPTS \$h/device/uevent && timeout 20 /usr/bin/iptsd-check-device /dev/\${h##*/}; done; true" >/dev/null 2>&1'
fi
sleep 15
s 'sudo -n sh -c "dmesg | grep -E \"FAULT INJECTION|Message lock|wedged|died|BUG:\" | tail -6; echo fault_param_now=\$(cat /sys/module/ipts/parameters/fault); dmesg | grep -cE \"Oops|BUG:|WARNING:|general protection\" > /run/sp7-r4-err0"'
echo "-- sleep after the fault (30 s RTC alarm, systemctl suspend)"
s0=$(s cat /sys/power/suspend_stats/success)
s 'sudo -n sh -c "rtcwake -m no -s 30 >/dev/null; systemctl suspend"'
t0=$(date +%s); ok=no
for _ in $(seq 40); do sleep 5; n=$(s cat /sys/power/suspend_stats/success 2>/dev/null); [ -n "$n" ] && [ "$n" != "$s0" ] && { ok=ok; break; }; done
echo "sleep_after_fault=$ok after $(( $(date +%s)-t0 )) s"
s 'sudo -n sh -c "dmesg | grep -E \"PM: suspend (entry|exit)|ipts.*(wedged|Stopping|Starting|died|leak)\" | tail -8; e0=\$(cat /run/sp7-r4-err0 2>/dev/null || echo 0); echo new_kernel_errors_after_fault=\$(( \$(dmesg | grep -cE \"Oops|BUG:|WARNING:|general protection\") - e0 ))"'
echo "-- reboot (safety net off)"
} >> "$OUT" 2>&1
"$HERE"/sp7-reboot-time.sh "r4-fault$F-$L" 'sudo -n systemctl reboot' 600 >> "$OUT" 2>&1
s 'sudo -n sh -c "ls /var/lib/systemd/pstore | tail -3; cat /sys/module/sp7_deadman/parameters/mode; cat /sys/module/ipts/srcversion"' >> "$OUT" 2>&1
tail -12 "$OUT"
