#!/bin/bash
# From a separate machine: run a command on the Surface that restarts it, time down/up over SSH.
#   sp7-reboot-time.sh <label> <remote command> [max_wait_s]
# Prints key=value lines: label, t_down, t_back, boot_id_changed, new_pstore.
H=${SP7_HOST:?set SP7_HOST=user@host of the test device}; L=$1; C=$2; MAX=${3:-900}
s() { timeout 12 ssh -o BatchMode=yes -o ConnectTimeout=6 $H "$@" 2>/dev/null; }
b0=$(s cat /proc/sys/kernel/random/boot_id); p0=$(s ls /var/lib/systemd/pstore | sort | paste -sd,)
t0=$(date +%s)
echo "label=$L"; echo "start=$(date '+%F %T')"; echo "cmd=$C"
timeout 10 ssh -o BatchMode=yes $H "$C" >/dev/null 2>&1 &
down=""
while :; do
	now=$(($(date +%s)-t0)); [ $now -gt $MAX ] && { echo "t_back=TIMEOUT"; echo "result=FAIL"; exit 1; }
	if s true; then
		if [ -n "$down" ]; then b1=$(s cat /proc/sys/kernel/random/boot_id); [ "$b1" != "$b0" ] && break; fi
	else
		[ -z "$down" ] && { down=$now; echo "t_down=$down"; }
	fi
	sleep 3
done
echo "t_back=$(($(date +%s)-t0))"
sleep 20
p1=$(s ls /var/lib/systemd/pstore | sort | paste -sd,)
echo "boot_id_changed=yes"
echo "new_pstore=$(comm -13 <(tr , '\n' <<<"$p0") <(tr , '\n' <<<"$p1") | paste -sd,)"
echo "uptime_s=$(s cut -d. -f1 /proc/uptime)"
echo "result=DONE"
