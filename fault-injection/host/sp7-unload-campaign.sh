#!/bin/bash
# From a separate machine: run ipts-unload-race.sh until <target> cycles have passed in total. A run that
# stops because the IPTS firmware stopped answering ("no hidraw node after load") is followed by
# a reboot (the only known way to clear it) and the next run; any other failure stops the campaign.
#   sp7-unload-campaign.sh <ko on Surface> <target> <tag> [insmod params] [race|unload]
# "race" drives ipts-race.sh instead (start-up race, R2); its passing cycles say "new_oops=0 poll=".
HERE=$(cd "$(dirname "$0")" && pwd)
WORK=$(mktemp -d "${TMPDIR:-/tmp}/sp7-campaign.XXXXXX")
KO=$1; TARGET=$2; TAG=$3; P=$4; KIND=${5:-unload}; H=${SP7_HOST:?set SP7_HOST=user@host of the test device}
if [ "$KIND" = race ]; then SCRIPT=/root/sp7/ipts-race.sh; OKPAT="new_oops=0 poll=[0-9]"; else SCRIPT=/root/sp7/ipts-unload-race.sh; OKPAT="leftover=none new_oops=0"; fi
s() { timeout 60 ssh -o BatchMode=yes -o ConnectTimeout=8 $H "$@"; }
total=0; stalls=0; run=0
while [ $total -lt $TARGET ]; do
	run=$((run+1)); LOG=/root/sp7/campaign-$TAG-run$run.log
	s "sudo -n setsid nohup $SCRIPT $KO $((TARGET-total)) $LOG $P >/dev/null 2>&1 </dev/null &" ; sleep 5
	until s "sudo -n grep -q '^DONE' $LOG" 2>/dev/null; do sleep 20; done
	s "sudo -n cat $LOG" > "$WORK"/campaign-$TAG-run$run.log
	ok=$(grep -cE "$OKPAT" "$WORK"/campaign-$TAG-run$run.log)
	total=$((total+ok))
	echo "run $run: ok=$ok total=$total $(grep -E '^cycle .*(no hidraw|OOPS|outlived|rmmod)|RESULT' "$WORK"/campaign-$TAG-run$run.log | grep -vE "$OKPAT" | tr '\n' ' ')"
	if grep -q "RESULT result=PASS" "$WORK"/campaign-$TAG-run$run.log || { [ "$KIND" = race ] && [ $total -ge $TARGET ]; }; then break; fi
	if grep -q "no hidraw node after load" "$WORK"/campaign-$TAG-run$run.log; then
		stalls=$((stalls+1))
		"$HERE"/sp7-reboot-time.sh "campaign-$TAG-stall$stalls" 'sudo -n systemctl reboot' 600 | grep -E "t_back|pstore" | tr '\n' ' '; echo
		sleep 10; continue
	fi
	echo "STOP: failure other than a firmware stall"; break
done
echo "CAMPAIGN tag=$TAG passed_cycles=$total stalls=$stalls runs=$run"
