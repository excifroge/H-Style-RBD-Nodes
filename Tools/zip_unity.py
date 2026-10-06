"""Pack the Unity folder for the release page: Dist/h_style_rbd_unity-<version>.zip, holding one folder
HStyleRbdUnity with the shader and the scripts. Run by Tools/make_release.sh:

    blender --background --factory-startup --python Tools/zip_unity.py

Every entry gets the same fixed date, like the extension zip (see Tools/build.sh), so the same source gives
the same file byte for byte.
"""
import os
import tomllib
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
with open(os.path.join(ROOT, "Extension", "blender_manifest.toml"), "rb") as fh:
    version = tomllib.load(fh)["version"]
source = os.path.join(ROOT, "Unity")
target = os.path.join(ROOT, "Dist", f"h_style_rbd_unity-{version}.zip")
os.makedirs(os.path.dirname(target), exist_ok=True)
names = sorted(name for name in os.listdir(source) if name.endswith((".cs", ".hlsl", ".shader")))
with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as z:
    for name in names:
        info = zipfile.ZipInfo("HStyleRbdUnity/" + name, date_time=(2000, 1, 1, 12, 0, 0))
        info.compress_type = zipfile.ZIP_DEFLATED
        info.external_attr = 0o644 << 16
        with open(os.path.join(source, name), "rb") as fh:
            z.writestr(info, fh.read())
print(f'created: "{target}", {os.path.getsize(target)}, {len(names)} files')
