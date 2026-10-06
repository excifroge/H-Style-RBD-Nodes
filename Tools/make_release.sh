#!/usr/bin/env bash
# Build the zip and refresh Repository/. Usage: bash Tools/make_release.sh
#
# Repository/ is a static extension repository: the zip of the current version and the index.json that
# Blender reads. Served as plain files, it is what makes two things work:
#   - drag and drop: a link to the zip with "?repository=./index.json" can be dropped onto Blender;
#   - updates: Blender lists a new version once the repository has been added.
# It also packs the Unity folder (Dist/h_style_rbd_unity-<version>.zip): the shader and scripts are not part
# of the extension, so they are a second file on the release page.
# The zip in Repository/ has no version in its name, so the link in the READMEs stays the same from one
# release to the next. Dist/ holds the same bytes under the versioned name; attach that one to the release page.
cd "$(dirname "$0")/.." || exit 1
B="${BLENDER:-blender}"
bash Tools/build.sh || exit 1
mkdir -p Repository && rm -f Repository/*.zip Repository/index.json
cp Dist/h_style_rbd_nodes-*.zip Repository/h_style_rbd_nodes.zip
"$B" --factory-startup --command extension server-generate --repo-dir Repository 2>&1 | grep -iE "found|rror|index"
[ -f Repository/index.json ] || { echo "FAIL  no Repository/index.json"; exit 1; }
"$B" --background --factory-startup --python Tools/zip_unity.py 2>&1 | grep -E "created|rror"
ls Dist/h_style_rbd_unity-*.zip >/dev/null 2>&1 || { echo "FAIL  no Unity zip"; exit 1; }
ls -l Repository
