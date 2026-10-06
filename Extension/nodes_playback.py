# SPDX-License-Identifier: GPL-3.0-or-later
"""The "RBD Playback" node group: moves every piece by its baked transform.

The cache is one mesh whose points are laid out frame after frame:
point (frame * piece_count + piece_id) holds that piece's world position, its
rotation ("rot") and its rest pivot ("pivot"). Reading it is a plain Sample Index,
so scrubbing the timeline costs almost nothing and nothing is re-simulated.
"""
from .core import KIND_PLAYBACK
from .nodekit import Builder, ensure_group
from .nodes_fracture import ATTR_PIECE

GROUP = "RBD Playback"
VERSION = 5


def build():
    b = Builder(GROUP, KIND_PLAYBACK, VERSION)
    geo = b.input("Geometry", "geo")
    use_rest = b.input("Use Frozen Pieces", "bool", False,
                       desc="Read the pieces frozen at bake time instead of the modifiers above (set by Bake)")
    rest = b.input("Frozen Pieces", "obj")
    geo = b.switch("GEOMETRY", use_rest, geo,
                   b.node("GeometryNodeObjectInfo", {"Object": rest}, transform_space="ORIGINAL")["Geometry"])
    cache = b.input("Cache", "obj")
    n_pieces = b.input("Piece Count", "int", 0, min=0)
    n_frames = b.input("Frame Count", "int", 0, min=0)
    start = b.input("Start Frame", "int", 1)
    b.panel("Retime")
    speed = b.input("Speed", "float", 1.0, desc="Playback speed of the baked motion. 0.5 is slow motion")
    offset = b.input("Frame Offset", "float", 0.0, desc="Shift the baked motion in time, in cache frames")

    # The cache object sits where the simulated object was at bake time. Motion is stored in that
    # world frame and brought back to local space with the same matrix, so the baked destruction
    # follows the object when it is moved, rotated or scaled later (like an H-Style file cache).
    cache_info = b.node("GeometryNodeObjectInfo", {"Object": cache}, transform_space="ORIGINAL")
    cache_geo = cache_info["Geometry"]
    to_world = cache_info["Transform"]
    to_local = b.node("FunctionNodeInvertMatrix", {"Matrix": to_world})["Matrix"]

    frame = b.node("GeometryNodeInputSceneTime")["Frame"]
    t = b.math("ADD", b.math("MULTIPLY", b.math("SUBTRACT", frame, start), speed), offset)
    last = b.math("MAXIMUM", b.math("SUBTRACT", n_frames, 1.0), 0.0)
    t = b.math("MINIMUM", b.math("MAXIMUM", t, 0.0), last)
    f0 = b.math("FLOOR", t)
    f1 = b.math("MINIMUM", b.math("ADD", f0, 1.0), last)
    blend = b.math("SUBTRACT", t, f0)

    pid = b.named(ATTR_PIECE, "INT")
    i0 = b.math("ROUND", b.math("MULTIPLY_ADD", f0, n_pieces, pid))
    i1 = b.math("ROUND", b.math("MULTIPLY_ADD", f1, n_pieces, pid))

    def sample(data_type, value, index):
        return b.node("GeometryNodeSampleIndex", {"Geometry": cache_geo, "Value": value, "Index": index},
                      data_type=data_type, domain="POINT", clamp=True).o

    cpos = b.pos()
    crot = b.named("rot", "QUATERNION")
    p = b.node("ShaderNodeMix", {"Factor": blend, "A": sample("FLOAT_VECTOR", cpos, i0),
                                 "B": sample("FLOAT_VECTOR", cpos, i1)}, data_type="VECTOR").o
    q = b.node("ShaderNodeMix", {"Factor": blend, "A": sample("QUATERNION", crot, i0),
                                 "B": sample("QUATERNION", crot, i1)}, data_type="ROTATION").o
    pivot = sample("FLOAT_VECTOR", b.named("pivot", "FLOAT_VECTOR"), pid)

    rest_world = b.node("FunctionNodeTransformPoint", {"Vector": b.pos(), "Transform": to_world}).o
    moved = b.vmath("ADD", p, b.node("FunctionNodeRotateVector",
                                     {"Vector": b.vmath("SUBTRACT", rest_world, pivot), "Rotation": q}).o)
    local = b.node("FunctionNodeTransformPoint", {"Vector": moved, "Transform": to_local}).o
    valid = b.bmath("AND", b.cmp("LESS_THAN", pid, n_pieces, "INT"), b.cmp("GREATER_THAN", n_frames, 0, "INT"))
    b.output("Geometry", "geo", b.set_pos(geo, position=local, selection=valid))
    return b.finish()


def ensure():
    return ensure_group(KIND_PLAYBACK, VERSION, build)
