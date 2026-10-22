#!/bin/bash
# usage: fixall.sh SRC_DIR WORK_DIR   (run from the project dir, or set DSD_PROJECT)
# Runs every mechanical fixer on the SRC drafts into WORK/<tool>, merges into WORK/all, judges once with fj.py.
T="$(cd "$(dirname "$0")" && pwd)"; P="${DSD_PROJECT:-$PWD}"
SRC="$(cd "$1" && pwd)"; mkdir -p "$2"; W="$(cd "$2" && pwd)"; mkdir -p "$W/all"
export AUTO_EXTRA_PROFILES='1.2/sp3,1.2/sp3 -profile,2.0/sp1p5 -profile'
cd "$P"
for t in nearfix swdefault vcall callarg osfree modfix spsize structcopy fnptr hwvol bitflag bittail; do
  python "$T/$t.py" "$SRC" "$W/$t" >"$W/$t.log" 2>&1
  [ -d "$W/$t" ] && cp -n "$W/$t"/*.c "$W/all/" 2>/dev/null
done
python "$T/fj.py" "$W/all" -j 12 2>&1 | tail -n 4
