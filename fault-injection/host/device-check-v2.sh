#!/bin/bash
# device-check-v2.sh - LOCKED test script for the ipts checker v2 (its sha256 is written into every
# evidence header; never edit it, write a new script instead).
#
# Read-only check of the Surface Pro 7, run from a separate machine:
#     scripts/device-check-v2.sh [out-dir]          (default: <ipts-rework-v2>/evidence)
#
# Writes <out-dir>/device-check-<YYYY-MM-DD>.txt (-2, -3 ... if that name exists) with the
# evidence header (this script's sha256, the boot ID, the loaded ipts srcversion), the
# Surface's `journalctl --list-boots`, the loaded ipts srcversion and the result of
# `sp7-manifest check`. Exit 0 when the manifest check says OK and the current boot is in
# the journal; 1 otherwise; 2 when the Surface cannot be reached.
#
# Nothing on the Surface is changed. The only write there is the one sp7-manifest check
# always makes (/run/sp7-manifest.status).
set -u
H=${SP7_HOST:?set SP7_HOST=user@host of the test device}
HERE=$(cd "$(dirname "$0")" && pwd)
SELF=$HERE/$(basename "$0")
OUTDIR=${1:-$HERE/../evidence}
mkdir -p "$OUTDIR" || exit 2
OUTDIR=$(cd "$OUTDIR" && pwd)

s() { timeout 60 ssh -o BatchMode=yes -o ConnectTimeout=8 "$H" "$@"; }

sha=$(sha256sum "$SELF" | cut -d' ' -f1)
boot=$(s cat /proc/sys/kernel/random/boot_id | tr -d -- '-') || { echo "device-check-v2: Surface unreachable" >&2; exit 2; }
[ ${#boot} -eq 32 ] || { echo "device-check-v2: bad boot ID '$boot'" >&2; exit 2; }
src=$(s cat /sys/module/ipts/srcversion 2>/dev/null)
[ -n "$src" ] || src=NOT-LOADED
lb=$(s journalctl --list-boots --no-pager) || { echo "device-check-v2: journalctl --list-boots failed" >&2; exit 2; }
man=$(s sudo -n /usr/local/sbin/sp7-manifest check 2>&1); mrc=$?
status=$(s cat /run/sp7-manifest.status 2>/dev/null)

d=$(date +%F); out=$OUTDIR/device-check-$d.txt; n=1
while [ -e "$out" ]; do n=$((n+1)); out=$OUTDIR/device-check-$d-$n.txt; done

if grep -qE "^ *-?[0-9]+ +$boot " <<<"$lb"; then inlb=yes; else inlb=no; fi
if [ $mrc -eq 0 ] && [[ "$status" == OK* ]]; then mv=OK; else mv=MISMATCH; fi
pass=0; [ "$mv" = OK ] && [ "$inlb" = yes ] && pass=1

{
	echo "# ipts-evidence v1"
	echo "# kind: device-check"
	echo "# phase: check"
	echo "# script: device-check-v2.sh"
	echo "# script-sha256: $sha"
	echo "# host: $H"
	echo "# boot-id: $boot"
	echo "# srcversion: $src"
	echo "# started: $(date -Iseconds)"
	sed 's/^/LIST-BOOTS /' <<<"$lb"
	echo "SRCVERSION $src"
	[ -n "$man" ] && sed 's/^/MANIFEST /' <<<"$man"
	echo "MANIFEST-STATUS $status"
	echo "MANIFEST-RC $mrc"
	echo "CYCLE 1 boot=$boot src=$src manifest=$mv listboots_has_boot=$inlb"
	echo "SUMMARY kind=device-check cycles=1 pass=$pass"
	echo "# finished: $(date -Iseconds)"
} > "$out"

echo "wrote $out"
echo "script-sha256 $sha"
echo "boot-id $boot  srcversion $src  manifest $status"
[ $pass -eq 1 ]
