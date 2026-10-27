#!/bin/bash
# campaign-v2.sh - LOCKED test script for the ipts checker v2 (its sha256 is written into every
# evidence header; never edit it, write a new script instead).
#
# Red F3 campaign on the Surface Pro 7, run from a separate machine (never on the Surface, never
# detached with setsid over SSH):
#     scripts/campaign-v2.sh f3-rmmod red <cycles> <ko> [out-dir]
#     scripts/campaign-v2.sh --dry-run f3-rmmod red <cycles> <ko>
#
# <ko>  a module path on the Surface (e.g. /var/tmp/ipts-fault.ko), loaded with insmod
#       before every cycle.
#
# The only kind/phase is f3-rmmod/red: the fixed (red) driver with the F3 fault build.
# Per cycle: load the fault build, write fault=3 (spawns a kthread that takes the message
# lock via ipts_mei_search() and exits holding it - no BUG(), no HID request), check the
# kernel log for "FAULT INJECTION 3", rmmod with a 30 s limit in its own systemd-run unit,
# sample where rmmod blocks (blocked_in=ipts|hidcore|none), and check that no D-state task
# has hidraw_ioctl or hid_destroy_device on its stack. Then reboot to clean.
#
# Evidence: <out-dir>/f3-rmmod-red-<YYYY-MM-DD>.txt (-2, -3 ... if taken), header with this
# script's sha256, boot ID and srcversion. Each CYCLE line carries
#   src= fault_fired= hidraw_stuck= rmmod_s= rmmod_rc= blocked_in= boot=
# SUMMARY carries kind/phase/cycles/pass and the recomputed hidcore count (0/cycles).
#
# Safety: before any cycle the script requires the deadman module loaded and kernel.panic > 0
# and records them. A hang in rmmod is bounded (30 s); the deadman + panic restart the
# Surface if the driver wedges during unload.
set -u
H=${SP7_HOST:?set SP7_HOST=user@host of the test device}
RMMOD_MAX=30
REBOOT_MAX=600
HERE=$(cd "$(dirname "$0")" && pwd)
SELF=$HERE/$(basename "$0")

DRY=0; [ "${1:-}" = --dry-run ] && { DRY=1; shift; }
KIND=${1:-}; PHASE=${2:-}; N=${3:-}; KO=${4:-}; OUTDIR=${5:-$HERE/../evidence}
usage() { sed -n '4,11p' "$SELF" >&2; exit 2; }
[ "$KIND" = f3-rmmod ] && [ "$PHASE" = red ] || usage
[[ "$N" =~ ^[0-9]+$ ]] && [ "$N" -ge 1 ] || usage
[ -n "$KO" ] || usage

if [ $DRY -eq 1 ]; then
	echo "plan: kind=$KIND phase=$PHASE cycles=$N ko=$KO host=$H"
	echo "plan: evidence -> $OUTDIR/$KIND-$PHASE-$(date +%F).txt"
	exit 0
fi

# --- remote side: one bash program, sent over SSH and run with sudo --------------------
remote_lib() { cat <<'EOF'
set -u
node() { local h; for h in /sys/class/hidraw/hidraw*; do grep -qs IPTS "$h/device/uevent" && { echo "${h##*/}"; return 0; }; done; return 1; }
wait_node() { local i; for i in $(seq 40); do node >/dev/null && return 0; sleep 0.25; done; return 1; }
src() { cat /sys/module/ipts/srcversion 2>/dev/null || echo NOT-LOADED; }
unload() { systemctl stop 'iptsd@*' 2>/dev/null; udevadm settle -t 10; [ -e /sys/module/ipts ] && { rmmod ipts || return 1; }; udevadm settle -t 10; return 0; }
load() {   # $1 = ko path
	unload || { echo "load_rc=rmmod-failed src=$(src)"; return 1; }
	insmod "$1" || { echo "load_rc=insmod-failed src=NOT-LOADED"; return 1; }
	if wait_node; then echo "load_rc=0 hidraw=yes src=$(src)"; else echo "load_rc=0 hidraw=no src=$(src)"; fi
}
fault3() { [ -w /sys/module/ipts/parameters/fault ] || { echo "fault_set=NO-PARAM"; return 1; }
	echo 3 > /sys/module/ipts/parameters/fault; echo "fault_set=3"; }
count() { journalctl -k -b --no-pager --since "@$1" 2>/dev/null | grep -cE "$2"; }
rmmod_f3() {   # $1 = limit s; blocked_in is where rmmod was *stuck* (only a hang is classified)
	local u="ipts-rmmod-$$-$RANDOM" t0 t rc pid stack bi=none
	systemctl stop 'iptsd@*' 2>/dev/null; udevadm settle -t 10
	t0=$(date +%s)
	systemd-run --quiet --collect --unit="$u" sh -c 'rmmod ipts; echo $? > /run/'"$u"'.rc'
	while :; do
		t=$(( $(date +%s) - t0 ))
		[ -e "/run/$u.rc" ] && { rc=$(cat "/run/$u.rc"); rm -f "/run/$u.rc"; break; }
		[ $t -gt $(( $1 + 10 )) ] && { rc=hang; break; }
		sleep 0.5
	done
	if [ "$rc" = hang ]; then
		pid=$(pgrep -x rmmod | head -1)
		if [ -n "$pid" ] && [ -r "/proc/$pid/stack" ]; then
			stack=$(cat "/proc/$pid/stack" 2>/dev/null)
			case "$stack" in
				*hidraw_ioctl*|*hid_destroy_device*) bi=hidcore ;;
				*ipts_*) bi=ipts ;;
			esac
		fi
	fi
	echo "rmmod_s=$t rmmod_rc=$rc blocked_in=$bi"
}
hidraw_stuck() {   # 0 = no D-state task has a HID-core function on its stack
	local pid
	for pid in $(ps -eo stat=,pid= | awk '$1 ~ /D/ {print $2}'); do
		grep -qsE 'hidraw_ioctl|hid_destroy_device' "/proc/$pid/stack" 2>/dev/null && { echo 1; return 0; }
	done
	echo 0
}
safety() { echo "deadman=$( [ -e /sys/module/sp7_deadman ] && cat /sys/module/sp7_deadman/parameters/mode || echo absent) panic=$(cat /proc/sys/kernel/panic) pstore=$(ls /sys/fs/pstore 2>/dev/null | wc -l)"; }
touchcheck() { local n; n=$(node) || { echo "touch=no-node"; return 0; }; if timeout 20 /usr/bin/iptsd-check-device "/dev/$n" >/dev/null 2>&1; then echo touch=ok; else echo touch=fail; fi; }
"$@"
EOF
}
r() { timeout "${T:-90}" ssh -o BatchMode=yes -o ConnectTimeout=8 "$H" "sudo -n bash -s -- $*" < <(remote_lib); }
q() { timeout 20 ssh -o BatchMode=yes -o ConnectTimeout=8 "$H" "$@" 2>/dev/null; }
field() { sed -n "s/.*\b$1=\([^ ]*\).*/\1/p" <<<"$2" | head -1; }
bootid() { q cat /proc/sys/kernel/random/boot_id | tr -d -- '-'; }
now() { q date +%s; }

reboot_timed() {   # prints "t_back=<s> boot=<new id>"; t_back=TIMEOUT after 600 s
	local b0 b1 t0 t
	b0=$(bootid); t0=$(date +%s)
	timeout 15 ssh -o BatchMode=yes "$H" 'sudo -n systemctl reboot' >/dev/null 2>&1 &
	while :; do
		t=$(( $(date +%s) - t0 ))
		[ $t -gt $REBOOT_MAX ] && { echo "t_back=TIMEOUT boot=none"; return 1; }
		b1=$(bootid)
		[ -n "$b1" ] && [ "$b1" != "$b0" ] && { echo "t_back=$(( $(date +%s) - t0 )) boot=$b1"; sleep 20; return 0; }
		sleep 5
	done
}

# --- start ---------------------------------------------------------------------------
sha=$(sha256sum "$SELF" | cut -d' ' -f1)
boot=$(bootid); [ ${#boot} -eq 32 ] || { echo "campaign-v2: Surface unreachable" >&2; exit 2; }
kosrc=$(q modinfo -F srcversion "$KO"); [ -n "$kosrc" ] || { echo "campaign-v2: $KO not found on the Surface" >&2; exit 2; }
safe=$(r safety)
dm=$(field deadman "$safe"); pn=$(field panic "$safe")
{ [ "$dm" = absent ] || [ "${pn:-0}" -le 0 ]; } && { echo "campaign-v2: safety net not ready ($safe); refusing" >&2; exit 2; }

mkdir -p "$OUTDIR" || exit 2; OUTDIR=$(cd "$OUTDIR" && pwd)
d=$(date +%F); out=$OUTDIR/$KIND-$PHASE-$d.txt; k=1
while [ -e "$out" ]; do k=$((k+1)); out=$OUTDIR/$KIND-$PHASE-$d-$k.txt; done
{
	echo "# ipts-evidence v1"
	echo "# kind: $KIND"
	echo "# phase: $PHASE"
	echo "# script: campaign-v2.sh"
	echo "# script-sha256: $sha"
	echo "# host: $H"
	echo "# boot-id: $boot"
	echo "# srcversion: $kosrc"
	echo "# ko: $KO"
	echo "# safety: $safe"
	echo "# started: $(date -Iseconds)"
} > "$out"
echo "evidence: $out"

pass=0; hidcore=0; i=0
while [ $i -lt "$N" ]; do
	i=$((i+1)); ok=0
	t0=$(now)
	l=$(r load "$KO"); s=$(field src "$l")
	r fault3 >/dev/null; sleep 2
	ff=$(r count "$t0" "'FAULT INJECTION 3'")
	m=$(T=60 r rmmod_f3 $RMMOD_MAX)
	hs=$(r hidraw_stuck)
	boot=$(bootid)
	rs=$(field rmmod_s "$m"); rc=$(field rmmod_rc "$m"); bi=$(field blocked_in "$m")
	[ "$bi" = hidcore ] && hidcore=$((hidcore+1))
	fired=no; [ "${ff:-0}" -ge 1 ] && fired=yes
	line="src=$s fault_fired=$fired hidraw_stuck=$hs rmmod_s=$rs rmmod_rc=$rc blocked_in=$bi boot=$boot"
	[ "$fired" = yes ] && [ "$hs" = 0 ] && [ "$rc" = 0 ] && [ "$bi" != hidcore ] && [ "${rs:-99}" -le $RMMOD_MAX ] && ok=1
	pass=$((pass+ok))
	line="$line $(reboot_timed | sed 's/boot=/after_boot=/')"
	echo "CYCLE $i $line" | tee -a "$out"
done

tc=$(r touchcheck)
if [ "$(field touch "$tc")" = ok ]; then echo "TOUCH-CHECK result=PASS $tc" >> "$out"; else echo "TOUCH-CHECK result=FAIL $tc" >> "$out"; fi
{
	echo "SUMMARY kind=$KIND phase=$PHASE cycles=$i pass=$pass hidcore=$hidcore"
	echo "# finished: $(date -Iseconds)"
} >> "$out"
tail -3 "$out"
[ "$pass" -eq "$i" ]
