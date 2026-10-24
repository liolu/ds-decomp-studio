#!/bin/bash
# agentrefill.sh ROUND [PER] : hand ONE fresh list of PER (30) compile/size funcs to a new agent slot of ROUND.
# Creates build/hunt/ROUND/aK/ + build/hunt/ROUND/listK.txt (K = next free index) and prints K.
# Fills the list from the size bands 40-170 ... 1200-2000 in order: when a band has fewer left than
# PER, the rest comes from the next band. Run from the game dir. Used to keep N agents busy in a loop.
# The list is written with LF endings (agentdeal writes CRLF on Windows -> names ending in \r).
R=build/hunt/$1; PER=${2:-30}; mkdir -p "$R"
K=1; while [ -e "$R/list$K.txt" ]; do K=$((K+1)); done
: > "$R/list$K.txt"
for band in "40 170" "171 300" "301 500" "501 800" "801 1200" "1201 2000"; do
  set -- $band
  LEFT=$((PER - $(grep -c . "$R/list$K.txt")))
  [ $LEFT -le 0 ] && break
  python ../../studio/gametools/agentdeal.py 1 $LEFT --status compile,size --min-size $1 --max-size $2 > /dev/null
  tr -d '\r' < build/hunt/agentlists/agent1.txt | grep . >> "$R/list$K.txt"
done
mkdir -p "$R/a$K"
echo $K
