"""Awkward real-world meshes and transforms through the whole workflow, driven like a user (operators
and panel settings): several islands, text, thin shells, holes, open sheets, non-manifold meshes,
non-uniform / negative scale, parents, modifiers above the fracture, tiny, huge and far-away objects.

    blender --background --factory-startup --python-exit-code 1 --python Tests/test_stress.py -- <out_dir> [case ...]
"""
import json
import math
import os
import sys
import time
import traceback

import bmesh
import bpy
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as T  # noqa: E402
import Extension  # noqa: E402
from Extension import core, nodes_rbd, sim, export  # noqa: E402

args = sys.argv[sys.argv.index("--") + 1:]
OUT = args[0]
ONLY = set(args[1:])
os.makedirs(OUT, exist_ok=True)
Extension.register()


def link(ob):
    bpy.context.scene.collection.objects.link(ob)
    return ob


def mesh_object(name, fn):
    return link(bpy.data.objects.new(name, T.mesh_from_bmesh(name, fn)))


def two_islands():
    def f(bm):
        bmesh.ops.create_cube(bm, size=1.0)
        r = bmesh.ops.create_cube(bm, size=0.6)
        bmesh.ops.translate(bm, vec=(1.5, 0.2, 0.0), verts=r["verts"])
    return mesh_object("TwoIslands", f)


def text_mesh():
    cu = bpy.data.curves.new("Txt", "FONT")
    cu.body = "RBD"
    cu.extrude = 0.15
    tmp = link(bpy.data.objects.new("TxtCurve", cu))
    bpy.context.view_layer.update()
    dg = bpy.context.evaluated_depsgraph_get()
    me = bpy.data.meshes.new_from_object(tmp.evaluated_get(dg))
    bpy.data.objects.remove(tmp)
    ob = link(bpy.data.objects.new("Text", me))
    ob.rotation_euler = (math.radians(90), 0.0, 0.0)
    return ob


def bowl():
    def f(bm):
        bmesh.ops.create_uvsphere(bm, u_segments=24, v_segments=12, radius=1.0)
        bmesh.ops.delete(bm, geom=[v for v in bm.verts if v.co.z > 0.05], context="VERTS")
    ob = mesh_object("Bowl", f)
    ob.modifiers.new("Solidify", "SOLIDIFY").thickness = 0.12
    return ob


def holed_cube():
    ob = mesh_object("Holed", lambda bm: bmesh.ops.create_cube(bm, size=2.0))
    cutter = mesh_object("Cutter", lambda bm: bmesh.ops.create_cone(bm, cap_ends=True, segments=16, radius1=0.5, radius2=0.5, depth=3.0))
    m = ob.modifiers.new("Hole", "BOOLEAN")
    m.object, m.operation = cutter, "DIFFERENCE"
    cutter.hide_viewport = cutter.hide_render = True
    return ob


def open_grid():
    return mesh_object("OpenGrid", lambda bm: bmesh.ops.create_grid(bm, x_segments=8, y_segments=8, size=1.0))


def cube(name="Cube", size=1.0):
    return mesh_object(name, lambda bm: bmesh.ops.create_cube(bm, size=size))


def nonuniform():
    ob = cube("NonUniform")
    ob.scale, ob.rotation_euler, ob.location = (1.0, 3.0, 0.5), (0.3, 0.2, 0.7), (1.0, 2.0, 1.5)
    return ob


def parented():
    parent = link(bpy.data.objects.new("Parent", None))
    parent.location, parent.rotation_euler, parent.scale = (2.0, -1.0, 1.0), (0.0, 0.5, 0.3), (1.5, 1.5, 1.5)
    ob = cube("Child")
    ob.parent = parent
    ob.location = (0.5, 0.0, 0.5)
    return ob


def mirrored():
    ob = cube("Mirrored")
    ob.scale = (-1.0, 1.0, 1.0)
    ob.location = (0.0, 0.0, 1.0)
    return ob


def subdivided():
    ob = cube("Subdivided", 2.0)
    ob.modifiers.new("Subsurf", "SUBSURF").levels = 2
    return ob


def plank():
    def f(bm):
        bmesh.ops.create_cube(bm, size=1.0)
        bmesh.ops.scale(bm, vec=(3.0, 0.3, 0.08), verts=bm.verts)
    return mesh_object("Plank", f)


def doubles():
    def f(bm):
        bmesh.ops.create_cube(bm, size=1.0)
        bm.faces.ensure_lookup_table()
        vs = bm.faces[0].verts[:]
        mid = bm.verts.new(sum((v.co for v in vs), vs[0].co * 0) / len(vs))   # a loose-ish interior face fan
        bm.faces.new((vs[0], vs[1], mid))
    return mesh_object("Doubles", f)


def tiny():
    ob = cube("Tiny", 0.02)
    ob.location = (0.0, 0.0, 0.01)
    return ob


def huge():
    ob = cube("Huge", 200.0)
    ob.location = (0.0, 0.0, 100.0)
    return ob


def far():
    ob = cube("Far", 2.0)
    ob.location = (5000.0, -3000.0, 1.0)
    return ob


def many_materials():
    def f(bm):
        bm.loops.layers.uv.new("UVMap")
        bm.loops.layers.uv.new("Lightmap")
        bmesh.ops.create_cube(bm, size=2.0, calc_uvs=True)
    ob = mesh_object("ManyMats", f)
    for i in range(3):
        ob.data.materials.append(bpy.data.materials.new(f"M{i}"))
    for i, p in enumerate(ob.data.polygons):
        p.material_index = i % 3
    ob.data.color_attributes.new("Paint", "BYTE_COLOR", "CORNER")
    ob.data.shape_keys  # noqa: B018  (no shape keys: just a mesh with several UV maps, materials, a paint layer)
    return ob


# closed: the mesh handed to the fracture is a closed volume, so volume must be conserved and no piece may be bad
CASES = {
    "two_islands": dict(make=two_islands, preset="CONCRETE", closed=True),
    # text: the font mesh is not welded (flagged), but it encloses a volume and the automatic exact fallback cuts it
    "text": dict(make=text_mesh, preset="CONCRETE", closed=True, flagged=True),
    "bowl_shell": dict(make=bowl, preset="CONCRETE", closed=True),
    "holed_cube": dict(make=holed_cube, preset="CONCRETE", closed=True),
    "open_grid": dict(make=open_grid, preset="GROUND", closed=False, flagged=True),   # no volume at all: must warn, must not crash
    "nonuniform_scale": dict(make=nonuniform, preset="CONCRETE", closed=True),
    "parented": dict(make=parented, preset="CONCRETE", closed=True),
    "mirrored": dict(make=mirrored, preset="CONCRETE", closed=True),
    "subdivided": dict(make=subdivided, preset="CONCRETE", closed=True),
    "plank_wood": dict(make=plank, preset="WOOD", closed=True),
    "non_manifold": dict(make=doubles, preset="CONCRETE", closed=False, flagged=True),
    "tiny_2cm": dict(make=tiny, preset="CONCRETE", closed=True, sink=0.15),            # Bullet is not accurate at centimetre scale
    "huge_200m": dict(make=huge, preset="CONCRETE", closed=True),
    "far_5km": dict(make=far, preset="CONCRETE", closed=True, playback=2e-4),          # float32 at 5 km
    "many_uv_materials": dict(make=many_materials, preset="CONCRETE", closed=True),
}

REP = T.Report("test_stress", OUT, "STRESS")
for name, case in CASES.items():
    if ONLY and name not in ONLY:
        continue
    c = REP.case(name)
    try:
        bpy.ops.wm.read_factory_settings(use_empty=True)
        scene = bpy.context.scene
        scene.frame_start, scene.frame_end = 1, 40
        ob = case["make"]()
        bpy.context.view_layer.objects.active = ob
        for o in bpy.context.view_layer.objects:
            o.select_set(o == ob)
        bpy.context.view_layer.update()
        base = core.EvalMesh(ob)
        size = float(np.linalg.norm(base.co.max(0) - base.co.min(0)))
        scene.cursor.location = tuple(base.co.mean(0))
        t = time.perf_counter()
        c.check("setup", bpy.ops.hrbd.setup() == {"FINISHED"})
        mod = ob.modifiers[-1]
        tree = mod.node_group
        fracture = next(n for n in tree.nodes if n.name == "RBD Material Fracture")
        solver = next(n for n in tree.nodes if n.name == "RBD Bullet Solver")
        local = np.array(ob.matrix_world.inverted()) @ np.append(base.co.mean(0), 1.0)
        local_size = float(max(ob.dimensions) / max(max(abs(x) for x in ob.matrix_world.to_scale()), 1e-9))
        fracture.inputs["Impact Point"].default_value = tuple(local[:3])
        fracture.inputs["Impact Radius"].default_value = 0.3 * local_size
        fracture.inputs["Material Type"].default_value = "Wood" if case["preset"] == "WOOD" else "Concrete"
        fracture.inputs["Scatter Points"].default_value = {"CONCRETE": 50, "GROUND": 70, "WOOD": 40}[case["preset"]]
        fracture.inputs["Impact Bias"].default_value = {"CONCRETE": 0.3, "GROUND": 0.6, "WOOD": 0.0}[case["preset"]]
        fracture.inputs["Cut Through"].default_value = case["preset"] == "GROUND"
        bpy.context.view_layer.update()
        em = core.EvalMesh(ob)
        open_edges = int(ob.get("hrbd_open_edges", 0))
        c.set(size_m=round(size, 3), pieces=em.n_pieces, fracture_s=round(time.perf_counter() - t, 2), open_edges=open_edges)
        flagged = bool(case.get("flagged"))
        c.check("open_mesh_is_flagged" if flagged else "closed_mesh_is_not_flagged", (open_edges > 0) == flagged, open_edges)
        c.check("pieces_made", em.n_pieces >= 20, em.n_pieces)
        vols = em.piece_volumes(em.proxy_co)
        if case["closed"]:
            p = base.co.astype(np.float64) - base.co.mean(0)
            tri = p[base.tris]
            base_vol = float(np.einsum("ij,ij->i", tri[:, 0], np.cross(tri[:, 1], tri[:, 2])).sum() / 6.0)
            if np.linalg.det(base.matrix[:3, :3]) < 0:
                base_vol = -base_vol
            ratio = float(vols.sum() / base_vol)
            c.set(volume_ratio=round(ratio, 4))
            c.check("volume_conserved", abs(ratio - 1.0) < 2e-3, round(ratio, 5))
            c.check("no_bad_pieces", int((vols <= 0).sum()) == 0, int((vols <= 0).sum()))

        # an explosion from the middle: an RBD Configure node between the fracture and the solver
        configure = tree.nodes.new("GeometryNodeGroup")
        configure.node_tree = nodes_rbd.configure()
        for stream in ("Geometry", "Constraint Geometry", "Proxy Geometry"):
            tree.links.new(fracture.outputs[stream], configure.inputs[stream])
            tree.links.new(configure.outputs[stream], solver.inputs[stream])
        burst = max(2.0 * size, 0.5)
        fracture.inputs["Constraints"].default_value = False
        configure.inputs["Set Initial Velocity"].default_value = True
        configure.inputs["Origin"].default_value = tuple(local[:3])
        configure.inputs["Speed"].default_value = burst
        solver.inputs["Ground Height"].default_value = ground = float(base.co[:, 2].min())
        solver.inputs["End Frame"].default_value = 40
        t = time.perf_counter()
        c.check("bake", bpy.ops.hrbd.bake() == {"FINISHED"})
        c.set(bake_s=round(time.perf_counter() - t, 2))
        pos, quat, piv, start = sim.read_cache(ob)
        speed = np.linalg.norm(np.diff(pos, axis=0), axis=-1) * scene.render.fps
        c.check("finite", bool(np.isfinite(pos).all() and np.isfinite(quat).all()))
        c.check("no_runaway_speed", float(speed.max() / burst) < 3.0, round(float(speed.max() / burst), 2))
        c.check("first_frame_is_rest", float(np.abs(pos[0] - piv).max() / size) < 1e-5)
        sink = float((ground - pos[..., 2].min()) / size)
        c.set(sink_below_ground_rel=round(sink, 3))
        c.check("stays_on_the_ground", sink < case.get("sink", 0.02), round(sink, 3))
        rest = sim.rest_pieces(ob)[0]
        worst = 0.0
        for k in (0, 10, 39):
            scene.frame_set(start + k)
            want = pos[k][rest.piece] + T.qrot(quat[k][rest.piece], rest.co - piv[rest.piece])
            worst = max(worst, float(np.abs(core.EvalMesh(ob).co - want).max()))
        c.check("playback_matches_cache", worst / size < case.get("playback", 1e-5), float(f"{worst / size:.2e}"))
        for op, ext in (("export_fbx", ".fbx"), ("export_vat", ".json"), ("export_alembic", ".abc")):
            path = os.path.join(OUT, f"stress_{name}{ext}")
            c.check(op, getattr(bpy.ops.hrbd, op)(filepath=path) == {"FINISHED"} and os.path.getsize(path) > 300)
        with open(os.path.join(OUT, f"stress_{name}.json"), encoding="utf-8") as fh:
            c.check("vat_lookup_is_second_uv", json.load(fh)["lookup_uv_index"] == 1)
        c.check("free", bpy.ops.hrbd.free_bake() == {"FINISHED"} and not [o for o in bpy.data.objects if o.name.startswith("RBD ")])
    except Exception:
        c.error()
    c.done()

# ---- nothing to simulate: the bake must not be offered, or say plainly what is missing
c = REP.case("no_fracture")
try:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    ob = cube("Plain")
    bpy.context.view_layer.objects.active = ob
    ob.select_set(True)
    c.check("no_network_no_bake_button", not bpy.ops.hrbd.bake.poll())
    # a solver node with nothing but the plain mesh wired into it
    bpy.ops.hrbd.setup()
    tree = ob.modifiers[-1].node_group
    fracture = next(n for n in tree.nodes if n.name == "RBD Material Fracture")
    solver = next(n for n in tree.nodes if n.name == "RBD Bullet Solver")
    gin = next(n for n in tree.nodes if n.bl_idname == "NodeGroupInput")
    tree.nodes.remove(fracture)
    tree.links.new(gin.outputs[0], solver.inputs["Geometry"])
    count = len(bpy.data.objects)
    try:
        bpy.ops.hrbd.bake()
        msg = ""
    except RuntimeError as e:
        msg = str(e)
    c.check("says_what_is_missing", "No pieces arrive at the RBD Bullet Solver node" in msg, msg.strip()[:160])
    c.check("nothing_left_behind", len(bpy.data.objects) == count and not solver.inputs["Baked"].default_value)
except Exception:
    c.error()
c.done()
REP.finish()
