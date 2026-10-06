"""List the interface text of the add-on (names of node inputs, outputs, panels, menu items, their
tooltips; labels and tooltips of the operators and their options), and say which of it has no
Chinese translation yet. Text drawn by hand in the panels (ui.PANEL_TEXT) is included.

    blender --background --factory-startup --python Tools/ui_strings.py [-- all]

"all" prints every string, not only the missing ones. Exit code 1 if something is missing.
"""
import os
import sys

import bpy

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from Extension import nodes_rbd, translations, ui  # noqa: E402

SHOW_ALL = "all" in sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else False
names, tips = [], []
for kind, (title, ensure) in nodes_rbd.NODES.items():
    group = ensure()
    for item in group.interface.items_tree:
        names.append(item.name)
        if item.description:
            tips.append(item.description)
    for node in group.nodes:
        if node.bl_idname == "GeometryNodeMenuSwitch":
            names += [e.name for e in node.enum_items]
for cls in ui.CLASSES:
    if getattr(cls, "bl_label", ""):
        names.append(cls.bl_label)
    if getattr(cls, "bl_description", ""):
        tips.append(cls.bl_description)
    for prop in getattr(cls, "__annotations__", {}).values():
        kw = getattr(prop, "keywords", {})
        if "HIDDEN" in kw.get("options", ()):
            continue
        if kw.get("name"):
            names.append(kw["name"])
        if kw.get("description"):
            tips.append(kw["description"])
        for item in kw.get("items", ()) if isinstance(kw.get("items"), (tuple, list)) else ():
            names.append(item[1])
            if item[2]:
                tips.append(item[2])
names += list(ui.PANEL_TEXT)


def unique(seq):
    seen, out = set(), []
    for s in seq:
        if s not in seen:
            seen.add(s)
            out.append(s)
    return out


names, tips = unique(names), unique(tips)
# What a Chinese interface really shows. Blender's own dictionary comes first for the words it knows
# (Geometry, Selection, Density ...), so those need no entry in the table.
view = bpy.context.preferences.view
view.language = "zh_HANS"
view.use_translate_interface = True
view.use_translate_tooltips = True
translations.register()
bad = 0
for label, strings in (("NAME", names), ("TIP", tips)):
    shown = {s: bpy.app.translations.pgettext_iface(s) for s in strings}
    missing = [s for s in strings if shown[s] == s and s not in translations.SAME]
    bad += len(missing)
    print(f"STRINGS {label}: {len(strings)} in the interface, {len(missing)} shown in English", flush=True)
    for s in missing:
        print(f"STRINGS {label} ! {s!r}", flush=True)
    if SHOW_ALL:
        for s in strings:
            print(f"STRINGS {label}   {s!r} -> {shown[s]!r}" + ("" if s in translations.ZH else "   (Blender's own)"), flush=True)
unused = [s for s in translations.ZH if s not in names and s not in tips]
print(f"STRINGS {len(unused)} translations are not interface text any more: {unused}", flush=True)
sys.exit(1 if bad else 0)
