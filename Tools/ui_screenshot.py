"""Open the sidebar on the H-Style RBD Nodes tab with a baked object and save a screenshot. Needs a window:
blender --no-window-focus -p 60 60 1500 950 --python Tools/ui_screenshot.py -- <png> [network|baked] [language] [interface scale, e.g. 0.6 to fit the whole panel]
(run with BLENDER_USER_RESOURCES pointing at a config where the extension is installed)"""
import sys, traceback
import bpy, bmesh


def quit_():
    bpy.ops.wm.quit_blender()
    return None


# first of all: whatever goes wrong below, this window must not stay open
bpy.app.timers.register(quit_, first_interval=9.0)

args = sys.argv[sys.argv.index("--") + 1:]
PNG, STATE = args[0], (args[1] if len(args) > 1 else "baked")
LANG = args[2] if len(args) > 2 else "en_US"
SCALE = float(args[3]) if len(args) > 3 else 0.0  # interface scale, to fit the whole panel into the shot
view = bpy.context.preferences.view
view.language = LANG
view.use_translate_interface = view.use_translate_tooltips = LANG != "en_US"
view.ui_scale = SCALE or 1.0
LOG = PNG + ".log"


def log(msg):
    with open(LOG, "a", encoding="utf-8") as fh:
        fh.write(msg + "\n")


def setup():
    try:
        for o in list(bpy.data.objects):
            if o.type == "MESH":
                bpy.data.objects.remove(o)
        scene = bpy.context.scene
        scene.frame_start, scene.frame_end = 1, 60
        me = bpy.data.meshes.new("Wall")
        bm = bmesh.new()
        bmesh.ops.create_cube(bm, size=1.0)
        bmesh.ops.scale(bm, vec=(4.0, 0.4, 2.4), verts=bm.verts)
        bmesh.ops.translate(bm, vec=(0, 0, 1.2), verts=bm.verts)
        bm.to_mesh(me)
        bm.free()
        ob = bpy.data.objects.new("Wall", me)
        scene.collection.objects.link(ob)
        win = bpy.context.window_manager.windows[0]
        area = next(a for a in win.screen.areas if a.type == "VIEW_3D")
        region = next(r for r in area.regions if r.type == "WINDOW")
        with bpy.context.temp_override(window=win, area=area, region=region):
            bpy.context.view_layer.objects.active = ob
            ob.select_set(True)
            bpy.ops.hrbd.setup()
            fracture = next(n for n in ob.modifiers[-1].node_group.nodes if n.name == "RBD Material Fracture")
            fracture.inputs["Scatter Points"].default_value = 120
            fracture.inputs["Impact Point"].default_value = (0.0, 0.0, 1.3)
            fracture.inputs["Impact Bias"].default_value = 0.4
            if STATE == "baked":
                ob.location.z = 1.5
                bpy.ops.hrbd.bake()
                scene.frame_set(24)
            area.spaces[0].show_region_ui = True
            bpy.ops.view3d.view_all()
        ui = next(r for r in area.regions if r.type == "UI")
        try:
            ui.active_panel_category = "H-Style RBD"
        except Exception as e:
            log("category: " + repr(e))
        log("setup ok")
    except Exception:
        log(traceback.format_exc())
    return None


def scroll():
    try:
        win = bpy.context.window_manager.windows[0]
        area = next(a for a in win.screen.areas if a.type == "VIEW_3D")
        ui = next(r for r in area.regions if r.type == "UI")
        ui.tag_redraw()
        log("scroll ok")
    except Exception:
        log(traceback.format_exc())
    return None


def shot():
    try:
        win = bpy.context.window_manager.windows[0]
        area = next(a for a in win.screen.areas if a.type == "VIEW_3D")
        ui = next(r for r in area.regions if r.type == "UI")
        try:
            ui.active_panel_category = "H-Style RBD"
        except Exception as e:
            log("category2: " + repr(e))
        with bpy.context.temp_override(window=win, area=area):
            bpy.ops.screen.screenshot_area(filepath=PNG)
        log("shot ok")
    except Exception:
        log(traceback.format_exc())
    return None


bpy.app.timers.register(setup, first_interval=1.5)
bpy.app.timers.register(scroll, first_interval=3.5)
bpy.app.timers.register(shot, first_interval=4.5)
bpy.app.timers.register(quit_, first_interval=6.5)
