# SPDX-License-Identifier: GPL-3.0-or-later
"""Exports of a baked object: Alembic, bone-driven FBX, and rigid-body VAT.

FBX and VAT are written from the transform cache itself, in the world frame of the bake
(where the object stood when it was simulated) and at the baked frame rate. They ignore the
Retime settings of the playback modifier. Alembic exports what the viewport shows.
"""
import json
import os

import bpy
import numpy as np
from mathutils import Matrix, Quaternion, Vector

from . import sim

VAT_SCHEMA = "hrbd_vat_1"
# The shader and the scripts that read a VAT export in Unity are not part of the extension (an extension
# holds Python only): they are in the Unity folder of the project's repository. A fork puts its own address here.
UNITY_FILES_URL = "https://github.com/excifroge/H-Style-RBD-Nodes/tree/main/Unity"

# Blender (right-handed, Z up) -> Unity (left-handed, Y up) for a mesh exported through FBX
# with "Apply Transform": unity = (-x, z, -y).
BASIS = {
    "UNITY": np.array([[-1.0, 0.0, 0.0], [0.0, 0.0, 1.0], [0.0, -1.0, 0.0]], np.float32),
    "BLENDER": np.eye(3, dtype=np.float32),
}


def _require_bake(ob):
    data = sim.read_cache(ob)
    if data is None:
        raise RuntimeError("Nothing is baked on this object (or the bake is incomplete). Bake the simulation first.")
    return data


COLOR_ATTRIBUTE = "RBD"


def piece_shader_data(pos, quat, pivots, fps, origin=None):
    """Per-piece values for shader-driven effects, each in 0..1:
    random, time the piece starts to move or turn (as a fraction of the bake), distance from the impact point."""
    f, n = pos.shape[:2]
    rnd = np.random.default_rng(12345).random(n)
    if f < 2:
        start = np.ones(n)                      # a single frame: nothing ever moves
    else:
        speed = np.linalg.norm(np.diff(pos, axis=0), axis=-1) * fps                          # m/s, [F-1, N]
        turn = 2.0 * np.arccos(np.clip(np.abs(np.sum(quat[1:] * quat[:-1], axis=-1)), 0.0, 1.0)) * fps   # rad/s
        moving = (speed > 0.05) | (turn > 0.2)
        first = np.where(moving.any(0), moving.argmax(0) + 1, f - 1)   # frame index the motion shows in
        start = first / (f - 1)
    origin = pivots.mean(0) if origin is None else np.asarray(origin, np.float32)
    dist = np.linalg.norm(pivots - origin, axis=1)
    dist = dist / max(float(dist.max()), 1e-9)
    return np.stack([rnd, start, dist], axis=1).astype(np.float32)


class Merged:
    """The bake with every set of pieces that stays together through all of it treated as one piece
    (and everything that never moves as one more): fewer bones or texture columns. The cut faces
    between merged pieces can never be seen and are dropped from the exported mesh.

    Like the H-Style clean-up before a destruction goes to a game engine.
    `limit` (metres) is how far any point of a merged piece may end up from where the simulation had
    it. Glue flexes a little under load, so with a very small limit hardly anything merges."""

    def __init__(self, ob, limit=0.01):
        pos, quat, pivots, self.start = _require_bake(ob)
        em = sim.rest_pieces(ob)[0]
        radius = np.zeros(len(pivots))
        np.maximum.at(radius, em.piece, np.linalg.norm(em.co - pivots[em.piece], axis=1))
        self.limit = max(float(limit), 1e-6)
        self.group, self.count, static, rep = sim.unbroken_groups(pos, quat, pivots, sim.read_contacts(ob), radius, self.limit)
        self.source_count = len(pivots)
        self.pos, self.quat, self.pivots = pos[:, rep].copy(), quat[:, rep].copy(), pivots[rep].copy()
        if static >= 0:
            self.pos[:, static] = self.pivots[static]          # exactly still: no resting jitter
            self.quat[:, static] = (1.0, 0.0, 0.0, 0.0)
        self.hidden = self._hidden_faces(em)

    def _hidden_faces(self, em):
        """Per polygon of the frozen pieces: is it a cut face between two pieces of the same group?
        Such a face has every corner in common with one other piece (the one on its other side)."""
        co = em.proxy_co
        span = float(np.linalg.norm(co.max(0) - co.min(0))) or 1.0
        h = max(span * 2e-4, 1e-6)
        piece = em.piece.tolist()
        keys, at = [], []
        for shift in (0.0, 0.5):                    # two half-offset grids, as in sim.adjacency()
            key = [tuple(k) for k in np.floor(co / h + shift).astype(np.int64).tolist()]
            here = {}
            for k, p in zip(key, piece):
                here.setdefault(k, set()).add(p)
            keys.append(key)
            at.append(here)
        group = self.group.tolist()
        loop_vert = em.loop_vert.tolist()
        starts = np.append(0, np.cumsum(em.loop_total)).tolist()
        hidden = np.zeros(len(em.loop_total), bool)
        for f in np.flatnonzero(em.inside).tolist():
            verts = loop_vert[starts[f]:starts[f + 1]]
            own = piece[verts[0]]
            common = None
            for v in verts:
                near = at[0][keys[0][v]] | at[1][keys[1][v]]
                common = set(near) if common is None else common & near
                if len(common) < 2:
                    break
            hidden[f] = any(p != own and group[p] == group[own] for p in common)
        return hidden

    def apply(self, me):
        """Turn a copy of the frozen pieces into the merged mesh: piece ids become group ids, hidden faces go."""
        ids = np.zeros(len(me.vertices), np.int32)
        me.attributes["piece_id"].data.foreach_get("value", ids)
        me.attributes["piece_id"].data.foreach_set("value", self.group[ids])
        if self.hidden.any():
            import bmesh
            bm = bmesh.new()
            bm.from_mesh(me)
            bm.faces.ensure_lookup_table()
            bmesh.ops.delete(bm, geom=[bm.faces[i] for i in np.flatnonzero(self.hidden).tolist()], context="FACES")
            bm.to_mesh(me)
            bm.free()


def _world_rest_mesh(ob, name, with_color=True, merged=None):
    """Copy of the frozen pieces placed where the object stood at bake time, plus per-vertex piece ids.

    The copy carries a colour attribute "RBD" for game shaders (linear values, not a visible colour):
    R = random per piece, G = when the piece starts to move (0 = first frame, 1 = last or never),
    B = distance of the piece from the impact point (0 = nearest, 1 = farthest), A = 1 on cut faces.
    The caller owns the returned mesh; if anything fails in here the copy is removed again.
    """
    cache, rest = sim.cache_info(ob)[:2]
    me = rest.data.copy()
    try:
        me.name = name
        if merged is not None:
            merged.apply(me)
        me.transform(cache.matrix_world)
        piece = np.zeros(len(me.vertices), np.int32)
        me.attributes["piece_id"].data.foreach_get("value", piece)
        if with_color:
            pos, quat, pivots = (merged.pos, merged.quat, merged.pivots) if merged is not None else sim.read_cache(ob)[:3]
            impact = cache.get("rbd_impact")
            data = piece_shader_data(pos, quat, pivots, float(cache.get("rbd_fps", 24.0)),
                                     None if impact is None else list(impact))
            loop_vert = np.empty(len(me.loops), np.int32)
            me.loops.foreach_get("vertex_index", loop_vert)
            inside = np.zeros(len(me.polygons), bool)
            if "inside" in me.attributes:
                me.attributes["inside"].data.foreach_get("value", inside)
            totals = np.empty(len(me.polygons), np.int32)
            me.polygons.foreach_get("loop_total", totals)
            rgba = np.ones((len(loop_vert), 4), np.float32)
            rgba[:, :3] = data[piece[loop_vert]]
            rgba[:, 3] = np.repeat(inside, totals).astype(np.float32)
            old = me.color_attributes.get(COLOR_ATTRIBUTE)
            if old is not None:
                me.color_attributes.remove(old)
            col = me.color_attributes.new(COLOR_ATTRIBUTE, "FLOAT_COLOR", "CORNER")
            col.data.foreach_set("color", rgba.reshape(-1))
            me.color_attributes.active_color = col
            me.color_attributes.render_color_index = list(me.color_attributes).index(col)
    except Exception:
        bpy.data.meshes.remove(me)
        raise
    return me, piece


class _Selection:
    """Select exactly the given objects for an exporter, then put the user's selection back."""

    def __init__(self, context, objects):
        self.context, self.objects = context, objects

    def __enter__(self):
        vl = self.context.view_layer
        vl.update()  # objects linked or removed a moment ago are not in the layer until it updates
        self.prev = [o for o in vl.objects if o is not None and o.select_get()]
        self.active = vl.objects.active
        for o in self.prev:
            o.select_set(False)
        for o in self.objects:
            o.select_set(True)
        vl.objects.active = self.objects[0]

    def __exit__(self, *exc):
        vl = self.context.view_layer
        for group, state in ((self.objects, False), (self.prev, True)):
            for o in group:
                try:
                    o.select_set(state)
                except (ReferenceError, RuntimeError):
                    pass
        try:
            vl.objects.active = self.active
        except ReferenceError:
            pass


# ------------------------------------------------------------------ Alembic
def export_alembic(context, ob, filepath):
    pos, _, _, start = _require_bake(ob)
    with _Selection(context, [ob]):
        bpy.ops.wm.alembic_export(filepath=filepath, start=start, end=start + pos.shape[0] - 1,
                                  selected=True, as_background_job=False)
    return {"file": filepath, "frames": int(pos.shape[0])}


# ------------------------------------------------------------------ FBX with one bone per piece
class Rig:
    """Armature (root + one bone per piece) with the baked motion as keyframes, and a skinned copy
    of the pieces. `remove()` deletes whatever was created, also after a failure half way."""

    def __init__(self, context, ob, collection=None, merged=None):
        self.arm_ob = self.skin = self.action = self.arm = self.mesh = None
        try:
            self._build(context, ob, collection or context.scene.collection, merged)
        except Exception:
            self.remove()
            raise

    def _build(self, context, ob, col, merged=None):
        if merged is not None:
            pos, quat, pivots, start = merged.pos, merged.quat, merged.pivots, merged.start
        else:
            pos, quat, pivots, start = _require_bake(ob)
        f, n = pos.shape[:2]
        name = ob.name
        self.arm = arm = bpy.data.armatures.new(name + "_Rig")
        self.arm_ob = arm_ob = bpy.data.objects.new(name + "_Rig", arm)
        col.objects.link(arm_ob)
        self.mesh, piece = _world_rest_mesh(ob, name + "_Skinned", merged=merged)
        self.skin = skin = bpy.data.objects.new(name + "_Skinned", self.mesh)
        col.objects.link(skin)

        with _Selection(context, [arm_ob]):
            bpy.ops.object.mode_set(mode="EDIT")
            try:
                root = arm.edit_bones.new("root")
                root.head, root.tail = (0.0, 0.0, 0.0), (0.0, 0.1, 0.0)
                for i in range(n):
                    eb = arm.edit_bones.new(f"piece_{i:04d}")
                    eb.head = Vector(pivots[i])
                    eb.tail = Vector(pivots[i]) + Vector((0.0, 0.1, 0.0))
                    eb.parent = root
            finally:
                bpy.ops.object.mode_set(mode="OBJECT")

        order = np.argsort(piece, kind="stable")
        bounds = np.append(0, np.cumsum(np.bincount(piece, minlength=n)))
        for i in range(n):
            idx = order[bounds[i]:bounds[i + 1]]
            if len(idx):
                skin.vertex_groups.new(name=f"piece_{i:04d}").add(idx.tolist(), 1.0, "REPLACE")
        skin.modifiers.new("Armature", "ARMATURE").object = arm_ob
        skin.parent = arm_ob

        # pose = rest^-1 * (motion of the piece relative to its rest) * rest, expressed per bone
        loc = np.zeros((f, n, 3), np.float32)
        rq = np.zeros((f, n, 4), np.float32)
        for i in range(n):
            rest = arm.bones[f"piece_{i:04d}"].matrix_local
            rest_inv = rest.inverted()
            un_pivot = Matrix.Translation(-Vector(pivots[i]))
            for k in range(f):
                motion = Matrix.Translation(Vector(pos[k, i])) @ Quaternion(quat[k, i]).to_matrix().to_4x4() @ un_pivot
                l, q, _ = (rest_inv @ motion @ rest).decompose()
                loc[k, i], rq[k, i] = l, q
        flip = np.sign(np.sum(rq[1:] * rq[:-1], axis=-1))
        flip[flip == 0] = 1
        rq[1:] *= np.cumprod(flip, axis=0)[..., None]

        self.action = action = bpy.data.actions.new(name + "_RBD")
        slot = action.slots.new(id_type="OBJECT", name=arm_ob.name)
        bag = action.layers.new("Layer").strips.new(type="KEYFRAME").channelbag(slot, ensure=True)
        arm_ob.animation_data_create()
        arm_ob.animation_data.action = action
        arm_ob.animation_data.action_slot = slot
        co = np.empty(f * 2, np.float32)
        co[0::2] = np.arange(start, start + f)
        linear = np.ones(f, np.int32)
        for i in range(n):
            bone = f"piece_{i:04d}"
            for path, data in ((f'pose.bones["{bone}"].location', loc[:, i]),
                               (f'pose.bones["{bone}"].rotation_quaternion', rq[:, i])):
                for c in range(data.shape[1]):
                    fc = bag.fcurves.new(path, index=c, group_name=bone)
                    fc.keyframe_points.add(f)
                    co[1::2] = data[:, c]
                    fc.keyframe_points.foreach_set("co", co)
                    fc.keyframe_points.foreach_set("interpolation", linear)
                    fc.update()

    def remove(self):
        for o in (self.skin, self.arm_ob):
            if o is not None:
                bpy.data.objects.remove(o)
        for block, store in ((self.mesh, bpy.data.meshes), (self.arm, bpy.data.armatures),
                             (self.action, bpy.data.actions)):
            if block is not None and block.users == 0:
                store.remove(block)
        self.arm_ob = self.skin = self.action = self.arm = self.mesh = None


def export_fbx(context, ob, filepath, keep_rig=False, merge=False, merge_distance=0.01):
    """`merge`: pieces that never come apart share one bone, see Merged."""
    cache, _, n, f, start, fps = sim.cache_info(ob) or (None,) * 6
    if cache is None:
        raise RuntimeError("Nothing is baked on this object (or the bake is incomplete). Bake the simulation first.")
    scene = context.scene
    merged = Merged(ob, merge_distance) if merge else None
    bones = merged.count if merge else n
    rig = Rig(context, ob, merged=merged)
    prev_range = (scene.frame_start, scene.frame_end)
    prev_fps = (scene.render.fps, scene.render.fps_base)
    ok = False
    try:
        scene.frame_start, scene.frame_end = start, start + f - 1
        # the exporter turns frames into seconds with the scene frame rate: use the one that was baked
        scene.render.fps = max(1, int(round(fps)))
        scene.render.fps_base = scene.render.fps / fps
        with _Selection(context, [rig.arm_ob, rig.skin]):
            bpy.ops.export_scene.fbx(
                filepath=filepath, use_selection=True, object_types={"ARMATURE", "MESH"},
                add_leaf_bones=False, apply_scale_options="FBX_SCALE_UNITS", colors_type="LINEAR",
                prioritize_active_color=True,
                bake_anim=True, bake_anim_use_all_bones=True, bake_anim_use_nla_strips=False,
                bake_anim_use_all_actions=False, bake_anim_force_startend_keying=True,
                bake_anim_simplify_factor=0.0,
            )
        ok = True
    finally:
        scene.frame_start, scene.frame_end = prev_range
        scene.render.fps, scene.render.fps_base = prev_fps
        if not (keep_rig and ok):
            rig.remove()
    return {"file": filepath, "bones": bones + 1, "frames": f, "pieces": n,
            "hidden_faces": int(merged.hidden.sum()) if merge else 0}


# ------------------------------------------------------------------ rigid-body VAT
def _pow2(x):
    p = 1
    while p < x:
        p *= 2
    return p


def convert_basis(pos, quat, pivots, basis):
    """Positions and wxyz quaternions expressed in another (possibly mirrored) coordinate basis."""
    c = BASIS[basis]
    det = float(np.linalg.det(c))
    p2 = pos @ c.T
    piv2 = pivots @ c.T
    q2 = quat.copy()
    q2[..., 1:] = det * (quat[..., 1:] @ c.T)  # a rotation axis is a pseudo-vector: it picks up det(C)
    return p2, q2, piv2


def _save_exr(name, pixels, path):
    h, w = pixels.shape[:2]
    img = bpy.data.images.new(name, width=w, height=h, alpha=True, float_buffer=True, is_data=True)
    try:
        img.pixels.foreach_set(np.ascontiguousarray(pixels, np.float32).reshape(-1))
        img.file_format = "OPEN_EXR"
        img.filepath_raw = path
        img.save()
    finally:
        bpy.data.images.remove(img)


def vat_textures(pos, quat, pivots, basis):
    """(position image, rotation image, layout dict). Row k = frame k, one extra row = rest pivots."""
    f, n = pos.shape[:2]
    p2, q2, piv2 = convert_basis(pos, quat, pivots, basis)
    w, h = _pow2(n + 1), _pow2(f + 1)  # one spare column (index n) that never moves, see bounds below
    tex_pos = np.zeros((h, w, 4), np.float32)
    tex_rot = np.zeros((h, w, 4), np.float32)
    tex_rot[..., 3] = 1.0
    tex_pos[:f, :n, :3] = p2
    tex_pos[:f, :n, 3] = 1.0
    tex_pos[f, :n, :3] = piv2
    tex_pos[f, :n, 3] = 1.0
    tex_rot[:f, :n, :3] = q2[..., 1:]
    tex_rot[:f, :n, 3] = q2[..., 0]
    lo = np.minimum(p2.reshape(-1, 3).min(0), piv2.min(0))
    hi = np.maximum(p2.reshape(-1, 3).max(0), piv2.max(0))
    layout = {"width": w, "height": h, "piece_count": n, "frame_count": f, "pivot_row": f, "static_column": n,
              "pivot_bounds_min": lo.tolist(), "pivot_bounds_max": hi.tolist()}
    return tex_pos, tex_rot, layout


def _add_bounds_triangles(me, lo, hi, static_piece, size=1e-3):
    """Append one millimetre-sized triangle at each of two opposite corners; returns the new piece ids."""
    import bmesh
    bm = bmesh.new()
    bm.from_mesh(me)
    layer = bm.verts.layers.int["piece_id"]
    for corner, sign in ((lo, 1.0), (hi, -1.0)):
        c = np.asarray(corner, np.float64)
        vs = [bm.verts.new(tuple(c + sign * size * np.array(d))) for d in ((0, 0, 0), (1, 0, 0), (0, 1, 1))]
        for v in vs:
            v[layer] = static_piece
        bm.faces.new(vs)
    bm.to_mesh(me)
    bm.free()
    piece = np.zeros(len(me.vertices), np.int32)
    me.attributes["piece_id"].data.foreach_get("value", piece)
    return piece


def _lookup_as_second_uv(me, lookup):
    """Store the lookup UVs as the SECOND UV layer (TEXCOORD1 in an engine), whatever the mesh had:
    layers after the first are taken off, "VAT" is added, and they are put back behind it."""
    if len(me.uv_layers) >= 8:
        raise RuntimeError("The mesh has 8 UV maps, the most Blender allows, so there is no room for the VAT "
                           "lookup map. Remove one UV map to export VAT.")
    taken = {layer.name for layer in me.uv_layers}
    vat_name = "VAT"                            # unless the mesh has a map of that name already
    while vat_name in taken:
        vat_name += "_lookup"
    active = me.uv_layers.active.name if me.uv_layers.active is not None else None
    render = next((layer.name for layer in me.uv_layers if layer.active_render), None)
    later = []
    for layer in list(me.uv_layers)[1:]:
        data = np.empty(len(me.loops) * 2, np.float32)
        layer.uv.foreach_get("vector", data)
        later.append((layer.name, data))
    for layer_name, _ in later:
        me.uv_layers.remove(me.uv_layers[layer_name])
    if len(me.uv_layers) == 0:
        me.uv_layers.new(name="UVMap")          # channel 0 has to exist for the lookup map to be channel 1
    me.uv_layers.new(name=vat_name, do_init=False).uv.foreach_set("vector", lookup.reshape(-1))
    for layer_name, data in later:
        me.uv_layers.new(name=layer_name, do_init=False).uv.foreach_set("vector", data)
    names = [layer.name for layer in me.uv_layers]
    if active in names:
        me.uv_layers.active = me.uv_layers[active]
    if render in names:
        me.uv_layers[render].active_render = True
    return names.index(vat_name)


def _dump_json(meta):
    """Indented like json.dumps(indent=1), except that long lists of numbers stay on one line."""
    lines = []
    for key, value in meta.items():
        if isinstance(value, list) and len(value) > 16:
            text = json.dumps(value, separators=(",", ":"))
        else:
            text = json.dumps(value, indent=1).replace("\n", "\n ")
        lines.append(f" {json.dumps(key)}: {text}")
    return "{\n" + ",\n".join(lines) + "\n}\n"


def export_vat(context, ob, directory, name=None, basis="UNITY", merge=False, merge_distance=0.01):
    """`merge`: pieces that never come apart share one texture column, see Merged."""
    pos, quat, pivots, start = _require_bake(ob)
    source_count = len(pivots)
    merged = Merged(ob, merge_distance) if merge else None
    if merge:
        pos, quat, pivots = merged.pos, merged.quat, merged.pivots
    fps = sim.cache_info(ob)[5]
    scene = context.scene
    name = name or bpy.path.clean_name(ob.name)
    os.makedirs(directory, exist_ok=True)
    tex_pos, tex_rot, layout = vat_textures(pos, quat, pivots, basis)
    paths = {k: os.path.join(directory, name + suffix) for k, suffix in
             (("pos.exr", "_pos.exr"), ("rot.exr", "_rot.exr"), ("mesh.fbx", "_mesh.fbx"), ("vat.json", ".json"))}
    _save_exr(name + "_pos", tex_pos, paths["pos.exr"])
    _save_exr(name + "_rot", tex_rot, paths["rot.exr"])

    me = mesh_ob = None
    try:
        me, piece = _world_rest_mesh(ob, name + "_VAT", merged=merged)
        co = np.empty(len(me.vertices) * 3, np.float32)
        me.vertices.foreach_get("co", co)
        reach = float(np.linalg.norm(co.reshape(-1, 3) - pivots[piece], axis=1).max())
        # Game engines cull by the bounds of the rest mesh, and a prefab cannot store wider ones.
        # Two tiny triangles at the corners of the whole animation's bounding box make the mesh
        # itself carry those bounds. They look up the static texel column, so they never move.
        lo = pos.reshape(-1, 3).min(0) - reach
        hi = pos.reshape(-1, 3).max(0) + reach
        piece = _add_bounds_triangles(me, lo, hi, static_piece=layout["static_column"])
        loop_vert = np.empty(len(me.loops), np.int32)
        me.loops.foreach_get("vertex_index", loop_vert)
        lookup = np.zeros((len(loop_vert), 2), np.float32)
        lookup[:, 0] = (piece[loop_vert] + 0.5) / layout["width"]
        lookup[:, 1] = 0.5
        lookup_uv_index = _lookup_as_second_uv(me, lookup)
        mesh_ob = bpy.data.objects.new(name + "_VAT", me)
        scene.collection.objects.link(mesh_ob)
        with _Selection(context, [mesh_ob]):
            bpy.ops.export_scene.fbx(
                filepath=paths["mesh.fbx"], use_selection=True, object_types={"MESH"},
                apply_scale_options="FBX_SCALE_UNITS", bake_space_transform=(basis == "UNITY"), colors_type="LINEAR",
                prioritize_active_color=True,
                bake_anim=False, mesh_smooth_type="FACE",
            )
    finally:
        if mesh_ob is not None:
            bpy.data.objects.remove(mesh_ob)
        if me is not None and me.users == 0:
            bpy.data.meshes.remove(me)

    meta = {
        "schema": VAT_SCHEMA,
        "basis": basis,
        "basis_matrix_from_blender": BASIS[basis].tolist(),
        "fps": fps,
        "start_frame": start,
        "lookup_uv_layer": "VAT, the second UV channel of the mesh (TEXCOORD1): u = (piece + 0.5) / width",
        "lookup_uv_index": lookup_uv_index,
        "position_file": os.path.basename(paths["pos.exr"]),
        "rotation_file": os.path.basename(paths["rot.exr"]),
        "mesh_file": os.path.basename(paths["mesh.fbx"]),
        "unity_files": "shader, set-up menu and player component for Unity: " + UNITY_FILES_URL,
        "merged": "pieces that never come apart share one column" if merge else "one column per piece",
        "source_piece_count": source_count,
        "position_texture": {"file": os.path.basename(paths["pos.exr"]),
                             "rgb": "piece pivot position per frame, object space, Blender units (metres)", "a": "1"},
        "rotation_texture": {"file": os.path.basename(paths["rot.exr"]),
                             "rgba": "quaternion xyzw, rotation of the piece relative to its rest pose"},
        "rows": "row k (v = (k + 0.5) / height) is frame k; row 'pivot_row' holds the rest pivots",
        "decode": "p = pivot_f + rotate(q_f, vertex - pivot_rest); n = rotate(q_f, normal); t.xyz = rotate(q_f, t.xyz)",
        # extents of the whole animation, for the renderer bounds (a rest-pose bound would get culled)
        "animation_bounds_min": (np.array(layout["pivot_bounds_min"]) - reach).tolist(),
        "animation_bounds_max": (np.array(layout["pivot_bounds_max"]) + reach).tolist(),
        "bounds_note": "the mesh carries these bounds itself (two 1 mm triangles at opposite corners)",
        "vertex_color": "linear RGBA: R random per piece, G start of motion 0..1 of the clip, "
                        "B distance from the impact point 0..1, A 1 on cut faces",
        "import_notes": "textures: no sRGB, no mipmaps, no compression, point filter, clamp, RGBAHalf or RGBAFloat",
        **layout,
    }
    events = sim.read_events(ob)
    meta.update({
        "events": "cracks opening between neighbouring pieces, sorted by time. event_times: seconds from the "
                  "start of the clip; event_positions: xyz in the object space of the mesh; event_sizes: metres "
                  "(square root of the area that came apart); event_speeds: how fast the gap opens, m/s",
        "event_count": int(len(events)),
        "event_times": [round(float(x), 4) for x in events[:, 0] / fps],
        "event_positions": [round(float(x), 4) for x in (events[:, 1:4] @ BASIS[basis].T).reshape(-1)],
        "event_sizes": [round(float(x), 4) for x in events[:, 4]],
        "event_speeds": [round(float(x), 3) for x in events[:, 5]],
    })
    with open(paths["vat.json"], "w", encoding="utf-8") as fh:
        fh.write(_dump_json(meta))
    return {"files": list(paths.values()), "json": paths["vat.json"], "events": int(len(events)), "pieces": source_count,
            "hidden_faces": int(merged.hidden.sum()) if merge else 0, **layout}
