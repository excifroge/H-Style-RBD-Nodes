"""Check that a drag-and-drop link leads Blender to the extension. Run after the repository was added and synced:

    blender --background --online-mode --python Tools/check_repository.py -- <link>

<link> is the address that the README offers for dragging: the zip, followed by "?repository=...".
Prints what Blender makes of it and exits 1 if Blender would not find the extension in a repository it knows.
"""
import sys

import bpy  # noqa: F401  (the extension modules need a running Blender)
from bl_pkg import bl_extension_ops, bl_extension_utils

link = sys.argv[sys.argv.index("--") + 1]
url, params = bl_extension_utils.url_parse_for_blender(link)
print("CHECK zip       :", url)
print("CHECK repository:", params.get("repository"))
print("CHECK needs     :", {k: v for k, v in params.items() if k != "repository"})
found = bl_extension_ops.extension_url_find_repo_index_and_pkg_id(url)
print("CHECK found     :", found[1:3] if found and found[0] != -1 else None)
ok = bool(found) and found[0] != -1 and found[2] == "h_style_rbd_nodes"
print("CHECK", "PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
