"""Headless checks of the three exports: each file is read back and compared with the baked motion.

What this proves: the files are self-consistent inside Blender. What it cannot prove: how Unity
or Unreal import them (axis handling, texture import settings, the HLSL compiling).
Run: blender --background --factory-startup --python-exit-code 1 --python Tests/test_export.py -- <out_dir>
"""
import json
import os
import sys
import time

import bpy
import numpy as np
from mathutils import Vector, kdtree

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as T  # noqa: E402
from Extension import core, export, sim  # noqa: E402

OUT = sys.argv[sys.argv.index("--") + 1]
REP = T.Report("test_export", OUT, "EXPORT")

bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
scene.frame_start, scene.frame_end = 1, 60
# moved, rotated and scaled on purpose, to catch any local / world mix-up
ob = T.add_object("Crate", T.box("Crate", (2.0, 1.5, 1.0), (0.0, 0.0, 0.0)), location=(1.0, -2.0, 1.2))
ob.rotation_euler = (0.2, 0.1, 0.6)
ob.scale = (1.2, 1.2, 1.2)
ob.data.uv_layers.new(name="UVMap")
ob.data.materials.append(bpy.data.materials.new("CrateOuter"))
frac_mod = T.add_fracture(ob, Pieces=80, Seed=11, Detail_Level=1, Noise_Height=0.02)
core.set_input(frac_mod, "Inner Material", bpy.data.materials.new("CrateInner"))
core.set_input(frac_mod, "Use Inner Material", True)
st = sim.SimSettings(frame_end=60, start_asleep=False, use_glue=False, burst_speed=6.0,
                     burst_origin=(1.0, -2.0, 0.8), burst_up=0.4)
res = sim.bake(bpy.context, ob, st)
pos, quat, piv, start = sim.read_cache(ob)
F, N = pos.shape[:2]
rest, _ = sim.rest_pieces(ob)
FRAMES = (0, 7, F // 3, F - 1)
TOL = 1e-4


def expected(k):
    return pos[k][rest.piece] + T.qrot(quat[k][rest.piece], rest.co - piv[rest.piece])


def new_objects(before, kind):
    return [o for o in bpy.data.objects if o not in before and o.type == kind]


def two_way_error(got, want):
    """Largest nearest-neighbour distance in both directions: nothing extra, nothing missing."""
    def one_way(a, b):
        kd = kdtree.KDTree(len(b))
        for i, p in enumerate(b):
            kd.insert(p, i)
        kd.balance()
        return max(kd.find(p)[2] for p in a)
    return max(one_way(got, want), one_way(want, got))


c = REP.case("bake")
c.set(pieces=N, frames=F, verts=len(rest.co), seconds=round(res.seconds, 2))
c.check("pieces_moved", res.moved == N, res.moved)
worst = 0.0
for k in FRAMES:
    scene.frame_set(start + k)
    worst = max(worst, float(np.abs(core.EvalMesh(ob).co - expected(k)).max()))
c.check("playback_matches_cache", worst < TOL, round(worst, 6))
c.done()

# ---------------------------------------------------------------- Alembic
c = REP.case("alembic")
try:
    path = os.path.join(OUT, "export_crate.abc")
    counts = T.datablock_counts()
    t = time.perf_counter()
    export.export_alembic(bpy.context, ob, path)
    c.set(seconds=round(time.perf_counter() - t, 2), size_mb=round(os.path.getsize(path) / 1e6, 2))
    c.check("export_leaves_nothing", T.datablock_counts() == counts)
    before = set(bpy.data.objects)
    bpy.ops.wm.alembic_import(filepath=path, set_frame_range=False, as_background_job=False)
    imp = new_objects(before, "MESH")[0]
    c.check("vertex_count", len(imp.data.vertices) == len(rest.co), len(imp.data.vertices))
    worst = 0.0
    for k in FRAMES:
        scene.frame_set(start + k)
        worst = max(worst, two_way_error(core.EvalMesh(imp).co, expected(k)))
    c.check("reimport_matches", worst < TOL, round(worst, 6))
    bpy.data.batch_remove([o for o in bpy.data.objects if o not in before])
except Exception:
    c.error()
c.done()

# ---------------------------------------------------------------- FBX with bones
c = REP.case("fbx")
try:
    path = os.path.join(OUT, "export_crate.fbx")
    counts = T.datablock_counts()
    def selection():
        bpy.context.view_layer.update()
        return [o.name for o in bpy.context.view_layer.objects if o is not None and o.select_get()]
    sel = selection()
    rng = (scene.frame_start, scene.frame_end)
    t = time.perf_counter()
    info = export.export_fbx(bpy.context, ob, path)
    c.set(seconds=round(time.perf_counter() - t, 2), size_mb=round(os.path.getsize(path) / 1e6, 2), bones=info["bones"])
    c.check("export_leaves_nothing", T.datablock_counts() == counts,
            {k: v - counts[k] for k, v in T.datablock_counts().items() if v != counts[k]})
    c.check("selection_and_range_restored", sel == selection() and rng == (scene.frame_start, scene.frame_end))
    before = set(bpy.data.objects)
    # Blender's importer shifts animation by `anim_offset` (default 1 frame); 0 keeps our frame numbers
    bpy.ops.import_scene.fbx(filepath=path, anim_offset=0.0, colors_type="LINEAR")  # read vertex colours as raw numbers
    mesh = new_objects(before, "MESH")[0]
    arm = new_objects(before, "ARMATURE")[0]
    c.check("bone_count", len(arm.data.bones) == N + 1, len(arm.data.bones))
    groups = np.array([len(v.groups) for v in mesh.data.vertices])
    c.check("one_bone_per_vertex", bool((groups == 1).all()), [int(groups.min()), int(groups.max())])
    c.check("uv_map_kept", [u.name for u in mesh.data.uv_layers] == ["UVMap"], [u.name for u in mesh.data.uv_layers])
    c.check("materials_kept", sorted(m.name.split(".")[0] for m in mesh.data.materials if m) == ["CrateInner", "CrateOuter"],
            [m.name if m else None for m in mesh.data.materials])
    used = np.zeros(len(mesh.data.polygons), np.int32)
    mesh.data.polygons.foreach_get("material_index", used)
    c.check("both_materials_used", len(set(used.tolist())) == 2, sorted(set(used.tolist())))
    # the shader data colour: constant per piece in RGB, alpha = cut-face mask, values raw (not sRGB-converted)
    col = mesh.data.color_attributes.get("RBD")
    c.check("shader_color_present", col is not None)
    rgba = np.empty(len(mesh.data.loops) * 4, np.float32)
    col.data.foreach_get("color", rgba)
    rgba = rgba.reshape(-1, 4)
    want = export.piece_shader_data(pos, quat, piv, 24.0, [1.0, -2.0, 0.8])
    # B is worked out here independently: distance of each rest pivot from the burst origin, over the largest
    dist = np.linalg.norm(piv - np.array([1.0, -2.0, 0.8], np.float32), axis=1)
    c.check("distance_channel_is_what_it_says", float(np.abs(want[:, 2] - dist / dist.max()).max()) < 1e-5)
    lv = np.empty(len(mesh.data.loops), np.int32)
    mesh.data.loops.foreach_get("vertex_index", lv)
    grp = np.array([v.groups[0].group for v in mesh.data.vertices])
    names = [g.name for g in mesh.vertex_groups]
    piece_of_vert = np.array([int(names[g].split("_")[1]) for g in grp])
    err = float(np.abs(rgba[:, :3] - want[piece_of_vert[lv]]).max())
    c.check("shader_color_matches_bake", err < 2e-3, round(err, 5))
    c.check("shader_color_alpha_is_cut_mask", set(np.round(rgba[:, 3]).astype(int).tolist()) == {0, 1}
            and 0.05 < float(rgba[:, 3].mean()) < 0.999, round(float(rgba[:, 3].mean()), 3))
    # start-of-motion on made-up motion with a known answer: piece 0 never moves, piece 1 slides from
    # frame 3 on, piece 2 only spins (in place) from frame 5 on
    fake_pos = np.zeros((11, 3, 3), np.float32)
    fake_pos[3:, 1, 0] = np.arange(8) * 0.1
    fake_quat = np.zeros((11, 3, 4), np.float32)
    fake_quat[..., 0] = 1.0
    ang = np.clip(np.arange(11) - 4, 0, None) * 0.2
    fake_quat[:, 2, 0], fake_quat[:, 2, 3] = np.cos(ang / 2), np.sin(ang / 2)
    got = export.piece_shader_data(fake_pos, fake_quat, np.zeros((3, 3), np.float32) + [[0, 0, 0], [1, 0, 0], [3, 0, 0]], 24.0, [0, 0, 0])
    c.check("start_of_motion_known_answer", np.allclose(got[:, 1], [1.0, 0.4, 0.5], atol=1e-6), got[:, 1].round(3).tolist())
    c.check("distance_known_answer", np.allclose(got[:, 2], [0.0, 1 / 3, 1.0], atol=1e-6), got[:, 2].round(3).tolist())
    one = export.piece_shader_data(fake_pos[:1], fake_quat[:1], np.zeros((3, 3), np.float32), 24.0)
    c.check("single_frame_does_not_crash", one.shape == (3, 3) and np.allclose(one[:, 1], 1.0))
    worst = 0.0
    for k in FRAMES:
        scene.frame_set(start + k)
        worst = max(worst, two_way_error(core.EvalMesh(mesh).co, expected(k)))
    c.check("reimport_matches", worst < TOL, round(worst, 6))
    bpy.data.batch_remove([o for o in bpy.data.objects if o not in before])

    # the animation must keep its real duration when the scene frame rate was changed after the bake
    scene.render.fps = 30
    path30 = os.path.join(OUT, "export_crate_fps30.fbx")
    export.export_fbx(bpy.context, ob, path30)
    c.check("scene_fps_restored", scene.render.fps == 30 and abs(scene.render.fps_base - 1.0) < 1e-6)
    scene.render.fps = 24

    def fbx_seconds(p):
        """Length of the animation as written in the file (Blender's importer keeps frame numbers, so
        the file has to be read directly to see real time)."""
        from io_scene_fbx import parse_fbx
        root, _ = parse_fbx.parse(p)
        stop = None
        for el in root.elems:
            if el.id == b"Objects":
                for stack in el.elems:
                    if stack.id == b"AnimationStack":
                        for props in stack.elems:
                            for prop in props.elems:
                                if prop.props and prop.props[0] == b"LocalStop":
                                    stop = prop.props[4]
        return stop / 46186158000.0

    c.set(fbx_seconds_scene24=round(fbx_seconds(path), 4), fbx_seconds_scene30=round(fbx_seconds(path30), 4))
    c.check("fbx_keeps_baked_duration", abs(fbx_seconds(path30) - fbx_seconds(path)) < 1e-3
            and abs(fbx_seconds(path) - (start + F - 1) / 24.0) < 0.05, [fbx_seconds(path), fbx_seconds(path30)])

    # a failure half way through building the rig must not leave an armature behind
    counts = T.datablock_counts()
    real = export._world_rest_mesh

    def boom(*a, **k):
        raise RuntimeError("simulated failure")
    export._world_rest_mesh = boom
    try:
        export.export_fbx(bpy.context, ob, os.path.join(OUT, "never.fbx"))
    except RuntimeError:
        pass
    finally:
        export._world_rest_mesh = real
    c.check("failed_export_leaves_nothing", T.datablock_counts() == counts and bpy.context.mode == "OBJECT",
            {k: v - counts[k] for k, v in T.datablock_counts().items() if v != counts[k]})
except Exception:
    c.error()
c.done()

# ---------------------------------------------------------------- VAT
c = REP.case("vat")
try:
    counts = T.datablock_counts()
    info = export.export_vat(bpy.context, ob, OUT, "export_crate", "UNITY")
    c.check("export_leaves_nothing", T.datablock_counts() == counts)
    with open(info["json"], encoding="utf-8") as fh:
        meta = json.load(fh)
    w, h = meta["width"], meta["height"]
    c.set(textures=f"{w}x{h}", files=[os.path.basename(p) for p in info["files"]])
    c.check("power_of_two", (w & (w - 1)) == 0 and (h & (h - 1)) == 0 and w >= N + 1 and h >= F + 1)
    c.check("fps_from_bake", abs(meta["fps"] - 24.0) < 1e-6, meta["fps"])

    def load(name):
        img = bpy.data.images.load(os.path.join(OUT, name))
        img.colorspace_settings.name = "Non-Color"
        a = np.empty(w * h * 4, np.float32)
        img.pixels.foreach_get(a)
        bpy.data.images.remove(img)
        return a.reshape(h, w, 4)

    tp, tr = load(meta["position_texture"]["file"]), load(meta["rotation_texture"]["file"])
    basis = np.array(meta["basis_matrix_from_blender"], np.float32)
    before = set(bpy.data.objects)
    bpy.ops.import_scene.fbx(filepath=os.path.join(OUT, "export_crate_mesh.fbx"))
    mesh = new_objects(before, "MESH")[0]
    em = core.EvalMesh(mesh)
    uv = mesh.data.uv_layers.get("VAT")
    c.check("mesh_has_lookup_uv", uv is not None)
    luv = np.empty(len(mesh.data.loops) * 2, np.float32)
    uv.uv.foreach_get("vector", luv)
    u_of_vert = np.zeros(len(em.co), np.float32)
    u_of_vert[em.loop_vert] = luv.reshape(-1, 2)[:, 0]
    col = np.floor(u_of_vert * w).astype(int)
    # the last six vertices are the two bounds triangles: they use the static column and never move
    static = col == meta["static_column"]
    c.check("bounds_triangles_present", int(static.sum()) == 6, int(static.sum()))
    lo_b, hi_b = np.array(meta["animation_bounds_min"]), np.array(meta["animation_bounds_max"])
    ext = em.co @ basis.T
    c.check("mesh_carries_animation_bounds", float(np.abs(ext.min(0) - lo_b).max()) < 5e-3 and float(np.abs(ext.max(0) - hi_b).max()) < 5e-3,
            [ext.min(0).round(3).tolist(), ext.max(0).round(3).tolist()])
    c.check("static_column_is_identity", float(np.abs(tp[:F + 1, meta["static_column"], :3]).max()) == 0.0
            and float(np.abs(tr[:F, meta["static_column"]] - np.array([0, 0, 0, 1])).max()) == 0.0)
    em.co, col = em.co[~static], col[~static]
    c.check("lookup_in_range", bool((col >= 0).all() and (col < N).all()))
    # every vertex must look up a piece that really has a vertex at that spot. Neighbouring pieces
    # share positions along their cut faces, so several pieces can be right for one position; the
    # decode check below (pieces flown apart) is what tells those apart.
    kd = kdtree.KDTree(len(rest.co))
    for i, p in enumerate(rest.co):
        kd.insert(p, i)
    kd.balance()
    wrong = sum(1 for p, k in zip(em.co, col) if k not in {int(rest.piece[i]) for _, i, _ in kd.find_range(p, 1e-4)})
    c.check("lookup_points_at_own_piece", wrong == 0, wrong)
    # decode exactly like HStyleRbdVAT.hlsl, in the target basis, and bring the result back to Blender axes
    vert_t = em.co @ basis.T
    pivot_rest = tp[meta["pivot_row"], col, :3]
    worst = 0.0
    for k in FRAMES:
        q = tr[k, col][:, [3, 0, 1, 2]]                  # texture is xyzw, qrot wants wxyz
        dec = tp[k, col, :3] + T.qrot(q, vert_t - pivot_rest)
        worst = max(worst, two_way_error(dec @ basis, expected(k)))   # orthonormal: inverse = transpose
    c.check("decode_matches", worst < TOL, round(worst, 6))
    # the mirrored basis must really be a mirror, and the rotation must stay a rotation in it
    c.check("basis_is_reflection", abs(float(np.linalg.det(basis)) + 1.0) < 1e-6)
    c.check("rotations_stay_unit", float(np.abs(np.linalg.norm(tr[:F, :N], axis=-1) - 1.0).max()) < 1e-3)
    lo, hi = np.array(meta["animation_bounds_min"]), np.array(meta["animation_bounds_max"])
    allp = np.concatenate([expected(k) @ basis.T for k in range(0, F, 5)])
    c.check("bounds_cover_animation", bool((allp >= lo - 1e-3).all() and (allp <= hi + 1e-3).all()))
    ev = sim.read_events(ob)
    et = np.array(meta["event_times"])
    ep = np.array(meta["event_positions"]).reshape(-1, 3)
    c.set(events=meta["event_count"])
    c.check("events_exported", meta["event_count"] == len(ev) == len(et) == len(ep) == len(meta["event_sizes"])
            == len(meta["event_speeds"]) and len(ev) > 50, [meta["event_count"], len(ev)])
    c.check("event_times_in_seconds", bool((np.diff(et) >= 0).all()) and float(np.abs(et - ev[:, 0] / meta["fps"]).max()) < 1e-3
            and 0 < et.min() and et.max() <= (F - 1) / meta["fps"] + 1e-6, [float(et.min()), float(et.max())])
    c.check("event_places_in_mesh_space", float(np.abs(ep @ basis - ev[:, 1:4]).max()) < 1e-3,
            round(float(np.abs(ep @ basis - ev[:, 1:4]).max()), 5))
    c.check("events_inside_animation_bounds", bool((ep >= lo - 1e-3).all() and (ep <= hi + 1e-3).all()))
    with open(info["json"], encoding="utf-8") as fh:
        longest = max(len(line) for line in fh)
        fh.seek(0)
        n_lines = sum(1 for _ in fh)
    c.check("json_stays_readable", n_lines < 80 and longest > 200, [n_lines, longest])
    # the files for Unity are not part of the extension: an export is its four files and says where the others are
    c.check("export_is_four_files", sorted(os.path.basename(p) for p in info["files"]) == sorted(
        "export_crate" + s for s in ("_pos.exr", "_rot.exr", "_mesh.fbx", ".json")), [os.path.basename(p) for p in info["files"]])
    c.check("json_says_where_the_unity_files_are", meta["unity_files"].endswith(export.UNITY_FILES_URL)
            and export.UNITY_FILES_URL.startswith("https://") and "unity_support_folder" not in meta, meta.get("unity_files"))
    unity = os.path.join(T.ROOT, "Unity")
    schema_in_unity = [name for name in sorted(os.listdir(unity)) if name.endswith((".cs", ".hlsl"))
                       and export.VAT_SCHEMA in open(os.path.join(unity, name), encoding="utf-8").read()]
    c.check("unity_files_name_the_same_schema", schema_in_unity == ["HStyleRbdVAT.hlsl", "HStyleRbdVatPlayer.cs", "HStyleRbdVatSetup.cs"],
            schema_in_unity)
    bpy.data.batch_remove([o for o in bpy.data.objects if o not in before])

except Exception:
    c.error()
c.done()

# ---------------------------------------------------------------- where the VAT lookup UV map ends up
c = REP.case("lookup_uv")
try:
    def quad_mesh(layer_names, active=None, render=None):
        me = bpy.data.meshes.new("LookupUvTest")
        me.from_pydata([(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)], [], [(0, 1, 2, 3)])
        for k, layer_name in enumerate(layer_names):
            layer = me.uv_layers.new(name=layer_name)
            layer.uv.foreach_set("vector", np.full(8, 0.1 * (k + 1), np.float32))
        if active:
            me.uv_layers.active = me.uv_layers[active]
        if render:
            me.uv_layers[render].active_render = True
        return me

    def values(me):
        out = {}
        for layer in me.uv_layers:
            a = np.empty(8, np.float32)
            layer.uv.foreach_get("vector", a)
            out[layer.name] = round(float(a[0]), 3)
        return out

    lookup = np.full((4, 2), 0.75, np.float32)
    me0 = quad_mesh([])
    c.check("no_uv_map", export._lookup_as_second_uv(me0, lookup) == 1 and [l.name for l in me0.uv_layers] == ["UVMap", "VAT"])
    me1 = quad_mesh(["Base"])
    c.check("one_uv_map", export._lookup_as_second_uv(me1, lookup) == 1 and values(me1) == {"Base": 0.1, "VAT": 0.75}, values(me1))
    me3 = quad_mesh(["Base", "Lightmap", "Detail"], active="Detail", render="Lightmap")
    idx = export._lookup_as_second_uv(me3, lookup)
    c.check("several_uv_maps_keep_their_data", idx == 1 and [l.name for l in me3.uv_layers] == ["Base", "VAT", "Lightmap", "Detail"]
            and values(me3) == {"Base": 0.1, "VAT": 0.75, "Lightmap": 0.2, "Detail": 0.3}, values(me3))
    c.check("active_and_render_flags_kept", me3.uv_layers.active.name == "Detail"
            and [l.name for l in me3.uv_layers if l.active_render] == ["Lightmap"],
            [me3.uv_layers.active.name, [l.name for l in me3.uv_layers if l.active_render]])
    # a map that is already called VAT must not be mistaken for the lookup map
    mev = quad_mesh(["VAT", "Other"])
    idx = export._lookup_as_second_uv(mev, lookup)
    names = [l.name for l in mev.uv_layers]
    c.check("name_clash", idx == 1 and names[0] == "VAT" and values(mev)[names[1]] == 0.75 and values(mev)["VAT"] == 0.1
            and values(mev)["Other"] == 0.2, [idx, values(mev)])
    # ... also when it is not the first one, and is the active and the render map
    mel = quad_mesh(["Base", "VAT"], active="VAT", render="VAT")
    idx = export._lookup_as_second_uv(mel, lookup)
    c.check("name_clash_later_map", idx == 1 and [l.name for l in mel.uv_layers] == ["Base", "VAT_lookup", "VAT"]
            and values(mel) == {"Base": 0.1, "VAT_lookup": 0.75, "VAT": 0.2} and mel.uv_layers.active.name == "VAT"
            and [l.name for l in mel.uv_layers if l.active_render] == ["VAT"],
            [idx, values(mel), mel.uv_layers.active.name, [l.name for l in mel.uv_layers if l.active_render]])
    bpy.data.meshes.remove(mel)
    me7 = quad_mesh([f"Map{k}" for k in range(7)])
    c.check("seven_uv_maps_still_fit", export._lookup_as_second_uv(me7, lookup) == 1 and len(me7.uv_layers) == 8
            and all(values(me7)[f"Map{k}"] == round(0.1 * (k + 1), 3) for k in range(7)), values(me7))
    me8 = quad_mesh([f"Map{k}" for k in range(8)])
    try:
        export._lookup_as_second_uv(me8, lookup)
        refused = False
    except RuntimeError as e:
        refused = "8 UV maps" in str(e)
    c.check("eight_uv_maps_refused_untouched", refused and len(me8.uv_layers) == 8
            and all(values(me8)[f"Map{k}"] == round(0.1 * (k + 1), 3) for k in range(8)), values(me8))
    for m in (me0, me1, me3, mev, me7, me8):
        bpy.data.meshes.remove(m)
except Exception:
    c.error()
c.done()

# ---------------------------------------------------------------- a bake of a single frame still exports
c = REP.case("single_frame")
try:
    sim.bake(bpy.context, ob, sim.SimSettings(frame_start=5, frame_end=5, start_asleep=False, use_glue=False))
    counts = T.datablock_counts()
    info = export.export_fbx(bpy.context, ob, os.path.join(OUT, "export_one_frame.fbx"))
    vat1 = export.export_vat(bpy.context, ob, OUT, "export_one_frame", "UNITY")
    c.check("exports_without_error", info["frames"] == 1 and vat1["frame_count"] == 1 and vat1["events"] == 0)
    c.check("export_leaves_nothing", T.datablock_counts() == counts)
except Exception:
    c.error()
c.done()

# ---------------------------------------------------------------- merging pieces that never come apart
c = REP.case("merge")
try:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.frame_start, scene.frame_end = 1, 50
    wall = T.add_object("Wall", T.box("Wall", (4.0, 0.4, 2.0), (0.0, 0.0, 1.0)), location=(0.5, 1.0, 0.0))
    wall.rotation_euler = (0.0, 0.0, 0.3)
    T.add_fracture(wall, Pieces=90, Seed=6, Secondary_Ratio=0.2)
    bpy.context.view_layer.update()
    # a blast in the middle of a glued, anchored wall: the middle flies, the rest stands
    centre = wall.matrix_world @ Vector((0.0, -0.4, 1.0))
    sim.bake(bpy.context, wall, sim.SimSettings(frame_end=50, glue_strength=2.5, cluster_pieces=4, anchor_bottom=True,
                                                burst_speed=6.0, burst_origin=tuple(centre), burst_radius=1.6, seed=3))
    wpos, wquat, wpiv, wstart = sim.read_cache(wall)
    WF, WN = wpos.shape[:2]
    wrest, _ = sim.rest_pieces(wall)
    # 2 cm of tolerance: the glue of the standing part flexes by about that much in the blast
    m = export.Merged(wall, 0.02)
    tight = export.Merged(wall, 0.002)
    c.set(groups_at_2mm_10mm_20mm=[tight.count, export.Merged(wall).count, m.count])
    c.check("tolerance_decides_how_much_merges", m.count < tight.count <= WN and export.Merged(wall).count <= tight.count
            and export.Merged(wall).limit == 0.01, [tight.count, export.Merged(wall).count, m.count])

    def face_area_of(em_):
        tri_face = np.repeat(np.arange(len(em_.loop_total)), np.maximum(em_.loop_total - 2, 0))
        a3, b3, c3 = (em_.proxy_co[em_.tris[:, k]].astype(np.float64) for k in range(3))
        return np.bincount(tri_face, weights=np.linalg.norm(np.cross(b3 - a3, c3 - a3), axis=1) / 2, minlength=len(em_.loop_total))

    # "still": no point of the piece ever gets a millimetre from where it started
    travel = np.linalg.norm(wpos - wpiv[None], axis=-1).max(0)
    reach = np.zeros(WN)
    np.maximum.at(reach, wrest.piece, np.linalg.norm(wrest.co - wpiv[wrest.piece], axis=1))
    still = travel + 2.0 * np.arccos(np.clip(np.abs(wquat[..., 0]), 0.0, 1.0)).max(0) * reach < 1e-3
    sizes = np.bincount(m.group, minlength=m.count)
    c.set(pieces=WN, groups=m.count, never_moving=int(still.sum()), in_the_static_group=int(sizes[0]),
          largest_moving_group=int(sizes[1:].max()) if m.count > 1 else 0, faces=len(wrest.inside),
          cut_faces=int(wrest.inside.sum()), hidden_faces=int(m.hidden.sum()))
    c.check("fewer_pieces", 1 < m.count < 0.8 * WN and int(still.sum()) > 10, [m.count, WN, int(still.sum())])
    c.check("still_pieces_share_group_0", bool((m.group[still] == 0).all()) and sizes[0] >= still.sum())
    c.check("static_group_is_exactly_still", float(np.abs(m.pos[:, 0] - m.pivots[0]).max()) == 0.0
            and float(np.abs(m.quat[:, 0] - np.array([1, 0, 0, 0])).max()) == 0.0)
    # every vertex, moved by its group instead of by its own piece: the same place within the tolerance
    # that decides "never came apart" (5 % of the contact, at least 2 mm), exactly the same for pieces left alone
    g = m.group[wrest.piece]
    worst, worst_alone = 0.0, 0.0
    alone = sizes[g] == 1
    for k in (0, 5, 12, 25, WF - 1):
        by_piece = wpos[k][wrest.piece] + T.qrot(wquat[k][wrest.piece], wrest.co - wpiv[wrest.piece])
        by_group = m.pos[k][g] + T.qrot(m.quat[k][g], wrest.co - m.pivots[g])
        err = np.linalg.norm(by_piece - by_group, axis=1)
        worst = max(worst, float(err.max()))
        worst_alone = max(worst_alone, float(err[alone].max()) if alone.any() else 0.0)
    c.set(merge_error_mm=round(worst * 1000, 2), merge_error_limit_mm=round(m.limit * 1000, 2))
    c.check("same_motion", worst <= m.limit + 1e-4 and worst_alone < 1e-6,
            [round(worst, 5), round(m.limit, 5), round(worst_alone, 8)])

    # hidden faces, found again in a different way: exact neighbour search instead of grid hashing
    kd = kdtree.KDTree(len(wrest.proxy_co))
    for i, p in enumerate(wrest.proxy_co):
        kd.insert(p, i)
    kd.balance()
    starts = np.append(0, np.cumsum(wrest.loop_total))
    again = np.zeros(len(wrest.inside), bool)
    reach = 2e-4 * float(np.linalg.norm(wrest.proxy_co.max(0) - wrest.proxy_co.min(0)))   # the grid size of the search under test
    for f in np.flatnonzero(wrest.inside):
        verts = wrest.loop_vert[starts[f]:starts[f + 1]]
        own = int(wrest.piece[verts[0]])
        common = None
        for v in verts:
            near = {int(wrest.piece[i]) for _, i, _ in kd.find_range(wrest.proxy_co[v], reach)}
            common = near if common is None else common & near
        again[f] = any(p != own and m.group[p] == m.group[own] for p in common)
    # (a grid cell is not a sphere: a sliver of a face, smaller than the cell, may be judged differently)
    c.check("hidden_faces_match_reference", int(m.hidden.sum()) > 100 and int((m.hidden != again).sum()) <= 2
            and float(face_area_of(wrest)[m.hidden != again].sum()) < 1e-4,
            [int(m.hidden.sum()), int(again.sum()), int((m.hidden != again).sum())])
    c.check("only_cut_faces_are_hidden", not bool((m.hidden & ~wrest.inside).any()))
    # a face is hidden on both sides or on neither: what is removed is in pairs of equal area
    face_area = face_area_of(wrest)
    face_group = m.group[wrest.piece[wrest.loop_vert[starts[:-1]]]]
    per_group = np.bincount(face_group, weights=face_area * m.hidden, minlength=m.count)
    contacts = sim.read_contacts(wall)
    inner = sum(area for a, b, _, area in contacts if m.group[a] == m.group[b])
    c.set(hidden_area_m2=round(float(per_group.sum()), 3), twice_the_inner_contact_area_m2=round(2 * inner, 3))
    c.check("both_sides_of_every_inner_contact", abs(float(per_group.sum()) - 2 * inner) < 0.02 * 2 * inner,
            [round(float(per_group.sum()), 4), round(2 * inner, 4)])

    # ---- bone FBX: fewer bones, and the picture is the same as without merging
    plain_path, merged_path = os.path.join(OUT, "merge_plain.fbx"), os.path.join(OUT, "merge_merged.fbx")
    counts = T.datablock_counts()
    plain = export.export_fbx(bpy.context, wall, plain_path)
    merged = export.export_fbx(bpy.context, wall, merged_path, merge=True, merge_distance=0.02)
    c.check("export_leaves_nothing", T.datablock_counts() == counts)
    c.set(bones=[plain["bones"], merged["bones"]],
          fbx_kb=[os.path.getsize(plain_path) // 1024, os.path.getsize(merged_path) // 1024])
    c.check("fewer_bones", merged["bones"] == m.count + 1 and plain["bones"] == WN + 1 and merged["hidden_faces"] == int(m.hidden.sum())
            and os.path.getsize(merged_path) < 0.9 * os.path.getsize(plain_path), [plain["bones"], merged["bones"]])

    def load(path):
        before = set(bpy.data.objects)
        bpy.ops.import_scene.fbx(filepath=path, anim_offset=0.0)
        return [o for o in bpy.data.objects if o not in before]

    def deformed(objects, frame):
        scene.frame_set(frame)
        mesh = next(o for o in objects if o.type == "MESH")
        return core.EvalMesh(mesh)

    wall.hide_render = wall.hide_viewport = True
    sets = {"plain": load(plain_path), "merged": load(merged_path)}
    faces = {k: len(next(o for o in v if o.type == "MESH").data.polygons) for k, v in sets.items()}
    c.set(fbx_faces=[faces["plain"], faces["merged"]])
    c.check("hidden_faces_are_gone", faces["plain"] - faces["merged"] == int(m.hidden.sum()), [faces["plain"], faces["merged"]])
    # every vertex that is still there sits where the unmerged export has one (same tolerance as above)
    worst = 0.0
    for k in (0, 12, WF - 1):
        a_mesh, b_mesh = deformed(sets["plain"], wstart + k), deformed(sets["merged"], wstart + k)
        tree = kdtree.KDTree(len(a_mesh.co))
        for i, p in enumerate(a_mesh.co):
            tree.insert(p, i)
        tree.balance()
        worst = max(worst, max(tree.find(p)[2] for p in b_mesh.co))
    c.check("merged_fbx_matches_plain", worst <= m.limit + 2e-4, round(worst, 5))
    # and the two look the same: rendered from the front and from behind
    cam = T.setup_render((480, 270))
    shading = bpy.context.scene.display.shading
    # one plain colour: the per-piece data in the vertex colours differs between the two on purpose
    shading.show_shadows, shading.show_cavity, shading.color_type = False, False, "SINGLE"
    different = []
    for k, direction in ((0, (0.3, -1.0, 0.3)), (10, (0.3, -1.0, 0.3)), (25, (-0.4, 1.0, 0.5)), (WF - 1, (0.3, -1.0, 0.3))):
        T.aim_camera(cam, tuple(wall.matrix_world @ Vector((0.0, 0.0, 1.0))), direction, 8.0)
        shots = {}
        for name, objects in sets.items():
            for other in sets.values():
                for o in other:
                    o.hide_render = other is not objects
            path = os.path.join(OUT, f"merge_{name}_{k:02d}.png")
            T.render_still(path, wstart + k)
            img = bpy.data.images.load(path)
            px = np.empty(img.size[0] * img.size[1] * 4, np.float32)
            img.pixels.foreach_get(px)
            bpy.data.images.remove(img)
            shots[name] = px.reshape(-1, 4)[:, :3]
        different.append(float((np.abs(shots["plain"] - shots["merged"]).max(axis=1) > 0.06).mean()))
    c.set(pixels_that_differ_percent=[round(100 * d, 3) for d in different])
    c.check("renders_look_the_same", max(different) < 0.004, [round(100 * d, 3) for d in different])
    bpy.data.batch_remove([o for group in sets.values() for o in group])
    wall.hide_render = wall.hide_viewport = False

    # ---- VAT: fewer columns, decodes to the same motion
    info = export.export_vat(bpy.context, wall, OUT, "merge_vat", "UNITY", merge=True, merge_distance=0.02)
    with open(info["json"], encoding="utf-8") as fh:
        meta = json.load(fh)
    c.set(vat_columns=[WN, meta["piece_count"]], vat_texture=f"{meta['width']}x{meta['height']}")
    c.check("vat_has_one_column_per_group", meta["piece_count"] == m.count and meta["source_piece_count"] == WN
            and meta["static_column"] == m.count and meta["width"] <= 2 ** int(np.ceil(np.log2(m.count + 1))),
            [meta["piece_count"], meta["width"]])
    w, h = meta["width"], meta["height"]

    def tex(name):
        img = bpy.data.images.load(os.path.join(OUT, name))
        img.colorspace_settings.name = "Non-Color"
        a = np.empty(w * h * 4, np.float32)
        img.pixels.foreach_get(a)
        bpy.data.images.remove(img)
        return a.reshape(h, w, 4)

    tp, tr = tex(meta["position_file"]), tex(meta["rotation_file"])
    basis = np.array(meta["basis_matrix_from_blender"], np.float32)
    before = set(bpy.data.objects)
    bpy.ops.import_scene.fbx(filepath=os.path.join(OUT, meta["mesh_file"]))
    vm = next(o for o in bpy.data.objects if o not in before and o.type == "MESH")
    em = core.EvalMesh(vm)
    luv = np.empty(len(vm.data.loops) * 2, np.float32)
    vm.data.uv_layers[meta["lookup_uv_index"]].uv.foreach_get("vector", luv)
    u = np.zeros(len(em.co), np.float32)
    u[em.loop_vert] = luv.reshape(-1, 2)[:, 0]
    col = np.floor(u * w).astype(int)
    keep = col != meta["static_column"]
    vert_t, col = (em.co @ basis.T)[keep], col[keep]
    c.check("lookup_in_range", bool((col >= 0).all() and (col < m.count).all()))
    kd_all = kdtree.KDTree(len(wrest.co))
    for i, p in enumerate(wrest.co):
        kd_all.insert(p, i)
    kd_all.balance()
    worst = 0.0
    for k in (0, 12, WF - 1):
        q = tr[k, col][:, [3, 0, 1, 2]]
        dec = (tp[k, col, :3] + T.qrot(q, vert_t - tp[meta["pivot_row"], col, :3])) @ basis
        want = wpos[k][wrest.piece] + T.qrot(wquat[k][wrest.piece], wrest.co - wpiv[wrest.piece])
        tree = kdtree.KDTree(len(want))
        for i, p in enumerate(want):
            tree.insert(p, i)
        tree.balance()
        worst = max(worst, max(tree.find(p)[2] for p in dec))
    c.check("merged_vat_decodes_to_the_bake", worst <= m.limit + 2e-4, round(worst, 5))
    c.check("events_unchanged", meta["event_count"] == len(sim.read_events(wall)) > 0, meta["event_count"])
    bpy.data.batch_remove([o for o in bpy.data.objects if o not in before])

    # ---- nothing to merge: every piece flies on its own
    sim.bake(bpy.context, wall, sim.SimSettings(frame_end=30, use_glue=False, start_asleep=False, burst_speed=8.0,
                                                burst_origin=tuple(centre)))
    loose = export.Merged(wall)
    c.check("nothing_to_merge", loose.count >= WN - 2 and int(loose.hidden.sum()) <= 2, [loose.count, WN, int(loose.hidden.sum())])
    # ---- everything stays: one piece, only the outside left
    sim.bake(bpy.context, wall, sim.SimSettings(frame_end=20, glue_strength=1e6, anchor_bottom=True))
    solid = export.Merged(wall)
    info = export.export_fbx(bpy.context, wall, os.path.join(OUT, "merge_solid.fbx"), merge=True)
    # (a few cut faces have a corner that only one of the two sides has, and stay; they are inside and never seen)
    c.check("all_one_piece", solid.count == 1 and float(solid.hidden[sim.rest_pieces(wall)[0].inside].mean()) > 0.99 and info["bones"] == 2,
            [solid.count, int(solid.hidden.sum()), int(sim.rest_pieces(wall)[0].inside.sum())])
except Exception:
    c.error()
c.done()

# ---------------------------------------------------------------- 500 bones
c = REP.case("fbx_500")
try:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.frame_start, scene.frame_end = 1, 100
    big = T.add_object("Block", T.box("Block", (3.0, 3.0, 3.0), (0.0, 0.0, 1.5)))
    T.add_fracture(big, Pieces=500, Seed=9)
    sim.bake(bpy.context, big, sim.SimSettings(frame_end=100, start_asleep=False, use_glue=False, burst_speed=5.0))
    path = os.path.join(OUT, "export_500.fbx")
    t = time.perf_counter()
    info = export.export_fbx(bpy.context, big, path)
    secs = time.perf_counter() - t
    c.set(bones=info["bones"], frames=info["frames"], seconds=round(secs, 1), size_mb=round(os.path.getsize(path) / 1e6, 1))
    c.check("bone_count", info["bones"] >= 501, info["bones"])
    before = set(bpy.data.objects)
    bpy.ops.import_scene.fbx(filepath=path, anim_offset=0.0)
    arm500 = [o for o in bpy.data.objects if o not in before and o.type == "ARMATURE"][0]
    c.check("bones_really_in_file", len(arm500.data.bones) == info["bones"], len(arm500.data.bones))
    bpy.data.batch_remove([o for o in bpy.data.objects if o not in before])
    c.check("export_time_ok", secs < 120.0, round(secs, 1))
    t = time.perf_counter()
    vat = export.export_vat(bpy.context, big, OUT, "export_500", "UNITY")
    c.set(vat_seconds=round(time.perf_counter() - t, 2), vat_textures=f"{vat['width']}x{vat['height']}")
except Exception:
    c.error()
c.done()

REP.finish()
