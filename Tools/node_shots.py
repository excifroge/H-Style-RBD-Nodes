"""One screenshot per RBD node, cropped to the node, for the documentation. Needs a window:

    blender --factory-startup --no-window-focus -p 60 60 1100 1300 --python Tools/node_shots.py -- <out folder> [language] [suffix] [interface scale]

language: en_US (default) or zh_HANS.  suffix: appended to the file names, for example _zh.
interface scale: 1.6 gives nodes about 560 pixels wide on a display scaled to 125%.

The add-on is taken from the source tree (Extension/), with every panel of every node open. All nodes are
shot at the same zoom (1:1). A node taller than the window is shot in several pieces, which are put together.
"""
import os
import sys
import traceback

import bpy
import numpy as np


def quit_():
    bpy.ops.wm.quit_blender()
    return None


# first of all: whatever goes wrong below, this window must not stay open
bpy.app.timers.register(quit_, first_interval=240.0)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
args = sys.argv[sys.argv.index("--") + 1:]
OUT = args[0]
LANG = args[1] if len(args) > 1 else "en_US"
SUFFIX = args[2] if len(args) > 2 else ""
SCALE = float(args[3]) if len(args) > 3 else 1.0
os.makedirs(OUT, exist_ok=True)
LOG = os.path.join(OUT, f"node_shots{SUFFIX}.log")
open(LOG, "w").close()
PAD = 16

# (file name, kind of node, {input: value})
SHOTS = [
    ("material_fracture_concrete", "material_fracture", {"Material Type": "Concrete"}),
    ("material_fracture_glass", "material_fracture", {"Material Type": "Glass"}),
    ("material_fracture_wood", "material_fracture", {"Material Type": "Wood"}),
    ("assemble", "assemble", {}),
    ("constraints_from_rules", "constraints_from_rules", {}),
    ("configure", "configure", {"Set Active": True, "Set Initial Velocity": True, "Set Activation": True,
                                "Set Physical Properties": True}),
    ("configure_constant", "configure", {"Set Initial Velocity": True, "Velocity Type": "Constant", "Set Activation": True,
                                         "Activation Type": "At Time"}),
    ("select_below_height", "select", {"Type": "Below Height"}),
    ("select_box", "select", {"Type": "Box"}),
    ("select_sphere", "select", {"Type": "Sphere"}),
    ("select_attribute", "select", {"Type": "Attribute", "Attribute": "Stay"}),
    ("constraint_properties", "constraint_properties", {}),
    ("cluster", "cluster", {}),
    ("exploded_view", "exploded_view", {}),
    ("bullet_solver", "bullet_solver", {}),
]
state = {"k": 0, "tree": None, "node": None, "canvas": None, "tiles": 0}


def log(msg):
    with open(LOG, "a", encoding="utf-8") as fh:
        fh.write(msg + "\n")


def editor():
    win = bpy.context.window_manager.windows[0]
    area = next(a for a in win.screen.areas if a.type == "NODE_EDITOR")
    region = next(r for r in area.regions if r.type == "WINDOW")
    return win, area, region


def rect():
    """The node on the screen, in pixels of the region: left, bottom, right, top."""
    node = state["node"]
    win, area, region = editor()
    scale = bpy.context.preferences.system.ui_scale
    x0, y1 = node.location.x * scale, node.location.y * scale
    w, h = node.dimensions.x, node.dimensions.y
    a = region.view2d.view_to_region(x0, y1 - h, clip=False)
    b = region.view2d.view_to_region(x0 + w, y1, clip=False)
    return float(a[0]), float(a[1]), float(b[0]), float(b[1])


def pan(dx, dy):
    """Move what is shown by (dx, dy) pixels on the screen."""
    win, area, region = editor()
    before = rect()
    with bpy.context.temp_override(window=win, area=area, region=region):
        bpy.ops.view2d.pan(deltax=int(round(-dx)), deltay=int(round(-dy)))
    after = rect()
    if abs((after[0] - before[0]) - dx) > 2 or abs((after[3] - before[3]) - dy) > 2:
        # the operator counts the other way round: undo, and go the right way
        with bpy.context.temp_override(window=win, area=area, region=region):
            bpy.ops.view2d.pan(deltax=int(round(2 * dx)), deltay=int(round(2 * dy)))


def setup():
    try:
        view = bpy.context.preferences.view
        view.language = LANG
        view.use_translate_interface = view.use_translate_tooltips = LANG != "en_US"
        view.ui_scale = SCALE
        import Extension
        from Extension import nodekit
        nodekit.OPEN_ALL_PANELS = True
        Extension.register()
        me = bpy.data.meshes.new("Shot")
        ob = bpy.data.objects.new("Shot", me)
        bpy.context.scene.collection.objects.link(ob)
        bpy.context.view_layer.objects.active = ob
        ob.select_set(True)
        tree = bpy.data.node_groups.new("Shot", "GeometryNodeTree")
        tree.interface.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
        tree.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
        ob.modifiers.new("RBD", "NODES").node_group = tree
        state["tree"] = tree
        win = bpy.context.window_manager.windows[0]
        area = max((a for a in win.screen.areas if a.type == "VIEW_3D"), key=lambda a: a.width * a.height)
        area.ui_type = "GeometryNodeTree"
        space = area.spaces.active
        space.show_region_ui = False
        space.show_region_toolbar = False
        space.overlay.show_context_path = False
        with bpy.context.temp_override(window=win, area=area):
            bpy.ops.screen.screen_full_area(use_hide_panels=True)
        log(f"setup ok, interface scale {bpy.context.preferences.system.ui_scale:.2f}")
        bpy.app.timers.register(prepare, first_interval=1.0)
    except Exception:
        log(traceback.format_exc())
    return None


def prepare():
    try:
        from Extension import nodes_rbd
        name, kind, values = SHOTS[state["k"]]
        tree = state["tree"]
        tree.nodes.clear()
        node = tree.nodes.new("GeometryNodeGroup")
        node.node_tree = nodes_rbd.NODES[kind][1]()
        node.name = node.label = nodes_rbd.NODES[kind][0]
        node.width = 280.0
        node.location = (0.0, 0.0)
        for key, value in values.items():
            node.inputs[key].default_value = value
        node.select = False
        state.update(node=node, canvas=None, tiles=0)
        bpy.app.timers.register(place, first_interval=0.6)
    except Exception:
        log(traceback.format_exc())
        bpy.app.timers.register(advance, first_interval=0.1)
    return None


def place():
    """Zoom 1:1, and the top left corner of the node in the top left corner of the editor."""
    try:
        win, area, region = editor()
        with bpy.context.temp_override(window=win, area=area, region=region):
            bpy.ops.view2d.reset()
        left, bottom, right, top = rect()
        pan(PAD - left, (region.height - PAD) - top)
        area.tag_redraw()
        bpy.app.timers.register(tile, first_interval=0.5)
    except Exception:
        log(traceback.format_exc())
        bpy.app.timers.register(advance, first_interval=0.1)
    return None


def tile():
    """Shoot what is visible of the node, and move on down the node until its bottom has been seen."""
    try:
        name = SHOTS[state["k"]][0]
        win, area, region = editor()
        left, bottom, right, top = rect()
        width, height = int(round(right - left)) + 2 * PAD, int(round(top - bottom)) + 2 * PAD
        if state["canvas"] is None:
            state["canvas"] = np.zeros((height, width, 4), np.float32)
        canvas = state["canvas"]
        full = os.path.join(OUT, f"_tile_{name}.png")
        with bpy.context.temp_override(window=win, area=area):
            bpy.ops.screen.screenshot_area(filepath=full)
        img = bpy.data.images.load(full)
        iw, ih = img.size
        px = np.empty(iw * ih * 4, np.float32)
        img.pixels.foreach_get(px)
        px = px.reshape(ih, iw, 4)
        bpy.data.images.remove(img)
        os.remove(full)
        ox, oy = region.x - area.x, region.y - area.y
        # canvas pixel (cx, cy) shows region pixel (cx + left - PAD, cy + bottom - PAD)
        x_off, y_off = int(round(left)) - PAD, int(round(bottom)) - PAD
        ry0, ry1 = max(y_off, 0), min(y_off + canvas.shape[0], region.height)
        rx0, rx1 = max(x_off, 0), min(x_off + canvas.shape[1], region.width)
        canvas[ry0 - y_off:ry1 - y_off, rx0 - x_off:rx1 - x_off] = px[ry0 + oy:ry1 + oy, rx0 + ox:rx1 + ox]
        state["tiles"] += 1
        if bottom - PAD < 0 and state["tiles"] < 8:
            # the bottom of the node is below the editor: move the view down by most of a screen
            pan(0.0, min(region.height - 3 * PAD, PAD - bottom))
            area.tag_redraw()
            bpy.app.timers.register(tile, first_interval=0.5)
            return None
        rows, cols = np.where(canvas[:, :, 3].max(axis=1) > 0)[0], np.where(canvas[:, :, 3].max(axis=0) > 0)[0]
        canvas = canvas[rows[0]:rows[-1] + 1, cols[0]:cols[-1] + 1]        # a row or column at the edge may have been missed
        out = bpy.data.images.new(name, canvas.shape[1], canvas.shape[0], alpha=True)
        out.pixels.foreach_set(np.ascontiguousarray(canvas).reshape(-1))
        out.filepath_raw = os.path.join(OUT, f"{name}{SUFFIX}.png")
        out.file_format = "PNG"
        out.save()
        bpy.data.images.remove(out)
        zoom = (right - left) / max(state["node"].dimensions.x, 1.0)
        log(f"shot {name}: {canvas.shape[1]}x{canvas.shape[0]} in {state['tiles']} piece(s), zoom {zoom:.3f}, "
            f"missing rows {int((canvas[:, :, 3].max(axis=1) == 0).sum())}")
    except Exception:
        log(traceback.format_exc())
    bpy.app.timers.register(advance, first_interval=0.1)
    return None


def advance():
    state["k"] += 1
    if state["k"] < len(SHOTS):
        bpy.app.timers.register(prepare, first_interval=0.1)
    else:
        log("done")
        bpy.app.timers.register(quit_, first_interval=0.5)
    return None


bpy.app.timers.register(setup, first_interval=1.5)
