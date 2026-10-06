"""Headless checks of the RBD Fracture node group, with hard pass/fail thresholds.

Run: blender --background --factory-startup --python-exit-code 1 --python Tests/test_fracture.py -- <out_dir> [case ...]
"""
import os
import sys
import time

import bmesh
import bpy
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as T  # noqa: E402
from Extension import core, nodes_fracture  # noqa: E402

args = sys.argv[sys.argv.index("--") + 1:]
OUT = args[0]
ONLY = set(args[1:])
REP = T.Report("test_fracture", OUT, "FRACTURE")


def shape(kind):
    if kind == "cube":
        return T.box(kind, (2.0, 2.0, 2.0))
    if kind == "sphere":
        return T.icosphere(kind, 1.0)
    if kind == "slab":
        return T.box(kind, (4.0, 4.0, 0.2))
    if kind == "pane":
        return T.box(kind, (3.0, 0.05, 2.0))
    if kind == "pillar":
        return T.box(kind, (0.5, 0.5, 3.0))
    if kind == "torus":
        return T.torus(kind)
    if kind == "monkey":
        return T.mesh_from_bmesh(kind, lambda bm: bmesh.ops.create_monkey(bm))
    if kind == "cube_uv":
        def f(bm):
            bm.loops.layers.uv.new("UVMap")
            bmesh.ops.create_cube(bm, size=2.0, calc_uvs=True)
        return T.mesh_from_bmesh(kind, f)
    raise ValueError(kind)


def source_volume(me):
    bm = bmesh.new()
    bm.from_mesh(me)
    v = bm.calc_volume(signed=True)
    bm.free()
    return v


def volumes_of(co, em):
    """Per-piece signed volume using the given vertex positions (float64, local reference)."""
    p = co.astype(np.float64) - co.mean(0)
    a, b, c = p[em.tris[:, 0]], p[em.tris[:, 1]], p[em.tris[:, 2]]
    signed = np.einsum("ij,ij->i", a, np.cross(b, c)) / 6.0
    return np.bincount(em.piece[em.tris[:, 0]], weights=signed, minlength=em.n_pieces)


# closed: the source is watertight, so every piece must be too (when no interior detail is added)
CASES = {
    "cube30": dict(shape="cube", inputs={"Pieces": 30}, closed=True, min_pieces=30),
    "sphere50": dict(shape="sphere", inputs={"Pieces": 50, "Seed": 3}, closed=True, min_pieces=50),
    "torus40": dict(shape="torus", inputs={"Pieces": 40, "Seed": 1}, closed=True, min_pieces=40),
    "slab_flat_impact": dict(shape="slab", inputs={"Pieces": 60, "Flat": True, "Impact Bias": 0.6,
                                                    "Impact Point": (0.5, 0.3, 0.0), "Impact Radius": 1.2},
                             closed=True, min_pieces=60),
    "pillar_wood": dict(shape="pillar", inputs={"Pieces": 40, "Cell Stretch": (1.0, 1.0, 8.0), "Seed": 5},
                        closed=True, min_pieces=40),
    "pane_radial": dict(shape="pane", inputs={"Pieces": 90, "Flat": True, "Radial Cracks": True, "Rings": 5,
                                               "Spokes": 12, "Impact Point": (0.3, 0.0, 0.2), "Impact Radius": 1.0},
                        closed=True, min_pieces=60),
    # impact point at the very corner with a radius larger than the pane: most ring seeds fall outside
    "pane_radial_corner": dict(shape="pane", inputs={"Pieces": 60, "Flat": True, "Radial Cracks": True, "Rings": 6,
                                                      "Spokes": 16, "Impact Point": (1.45, 0.0, 0.95), "Impact Radius": 2.5},
                               closed=True, min_pieces=20),
    "cube_impact_outside": dict(shape="cube", inputs={"Pieces": 40, "Impact Bias": 0.9, "Impact Point": (3.0, 0.0, 0.0),
                                                       "Impact Radius": 2.5}, closed=True, min_pieces=30),
    "cube_secondary": dict(shape="cube", inputs={"Pieces": 30, "Secondary Ratio": 0.5, "Secondary Pieces": 4, "Seed": 2},
                           closed=True, min_pieces=60, size_ratio=30.0),
    "slab_secondary_flat": dict(shape="slab", inputs={"Pieces": 40, "Flat": True, "Secondary Ratio": 0.4, "Secondary Pieces": 3},
                                closed=True, min_pieces=60),
    # degenerate seed sets. Duplicate cells would show up as a volume ratio above 1 (pieces on top of each other)
    "cube_single_seed": dict(shape="cube", inputs={"Pieces": 1, "Secondary Ratio": 1.0, "Secondary Pieces": 6},
                             closed=True, min_pieces=1),
    "cube_two_seeds": dict(shape="cube", inputs={"Pieces": 2, "Secondary Ratio": 1.0, "Secondary Pieces": 3},
                           closed=True, min_pieces=2),
    "cube_detail": dict(shape="cube", inputs={"Pieces": 30, "Detail Level": 2, "Noise Height": 0.03,
                                               "Noise Scale": 3.0, "Edge Fade": 0.08}, closed=False, min_pieces=30,
                        detail=0.03),
    "cube_uv": dict(shape="cube_uv", inputs={"Pieces": 20, "Inner UV Scale": 0.5}, closed=True, min_pieces=20, uv=0.5),
    "cube_far": dict(shape="cube", inputs={"Pieces": 30}, closed=True, min_pieces=30, location=(10000.0, 10000.0, 10000.0)),
    "monkey_robust": dict(shape="monkey", inputs={"Pieces": 25, "Robust Boolean": True}, closed=None, min_pieces=20),
    "cube500": dict(shape="cube", inputs={"Pieces": 500}, closed=True, min_pieces=500, max_seconds=5.0),
}

for name, case in CASES.items():
    if ONLY and name not in ONLY:
        continue
    c = REP.case(name)
    try:
        bpy.ops.wm.read_factory_settings(use_empty=True)
        me = shape(case["shape"])
        ob = T.add_object(name, me, location=case.get("location", (0.0, 0.0, 0.0)))
        mod = ob.modifiers.new(core.MOD_FRACTURE, "NODES")
        mod.node_group = nodes_fracture.ensure()
        for k, v in case["inputs"].items():
            core.set_input(mod, k, v)
        t = time.perf_counter()
        bpy.context.view_layer.update()
        em = core.EvalMesh(ob)
        seconds = time.perf_counter() - t
        src_vol = source_volume(me)
        vols = em.piece_volumes()
        proxy_vols = volumes_of(em.proxy_co, em)
        c.set(pieces=em.n_pieces, verts=len(em.co), eval_s=round(seconds, 3),
              inside_faces=int(em.inside.sum()), outside_faces=int((~em.inside).sum()))
        c.check("no_node_warnings", len(mod.node_warnings) == 0, [w.message for w in mod.node_warnings][:3])
        c.check("piece_count", em.n_pieces >= case["min_pieces"], em.n_pieces)
        if "max_pieces" in case:
            c.check("no_duplicate_pieces", em.n_pieces <= case["max_pieces"], em.n_pieces)
        c.check("has_cut_faces", em.inside.sum() > 0 and (~em.inside).sum() > 0)
        if case["closed"] is not None:
            # the flat (pre-detail) pieces must add up to exactly the source volume
            c.check("volume_conserved", abs(proxy_vols.sum() / src_vol - 1.0) < 1e-3, round(float(proxy_vols.sum() / src_vol), 6))
            c.check("no_inverted_pieces", (proxy_vols > 0).all(), int((proxy_vols <= 0).sum()))
        if case["closed"]:
            c.check("watertight", em.open_edges() == 0, em.open_edges())
            c.check("world_volume_stable", abs(vols.sum() / src_vol - 1.0) < 1e-3, round(float(vols.sum() / src_vol), 6))
        c.check("pivot_attribute", em.pivot_attr is not None
                and float(np.abs(em.pivot_attr - em.vertex_means()[em.piece]).max()) < 1e-3 * (1 + np.abs(em.co).max()))
        if "size_ratio" in case:
            # broken-up cells make pieces much smaller than their unbroken neighbours
            ratio = float(proxy_vols.max() / proxy_vols.min())
            c.set(largest_to_smallest_piece=round(ratio, 1))
            c.check("secondary_adds_size_variation", ratio > case["size_ratio"], round(ratio, 1))
        if "detail" in case:
            moved = np.linalg.norm(em.co - em.proxy_co, axis=1)
            c.set(detail_max_offset=round(float(moved.max()), 4), detail_moved_share=round(float((moved > 1e-5).mean()), 3))
            c.check("detail_moves_cut_faces", moved.max() > 0.2 * case["detail"])
            c.check("detail_bounded", moved.max() <= 2.0 * case["detail"] * 1.01, round(float(moved.max()), 4))
            # vertices on the original surface must stay exactly there, or the outside would open up
            from mathutils import bvhtree
            bvh = bvhtree.BVHTree.FromPolygons([tuple(v.co) for v in me.vertices], [tuple(p.vertices) for p in me.polygons])
            on_surface = np.array([bvh.find_nearest(tuple(p))[3] < 1e-5 for p in em.proxy_co])
            c.check("surface_vertices_fixed", float(moved[on_surface].max()) < 1e-5, round(float(moved[on_surface].max()), 6))
            c.check("detail_keeps_volume", abs(vols.sum() / src_vol - 1.0) < 0.02, round(float(vols.sum() / src_vol), 4))
        if "uv" in case:
            dg = bpy.context.evaluated_depsgraph_get()
            m = ob.evaluated_get(dg).to_mesh()
            uv = np.empty(len(m.loops) * 2, np.float32)
            m.uv_layers["UVMap"].uv.foreach_get("vector", uv)
            uv = uv.reshape(-1, 2)
            face_of_loop = np.repeat(np.arange(len(em.loop_total)), em.loop_total)
            ins = em.inside[face_of_loop]
            ob.evaluated_get(dg).to_mesh_clear()
            c.check("outside_uv_kept", uv[~ins].min() >= -1e-4 and uv[~ins].max() <= 1.0001 and np.ptp(uv[~ins]) > 0.5)
            # box projection of a 2 m cube scaled by 0.5 -> cut-face UVs spread over about 2 * 0.5 = 1 unit
            spread = float(np.ptp(uv[ins], axis=0).max())
            c.check("inside_uv_projected", 0.5 < spread <= 1.05, round(spread, 3))
        if "max_seconds" in case:
            c.check("fast_enough", seconds < case["max_seconds"], round(seconds, 3))
        core.set_input(mod, "Exploded View", 0.35)
        T.add_piece_colors(ob)
        cam = T.setup_render((960, 720))
        bpy.context.view_layer.update()
        ex = core.EvalMesh(ob)
        lo, hi = ex.co.min(0), ex.co.max(0)
        T.aim_camera(cam, (lo + hi) / 2, distance=float(np.linalg.norm(hi - lo)) * 1.15)
        T.render_still(os.path.join(OUT, f"fracture_{name}.png"))
    except Exception:
        c.error()
    c.done()

# ---- shading: the pieces at rest must look like the model they were cut from
if not ONLY or "shading_normals" in ONLY:
    c = REP.case("shading_normals")
    try:
        def corner_data(ob_):
            dg = bpy.context.evaluated_depsgraph_get()
            m = ob_.evaluated_get(dg).to_mesh()
            n_loops = len(m.loops)
            nor = np.empty(n_loops * 3, np.float32)
            m.corner_normals.foreach_get("vector", nor)
            lv = np.empty(n_loops, np.int32)
            m.loops.foreach_get("vertex_index", lv)
            co = np.empty(len(m.vertices) * 3, np.float32)
            m.vertices.foreach_get("co", co)
            inside = np.zeros(len(m.polygons), bool)
            m.attributes["inside"].data.foreach_get("value", inside)
            tot = np.empty(len(m.polygons), np.int32)
            m.polygons.foreach_get("loop_total", tot)
            fn = np.empty(len(m.polygons) * 3, np.float32)
            m.polygons.foreach_get("normal", fn)
            piece = np.zeros(len(m.vertices), np.int32)
            m.attributes["piece_id"].data.foreach_get("value", piece)
            ob_.evaluated_get(dg).to_mesh_clear()
            return (nor.reshape(-1, 3), co.reshape(-1, 3)[lv], np.repeat(inside, tot), np.repeat(fn.reshape(-1, 3), tot, axis=0),
                    piece[lv])

        def angle(a, b_):
            return np.degrees(np.arccos(np.clip(np.sum(a * b_, axis=1), -1.0, 1.0)))

        # a smooth ball: the shading normal of the unbroken ball points away from the centre
        bpy.ops.wm.read_factory_settings(use_empty=True)
        me = T.icosphere("Ball", 1.0, 3)
        for p in me.polygons:
            p.use_smooth = True
        ball = T.add_object("Ball", me)
        mod = T.add_fracture(ball, Pieces=30, Seed=1)
        bpy.context.view_layer.update()
        nor, pos, inside, face_n, piece = corner_data(ball)
        on_vertex = np.abs(np.linalg.norm(pos, axis=1) - 1.0) < 1e-3          # corners at vertices of the ball itself
        outer = ~inside
        radial = pos / np.linalg.norm(pos, axis=1, keepdims=True)
        off = angle(nor, radial)
        c.set(ball_outer_corners=int(outer.sum()), ball_max_deg=round(float(off[outer].max()), 2),
              ball_at_vertices_max_deg=round(float(off[outer & on_vertex].max()), 2))
        c.check("no_node_warnings", len(mod.node_warnings) == 0, [w.message for w in mod.node_warnings][:3])
        # (without this the corners along the cuts were up to 10 degrees off: seams between the pieces)
        c.check("smooth_model_keeps_its_normals", float(off[outer & on_vertex].max()) < 1.5 and float(off[outer].max()) < 4.0,
                [round(float(off[outer & on_vertex].max()), 2), round(float(off[outer].max()), 2)])
        c.check("cut_faces_are_flat", float(angle(nor[inside], face_n[inside]).max()) < 0.5, round(float(angle(nor[inside], face_n[inside]).max()), 3))

        # a box: every corner keeps the normal of its own side, also right on the hard edges
        bpy.ops.wm.read_factory_settings(use_empty=True)
        cube = T.add_object("Cube", T.box("Cube", (2.0, 2.0, 2.0)))
        T.add_fracture(cube, Pieces=30, Seed=1)
        bpy.context.view_layer.update()
        nor, pos, inside, face_n, piece = corner_data(cube)
        c.check("hard_edges_stay_hard", float(angle(nor[~inside], face_n[~inside]).max()) < 0.5,
                round(float(angle(nor[~inside], face_n[~inside]).max()), 3))
        c.check("cube_cut_faces_are_flat", float(angle(nor[inside], face_n[inside]).max()) < 0.5)

        # the normals turn with the pieces: after a bake, a piece's normals are its rest normals rotated with it
        from Extension import sim
        bpy.ops.wm.read_factory_settings(use_empty=True)
        scene = bpy.context.scene
        scene.frame_start, scene.frame_end = 1, 30
        me = T.icosphere("Ball", 1.0, 3)
        for p in me.polygons:
            p.use_smooth = True
        ball = T.add_object("Ball", me, location=(0.0, 0.0, 2.0))
        T.add_fracture(ball, Pieces=20, Seed=2)
        bpy.context.view_layer.update()
        rest_nor, _, _, _, rest_piece = corner_data(ball)
        sim.bake(bpy.context, ball, sim.SimSettings(frame_end=30, start_asleep=False, use_glue=False, burst_speed=5.0,
                                                    burst_origin=(0.0, 0.0, 1.5), burst_spin=6.0))
        _, quat, _, start = sim.read_cache(ball)
        scene.frame_set(start + 20)
        nor, _, _, _, piece = corner_data(ball)
        turned = T.qrot(quat[20][rest_piece], rest_nor)
        spin = np.degrees(2 * np.arccos(np.clip(np.abs(quat[20][:, 0]), 0, 1)))
        c.set(piece_rotation_deg=[round(float(spin.min()), 1), round(float(spin.max()), 1)],
              normal_follow_error_deg=round(float(angle(nor, turned).max()), 3))
        c.check("normals_turn_with_the_pieces", np.array_equal(piece, rest_piece) and float(spin.max()) > 30.0
                and float(angle(nor, turned).max()) < 1.0, round(float(angle(nor, turned).max()), 3))
    except Exception:
        c.error()
    c.done()

# ---- a user's own node group with the same name must never be touched
if not ONLY or "user_group_untouched" in ONLY:
    c = REP.case("user_group_untouched")
    try:
        bpy.ops.wm.read_factory_settings(use_empty=True)
        mine = bpy.data.node_groups.new(nodes_fracture.GROUP, "GeometryNodeTree")
        mine.nodes.new("GeometryNodeMeshCube")
        ours = nodes_fracture.ensure()
        c.check("separate_group", ours != mine)
        c.check("user_nodes_kept", len(mine.nodes) == 1, len(mine.nodes))
        c.check("ours_marked", ours.get(core.KIND_PROP) == core.KIND_FRACTURE)
        c.check("ensure_is_stable", nodes_fracture.ensure() == ours)
        # a version upgrade rebuilds our group in place and keeps the values set on modifiers
        ob = T.add_object("Cube", T.box("Cube", (2.0, 2.0, 2.0)))
        mod = ob.modifiers.new(core.MOD_FRACTURE, "NODES")
        mod.node_group = ours
        core.set_input(mod, "Pieces", 77)
        core.set_input(mod, "Cell Stretch", (1.0, 2.0, 3.0))
        ours[core.VERSION_PROP] = -1
        rebuilt = nodes_fracture.ensure()
        c.check("rebuilt_in_place", rebuilt == ours and mod.node_group == ours)
        # a build that dies half way must not be mistaken for a finished group
        from Extension import nodekit
        half = nodekit.Builder("Half Built", "selftest", 7)
        half.input("Geometry", "geo")
        c.check("half_built_is_not_current", nodekit.find_group("selftest").get(core.VERSION_PROP) != 7)
        built = []

        def build_selftest():
            b2 = nodekit.Builder("Half Built", "selftest", 7)
            b2.output("Geometry", "geo", b2.input("Geometry", "geo"))
            built.append(1)
            return b2.finish()
        g = nodekit.ensure_group("selftest", 7, build_selftest)
        c.check("half_built_is_rebuilt", built == [1] and g.get(core.VERSION_PROP) == 7 and nodekit.ensure_group("selftest", 7, build_selftest) == g
                and built == [1])
        c.check("values_survive_upgrade", core.get_input(mod, "Pieces") == 77
                and tuple(round(x, 3) for x in core.get_input(mod, "Cell Stretch")) == (1.0, 2.0, 3.0),
                [core.get_input(mod, "Pieces"), list(core.get_input(mod, "Cell Stretch"))])
    except Exception:
        c.error()
    c.done()

REP.finish()
