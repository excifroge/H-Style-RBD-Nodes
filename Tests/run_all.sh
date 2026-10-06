#!/usr/bin/env bash
# Run every headless test and say PASS or FAIL for each. Usage: bash Tests/run_all.sh [--installed]
#   --installed  also builds the extension zip, installs it into a throw-away Blender config
#                (Tools/UserResources) and runs the add-on test against the installed copy.
cd "$(dirname "$0")/.." || exit 1
B="${BLENDER:-blender}"
ROOT="$(pwd -W 2>/dev/null || pwd)"
OUT="$ROOT/Tests/Out"
fail=0

run() {  # name, extra blender args..., then the script arguments
  local name="$1"; shift
  "$B" --background "$@" 2>&1 | grep -E "^(FRACTURE|NODES|BAKE|EXPORT|STRESS|ADDON) " | sed 's/\\n/\n/g' | cut -c1-"${COLS:-400}"
  local code=${PIPESTATUS[0]}
  if [ "$code" -eq 0 ]; then echo "PASS  $name"; else echo "FAIL  $name (exit $code)"; fail=1; fi
}

for t in test_fracture test_nodes test_bake test_export test_stress test_addon; do
  run "$t" --factory-startup --python-exit-code 1 --python "Tests/$t.py" -- "$OUT"
done

if [ "$1" = "--installed" ]; then
  BLENDER="$B" bash Tools/build.sh || fail=1
  export BLENDER_USER_RESOURCES="$ROOT/Tools/UserResources"
  mkdir -p "$BLENDER_USER_RESOURCES"
  "$B" --command extension install-file -r user_default -e Dist/h_style_rbd_nodes-*.zip 2>&1 | grep -E "STATUS|rror"
  [ "${PIPESTATUS[0]}" -eq 0 ] || { echo "FAIL  extension install"; fail=1; }
  # the installed copy must be byte-identical to the source that the other tests ran against
  inst="$BLENDER_USER_RESOURCES/extensions/user_default/h_style_rbd_nodes"
  for f in Extension/*.py Extension/*.toml; do
    cmp -s "$f" "$inst/$(basename "$f")" || { echo "FAIL  installed $(basename "$f") differs from source"; fail=1; }
  done
  run "test_addon (installed zip)" --python-exit-code 1 --python Tests/test_addon.py -- "$OUT" installed
fi

if [ "$fail" -eq 0 ]; then echo "ALL TESTS PASSED"; else echo "SOME TESTS FAILED"; fi
exit $fail
