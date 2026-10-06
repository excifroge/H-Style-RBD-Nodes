"""Build the example .blend files the way a user does: the RBD Network button, RBD nodes from the
Add menu, values typed into the nodes, the Bake button. Also renders a preview sheet of each.

    blender --background --factory-startup --python Examples/make_examples.py -- [output folder] [frames folder or -] [example name ...]

With a frames folder, every second frame of each example is also rendered there as a small PNG
(Tools/frames_to_gif.py turns those into the animated previews of the README).

Every file is fractured, baked and ready to scrub: select the object and open a Geometry Nodes
editor to see its RBD nodes. The baked motion plays without the add-on installed (the node groups
and the cache are stored in the file); the Bake button and the exports need the add-on.
"""
import math
import os
import sys

import bmesh
import bpy
import numpy as np
from mathutils import Vector

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
OUT = args[0] if args else HERE
FRAMES = args[1] if len(args) > 1 and args[1] != "-" else None
ONLY = set(args[2:])          # example names; none = all of them
os.makedirs(OUT, exist_ok=True)

if not hasattr(bpy.types, "HRBD_PT_main"):   # not installed: use the source tree
    sys.path.insert(0, ROOT)
    import Extension
    Extension.register()

STREAMS = ("Geometry", "Constraint Geometry", "Proxy Geometry")


# ---------------------------------------------------------------- the scene
def box(name, size, center):
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bm.loops.layers.uv.new("UVMap")
    bmesh.ops.create_cube(bm, size=1.0, calc_uvs=True)
    bmesh.ops.scale(bm, vec=size, verts=bm.verts)
    bmesh.ops.translate(bm, vec=center, verts=bm.verts)
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(ob)
    return ob


def material(name, color, rough=0.7):
    m = bpy.data.materials.new(name)
    m.diffuse_color = (*color, 1.0)
    m.roughness = rough
    return m


def collider_ball(radius, start, end, frames):
    col = bpy.data.collections.new("Colliders")
    bpy.context.scene.collection.children.link(col)
    me = bpy.data.meshes.new("Ball")
    bm = bmesh.new()
    bmesh.ops.create_icosphere(bm, subdivisions=3, radius=radius)
    bm.to_mesh(me)
    bm.free()
    ball = bpy.data.objects.new("Ball", me)
    col.objects.link(ball)
    ball.data.materials.append(material("Ball", (0.75, 0.2, 0.15), 0.4))
    ball.location = start
    ball.keyframe_insert("location", frame=frames[0])
    ball.location = end
    ball.keyframe_insert("location", frame=frames[1])
    return col


def start(frame_end):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.frame_start, scene.frame_end = 1, frame_end
    scene.render.fps = 24
    floor = box("Floor (visual only)", (40.0, 40.0, 0.02), (0.0, 0.0, -0.011))
    floor.data.materials.append(material("Floor", (0.32, 0.33, 0.35)))
    floor.hide_select = True
    sun = bpy.data.objects.new("Sun", bpy.data.lights.new("Sun", "SUN"))
    sun.rotation_euler = (math.radians(50), 0.0, math.radians(35))
    sun.data.energy = 3.0
    scene.collection.objects.link(sun)
    return scene


# ---------------------------------------------------------------- the node network
def network(ob, template, outer):
    """The RBD Network button. Returns the node tree."""
    ob.data.materials.append(material(ob.name + " Outer", outer))
    bpy.context.view_layer.objects.active = ob
    for o in bpy.context.view_layer.objects:
        o.select_set(o == ob)
    assert bpy.ops.hrbd.setup(template=template) == {"FINISHED"}
    return ob.modifiers[-1].node_group


def rbd(tree, name):
    return next(n for n in tree.nodes if n.name == name)


def add(tree, kind):
    """Add > RBD > ... in the node editor. The new node is not wired yet."""
    assert bpy.ops.hrbd.add_node(kind=kind) == {"FINISHED"}
    return tree.nodes.active


def insert(tree, node, before):
    """Drop `node` on the three wires that go into `before`."""
    for name in STREAMS:
        link = before.inputs[name].links[0]
        source = link.from_socket
        tree.links.remove(link)
        tree.links.new(source, node.inputs[name])
        tree.links.new(node.outputs[name], before.inputs[name])


def put(node, values):
    for name, value in values.items():
        node.inputs[name].default_value = value


def select(tree, into, values):
    """An RBD Select node wired into the Selection of `into`."""
    node = add(tree, "select")
    put(node, values)
    tree.links.new(node.outputs["Selection"], into.inputs["Selection"])
    return node


def tidy(tree):
    """The RBD nodes in a row, in the order the geometry flows through them; selections above the node they feed."""
    out = next(n for n in tree.nodes if n.bl_idname == "NodeGroupOutput")
    row, node = [], out
    while node.inputs and node.inputs[0].links:
        node = node.inputs[0].links[0].from_node
        row.append(node)
    row.reverse()                                   # Group Input, RBD nodes ...
    for k, node in enumerate(row):
        node.location = (340.0 * k - 300.0, 0.0 if k == 0 else 80.0)
    out.location = (340.0 * len(row) - 300.0, 0.0)
    for node in tree.nodes:
        if node not in row and node != out:
            feeds = [link.to_node for s in node.outputs for link in s.links]
            if feeds:
                above = len([n for n in tree.nodes if n != node and n not in row and n.location.y > 300.0
                             and abs(n.location.x - (feeds[0].location.x - 320.0)) < 1.0])
                node.location = (feeds[0].location.x - 320.0, 420.0 + 300.0 * above)
                if feeds[0] not in row:             # feeds another helper (a Boolean Math): further left
                    node.location = (feeds[0].location.x - 320.0, feeds[0].location.y + 150.0 - 300.0 * above)


def finish(name, ob, target, distance, direction=(1.0, -1.25, 0.6), stills=(1, 12, 30, 80)):
    scene = bpy.context.scene
    tree = ob.modifiers[-1].node_group
    tidy(tree)
    bpy.context.view_layer.objects.active = ob
    for o in bpy.context.view_layer.objects:
        o.select_set(o == ob)
    assert bpy.ops.hrbd.bake() == {"FINISHED"}
    cam = bpy.data.objects.new("Camera", bpy.data.cameras.new("Camera"))
    scene.collection.objects.link(cam)
    d = Vector(direction).normalized()
    cam.location = Vector(target) + d * distance
    cam.rotation_euler = (-d).to_track_quat("-Z", "Y").to_euler()
    cam.data.clip_end = 500
    scene.camera = cam
    scene.frame_set(1)
    # The file browser of the Shading workspace starts in the Documents folder of whoever runs this, and
    # that path would be saved into the file (with the user name in it).
    for screen in bpy.data.screens:
        for area in screen.areas:
            for space in area.spaces:
                if space.type == "FILE_BROWSER" and space.params is not None:
                    # (Blender saves the whole buffer, also what is left in it behind the end of the new text)
                    space.params.directory = b"/" * 1089
                    space.params.directory = b"//"
    path = os.path.join(OUT, name + ".blend")
    bpy.ops.wm.save_as_mainfile(filepath=path)

    # preview sheet
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.render.resolution_x, scene.render.resolution_y = 800, 450
    sh = scene.display.shading
    sh.light, sh.color_type, sh.show_cavity, sh.show_shadows = "STUDIO", "MATERIAL", True, True
    scene.world = bpy.data.worlds.new("World")
    scene.world.color = (0.55, 0.57, 0.6)
    tiles = []
    for f in stills:
        scene.frame_set(f)
        scene.render.filepath = os.path.join(OUT, f"_{name}_{f:03d}.png")
        bpy.ops.render.render(write_still=True)
        tiles.append(scene.render.filepath)
    imgs = [bpy.data.images.load(p) for p in tiles]
    w, h = imgs[0].size
    sheet = np.zeros((2 * h, 2 * w, 4), np.float32)
    for k, im in enumerate(imgs):
        a = np.empty(w * h * 4, np.float32)
        im.pixels.foreach_get(a)
        r, c = k // 2, k % 2
        sheet[(1 - r) * h:(2 - r) * h, c * w:(c + 1) * w] = a.reshape(h, w, 4)
    out = bpy.data.images.new("sheet", 2 * w, 2 * h, alpha=True)
    out.pixels.foreach_set(sheet.reshape(-1))
    scene.render.image_settings.file_format = "JPEG"
    scene.render.image_settings.quality = 88
    out.save_render(os.path.join(OUT, name + ".jpg"), scene=scene)
    for p in tiles:
        os.remove(p)
    if FRAMES:
        scene.render.image_settings.file_format = "PNG"
        scene.render.resolution_x, scene.render.resolution_y = 480, 270
        last = min(scene.frame_end, stills[-1])
        for f in range(1, last + 1, 2):
            scene.frame_set(f)
            scene.render.filepath = os.path.join(FRAMES, name, f"f{f:03d}.png")
            bpy.ops.render.render(write_still=True)
    names = [n.name for n in tree.nodes if n.bl_idname == "GeometryNodeGroup"]
    print(f"EXAMPLE {name}: saved {os.path.basename(path)} ({os.path.getsize(path) / 1e6:.1f} MB), nodes: {names}", flush=True)


def want(name):
    return not ONLY or name in ONLY


def inside(ob, color):
    return {"Assign Inside Material": True, "Inside Material": material(ob.name + " Inner", color, 0.9)}


# 1. a wall, held at the bottom, smashed by an animated ball
#    RBD Material Fracture -> RBD Cluster -> RBD Configure (bottom row: not active) -> RBD Bullet Solver
if want("01_wall_smash"):
    start(110)
    wall = box("Wall", (6.0, 0.5, 3.0), (0.0, 0.0, 1.5))
    tree = network(wall, "FRACTURE", (0.62, 0.6, 0.56))
    fracture, solver = rbd(tree, "RBD Material Fracture"), rbd(tree, "RBD Bullet Solver")
    put(fracture, {"Material Type": "Concrete", "Scatter Points": 260, "Impact Point": (0.0, -0.25, 1.6), "Impact Bias": 0.5,
                   "Impact Radius": 1.0, "Secondary Fracture": True, "Fracture Ratio": 0.2, "Detail": True, "Noise Amplitude": 0.02,
                   "Primary Strength": 4.0, "Strength Variance": 0.3, **inside(wall, (0.35, 0.33, 0.3))})
    cluster = add(tree, "cluster")
    insert(tree, cluster, solver)
    put(cluster, {"Size": 0.7, "Strength Scale": 10.0})
    configure = add(tree, "configure")
    insert(tree, configure, solver)
    put(configure, {"Set Active": True, "Active": False})
    select(tree, configure, {"Type": "Below Height", "Height": 0.05})
    put(solver, {"Start Asleep": True, "Collision Objects": collider_ball(0.6, (0, -8, 1.6), (0, 8, 1.6), (1, 25))})
    finish("01_wall_smash", wall, (0, 0, 1.4), 11.0, stills=(1, 15, 32, 110))

# 2. the ground bursting open: a wave from the impact point lets the pieces go and throws them up
#    RBD Material Fracture (Cut Through) -> RBD Configure (velocity + activation wave) -> RBD Bullet Solver
if want("02_ground_crack"):
    start(96)
    ground = box("Ground", (8.0, 8.0, 0.3), (0.0, 0.0, 0.15))
    tree = network(ground, "FRACTURE", (0.45, 0.43, 0.38))
    fracture, solver = rbd(tree, "RBD Material Fracture"), rbd(tree, "RBD Bullet Solver")
    put(fracture, {"Material Type": "Concrete", "Cut Through": True, "Scatter Points": 180, "Impact Point": (0.0, 0.0, 0.15),
                   "Impact Bias": 0.6, "Impact Radius": 2.5, "Secondary Fracture": True, "Fracture Ratio": 0.15,
                   "Detail": True, "Noise Amplitude": 0.01, "Constraints": False, **inside(ground, (0.25, 0.2, 0.16))})
    configure = add(tree, "configure")
    insert(tree, configure, solver)
    put(configure, {"Set Initial Velocity": True, "Velocity Type": "Radial", "Origin": (0.0, 0.0, 0.15), "Speed": 7.0,
                    "Falloff Radius": 4.5, "Up Bias": 0.75,
                    "Set Activation": True, "Activation Type": "Radial Wave", "Wave Origin": (0.0, 0.0, 0.15), "Wave Speed": 8.0})
    finish("02_ground_crack", ground, (0, 0, 0.9), 15.0, direction=(1.0, -1.2, 0.75), stills=(1, 10, 24, 96))

# 3. an explosion
#    RBD Material Fracture -> RBD Configure (radial velocity) -> RBD Bullet Solver
if want("03_explosion"):
    start(96)
    crate = box("Block", (2.0, 2.0, 2.0), (0.0, 0.0, 1.0))
    tree = network(crate, "FRACTURE", (0.55, 0.5, 0.42))
    fracture, solver = rbd(tree, "RBD Material Fracture"), rbd(tree, "RBD Bullet Solver")
    put(fracture, {"Material Type": "Concrete", "Scatter Points": 160, "Impact Point": (0.0, 0.0, 0.7), "Impact Bias": 0.2,
                   "Impact Radius": 0.7, "Secondary Fracture": True, "Fracture Ratio": 0.2, "Detail": True, "Noise Amplitude": 0.015,
                   "Constraints": False, **inside(crate, (0.3, 0.24, 0.2))})
    configure = add(tree, "configure")
    insert(tree, configure, solver)
    put(configure, {"Set Initial Velocity": True, "Velocity Type": "Radial", "Origin": (0.0, 0.0, 0.7), "Speed": 9.0, "Up Bias": 0.25})
    finish("03_explosion", crate, (0, 0, 1.6), 15.0, stills=(1, 6, 16, 96))

# 4. a glass pane shot through
#    RBD Material Fracture (Glass) -> RBD Configure (bottom edge: not active) -> RBD Bullet Solver
if want("04_glass"):
    start(96)
    pane = box("Glass", (3.0, 0.05, 2.0), (0.0, 0.0, 1.0))
    tree = network(pane, "FRACTURE", (0.55, 0.75, 0.8))
    fracture, solver = rbd(tree, "RBD Material Fracture"), rbd(tree, "RBD Bullet Solver")
    put(fracture, {"Material Type": "Glass", "Impact Point": (0.3, 0.0, 1.2), "Radial Crack Number": 16, "Concentric Crack Number": 6,
                   "Impact Spread": 2.2, "Primary Strength": 0.1, "Strength Variance": 0.6, **inside(pane, (0.75, 0.9, 0.92))})
    configure = add(tree, "configure")
    insert(tree, configure, solver)
    put(configure, {"Set Active": True, "Active": False})
    select(tree, configure, {"Type": "Below Height", "Height": 0.05})
    put(solver, {"Start Asleep": True, "Collision Objects": collider_ball(0.22, (0.3, -6, 1.2), (0.3, 6, 1.2), (1, 16))})
    finish("04_glass", pane, (0, 0, 1.0), 6.5, direction=(0.6, -1.3, 0.35), stills=(1, 10, 20, 96))

# 5. a wooden post snapped by a swinging ball
#    RBD Material Fracture (Wood) -> RBD Cluster -> RBD Configure (the foot: not active) -> RBD Bullet Solver
if want("05_wood_post"):
    start(96)
    post = box("Post", (0.4, 0.4, 3.0), (0.0, 0.0, 1.5))
    tree = network(post, "FRACTURE", (0.5, 0.36, 0.2))
    fracture, solver = rbd(tree, "RBD Material Fracture"), rbd(tree, "RBD Bullet Solver")
    put(fracture, {"Material Type": "Wood", "Scatter Points": 60, "Impact Point": (0.0, 0.0, 1.6), "Detail": True,
                   "Noise Amplitude": 0.004, "Primary Strength": 3.0, **inside(post, (0.78, 0.62, 0.38))})
    cluster = add(tree, "cluster")
    insert(tree, cluster, solver)
    put(cluster, {"Size": 0.35, "Strength Scale": 10.0})
    configure = add(tree, "configure")
    insert(tree, configure, solver)
    put(configure, {"Set Active": True, "Active": False})
    select(tree, configure, {"Type": "Below Height", "Height": 0.3})
    put(solver, {"Start Asleep": True, "Collision Objects": collider_ball(0.35, (-5, 0, 1.7), (5, 0, 1.7), (1, 20))})
    finish("05_wood_post", post, (0, 0, 1.45), 10.0, stills=(1, 12, 22, 96))

# 6. a wall of modelled bricks (nothing is cut), its two ends painted to stay, hit by a ball
#    RBD Assemble -> RBD Constraints From Rules -> RBD Configure (painted or on the ground: not active) -> RBD Bullet Solver
if want("06_brick_wall"):
    start(110)
    bm = bmesh.new()
    cols, rows, size = 12, 10, (0.5, 0.25, 0.25)
    brick_of_vert = []
    for j in range(rows):
        shift = 0.5 * size[0] if j % 2 else 0.0
        for i in range(cols):
            for v in bmesh.ops.create_cube(bm, size=1.0)["verts"]:
                v.co.x = (v.co.x + 0.5 + i) * size[0] - cols * size[0] / 2 + shift
                v.co.y = v.co.y * size[1]
                v.co.z = (v.co.z + 0.5 + j) * size[2]
                brick_of_vert.append(i)
    me = bpy.data.meshes.new("Bricks")
    bm.to_mesh(me)
    bm.free()
    bricks = bpy.data.objects.new("Bricks", me)
    bpy.context.scene.collection.objects.link(bricks)
    # the vertex group that keeps both ends of the wall standing
    ends = bricks.vertex_groups.new(name="Stay")
    for v in me.vertices:
        i = brick_of_vert[v.index]
        ends.add([v.index], 1.0 if i < 2 or i >= cols - 2 else 0.0, "REPLACE")
    tree = network(bricks, "PIECES", (0.6, 0.3, 0.22))
    rules, solver = rbd(tree, "RBD Constraints From Rules"), rbd(tree, "RBD Bullet Solver")
    put(rules, {"Strength": 0.6, "Strength Variance": 0.5})
    configure = add(tree, "configure")
    insert(tree, configure, solver)
    put(configure, {"Set Active": True, "Active": False})
    # two selections joined by an ordinary Boolean Math node: painted, or standing on the ground
    either = tree.nodes.new("FunctionNodeBooleanMath")
    either.operation = "OR"
    tree.links.new(either.outputs[0], configure.inputs["Selection"])
    for k, values in enumerate(({"Type": "Attribute", "Attribute": "Stay"}, {"Type": "Below Height", "Height": 0.02})):
        node = add(tree, "select")
        put(node, values)
        tree.links.new(node.outputs["Selection"], either.inputs[k])
    put(solver, {"Start Asleep": True, "Collision Objects": collider_ball(0.5, (0, -8, 1.4), (0, 8, 1.4), (1, 22))})
    finish("06_brick_wall", bricks, (0, 0, 1.1), 10.0, stills=(1, 14, 26, 110))

# 7. the explosion again, in a wind: an initial velocity and Blender's own force fields at the same time
#    RBD Material Fracture -> RBD Configure (radial velocity) -> RBD Bullet Solver (Force Fields on) + a Wind and a Turbulence field
if want("07_explosion_wind"):
    start(96)
    crate = box("Block", (2.0, 2.0, 2.0), (0.0, 0.0, 1.0))
    tree = network(crate, "FRACTURE", (0.55, 0.5, 0.42))
    fracture, solver = rbd(tree, "RBD Material Fracture"), rbd(tree, "RBD Bullet Solver")
    put(fracture, {"Material Type": "Concrete", "Scatter Points": 160, "Impact Point": (0.0, 0.0, 0.7), "Impact Bias": 0.2,
                   "Impact Radius": 0.7, "Secondary Fracture": True, "Fracture Ratio": 0.2, "Detail": True, "Noise Amplitude": 0.015,
                   "Constraints": False, **inside(crate, (0.3, 0.24, 0.2))})
    configure = add(tree, "configure")
    insert(tree, configure, solver)
    put(configure, {"Set Initial Velocity": True, "Velocity Type": "Radial", "Origin": (0.0, 0.0, 0.7), "Speed": 7.0, "Up Bias": 0.35})
    # Blender's rigid bodies feel a field of strength 1 as 1/24 newton at 24 fps: pieces of a few kilograms need hundreds
    bpy.ops.object.effector_add(type="WIND", location=(-4.0, 0.0, 2.0), rotation=(0.0, math.radians(90.0), 0.0))    # blows along +X
    bpy.context.object.field.strength = 300.0
    bpy.ops.object.effector_add(type="TURBULENCE", location=(0.0, 0.0, 2.0))
    bpy.context.object.field.strength, bpy.context.object.field.size = 250.0, 1.5
    put(solver, {"Force Fields": True, "Field Weight": 1.0})
    finish("07_explosion_wind", crate, (4.0, 0, 1.4), 24.0, stills=(1, 8, 24, 60))

print("EXAMPLES DONE", flush=True)
