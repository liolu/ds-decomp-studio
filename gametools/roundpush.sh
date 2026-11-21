#!/bin/bash
# roundpush.sh ROUND : everything after an agent round, no questions asked (run from the game dir, env.sh sourced).
#  1. agentround.py ROUND (collect aK/*.c, symfix, judge all profiles, submit-many + main submits)
#  2. workbench commit (one full verify) + Co-Authored-By trailer
#  3. configure.py eu + match.py progress --rebuild + progress/report.json.gz (+ README badges) commit
#  4. git push
# Logs in ROUND/push.log. Stops at the first failing step.
set -e
R=build/hunt/$1; LOG=$R/push.log
G="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"  # studio/gametools, from any game folder (projets/ or games/<L>/)
# the game's build tools: its own tools/, or the shared tools/ of All-nds-decomp-games (games/<L>/<game>/)
if [ -f tools/configure.py ]; then BT=tools; else BT=../../../tools; fi
TRAILER='Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>'
export COMMIT_TRAILER="$TRAILER"  # workbench commit adds it (gitcommit.py): no amend of a commit that may be another game's
export AUTO_EXTRA_PROFILES='1.2/sp3,1.2/sp2p3,1.2/sp3 -O2,p,2.0/sp1p5 -O2,p,2.0/sp1p5 -profile,1.2/sp3 -profile,1.2/sp2p3 -profile,1.2/sp2p3 -thumb,2.0/sp1p5 -thumb,1.2/sp2p3 -proc arm7tdmi,1.2/sp3 -proc arm7tdmi,2.0/sp1p5 -O1,2.0/sp1p5 -O2,2.0/sp1p5 -O4,s'
{
echo "== agentround $(date +%H:%M)"; python $G/agentround.py "$R" $AGENTROUND_ARGS
echo "== commit $(date +%H:%M)"; BEFORE=$(git log -1 --format=%H -- .)  # this game's last commit
python $G/workbench.py commit
if [ "$(git log -1 --format=%H -- .)" = "$BEFORE" ]; then echo "nothing committed"; exit 0; fi
N=$(git log -1 --format=%s -- . | grep -o '[0-9]\+' | head -1)
echo "== progress $(date +%H:%M)"
python $BT/configure.py eu > /dev/null
python $BT/match.py progress --rebuild
gzip -9 -c build/eu/report.json > progress/report.json.gz
git add progress/report.json.gz README.md
git commit -q -m "progress: report after match $N (claude)" -m "$TRAILER" -- progress/report.json.gz README.md
echo "== push $(date +%H:%M)"; git push
echo "== done $(date +%H:%M)"
} 2>&1 | tee "$LOG"
