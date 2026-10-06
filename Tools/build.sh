#!/usr/bin/env bash
# Build the extension zip into Dist/. Usage: bash Tools/build.sh   (BLENDER=/path/to/blender if not on the PATH)
#
# The files are copied to Dist/Stage first and all given the same date. A zip stores the clock time of
# every file without a time zone, so the times of an ordinary build tell where and when it was made. With
# one fixed date the same source also gives the same zip, byte for byte.
cd "$(dirname "$0")/.." || exit 1
B="${BLENDER:-blender}"
rm -rf Dist && mkdir -p Dist/Stage
cp Extension/*.py Extension/*.toml Extension/*.txt Extension/*.cs Extension/*.hlsl Extension/*.shader Dist/Stage/
touch -d "2000-01-01 12:00:00" Dist/Stage/*
"$B" --factory-startup --command extension validate Dist/Stage 2>&1 | grep -iE "error|success"
[ "${PIPESTATUS[0]}" -eq 0 ] || { echo "FAIL  extension validate"; exit 1; }
"$B" --factory-startup --command extension build --source-dir Dist/Stage --output-dir Dist 2>&1 | grep -E "created|rror"
rm -rf Dist/Stage
ls Dist/h_style_rbd_nodes-*.zip >/dev/null 2>&1 || { echo "FAIL  extension build"; exit 1; }
