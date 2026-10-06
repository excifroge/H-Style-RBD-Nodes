#!/usr/bin/env bash
# Drop a fresh export into an EMPTY Unity project (URP only) and check it there, in batch mode (no window):
# the exported scripts compile as part of a project, "Set Up VAT From Json" works, and the prefab plays in
# Play mode with particles at the cracks. Takes a few minutes the first time (package import).
#   blender --background --factory-startup --python Tests/unity_export.py -- Tests/Out/Unity
#   bash Tests/Unity/Fresh/run_fresh.sh
cd "$(dirname "$0")/../../.." || exit 1
U="${UNITY:-C:/Program Files/Unity/Hub/Editor/6000.0.74f1/Editor/Unity.exe}"
ROOT="$(pwd -W 2>/dev/null || pwd)"
SRC="$ROOT/Tests/Out/Unity"
P="$ROOT/Tests/Out/UnityFresh"
rm -rf "$P/Assets" "$P/fresh_result.txt" "$P/unity.log"
mkdir -p "$P/Assets/RbdExport" "$P/Assets/Editor" "$P/Packages" "$P/ProjectSettings"
printf 'm_EditorVersion: %s\n' "$(basename "$(dirname "$(dirname "$U")")")" > "$P/ProjectSettings/ProjectVersion.txt"
cat > "$P/Packages/manifest.json" <<'JSON'
{
  "dependencies": {
    "com.unity.render-pipelines.universal": "17.0.4",
    "com.unity.modules.animation": "1.0.0",
    "com.unity.modules.imageconversion": "1.0.0",
    "com.unity.modules.jsonserialize": "1.0.0",
    "com.unity.modules.particlesystem": "1.0.0",
    "com.unity.modules.physics": "1.0.0"
  }
}
JSON
cp -r "$SRC/HStyleRbdUnity" "$SRC"/unity_wall* "$SRC"/unity_vat* "$SRC/unity_bones.fbx" "$P/Assets/RbdExport/"
cp "$SRC/events_truth.txt" "$P/"
cp Tests/Unity/Fresh/HStyleRbdFreshCheck.cs "$P/Assets/Editor/"
cp Tests/Unity/Fresh/HStyleRbdPlayProbe.cs "$P/Assets/"
timeout 1500 "$U" -batchmode -projectPath "$P" -executeMethod HStyleRbdFreshCheck.Run -logFile "$P/unity.log"
code=$?
echo "Unity exit code $code"
cat "$P/fresh_result.txt" 2>/dev/null || { echo "no result file; last lines of the log:"; grep -E "error CS|Exception|rror:" "$P/unity.log" | head -20; tail -5 "$P/unity.log"; }
exit $code
