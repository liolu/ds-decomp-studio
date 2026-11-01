#!/bin/bash
# roundpush.sh ROUND : everything after an agent round, no questions asked (run from the game dir, env.sh sourced).
#  1. agentround.py ROUND (collect aK/*.c, symfix, judge all profiles, submit-many + main submits)
#  2. workbench commit (one full verify) + Co-Authored-By trailer
#  3. configure.py eu + match.py progress --rebuild + progress/report.json.gz (+ README badges) commit
#  4. git push
# Logs in ROUND/push.log. Stops at the first failing step.
set -e
R=build/hunt/$1; G=../../studio/gametools; LOG=$R/push.log
TRAILER='Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>'
export AUTO_EXTRA_PROFILES='1.2/sp3,1.2/sp2p3,1.2/sp3 -O2,p,2.0/sp1p5 -O2,p,2.0/sp1p5 -profile,1.2/sp3 -profile,1.2/sp2p3 -profile,1.2/sp2p3 -thumb,2.0/sp1p5 -thumb,1.2/sp2p3 -proc arm7tdmi,1.2/sp3 -proc arm7tdmi,2.0/sp1p5 -O1,2.0/sp1p5 -O2,2.0/sp1p5 -O4,s'
{
echo "== agentround $(date +%H:%M)"; python $G/agentround.py "$R"
echo "== commit $(date +%H:%M)"; BEFORE=$(git rev-parse HEAD)
python $G/workbench.py commit
if [ "$(git rev-parse HEAD)" = "$BEFORE" ]; then echo "nothing committed"; exit 0; fi
MSG=$(git log -1 --format=%B); case "$MSG" in *"$TRAILER"*) ;; *) git commit --amend -q -m "$MSG" -m "$TRAILER";; esac
N=$(git log -1 --format=%s | grep -o '[0-9]\+' | head -1)
echo "== progress $(date +%H:%M)"
python tools/configure.py eu > /dev/null
python tools/match.py progress --rebuild
gzip -9 -c build/eu/report.json > progress/report.json.gz
git add progress/report.json.gz README.md
git commit -q -m "progress: report after match $N (claude)" -m "$TRAILER"
echo "== push $(date +%H:%M)"; git push
echo "== done $(date +%H:%M)"
} 2>&1 | tee "$LOG"
