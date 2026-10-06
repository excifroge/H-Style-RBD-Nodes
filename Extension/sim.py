# SPDX-License-Identifier: GPL-3.0-or-later
"""Bake: fractured pieces -> Blender's built-in Bullet rigid bodies -> transform cache.

The simulation runs in a throw-away scene. Every piece becomes a temporary rigid body
object, glue becomes breakable Fixed constraints, the result is recorded frame by frame
into one cache mesh, and every temporary object is deleted again. The user's scene only
gains the cache, the frozen pieces and an "RBD Playback" modifier.
"""
import time
from dataclasses import dataclass, field

import bpy
import numpy as np
from mathutils import Quaternion, Vector

from . import core, graph, nodes_playback, nodes_rbd

CACHE_PREFIX = "RBD Cache."
REST_PREFIX = "RBD Rest."
SIM_SCENE = "H-Style RBD Nodes Sim"
FROZEN_PROP = "rbd_frozen_modifiers"
REF_CACHE, REF_REST = "hrbd_cache", "hrbd_rest"   # helper objects, also findable without the modifier
OWNED_PROP = "hrbd_helper"                             # marks the helper objects this add-on created
PRE_ROLL = 1  # frames simulated before the first cached frame


@dataclass
class SimSettings:
    frame_start: int = 1
    frame_end: int = 120
    substeps: int = 10
    solver_iterations: int = 10
    density: float = 100.0
    friction: float = 0.6
    bounce: float = 0.05
    linear_damping: float = 0.04
    angular_damping: float = 0.1
    collision_margin: float = 0.0
    start_asleep: bool = True
    use_glue: bool = True
    glue_strength: float = 5.0
    glue_variation: float = 0.0       # random +- fraction of each bond's strength
    cluster_pieces: int = 0           # average pieces per cluster; 0 or 1 = no clustering
    cluster_strength: float = 10.0    # bonds inside a cluster are this many times stronger
    glue_distance: float = 0.002      # loose parts whose faces are closer than this count as touching (metres)
    glue_iterations: int = 30         # solver iterations spent on every glue bond (0 = as many as on contacts)
    gravity: tuple = None             # None = the gravity of the scene
    anchor_bottom: bool = False
    anchor_height: float = 0.05
    use_ground: bool = True
    ground_z: float = 0.0
    collider_collection: object = None
    use_fields: bool = True           # the force fields of the scene act on the pieces
    field_weight: float = 1.0         # all of them multiplied by this
    field_collection: object = None   # only the fields in this collection; None = every field of the scene
    activation: str = "NONE"          # NONE / RADIAL
    activation_origin: tuple = (0.0, 0.0, 0.0)
    activation_speed: float = 10.0    # metres per second
    activation_delay: int = 0         # frames after frame_start
    burst_speed: float = 0.0          # m/s given to pieces when they are released (0 = off)
    burst_origin: tuple = (0.0, 0.0, 0.0)
    burst_radius: float = 0.0         # speed fades to zero at this distance (0 = no fade)
    burst_up: float = 0.3             # 0 = straight away from the origin, 1 = straight up
    burst_spin: float = 3.0           # random tumbling, radians per second
    burst_variation: float = 0.3      # random +- fraction of the speed
    seed: int = 0


# the kinds of force field the rigid body world has a weight for (EffectorWeights)
FIELD_WEIGHTS = ("boid", "charge", "curve_guide", "drag", "force", "harmonic", "lennardjones", "magnetic", "smokeflow",
                 "texture", "turbulence", "vortex", "wind")


@dataclass
class BakeResult:
    pieces: int = 0
    frames: int = 0
    glue: int = 0
    glue_separated: int = 0           # estimate: bonded neighbours that ended up apart
    clusters: int = 0
    anchored: int = 0
    moved: int = 0
    events: int = 0                   # cracks that opened between neighbouring pieces
    fields: int = 0                   # force fields that acted on the pieces
    seconds: float = 0.0
    notes: list = field(default_factory=list)


# ------------------------------------------------------------------ bake state on the object
def _in_use(helper):
    """Does any object still point at this helper? Scans the real references (our own properties and
    the object inputs of every Geometry Nodes modifier) instead of trusting the user count, which
    Blender 5.2 leaves raised when a modifier holding the pointer is deleted."""
    for tree in bpy.data.node_groups:
        for node in graph.rbd_nodes(tree, nodes_rbd.KIND_BULLET_SOLVER):
            if node.inputs["Cache"].default_value == helper or node.inputs["Frozen Pieces"].default_value == helper:
                return True
    for o in bpy.data.objects:
        if o.get(REF_CACHE) == helper or o.get(REF_REST) == helper:
            return True
        for m in o.modifiers:
            if m.type != "NODES":
                continue
            inputs = getattr(getattr(m, "properties", None), "inputs", None)
            if inputs is None:
                continue
            for key in inputs.keys():
                try:
                    if inputs[key]["value"] == helper:
                        return True
                except (KeyError, TypeError):
                    pass
    return False


def _remove_unused(o):
    """Delete a helper object and its mesh. Only objects this add-on created (they carry a marker) are
    ever deleted, and only when nothing refers to them and nobody linked them into a scene: when in
    doubt the object is left alone."""
    if o is None:
        return
    try:
        if not o.get(OWNED_PROP) or o.users_collection or _in_use(o):
            return
    except ReferenceError:
        return
    me = o.data
    bpy.data.objects.remove(o)
    if me is not None and me.users == 0:
        bpy.data.meshes.remove(me)


def _linked(ob):
    """(playback modifier, cache object, frozen pieces object) as referenced by the modifier itself,
    so renaming or duplicating the object cannot make us touch the wrong data."""
    pm = core.find_modifier(ob, core.KIND_PLAYBACK)
    if pm is None:
        return None, None, None
    try:
        return pm, core.get_input(pm, "Cache"), core.get_input(pm, "Frozen Pieces")
    except KeyError:
        return pm, None, None


def cache_info(ob):
    """(cache, frozen pieces, piece count, frame count, start frame, fps) of a complete bake, else None.
    Cheap (no array reads), so it is safe to call from panel drawing and operator polls."""
    site = graph.solver_site(ob)
    if site is not None:
        node = site[1]
        baked = bool(node.inputs["Baked"].default_value)
        cache = node.inputs["Cache"].default_value if baked else None
        rest = node.inputs["Frozen Pieces"].default_value if baked else None
    else:
        _, cache, rest = _linked(ob)
    if cache is None or rest is None or cache.type != "MESH" or rest.type != "MESH":
        return None
    if "rbd_pieces" not in cache or "rbd_frames" not in cache:
        return None
    n, f = int(cache["rbd_pieces"]), int(cache["rbd_frames"])
    me = cache.data
    if n * f == 0 or len(me.vertices) != n * f:
        return None
    for mesh, name, data_type in ((me, "rot", "QUATERNION"), (me, "pivot", "FLOAT_VECTOR"), (rest.data, "piece_id", "INT")):
        attr = mesh.attributes.get(name)
        if attr is None or attr.data_type != data_type or attr.domain != "POINT":
            return None
    return cache, rest, n, f, int(cache.get("rbd_frame_start", 1)), float(cache.get("rbd_fps", 24.0))


def is_baked(ob):
    return cache_info(ob) is not None


def unfreeze(ob):
    """Give the modifiers above the playback modifier back the visibility they had before the bake."""
    saved = ob.get(FROZEN_PROP)
    if saved is None:
        return
    saved = dict(saved)
    for m in ob.modifiers:
        vis = saved.get(str(m.persistent_uid))
        if vis is not None:
            m.show_viewport, m.show_render = bool(vis[0]), bool(vis[1])
    del ob[FROZEN_PROP]


def _freeze(ob, pm):
    """Switch off everything above the playback modifier: its result now lives in the frozen pieces,
    so scrubbing the timeline no longer re-runs the fracture every frame."""
    saved = {k: list(v) for k, v in dict(ob.get(FROZEN_PROP) or {}).items()}
    for m in ob.modifiers:
        if m == pm:
            break
        key = str(m.persistent_uid)
        if key not in saved:  # keep the true pre-bake state across re-bakes
            saved[key] = [int(m.show_viewport), int(m.show_render)]
        m.show_viewport = m.show_render = False
    ob[FROZEN_PROP] = saved


def rest_pieces(ob, want_mesh=False, fresh=False):
    """The fractured pieces at rest: (EvalMesh, new Mesh copy or None).

    Baked objects answer from the pieces frozen at bake time, so exports always match the cache.
    Otherwise (and for what a re-bake will see: `want_mesh` or `fresh`) the modifier stack above the
    playback modifier is evaluated. Nothing is left changed on the object: visibilities are put
    back exactly.
    """
    info = cache_info(ob)
    if info is not None and not (want_mesh or fresh):
        return core.EvalMesh(ob, mesh=info[1].data, matrix=info[0].matrix_world), None
    site = graph.solver_site(ob)
    if site is not None:
        return graph.pieces(ob, site[0], site[1], want_mesh=want_mesh)   # what arrives at the solver node
    pm = core.find_modifier(ob, core.KIND_PLAYBACK)
    before = [(m, m.show_viewport) for m in ob.modifiers]
    frozen = dict(ob.get(FROZEN_PROP) or {})
    # what gets simulated is the fracture as it is, not pushed apart for inspection
    frac = core.find_modifier(ob, core.KIND_FRACTURE) if (want_mesh or fresh) else None
    explode = 0.0
    if frac is not None:
        try:
            explode = float(core.get_input(frac, "Exploded View"))
        except KeyError:
            pass
    try:
        if explode:
            core.set_input(frac, "Exploded View", 0.0)
        below = False
        for m in ob.modifiers:
            below = below or m == pm
            if below:
                m.show_viewport = False  # the playback modifier and anything stacked after it
            elif str(m.persistent_uid) in frozen:
                m.show_viewport = bool(frozen[str(m.persistent_uid)][0])
        bpy.context.view_layer.update()
        dg = bpy.context.evaluated_depsgraph_get()
        em = core.EvalMesh(ob, dg)
        me = None
        if want_mesh:
            me = bpy.data.meshes.new_from_object(ob.evaluated_get(dg), preserve_all_data_layers=True, depsgraph=dg)
        return em, me
    finally:
        for m, vis in before:
            m.show_viewport = vis
        if explode:
            _attempt(lambda: core.set_input(frac, "Exploded View", explode))


PLAYBACK_INPUTS = ("Use Frozen Pieces", "Frozen Pieces", "Cache", "Piece Count", "Frame Count", "Start Frame")


def _set_ref(ob, key, target):
    if target is None:
        if key in ob:
            ob[key] = None      # release the pointer before dropping the key, or the user count stays up
            del ob[key]
    else:
        ob[key] = target


def _attempt(fn):
    """Run one step of a rollback or clean-up; a failing step must not stop the remaining ones."""
    try:
        fn()
    except Exception:
        pass


SITE_INPUTS = ("Baked", "Cache", "Frozen Pieces", "Piece Count", "Frame Count", "Cache Start Frame")


def _cache_object(ob, pos, quat, pivots, frame_start, fps, impact, events, contacts):
    """The cache as an object of its own: one point per piece per frame. Nothing is left behind if it fails."""
    f, n = pos.shape[:2]
    cache_mesh = bpy.data.meshes.new(CACHE_PREFIX + ob.name)
    try:
        cache_mesh.vertices.add(f * n)
        cache_mesh.vertices.foreach_set("co", pos.reshape(-1))
        cache_mesh.attributes.new("rot", "QUATERNION", "POINT").data.foreach_set("value", quat.reshape(-1))
        cache_mesh.attributes.new("pivot", "FLOAT_VECTOR", "POINT").data.foreach_set(
            "vector", np.tile(pivots, (f, 1)).reshape(-1))
        cache = bpy.data.objects.new(cache_mesh.name, cache_mesh)
    except Exception:
        bpy.data.meshes.remove(cache_mesh)
        raise
    cache[OWNED_PROP] = 1
    cache["rbd_pieces"], cache["rbd_frames"], cache["rbd_frame_start"], cache["rbd_fps"] = n, f, frame_start, fps
    cache.matrix_world = ob.matrix_world.copy()  # where the object was when it was simulated
    if impact is not None:
        cache["rbd_impact"] = [float(x) for x in impact]
    if events is not None and len(events):
        cache[EVENTS_PROP] = np.asarray(events, np.float64).reshape(-1).tolist()
    if contacts:
        cache[CONTACTS_PROP] = [float(x) for a, b, point, area in contacts for x in (a, b, *point, area)]
    return cache


def _write_site(ob, site, rest_mesh, pos, quat, pivots, frame_start, fps, impact, events, defer, contacts):
    """write_cache() for an object whose solver is an RBD Bullet Solver node: the node gets the cache."""
    node = site[1]
    f, n = pos.shape[:2]
    before = {name: node.inputs[name].default_value for name in SITE_INPUTS}
    made = []

    def undo():
        for name, v in before.items():
            _attempt(lambda name=name, v=v: graph.set_value(node, name, v))
        for o in made:
            me = o.data
            _attempt(lambda o=o: bpy.data.objects.remove(o))
            if me is not rest_mesh:
                _attempt(lambda me=me: bpy.data.meshes.remove(me) if me.users == 0 else None)

    def finish():
        _attempt(lambda: _remove_unused(before["Cache"]))
        _attempt(lambda: _remove_unused(before["Frozen Pieces"]))

    try:
        cache = _cache_object(ob, pos, quat, pivots, frame_start, fps, impact, events, contacts)
        made.append(cache)
        rest_mesh.name = REST_PREFIX + ob.name
        rest = bpy.data.objects.new(rest_mesh.name, rest_mesh)
        rest[OWNED_PROP] = 1
        made.append(rest)
        for name, v in zip(SITE_INPUTS, (True, cache, rest, n, f, frame_start)):
            graph.set_value(node, name, v)
    except Exception:
        undo()
        raise
    if defer:
        return undo, finish
    finish()
    return cache


def write_cache(ob, rest_mesh, pos, quat, pivots, frame_start, fps, impact=None, events=None, defer=False,
                contacts=None):
    """Store a finished simulation on the object. Either everything is in place afterwards, or
    (on any error) the object is as it was: old bake playing, same modifier visibilities, nothing
    new left behind.

    With `defer` the previous bake is not let go yet and (undo, finish) is returned: finish() drops
    the old helper objects, undo() puts the object back exactly as it was before this call. That is
    how several objects are written as one: if a later one fails, the earlier ones are undone."""
    site = graph.solver_site(ob)
    if site is not None:
        return _write_site(ob, site, rest_mesh, pos, quat, pivots, frame_start, fps, impact, events, defer, contacts)
    f, n = pos.shape[:2]
    pm, old_cache, old_rest = _linked(ob)
    ref_before = (ob.get(REF_CACHE), ob.get(REF_REST))
    # the playback modifier may have been deleted by hand: the object still knows its helpers
    old_cache, old_rest = old_cache or ref_before[0], old_rest or ref_before[1]
    snapshot = None
    if pm is not None:
        snapshot = {"group": pm.node_group, "vis": (pm.show_viewport, pm.show_render), "inputs": {}}
        for name in PLAYBACK_INPUTS:
            try:
                snapshot["inputs"][name] = core.get_input(pm, name)
            except KeyError:
                pass
    stack = [(m, m.show_viewport, m.show_render) for m in ob.modifiers]
    frozen_before = ob.get(FROZEN_PROP)
    frozen_before = {k: list(v) for k, v in dict(frozen_before).items()} if frozen_before is not None else None
    created_pm = False
    cache = rest = cache_mesh = None

    def undo():
        # put the object back as it was; every step on its own, so one failing step cannot strand the rest
        if created_pm:
            _attempt(lambda: ob.modifiers.remove(pm))
        elif pm is not None and snapshot is not None:
            _attempt(lambda: setattr(pm, "node_group", snapshot["group"]))
            for name, value in snapshot["inputs"].items():
                _attempt(lambda name=name, value=value: core.set_input(pm, name, value))
            _attempt(lambda: setattr(pm, "show_viewport", snapshot["vis"][0]))
            _attempt(lambda: setattr(pm, "show_render", snapshot["vis"][1]))
        for m, sv, sr in stack:
            _attempt(lambda m=m, sv=sv: setattr(m, "show_viewport", sv))
            _attempt(lambda m=m, sr=sr: setattr(m, "show_render", sr))
        if frozen_before is None:
            _attempt(lambda: ob.pop(FROZEN_PROP, None))
        else:
            _attempt(lambda: ob.__setitem__(FROZEN_PROP, frozen_before))
        _attempt(lambda: _set_ref(ob, REF_CACHE, ref_before[0]))
        _attempt(lambda: _set_ref(ob, REF_REST, ref_before[1]))
        for o in (cache, rest):
            if o is not None:
                _attempt(lambda o=o: bpy.data.objects.remove(o))
        if cache_mesh is not None:
            _attempt(lambda: bpy.data.meshes.remove(cache_mesh) if cache_mesh.users == 0 else None)

    def finish():
        # The new bake is fully in place. Letting go of the old one is clean-up: if it fails, the
        # worst case is a leftover helper object, never a broken bake.
        _attempt(lambda: _remove_unused(old_cache))
        _attempt(lambda: _remove_unused(old_rest))

    try:
        cache_mesh = bpy.data.meshes.new(CACHE_PREFIX + ob.name)
        cache_mesh.vertices.add(f * n)
        cache_mesh.vertices.foreach_set("co", pos.reshape(-1))
        cache_mesh.attributes.new("rot", "QUATERNION", "POINT").data.foreach_set("value", quat.reshape(-1))
        cache_mesh.attributes.new("pivot", "FLOAT_VECTOR", "POINT").data.foreach_set(
            "vector", np.tile(pivots, (f, 1)).reshape(-1))
        cache = bpy.data.objects.new(cache_mesh.name, cache_mesh)
        cache[OWNED_PROP] = 1
        cache["rbd_pieces"], cache["rbd_frames"], cache["rbd_frame_start"], cache["rbd_fps"] = n, f, frame_start, fps
        cache.matrix_world = ob.matrix_world.copy()  # where the object was when it was simulated
        if impact is not None:
            cache["rbd_impact"] = [float(x) for x in impact]
        if events is not None and len(events):
            cache[EVENTS_PROP] = np.asarray(events, np.float64).reshape(-1).tolist()
        if contacts:
            # which pieces touched which when this was simulated: a, b, x, y, z, area per pair
            cache[CONTACTS_PROP] = [float(x) for a, b, point, area in contacts for x in (a, b, *point, area)]
        rest_mesh.name = REST_PREFIX + ob.name
        rest = bpy.data.objects.new(rest_mesh.name, rest_mesh)
        rest[OWNED_PROP] = 1
        tree = nodes_playback.ensure()
        if pm is None:
            pm = ob.modifiers.new(core.MOD_PLAYBACK, "NODES")
            created_pm = True
        pm.node_group = tree
        for name, value in zip(PLAYBACK_INPUTS, (True, rest, cache, n, f, frame_start)):
            core.set_input(pm, name, value)
        pm.show_viewport = pm.show_render = True
        _freeze(ob, pm)
        _set_ref(ob, REF_CACHE, cache)
        _set_ref(ob, REF_REST, rest)
    except Exception:
        undo()
        raise
    if defer:
        return undo, finish
    finish()
    return cache


def read_cache(ob):
    """(pos[F,N,3], quat[F,N,4] wxyz, pivots[N,3], frame_start) in the bake-time world frame,
    or None if nothing is baked."""
    info = cache_info(ob)
    if info is None:
        return None
    cache, _, n, f, start, _ = info
    me = cache.data
    pos = np.empty(n * f * 3, np.float32)
    me.vertices.foreach_get("co", pos)
    quat = np.empty(n * f * 4, np.float32)
    me.attributes["rot"].data.foreach_get("value", quat)
    piv = np.empty(n * f * 3, np.float32)
    me.attributes["pivot"].data.foreach_get("vector", piv)
    return pos.reshape(f, n, 3), quat.reshape(f, n, 4), piv.reshape(f, n, 3)[0].copy(), start


def free_cache(ob):
    site = graph.solver_site(ob)
    if site is not None:
        node = site[1]
        held = [node.inputs["Cache"].default_value, node.inputs["Frozen Pieces"].default_value]
        for name, v in zip(SITE_INPUTS, (False, None, None, 0, 0, 1)):
            graph.set_value(node, name, v)
        for o in held:
            _attempt(lambda o=o: _remove_unused(o))
        return
    pm, cache, rest = _linked(ob)
    # Everything that might be a helper of this object: what the modifier points at and what the
    # object itself remembers (the modifier may have been deleted or re-pointed by hand).
    # _remove_unused() only ever deletes objects that carry our marker.
    candidates = [o for o in (cache, rest, ob.get(REF_CACHE), ob.get(REF_REST)) if o is not None]
    if pm is not None:
        # clear the pointers first: removing a modifier does not release the objects its inputs point to
        for name in ("Cache", "Frozen Pieces"):
            try:
                core.set_input(pm, name, None)
            except KeyError:
                pass
        ob.modifiers.remove(pm)
    _set_ref(ob, REF_CACHE, None)
    _set_ref(ob, REF_REST, None)
    for o in candidates:
        _attempt(lambda o=o: _remove_unused(o))
    unfreeze(ob)


# ------------------------------------------------------------------ what gets glued to what
def contact_area(points):
    """Area of the convex hull of (roughly coplanar) points: the size of the face two pieces share."""
    if len(points) < 3:
        return 0.0
    q = points - points.mean(0)
    _, _, vt = np.linalg.svd(q, full_matrices=False)
    xy = q @ vt[:2].T
    xy = xy[np.lexsort((xy[:, 1], xy[:, 0]))]

    def half(pts):
        h = []
        for p in pts:
            while len(h) >= 2 and (h[-1][0] - h[-2][0]) * (p[1] - h[-2][1]) - (h[-1][1] - h[-2][1]) * (p[0] - h[-2][0]) <= 0:
                h.pop()
            h.append(p)
        return h
    hull = half(xy)[:-1] + half(xy[::-1])[:-1]
    if len(hull) < 3:
        return 0.0
    hull = np.array(hull)
    x, y = hull[:, 0], hull[:, 1]
    return 0.5 * abs(float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1))))


SLIVER = 1e-3   # contacts smaller than this fraction of the median contact are not worth a bond


def adjacency(em, n, touch=None):
    """Pairs of pieces that share a cut face: [(piece a, piece b, contact point, contact area)].

    Two neighbouring pieces were cut by the same plane out of the same mesh, so the corners of
    their shared face coincide. Vertices are hashed on two half-offset grids so that a pair
    sitting on a cell border of one grid is still caught by the other; the points a pair shares
    then give the area of their contact. Touching along an edge or at a corner has no area and
    is not a bond, and neither are slivers far smaller than the usual contact.

    Pieces that were not cut (loose parts) are matched by touching faces instead, see _touching():
    `touch` is how close their faces must be, in metres (default: a hair's breadth for the object).
    """
    co = em.proxy_co
    span = float(np.linalg.norm(co.max(0) - co.min(0))) or 1.0
    h = max(span * 2e-4, 1e-6)
    if len(em.inside) and not em.inside.any():
        return _bonds(_touching(em, h if touch is None else max(float(touch), 1e-6)))
    shared = {}
    for shift in (0.0, 0.5):
        key = np.floor(co / h + shift).astype(np.int64)
        order = np.lexsort((key[:, 2], key[:, 1], key[:, 0]))
        k = key[order]
        new = np.ones(len(k), bool)
        new[1:] = np.any(k[1:] != k[:-1], axis=1)
        starts = np.flatnonzero(new)
        ends = np.append(starts[1:], len(k))
        for s, e in zip(starts, ends):
            if e - s < 2:
                continue
            idx = order[s:e]
            ps = np.unique(em.piece[idx])
            if len(ps) < 2:
                continue
            c = co[idx].mean(0)
            for a in range(len(ps)):
                for bq in range(a + 1, len(ps)):
                    shared.setdefault((int(ps[a]), int(ps[bq])), []).append(c)
    return _bonds(shared)


def _touching(em, tol):
    """Contact points between pieces that were modelled separately: {(a, b): [points]}.

    Their faces touch, but their corners need not coincide (bricks laid in a running bond). A corner
    of one piece that lies on a face of another piece is a point of their contact; for two flat
    faces that overlap, those corners outline the overlap."""
    from mathutils.bvhtree import BVHTree
    co = em.proxy_co.astype(np.float64)
    tri_piece = em.piece[em.tris[:, 0]]
    bvh = BVHTree.FromPolygons(co.tolist(), em.tris.tolist())
    shared = {}
    for i, p in enumerate(co.tolist()):
        own = int(em.piece[i])
        seen = {own}
        for location, normal, tri, distance in bvh.find_nearest_range(p, tol):
            other = int(tri_piece[tri])
            if other in seen:
                continue
            # Across a gap, only a face the corner looks straight at counts (the offset runs along the
            # face normal). Otherwise parts that merely pass each other's corners would be glued.
            if distance > 1e-7 and abs((Vector(p) - location).dot(normal)) < 0.95 * distance:
                continue
            seen.add(other)
            shared.setdefault((min(own, other), max(own, other)), []).append(p)
    return shared


def _bonds(shared):
    """[(piece a, piece b, contact point, contact area)] from the points each pair has in common."""
    found = []
    for (a, bq), pts in shared.items():
        p = np.array(pts, np.float64)
        area = contact_area(p)
        if area > 0.0:
            found.append((a, bq, p.mean(0), area))
    if not found:
        return []
    typical = float(np.median([f[3] for f in found]))
    return [f for f in found if f[3] >= SLIVER * typical]


def clusters(pivots, pieces_per_cluster, rng):
    """Group pieces into chunks: every piece joins the nearest of a few randomly chosen pieces."""
    n = len(pivots)
    k = max(1, int(round(n / max(pieces_per_cluster, 1))))
    centres = pivots[rng.choice(n, size=min(k, n), replace=False)]
    d = np.linalg.norm(pivots[:, None, :] - centres[None, :, :], axis=2)
    return np.argmin(d, axis=1), len(centres)


@dataclass
class GluePlan:
    pairs: list                 # (piece a, piece b, contact point, contact area)
    strength: np.ndarray        # per bond, in the units of Glue Strength (before the mass of the pieces)
    cluster_of: object          # per piece cluster index, or None
    n_clusters: int = 0


def glue_plan(em, pivots, st):
    """Which pieces are glued, how strongly, and which cluster each piece is in. The bake and the
    viewport preview both use this, so the preview shows exactly what will be simulated."""
    n = em.n_pieces
    pairs = adjacency(em, n, st.glue_distance) if st.use_glue else []
    rng = np.random.default_rng([st.seed, 7])   # its own stream: the same plan whatever else is randomised
    cluster_of, n_clusters = None, 0
    if pairs and st.cluster_pieces > 1:
        cluster_of, n_clusters = clusters(pivots, st.cluster_pieces, rng)
    typical_area = float(np.median([p[3] for p in pairs])) if pairs else 1.0
    strength = np.zeros(len(pairs))
    for i, (a, bq, _, area) in enumerate(pairs):
        k = st.glue_strength * (1.0 + st.glue_variation * rng.uniform(-1.0, 1.0))
        # a bond over a small contact is weaker than one over a large contact (clamped, so one
        # odd face cannot dominate): cracks then run through the thin connections first
        k *= float(np.clip(np.sqrt(area / max(typical_area, 1e-12)), 0.35, 2.5))
        if cluster_of is not None and cluster_of[a] == cluster_of[bq]:
            k *= st.cluster_strength
        strength[i] = max(k, 0.0)
    return GluePlan(pairs, strength, cluster_of, n_clusters)


# ------------------------------------------------------------------ crack events
EVENTS_PROP = "rbd_events"
CONTACTS_PROP = "rbd_contacts"
EVENT_FIELDS = 6   # frame index, x, y, z, size, speed
EVENT_CHUNK = 2_000_000   # frames x pairs worked on at a time: the work arrays stay within tens of megabytes


def _rotate(q, v):
    """Rotate vectors by wxyz quaternions (numpy, broadcasting)."""
    w, u = q[..., :1], q[..., 1:]
    t = 2.0 * np.cross(u, v)
    return v + w * t + np.cross(u, t)


def _gaps(pos, quat, pivots, part):
    """The contact point of every pair in `part`, carried along by each of its two pieces:
    (point on a [frames, pairs, 3], point on b, their distance [frames, pairs], size of the contact [pairs])."""
    a = np.array([p[0] for p in part])
    b = np.array([p[1] for p in part])
    c = np.array([p[2] for p in part], np.float64)
    size = np.sqrt(np.array([p[3] for p in part], np.float64))
    ca = pos[:, a] + _rotate(quat[:, a], (c - pivots[a]).astype(np.float32)[None])
    cb = pos[:, b] + _rotate(quat[:, b], (c - pivots[b]).astype(np.float32)[None])
    return ca, cb, np.linalg.norm(ca - cb, axis=-1), size


def _apart_distance(size):
    """How far the two copies of a contact point must be from each other to call the pieces apart."""
    return np.maximum(0.05 * size, 0.002)


def crack_events(pos, quat, pivots, pairs, fps):
    """When and where neighbouring pieces come apart: at most one event per shared cut face.

    The contact point of a pair is carried along by each of its two pieces. The crack opens on the
    first frame after the last one on which the two copies still coincide, and only if they are apart
    at the end (a bond that flexes and settles again is not a crack).
    Rows, sorted by frame: frame index (0 = first cached frame), x, y, z (bake-time world space,
    half-way between the two pieces), size (square root of the contact area, metres), opening
    speed (m/s)."""
    frames = len(pos)
    if not pairs or frames < 2:
        return np.zeros((0, EVENT_FIELDS), np.float32)
    rows = []
    step = max(1, EVENT_CHUNK // frames)
    for lo in range(0, len(pairs), step):
        ca, cb, gap, size = _gaps(pos, quat, pivots, pairs[lo:lo + step])
        apart = gap > _apart_distance(size)[None]
        apart[0] = False                                            # the first frame is the rest pose
        k = frames - np.argmax(~apart[::-1], axis=0)                # first frame after the last "together"
        e = np.flatnonzero(apart[-1])
        k = k[e]
        mid = 0.5 * (ca[k, e] + cb[k, e])
        speed = (gap[k, e] - gap[k - 1, e]) * fps
        rows.append(np.column_stack([k, mid, size[e], speed]).astype(np.float32))
    out = np.concatenate(rows)
    return out[np.argsort(out[:, 0], kind="stable")]


def read_contacts(ob):
    """[(piece a, piece b, contact point, contact area)] as found when the object was baked, or None if
    nothing is baked."""
    info = cache_info(ob)
    if info is None:
        return None
    raw = info[0].get(CONTACTS_PROP)
    if raw is None:                 # nothing touched, or baked before contacts were kept: look again
        em = rest_pieces(ob)[0]
        return adjacency(em, em.n_pieces)
    rows = np.array(list(raw), np.float64).reshape(-1, 6)
    return [(int(r[0]), int(r[1]), r[2:5].copy(), float(r[5])) for r in rows]


def unbroken_groups(pos, quat, pivots, contacts, radius=None, limit=0.003):
    """Which pieces can be treated as one piece: (group per piece, number of groups, index of the
    group that never moves or -1, one representative piece per group).

    Two neighbours whose shared contact point never comes apart during the whole bake move as one
    body; the groups are connected sets of such neighbours. Everything that does not move at all
    goes into one group, whether it touches or not, and so does whatever never comes apart from it.

    A group takes the motion of one of its pieces. `limit` (metres) is the promise that comes with
    that: no point of a merged piece, within `radius` of its pivot, is ever further than this from
    where its own motion had it. Small drifts add up along a chain of neighbours, so a piece far
    down the chain may not follow the group's stand-in closely enough: those pieces are grouped
    again among themselves, in a few rounds, and what is left keeps its own motion."""
    n, frames = len(pivots), len(pos)
    radius = np.zeros(n) if radius is None else np.asarray(radius, np.float64)
    step = max(1, EVENT_CHUNK // max(frames, 1))
    stays = []
    for lo in range(0, len(contacts), step):
        part = contacts[lo:lo + step]
        _, _, gap, _ = _gaps(pos, quat, pivots, part)
        stays += [(a, b) for (a, b, _, _), together in zip(part, (gap <= limit).all(0).tolist()) if together]
    travel = np.linalg.norm(pos - pivots[None], axis=-1).max(0)
    turn = 2.0 * np.arccos(np.clip(np.abs(quat[..., 0]), 0.0, 1.0)).max(0)
    rest = np.flatnonzero(travel + turn * radius < 0.2 * limit).tolist()
    static = rest[0] if rest else -1

    def strays(p, r):
        """How far the pieces p get from where the motion of their stand-ins r would have them."""
        out = np.zeros(len(p))
        for lo in range(0, len(p), step):
            pp, rr = p[lo:lo + step], r[lo:lo + step]
            where = pos[:, rr] + _rotate(quat[:, rr], (pivots[pp] - pivots[rr]).astype(np.float32)[None])
            apart = np.linalg.norm(pos[:, pp] - where, axis=-1)
            angle = 2.0 * np.arccos(np.clip(np.abs(np.sum(quat[:, pp] * quat[:, rr], axis=-1)), 0.0, 1.0))
            out[lo:lo + step] = (apart + angle * radius[pp][None]).max(0)
        return out

    stand_in = np.full(n, -1)                   # the piece each piece takes its motion from
    pending = np.ones(n, bool)
    for round_ in range(8):
        todo = np.flatnonzero(pending)
        if not len(todo):
            break
        parent = {i: i for i in todo.tolist()}

        def find(i):
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i

        for a, b in stays:
            if pending[a] and pending[b]:
                parent[find(a)] = find(b)
        if round_ == 0:
            for i in rest[1:]:
                parent[find(i)] = find(static)
        lead = {}
        for i in todo.tolist():
            lead.setdefault(find(i), i)
        if round_ == 0 and static >= 0:
            lead[find(static)] = static         # the still group moves like a piece that is still
        leads = np.array([lead[find(i)] for i in todo.tolist()])
        follows = strays(todo, leads) <= limit  # a lead always follows itself
        if round_ == 0 and static >= 0:
            # the still group does not move at all (not even the little its stand-in does): what
            # counts for its pieces is how far they get from their own rest pose
            still = leads == static
            follows[still] = (travel + turn * radius)[todo[still]] <= limit
        stand_in[todo[follows]] = leads[follows]
        pending[todo[follows]] = False
    left = np.flatnonzero(pending)
    stand_in[left] = left
    order = ([static] if static >= 0 else [])
    seen = set(order)
    for r in stand_in.tolist():
        if r not in seen:
            seen.add(r)
            order.append(r)
    index = {r: k for k, r in enumerate(order)}
    group = np.array([index[r] for r in stand_in.tolist()], np.int32)
    return group, len(order), (0 if static >= 0 else -1), np.array(order, np.int32)


def read_events(ob):
    """Crack events of the bake on this object, [E, 6] (see crack_events), or None if nothing is baked."""
    info = cache_info(ob)
    if info is None:
        return None
    raw = info[0].get(EVENTS_PROP)
    if raw is None:
        return np.zeros((0, EVENT_FIELDS), np.float32)
    return np.array(list(raw), np.float32).reshape(-1, EVENT_FIELDS)


# ------------------------------------------------------------------ glue preview in the viewport
GLUE_PREFIX = "RBD Glue."
REF_GLUE = "hrbd_glue_preview"


GLUE_MARK = "hrbd_glue_lines"   # marks a preview object, so previews nobody shows any more can be found


def _sweep_glue_previews():
    """Delete the previews that no object refers to: replaced ones, and those of deleted objects.
    A preview that a duplicate of the object still shows is in use and stays."""
    used = {o.get(REF_GLUE) for o in bpy.data.objects} - {None}
    for o in [o for o in bpy.data.objects if o.get(GLUE_MARK) and o.get(OWNED_PROP) and o not in used]:
        me = o.data
        bpy.data.objects.remove(o)
        if me is not None and me.users == 0:
            bpy.data.meshes.remove(me)


def remove_glue_preview(ob):
    _set_ref(ob, REF_GLUE, None)
    _sweep_glue_previews()


def build_glue_preview(context, ob, st):
    """A wireframe of the glue network: one vertex per piece (its centre), one edge per bond.
    Edge attribute "strength" and point attribute "cluster" hold what the bake will use.
    It is a snapshot of the settings at this moment; it follows the object when that is moved.
    Returns (preview object or None, GluePlan). On an error the previous preview is still there."""
    em, _ = rest_pieces(ob, fresh=True)      # what a bake started now would simulate
    if not em.has_pieces:
        raise RuntimeError("Add an RBD Fracture to the object first.")
    _collision_points(ob, em)
    pivots = em.piece_centroids(em.proxy_co)
    plan = glue_plan(em, pivots, st)
    preview = me = None
    if plan.pairs:
        try:
            me = bpy.data.meshes.new(GLUE_PREFIX + ob.name)
            me.from_pydata(pivots.tolist(), [(a, b) for a, b, _, _ in plan.pairs], [])
            me.attributes.new("strength", "FLOAT", "EDGE").data.foreach_set("value", plan.strength.astype(np.float32))
            cluster = plan.cluster_of if plan.cluster_of is not None else np.zeros(len(pivots), int)
            me.attributes.new("cluster", "INT", "POINT").data.foreach_set("value", np.asarray(cluster, np.int32))
            preview = bpy.data.objects.new(me.name, me)
            preview[OWNED_PROP] = preview[GLUE_MARK] = 1
            preview.display_type, preview.show_in_front = "WIRE", True
            preview.hide_select = preview.hide_render = True
            (ob.users_collection[0] if ob.users_collection else context.scene.collection).objects.link(preview)
            # the vertices are where the pieces are in the world right now; from here on they follow the object
            preview.parent = ob
            preview.matrix_parent_inverse = ob.matrix_world.inverted()
        except Exception:
            if preview is not None:
                _attempt(lambda: bpy.data.objects.remove(preview))
            if me is not None:
                _attempt(lambda: bpy.data.meshes.remove(me) if me.users == 0 else None)
            raise
    try:
        _set_ref(ob, REF_GLUE, preview)      # only now is the old preview let go
    except Exception:
        if preview is not None:
            _attempt(lambda: bpy.data.objects.remove(preview))
            _attempt(lambda: bpy.data.meshes.remove(me) if me.users == 0 else None)
        raise
    _attempt(_sweep_glue_previews)
    return preview, plan


# ------------------------------------------------------------------ the bake
def _collision_points(ob, em, notes=None):
    """Settle which positions describe the collision shapes (em.proxy_co).

    rbd_rest is the flat shape before the interior noise of the fracture. If something after the
    fracture deformed the mesh further (a Displace modifier, say) it no longer describes the pieces,
    and the visible shape is used instead."""
    if em.proxy_co is em.co:
        return
    allowed = 0.0
    frac = core.find_modifier(ob, core.KIND_FRACTURE)
    site = graph.solver_site(ob)
    if site is not None:
        # RBD nodes: the largest noise any RBD Material Fracture node in the tree may have added
        scale = float(np.linalg.svd(em.matrix[:3, :3], compute_uv=False).max())
        for node in graph.rbd_nodes(site[0].node_group, nodes_rbd.KIND_MATERIAL_FRACTURE):
            try:
                allowed = max(allowed, 2.05 * float(graph.value(node, "Noise Amplitude")) * scale + 1e-5)
            except RuntimeError:        # driven by another node: any amount is possible
                allowed = float("inf")
    elif frac is not None:
        try:
            # the noise moves a vertex by at most sqrt(3) x Noise Height in local space;
            # positions here are in world space, so the object scale comes on top
            scale = float(np.linalg.svd(em.matrix[:3, :3], compute_uv=False).max())
            allowed = 2.05 * float(core.get_input(frac, "Noise Height")) * scale + 1e-5
        except KeyError:
            pass
    if float(np.linalg.norm(em.co - em.proxy_co, axis=1).max()) > allowed:
        em.proxy_co = em.co
        if notes is not None:
            notes.append("the mesh is deformed after the fracture: collisions use the deformed shape")


# Modifiers that build or refine a mesh the same way on every frame (unless their settings are animated,
# which is not looked at). A collider that only has these keeps its shape.
STATIC_MODIFIERS = {"SUBSURF", "MULTIRES", "BEVEL", "SOLIDIFY", "MIRROR", "ARRAY", "TRIANGULATE", "WELD", "EDGE_SPLIT",
                    "DECIMATE", "REMESH", "WEIGHTED_NORMAL", "NORMAL_EDIT", "UV_PROJECT", "UV_WARP", "DATA_TRANSFER",
                    "SMOOTH", "LAPLACIANSMOOTH", "CORRECTIVE_SMOOTH", "WIREFRAME", "SKIN", "SCREW", "MASK"}


def _changes_shape(src):
    """Can the mesh of this collider change during the simulation (armature, shape keys, a cache...)?"""
    keys = src.data.shape_keys
    if keys is not None and len(keys.key_blocks) > 1:
        return True
    return any(m.show_viewport and m.type not in STATIC_MODIFIERS for m in src.modifiers)


def settle(pos, quat, distance=5e-4, angle=2e-3):
    """Lock every piece in its final pose from the moment it no longer leaves it (in place).

    A piece lying on the ground keeps trembling by fractions of a millimetre in the solver. From the
    first frame after which it stays within `distance` metres and `angle` radians of where it ends,
    it is put exactly there: truly still, which is also what compresses best in an engine.
    A piece that never gets further than that from where it ends has not really moved at all: it is
    kept in its first pose instead, so that the first frame stays the unbroken model.
    Returns how many pieces were locked before the last frame."""
    frames = len(pos)
    if frames < 2:
        return 0
    near = np.linalg.norm(pos - pos[-1][None], axis=-1) < distance
    near &= 2.0 * np.arccos(np.clip(np.abs(np.sum(quat * quat[-1][None], axis=-1)), 0.0, 1.0)) < angle
    # the first frame of the last unbroken stretch of "near" (the last frame is always near itself)
    first = frames - np.argmax(~near[::-1], axis=0)
    never = near.all(0)
    first[never] = frames                     # handled separately below
    lock = np.arange(frames)[:, None] >= first[None]
    pos[lock] = np.broadcast_to(pos[-1][None], pos.shape)[lock]
    quat[lock] = np.broadcast_to(quat[-1][None], quat.shape)[lock]
    pos[:, never] = pos[0, never][None]
    quat[:, never] = quat[0, never][None]
    return int((first < frames - 1).sum() + never.sum())


def settings_from_node(node):
    """The settings typed into an RBD Bullet Solver node."""
    val = lambda name: graph.value(node, name)          # noqa: E731
    return SimSettings(
        frame_start=int(val("Start Frame")), frame_end=int(val("End Frame")), substeps=int(val("Bullet Substeps")),
        solver_iterations=int(val("Constraint Iterations")), glue_iterations=int(val("Glue Iterations")),
        density=float(val("Density")), friction=float(val("Friction")), bounce=float(val("Bounce")),
        collision_margin=float(val("Collision Padding")), linear_damping=float(val("Linear Damping")),
        angular_damping=float(val("Angular Damping")), start_asleep=bool(val("Start Asleep")),
        use_ground=bool(val("Ground Plane")), ground_z=float(val("Ground Height")),
        collider_collection=val("Collision Objects"), gravity=tuple(val("Gravity")),
        use_fields=bool(val("Force Fields")), field_weight=float(val("Field Weight")),
        field_collection=val("Limit To"))


class _Job:
    """One object taking part in a bake."""

    def __init__(self, ob):
        self.ob = ob
        self.res = BakeResult()
        self.em = self.rest_mesh = None
        self.bodies = []          # the temporary rigid body objects, one per piece


def bake(context, ob, st: SimSettings, progress=None):
    """Simulate one object and store the result on it. See bake_many()."""
    return bake_many(context, [ob], st, progress)[0]


def bake_many(context, objects, st: SimSettings = None, progress=None):
    """Simulate the pieces of all the objects in one Bullet world, so they collide with each other,
    and store each object's motion on that object. Returns one BakeResult per object.

    Glue only holds pieces of the same object together. Nothing is changed on any object unless the
    whole bake succeeds: all of the objects get their new cache, or none of them."""
    t_all = time.perf_counter()
    nodes_rbd.refresh()        # a file from an older version: its RBD nodes get the inputs added since
    scene = context.scene
    fps = scene.render.fps / scene.render.fps_base
    jobs = [_Job(ob) for ob in objects]
    if st is None:
        # RBD nodes: the settings are on the solver node of the first object
        site = graph.solver_site(objects[0])
        if site is None:
            raise RuntimeError(f'"{objects[0].name}" has no RBD Bullet Solver node.')
        st = settings_from_node(site[1])
        if st.frame_end < st.frame_start:
            raise RuntimeError("The End Frame of the solver is before its Start Frame.")
    made_objects, made_meshes, made_collections = [], [], []
    sim = None
    try:
        for job in jobs:
            ob, res = job.ob, job.res
            who = f'"{ob.name}": ' if len(jobs) > 1 else ""
            em, job.rest_mesh = rest_pieces(ob, want_mesh=True)
            job.em = em
            if not em.has_pieces:
                if graph.solver_site(ob) is not None:
                    raise RuntimeError(who + "No pieces arrive at the RBD Bullet Solver node. Wire an RBD Material "
                                             "Fracture node into its Geometry input (the mesh must be a closed volume).")
                if core.find_modifier(ob, core.KIND_FRACTURE) is None:
                    raise RuntimeError(who + "Add an RBD Fracture to the object first.")
                raise RuntimeError(who + "The fracture produced no pieces. The mesh must be a closed volume: "
                                   "give flat sheets thickness (Solidify) and close holes.")
            size = float(np.linalg.norm(em.co.max(0) - em.co.min(0)))
            if size < 0.2:
                res.notes.append(f"the object is only {size * 100:.0f} cm across: Bullet is not accurate at this scale "
                                 "(expect millimetre-deep penetrations); scale it up if you can")
            n = em.n_pieces
            _collision_points(ob, em, res.notes)
            # mass and centre of mass come from the flat collision shape, not from the roughened faces
            pivots = em.piece_centroids(em.proxy_co)
            volumes = em.piece_volumes(em.proxy_co)
            bad = int((volumes <= 1e-12).sum())
            if bad:
                # open or inside-out pieces have no usable volume: weigh them by their bounding box instead
                lo = np.full((n, 3), np.inf)
                hi = np.full((n, 3), -np.inf)
                np.minimum.at(lo, em.piece, em.co)
                np.maximum.at(hi, em.piece, em.co)
                volumes = np.where(volumes > 1e-12, volumes, np.prod(np.maximum(hi - lo, 1e-4), axis=1) * 0.5)
                res.notes.append(f"{bad} pieces are not watertight: their mass is estimated from the bounding box")
            zmin = np.full(n, np.inf)
            np.minimum.at(zmin, em.piece, em.co[:, 2])
            anchored = np.zeros(n, bool)
            if st.anchor_bottom:
                anchored = zmin <= float(em.co[:, 2].min()) + st.anchor_height
            if em.anchor is not None:
                # painted anchors: a piece stays when most of it is painted
                painted = (np.bincount(em.piece, weights=em.anchor, minlength=n)
                           / np.maximum(np.bincount(em.piece, minlength=n), 1)) >= 0.5
                anchored = anchored | painted
                if not painted.any():
                    res.notes.append("the anchor group does not anchor any piece: paint weights above 0.5 where "
                                     "pieces must stay")
            # what RBD nodes wrote on the pieces (each value is the average over the piece)
            density = em.per_piece(nodes_rbd.ATTR_DENSITY)
            active = em.per_piece(nodes_rbd.ATTR_ACTIVE)
            if active is not None:
                anchored = anchored | (active < 0.5)
            # (a negative value means "not set for this piece": the value of the solver is used)
            job.friction, job.bounce = em.per_piece(nodes_rbd.ATTR_FRICTION), em.per_piece(nodes_rbd.ATTR_BOUNCE)
            if job.friction is not None:
                job.friction = np.where(job.friction < 0.0, st.friction, job.friction)
            if job.bounce is not None:
                job.bounce = np.where(job.bounce < 0.0, st.bounce, job.bounce)
            if density is not None:
                density = np.where(density <= 0.0, st.density, density)
            # velocities point in the directions of the object, but their size is metres per second in the
            # world: an object that is scaled up does not throw its pieces faster
            turn = em.matrix[:3, :3] / np.maximum(np.linalg.norm(em.matrix[:3, :3], axis=0), 1e-12)
            v, w = em.per_piece(nodes_rbd.ATTR_VELOCITY), em.per_piece(nodes_rbd.ATTR_SPIN)
            job.v = None if v is None else v @ turn.T
            job.w = None if w is None else w @ turn.T
            job.activate = em.per_piece(nodes_rbd.ATTR_ACTIVATE)
            job.site = graph.solver_site(ob)
            # RBD nodes: what collides is the proxy geometry that arrives at the solver node
            job.shapes = graph.proxy(ob, job.site[0], job.site[1]) if job.site is not None else {}
            job.n, job.pivots, job.anchored, job.zmin = n, pivots, anchored, zmin
            job.mass = np.maximum(volumes * (st.density if density is None else np.maximum(density, 1e-6)), 1e-4)
            res.pieces, res.anchored = n, int(anchored.sum())
        lo_all = np.min([job.em.co.min(0) for job in jobs], axis=0)
        hi_all = np.max([job.em.co.max(0) for job in jobs], axis=0)
        extent = float(np.linalg.norm(hi_all - lo_all))

        sim = bpy.data.scenes.new(SIM_SCENE)
        sim.render.fps, sim.render.fps_base = scene.render.fps, scene.render.fps_base
        # The solver starts one frame early. Bullet only picks up the velocity of an animated body
        # from the second simulated step on, so a burst on the first visible frame needs this lead-in.
        sim.frame_start, sim.frame_end = st.frame_start - PRE_ROLL, st.frame_end
        sim.use_gravity, sim.gravity = scene.use_gravity, scene.gravity
        if st.gravity is not None:
            sim.use_gravity, sim.gravity = True, st.gravity
        with context.temp_override(scene=sim):
            bpy.ops.rigidbody.world_add()
        rbw = sim.rigidbody_world
        for attr, label in (("collection", "H-Style RBD Nodes Bodies"), ("constraints", "H-Style RBD Nodes Glue")):
            c = bpy.data.collections.new(label)
            setattr(rbw, attr, c)
            made_collections.append(c)
        tmp = bpy.data.collections.new("H-Style RBD Nodes Temp")
        sim.collection.children.link(tmp)
        made_collections.append(tmp)
        rbw.substeps_per_frame, rbw.solver_iterations = st.substeps, st.solver_iterations
        rbw.point_cache.frame_start, rbw.point_cache.frame_end = st.frame_start - PRE_ROLL, st.frame_end

        def add_object(name, data):
            o = bpy.data.objects.new(name, data)
            tmp.objects.link(o)
            made_objects.append(o)
            return o

        handover = {}        # {frame: the bodies that are handed to the solver on that frame}
        for index, job in enumerate(jobs):
            em, res, n, pivots, mass, anchored = job.em, job.res, job.n, job.pivots, job.mass, job.anchored
            # the first object draws the same random numbers as when it is baked alone
            rng = np.random.default_rng([st.seed, 3] if index == 0 else [st.seed, 3, index])
            order = np.argsort(em.piece, kind="stable")
            bounds = np.append(0, np.cumsum(np.bincount(em.piece, minlength=n)))
            for i in range(n):
                idx = order[bounds[i]:bounds[i + 1]]
                me = bpy.data.meshes.new(f"rbdp{i:05d}")
                me.vertices.add(len(job.shapes[i]) if i in job.shapes else len(idx))
                # collision shape = convex hull of the proxy geometry of the piece; without one, of the
                # flat (pre-detail) piece itself
                shape = job.shapes.get(i)
                if shape is None:
                    shape = em.proxy_co[idx]
                me.vertices.foreach_set("co", (shape - pivots[i]).astype(np.float32).reshape(-1))
                made_meshes.append(me)
                o = add_object(me.name, me)
                o.location = pivots[i]
                rbw.collection.objects.link(o)
                rb = o.rigid_body
                rb.collision_shape = "CONVEX_HULL"
                rb.type = "PASSIVE" if anchored[i] else "ACTIVE"
                rb.mass = float(mass[i])
                rb.friction = st.friction if job.friction is None else float(job.friction[i])
                rb.restitution = st.bounce if job.bounce is None else float(min(max(job.bounce[i], 0.0), 1.0))
                rb.linear_damping, rb.angular_damping = st.linear_damping, st.angular_damping
                rb.use_margin, rb.collision_margin = True, st.collision_margin
                rb.use_deactivation = True
                rb.use_start_deactivated = st.start_asleep
                job.bodies.append(o)

            # H-Style control of when and how a piece is handed to the solver.
            # Until its release frame a piece is "animated" (held in place). A burst moves it for one
            # frame while it is still animated; Bullet then takes over with exactly that velocity.
            release = np.full(n, st.frame_start, int)
            if st.activation == "RADIAL" and st.activation_speed > 0:
                dist = np.linalg.norm(pivots - np.asarray(st.activation_origin, np.float32), axis=1)
                release = st.frame_start + st.activation_delay + np.ceil(dist / st.activation_speed * fps).astype(int)
            kick = np.zeros((n, 3))
            spin = np.zeros((n, 3))
            if st.burst_speed > 0:
                d = pivots - np.asarray(st.burst_origin, np.float32)
                dist = np.linalg.norm(d, axis=1)
                away = d / np.maximum(dist, 1e-6)[:, None]
                aim = away * (1.0 - st.burst_up) + np.array([0.0, 0.0, 1.0]) * st.burst_up
                if st.use_ground:
                    aim[:, 2] = np.abs(aim[:, 2])  # a blast reflects off the ground instead of pushing pieces into it
                aim /= np.maximum(np.linalg.norm(aim, axis=1), 1e-6)[:, None]
                fade = np.clip(1.0 - dist / st.burst_radius, 0.0, 1.0) if st.burst_radius > 0 else np.ones(n)
                jitter = 1.0 + st.burst_variation * rng.uniform(-1.0, 1.0, n)
                kick = aim * (st.burst_speed * fade * jitter)[:, None]
                axis = rng.normal(size=(n, 3))
                axis /= np.maximum(np.linalg.norm(axis, axis=1), 1e-6)[:, None]
                spin = axis * (st.burst_spin * fade * rng.uniform(0.3, 1.0, n))[:, None]
                release = np.maximum(release, st.frame_start + 1)
            if job.activate is not None:
                # activate_time: seconds after the start frame at which the piece is handed to the solver
                release = np.maximum(release, st.frame_start + np.ceil(np.maximum(job.activate, 0.0) * fps - 1e-6).astype(int))
            if job.v is not None or job.w is not None:
                # a piece that was given a velocity or a spin of its own (either one is enough) leaves with those
                v = np.zeros((n, 3)) if job.v is None else job.v
                w = np.zeros((n, 3)) if job.w is None else job.w
                moving = (np.linalg.norm(v, axis=1) > 1e-6) | (np.linalg.norm(w, axis=1) > 1e-6)
                kick = np.where(moving[:, None], v, kick)
                spin = np.where(moving[:, None], w, spin)
                release = np.where(moving, np.maximum(release, st.frame_start + 1), release)
            if st.use_ground:
                # The hand-over moves a piece for one frame without looking at collisions. A piece that is
                # thrown at the ground would end up under it: it goes down as far as the ground and no further.
                kick[:, 2] = np.maximum(kick[:, 2], np.minimum((st.ground_z - job.zmin) * fps, 0.0))
            if not st.start_asleep:
                # awake pieces are held through the lead-in frame so the first cached frame is the rest pose
                release = np.maximum(release, st.frame_start + 1)
            last_handover = st.frame_start
            for i, o in enumerate(job.bodies):
                has_kick = float(np.abs(kick[i]).max()) > 1e-6 or float(np.abs(spin[i]).max()) > 1e-6
                if anchored[i] or (release[i] <= st.frame_start and not has_kick):
                    continue
                rb = o.rigid_body
                rb.use_start_deactivated = False
                r = int(release[i])
                if has_kick:
                    # frames r-1 -> r: animated move by exactly kick/fps; the solver takes over at r+1
                    o.keyframe_insert("location", frame=r - 1)
                    o.keyframe_insert("rotation_euler", frame=r - 1)
                    o.location = Vector(pivots[i]) + Vector(kick[i]) / fps
                    angle = float(np.linalg.norm(spin[i])) / fps
                    if angle > 1e-6:
                        o.rotation_euler = Quaternion(Vector(spin[i]).normalized(), angle).to_euler()
                    o.keyframe_insert("location", frame=r)
                    o.keyframe_insert("rotation_euler", frame=r)
                    o.location, o.rotation_euler = pivots[i], (0.0, 0.0, 0.0)    # at rest until the keyframes move it
                    r += 1
                # Held until frame r: "Animated", and not "Dynamic". The second is for force fields. Blender
                # applies them to animated bodies too, and the force piles up on the body until it is let go
                # (measured: the piece then leaves with the push of all the time it was held); a body that is
                # not Dynamic is skipped by the fields.
                # The two switches are thrown by the loop that steps the frames, not by keyframes: Blender
                # does not order the evaluation of such keyframes against the simulation step, and in about
                # four bakes out of ten the piece was let go one frame late.
                rb.kinematic, rb.enabled = True, False
                handover.setdefault(r, []).append(o)
                last_handover = max(last_handover, r)
            if last_handover > st.frame_start + 2:
                res.notes.append(f"last piece handed to the solver at frame {last_handover}")
                if last_handover > st.frame_end:
                    res.notes.append("some pieces are released after the end frame and never move")

            if job.site is not None:
                # RBD nodes: the glue is whatever constraint geometry arrives at the solver node
                wired = graph.constraints(job.ob, job.site[0], job.site[1])
                pairs_in, strength_in = wired if wired is not None else ([], np.zeros(0))
                ok = [k for k, p in enumerate(pairs_in) if p[0] < n and p[1] < n]
                plan = GluePlan([pairs_in[k] for k in ok], np.asarray(strength_in)[ok], None, 0)
            else:
                plan = glue_plan(em, pivots, st)
            res.clusters = plan.n_clusters
            for (a, bq, point, _), strength in zip(plan.pairs, plan.strength):
                e = add_object("rbdglue", None)
                e.location = point
                rbw.constraints.objects.link(e)
                c = e.rigid_body_constraint
                c.type, c.object1, c.object2 = "FIXED", job.bodies[a], job.bodies[bq]
                c.use_breaking, c.disable_collisions = True, True
                c.breaking_threshold = float(strength) * float(min(mass[a], mass[bq]))
                if st.glue_iterations > 0:
                    # With the few iterations that are enough for contacts, a bond gives like rubber: a
                    # wall that is hit shows cracks all over which close again. More iterations on the
                    # bonds alone make it stiff, for a fraction of the cost of raising them everywhere.
                    c.use_override_solver_iterations = True
                    c.solver_iterations = int(st.glue_iterations)
            res.glue = len(plan.pairs)
            job.pairs = plan.pairs
            # cracks are reported between every pair of neighbours, glued or not
            job.contacts = plan.pairs if (plan.pairs or (st.use_glue and job.site is None)) else adjacency(em, n, st.glue_distance)

        if st.use_ground:
            gm = bpy.data.meshes.new("rbdground")
            # thick enough that a fast piece of a very large object does not pass through it in one step
            s, t = max(500.0, 50.0 * extent), max(1.0, 0.25 * extent)
            # A Box collision shape is centred on the object origin, so the mesh must be too.
            gm.from_pydata([(x, y, z) for x in (-s, s) for y in (-s, s) for z in (-t, t)], [],
                           [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)])
            made_meshes.append(gm)
            g = add_object("rbdground", gm)
            # centred under the objects, wherever in the world they are
            g.location = (float((lo_all[0] + hi_all[0]) / 2), float((lo_all[1] + hi_all[1]) / 2), st.ground_z - t)
            rbw.collection.objects.link(g)
            g.rigid_body.type, g.rigid_body.collision_shape = "PASSIVE", "BOX"
            g.rigid_body.friction, g.rigid_body.restitution = st.friction, st.bounce

        deforming, baked_colliders = [], []
        if st.collider_collection is not None:
            for src in st.collider_collection.all_objects:
                if src in objects or src.type != "MESH":
                    continue
                # a copy, so the user's object is never given rigid body settings. It follows the
                # original's animation and is always an animated passive body here.
                proxy = src.copy()
                tmp.objects.link(proxy)
                made_objects.append(proxy)
                rbw.collection.objects.link(proxy)
                if proxy.field is not None:
                    proxy.field.type = "NONE"     # a collider that is a force field too: the field acts once, below
                rb = proxy.rigid_body
                rb.type, rb.kinematic = "PASSIVE", True
                rb.collision_shape, rb.mesh_source = "MESH", "FINAL"
                # A collider whose shape changes over time (a character moved by an armature, shape
                # keys, another object baked with these nodes) needs its collision mesh rebuilt as it goes.
                # Blender does that once per frame, not per solver step: the surface jumps, and what
                # it touches is thrown harder than a rigidly moving collider would throw it.
                rb.use_deform = _changes_shape(src)
                if rb.use_deform:
                    deforming.append(src.name)
                if is_baked(src):
                    baked_colliders.append(src.name)
                rb.friction, rb.restitution = st.friction, st.bounce
        if deforming:
            for job in jobs:
                job.res.notes.append(
                    f"{len(deforming)} collider(s) change shape ({', '.join(deforming[:3])}): they hit harder than "
                    "a rigid collider (more so with more substeps). A rigid stand-in object is more accurate")
        if baked_colliders:
            # measured: such a collider is not felt at all in one bake out of every few
            for job in jobs:
                job.res.notes.append(
                    f"{', '.join(baked_colliders[:3])}: an object baked with these nodes is not a reliable collider. Select the "
                    "objects and bake them together instead")
        # Force fields act on the pieces as they act on Blender's own rigid bodies: the field objects are
        # linked into the simulation scene as they are (they follow their own animation), and the Field
        # Weights of the rigid body world do the rest.
        fields = []
        if st.use_fields and st.field_weight > 0.0:
            pool = scene.objects if st.field_collection is None else st.field_collection.all_objects
            fields = [src for src in pool if src.field is not None and src.field.type != "NONE" and src not in objects]
            for src in fields:
                if src.name not in tmp.objects:
                    tmp.objects.link(src)
        # The weight goes on every kind of field by itself. The "all" weight is left alone: Blender multiplies
        # gravity by it as well (measured: with all = 0 nothing falls).
        for kind in FIELD_WEIGHTS:
            if hasattr(rbw.effector_weights, kind):
                setattr(rbw.effector_weights, kind, st.field_weight)
        if fields:
            names = ", ".join(src.name for src in fields[:3]) + (" ..." if len(fields) > 3 else "")
            for job in jobs:
                job.res.fields = len(fields)
                job.res.notes.append(f"{len(fields)} force field(s) act on the pieces ({names})")
                if st.start_asleep:
                    job.res.notes.append("Start Asleep: a force field wakes every piece it reaches")

        frames = st.frame_end - st.frame_start + 1
        for job in jobs:
            job.pos = np.zeros((frames, job.n, 3), np.float32)
            job.quat = np.zeros((frames, job.n, 4), np.float32)
        layer = sim.view_layers[0]
        dg = layer.depsgraph  # created here; frame_set only updates depsgraphs that already exist
        def hand_over(f):
            # the pieces that are let go on frame f: from here on the solver moves them
            for o in handover.pop(f, ()):
                o.rigid_body.kinematic, o.rigid_body.enabled = False, True

        for f in range(st.frame_start - PRE_ROLL, st.frame_start):
            hand_over(f)
            sim.frame_set(f)
            layer.update()
        for k in range(frames):
            hand_over(st.frame_start + k)
            sim.frame_set(st.frame_start + k)
            layer.update()
            for job in jobs:
                pos, quat = job.pos, job.quat
                for i, o in enumerate(job.bodies):
                    m = o.evaluated_get(dg).matrix_world
                    pos[k, i] = m.translation
                    quat[k, i] = m.to_quaternion()
            if progress is not None:
                progress(k + 1, frames)

        impact = st.burst_origin if st.burst_speed > 0 else (st.activation_origin if st.activation == "RADIAL" else None)
        for job in jobs:
            res, pos, quat, pivots = job.res, job.pos, job.quat, job.pivots
            # keep neighbouring frames on the same side of the quaternion double cover so blending is clean
            flip = np.sign(np.sum(quat[1:] * quat[:-1], axis=-1))
            flip[flip == 0] = 1
            quat[1:] *= np.cumprod(flip, axis=0)[..., None]
            settle(pos, quat)
            res.frames = frames
            res.moved = int((np.linalg.norm(pos[-1] - pos[0], axis=1) > 0.01).sum())
            if job.pairs:
                a = np.array([p[0] for p in job.pairs])
                bq = np.array([p[1] for p in job.pairs])
                rest_d = np.linalg.norm(pivots[a] - pivots[bq], axis=1)
                end_d = np.linalg.norm(pos[-1, a] - pos[-1, bq], axis=1)
                res.glue_separated = int((np.abs(end_d - rest_d) > 0.05 * np.maximum(rest_d, 1e-6)).sum())
            if abs(scene.unit_settings.scale_length - 1.0) > 1e-6:
                res.notes.append("scene unit scale is not 1: sizes are treated as metres")
            job.events = crack_events(pos, quat, pivots, job.contacts, fps)
            res.events = len(job.events)
        # The simulation is complete: only now is anything written to the objects. Should writing one
        # of them fail, the ones written before it are put back as they were: all of them or none.
        written = []
        try:
            for job in jobs:
                written.append(write_cache(job.ob, job.rest_mesh, job.pos, job.quat, job.pivots, st.frame_start, fps,
                                           impact, job.events, defer=True, contacts=job.contacts))
        except Exception:
            for undo, _ in reversed(written):
                _attempt(undo)
            raise
        for job, (_, finish) in zip(jobs, written):
            finish()
            job.rest_mesh = None  # now owned by the frozen pieces object
    finally:
        # keyframes on the temporary pieces made actions; collect them before the objects go
        actions = {o.animation_data.action for job in jobs for o in job.bodies
                   if o.animation_data is not None and o.animation_data.action is not None}
        if made_objects:
            bpy.data.batch_remove(made_objects)
        if sim is not None:
            bpy.data.scenes.remove(sim)
        for c in made_collections:
            if c.name in bpy.data.collections:
                bpy.data.collections.remove(c)
        leftovers = [m for m in made_meshes] + [a for a in actions if a.users == 0]
        leftovers += [job.rest_mesh for job in jobs if job.rest_mesh is not None]
        if leftovers:
            bpy.data.batch_remove(leftovers)
    seconds = time.perf_counter() - t_all
    for job in jobs:
        job.res.seconds = seconds
    return [job.res for job in jobs]
