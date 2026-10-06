"""Open the Geometry Nodes editor on an object with an RBD network and save a screenshot. Needs a window:
blender --no-window-focus -p 60 60 1700 1000 --python Tools/node_screenshot.py -- <png> [material] [inside or -] [language]
(run with BLENDER_USER_RESOURCES pointing at a config where the extension is installed)
material: Concrete / Glass / Wood.  "inside": show the inside of the RBD Material Fracture node instead.
With "file" in place of the material, nothing is built: the network of the active object of the .blend given
on the command line (before --python) is shown.   blender ... Examples/06_brick_wall.blend --python ... -- <png> file"""
import sys
import traceback

import bmesh
import bpy


def quit_():
    bpy.ops.wm.quit_blender()
    return None


# first of all: whatever goes wrong below, this window must not stay open
bpy.app.timers.register(quit_, first_interval=10.0)

args = sys.argv[sys.argv.index("--") + 1:]
PNG = args[0]
MATERIAL = args[1] if len(args) > 1 else "Concrete"
INSIDE = len(args) > 2 and args[2] == "inside"
LOG = PNG + ".log"
LANG = args[3] if len(args) > 3 else "en_US"      # for example zh_HANS
view = bpy.context.preferences.view
view.language = LANG
view.use_translate_interface = LANG != "en_US"
view.ui_scale = 1.0


def log(msg):
    with open(LOG, "a", encoding="utf-8") as fh:
        fh.write(msg + "\n")


def setup_file():
    try:
        ob = bpy.context.view_layer.objects.active
        win = bpy.context.window_manager.windows[0]
        area = max((a for a in win.screen.areas if a.type in ("VIEW_3D", "NODE_EDITOR")), key=lambda a: a.width * a.height)
        area.ui_type = "GeometryNodeTree"
        area.spaces.active.show_region_ui = False
        log("file ok: " + ", ".join(n.name for n in ob.modifiers[-1].node_group.nodes))
    except Exception:
        log(traceback.format_exc())
    return None


def setup():
    if MATERIAL == "file":
        return setup_file()
    try:
        for o in list(bpy.data.objects):
            if o.type == "MESH":
                bpy.data.objects.remove(o)
        me = bpy.data.meshes.new("Wall")
        bm = bmesh.new()
        bmesh.ops.create_cube(bm, size=1.0)
        bmesh.ops.scale(bm, vec=(4.0, 0.4, 2.4), verts=bm.verts)
        bmesh.ops.translate(bm, vec=(0, 0, 1.2), verts=bm.verts)
        bm.to_mesh(me)
        bm.free()
        ob = bpy.data.objects.new("Wall", me)
        bpy.context.scene.collection.objects.link(ob)
        bpy.context.view_layer.objects.active = ob
        ob.select_set(True)
        win = bpy.context.window_manager.windows[0]
        area = next(a for a in win.screen.areas if a.type == "VIEW_3D")
        with bpy.context.temp_override(window=win, area=area):
            bpy.ops.hrbd.setup()
        mod = ob.modifiers[-1]
        node = next(n for n in mod.node_group.nodes if n.name == "RBD Material Fracture")
        node.inputs["Material Type"].default_value = MATERIAL
        node.inputs["Scatter Points"].default_value = 60
        for n in mod.node_group.nodes:
            n.select = n == node
        mod.node_group.nodes.active = node
        area.ui_type = "GeometryNodeTree"
        space = area.spaces.active
        space.show_region_ui = False
        log("setup ok: " + ", ".join(n.name for n in mod.node_group.nodes))
    except Exception:
        log(traceback.format_exc())
    return None


def frame():
    try:
        win = bpy.context.window_manager.windows[0]
        area = next(a for a in win.screen.areas if a.type == "NODE_EDITOR")
        region = next(r for r in area.regions if r.type == "WINDOW")
        with bpy.context.temp_override(window=win, area=area, region=region):
            if INSIDE:
                bpy.ops.node.group_edit()
            bpy.ops.node.view_all()
        log("frame ok")
    except Exception:
        log(traceback.format_exc())
    return None


def shot():
    try:
        win = bpy.context.window_manager.windows[0]
        area = next(a for a in win.screen.areas if a.type == "NODE_EDITOR")
        with bpy.context.temp_override(window=win, area=area):
            bpy.ops.screen.screenshot_area(filepath=PNG)
        log("shot ok")
    except Exception:
        log(traceback.format_exc())
    return None


bpy.app.timers.register(setup, first_interval=1.5)
bpy.app.timers.register(frame, first_interval=3.5)
bpy.app.timers.register(shot, first_interval=5.5)
bpy.app.timers.register(quit_, first_interval=7.5)
