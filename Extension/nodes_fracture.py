# SPDX-License-Identifier: GPL-3.0-or-later
"""The "RBD Fracture" node group: Voronoi fracture built from stock Geometry Nodes.

How one cell is made (no Voronoi node exists, so it is derived geometrically):
  A Voronoi cell is the intersection of half-spaces, one per neighbouring seed
  (the plane halfway between the two seeds) plus six bounding-box planes.
  The polar dual of that intersection is a convex hull: plane (n, d) -> point n/d.
  So: dual points -> Convex Hull -> Dual Mesh (faces become vertices) -> move each
  vertex to normal/offset of the hull face it came from. That is the cell.
  The cell is then intersected with the source mesh by Mesh Boolean.
"""
import math

from .core import KIND_FRACTURE
from .nodekit import Builder, ensure_group, find_socket

GROUP = "RBD Fracture"
VERSION = 19

ATTR_PIECE = "piece_id"      # int, point domain: which piece a vertex belongs to
ATTR_INSIDE = "inside"       # bool, face domain: face was created by the fracture
ATTR_PIVOT = "rbd_pivot"     # vector, point domain: rest centre of the piece
ATTR_REST = "rbd_rest"       # vector, point domain: position before interior detail (collision proxy)
ATTR_ANCHOR = "rbd_anchor"   # float, point domain: the piece's average anchor weight (only when a group is set)
_ATTR_OUTER = "rbd_outer"    # temporary face tag carried through the boolean


def build():
    b = Builder(GROUP, KIND_FRACTURE, VERSION)
    geo_in = b.input("Geometry", "geo")
    extra_in = b.input("Extra Points", "geo",
                       desc="Optional. Used as the cell points instead of scattering; with Radial Cracks the "
                            "first of them is the impact point")
    pieces = b.input("Pieces", "int", 30, min=1, max=5000, desc="Number of Voronoi seed points")
    seed = b.input("Seed", "int", 0, min=0)
    b.panel("Impact")
    impact_bias = b.input("Impact Bias", "float", 0.0, min=0.0, max=1.0, subtype="FACTOR",
                          desc="Fraction of the seeds concentrated around the impact point (small pieces there)")
    impact_pos = b.input("Impact Point", "vec", (0.0, 0.0, 0.0), subtype="TRANSLATION")
    impact_radius = b.input("Impact Radius", "float", 0.5, min=0.001, subtype="DISTANCE")
    b.panel("Secondary Fracture")
    sec_ratio = b.input("Secondary Ratio", "float", 0.0, min=0.0, max=1.0, subtype="FACTOR",
                        desc="Share of the pieces that are broken up again into smaller ones")
    sec_pieces = b.input("Secondary Pieces", "int", 4, min=1, max=32,
                         desc="Extra seed points added inside each piece that is broken up again")
    b.panel("Shape")
    loose = b.input("Use Loose Parts", "bool", False,
                    desc="Do not cut: every loose part (connected island) of the mesh is one piece. For models "
                         "that are already in pieces: bricks, planks, hand-cut debris")
    stretch = b.input("Cell Stretch", "vec", (1.0, 1.0, 1.0), min=0.01, subtype="XYZ",
                      desc="Elongate cells along an axis. (1, 1, 6) gives wood-like splinters along Z")
    flat = b.input("Flat", "bool", False,
                   desc="2.5D: cut straight through the thinnest axis. Use for glass panes and ground slabs")
    radial = b.input("Radial Cracks", "bool", False,
                     desc="Glass pattern: cracks radiating from the impact point crossed by rings")
    rings = b.input("Rings", "int", 5, min=1, max=64)
    spokes = b.input("Spokes", "int", 12, min=3, max=128)
    b.panel("Interior Detail")
    detail = b.input("Detail Level", "int", 0, min=0, max=5,
                     desc="Subdivide the cut faces and roughen them with noise. 0 = flat cuts")
    noise_amp = b.input("Noise Height", "float", 0.02, min=0.0, subtype="DISTANCE")
    noise_scale = b.input("Noise Scale", "float", 3.0, min=0.0)
    noise_fade = b.input("Edge Fade", "float", 0.05, min=0.0001, subtype="DISTANCE",
                         desc="The roughness fades out over this distance from the original surface")
    b.panel("Simulation")
    anchor_name = b.input("Anchor Group", "str", "",
                          desc="Vertex group painted where pieces must stay in place. A piece is anchored "
                               "when most of it is painted (average weight of 0.5 or more)")
    b.panel("Output")
    use_inner = b.input("Use Inner Material", "bool", False)
    inner_mat = b.input("Inner Material", "mat")
    uv_name = b.input("UV Map", "str", "UVMap", desc="Cut faces get box-projected UVs in this UV map")
    uv_scale = b.input("Inner UV Scale", "float", 1.0, min=0.0)
    explode = b.input("Exploded View", "float", 0.0, min=0.0, desc="Push pieces apart to inspect the fracture")
    robust = b.input("Robust Boolean", "bool", False,
                     desc="Always use the slow exact boolean. It is used automatically where the fast one fails; "
                          "enable this when pieces still go missing")

    # ---- work in a space where the cells are isotropic
    inv_stretch = b.vmath("DIVIDE", (1.0, 1.0, 1.0), stretch)
    src = b.node("GeometryNodeTransform", {"Geometry": geo_in, "Scale": inv_stretch}).o
    src = b.store(src, _ATTR_OUTER, "BOOLEAN", "FACE", True)
    impact_s = b.vmath("MULTIPLY", impact_pos, inv_stretch)

    bb = b.node("GeometryNodeBoundBox", {"Geometry": src})
    size = b.vmath("SUBTRACT", bb["Max"], bb["Min"])
    center = b.vmath("SCALE", b.vmath("ADD", bb["Max"], bb["Min"]), scale=0.5)
    diag = b.vmath("LENGTH", size)
    margin = b.math("ADD", b.math("MULTIPLY", diag, 0.05), 0.001)
    bmin = b.vmath("SUBTRACT", bb["Min"], b.comb(margin, margin, margin))
    bmax = b.vmath("ADD", bb["Max"], b.comb(margin, margin, margin))

    sx, sy, sz = b.sep(size)
    x_thin = b.bmath("AND", b.cmp("LESS_EQUAL", sx, sy), b.cmp("LESS_EQUAL", sx, sz))
    y_thin = b.bmath("AND", b.bmath("NOT", x_thin), b.cmp("LESS_EQUAL", sy, sz))
    z_thin = b.bmath("NOR", x_thin, y_thin)
    thin = b.comb(x_thin, y_thin, z_thin)
    in_plane = b.vmath("SUBTRACT", (1.0, 1.0, 1.0), thin)

    def keep_in_box(points):
        """Drop seeds outside the source bounds. The cell construction measures the box planes from
        the seed, which only works for seeds inside the box."""
        half = b.vmath("SCALE", size, scale=0.5)
        off = b.vmath("SUBTRACT", b.vmath("ABSOLUTE", b.vmath("SUBTRACT", b.pos(), center)), half)
        ox, oy, oz = b.sep(off)
        outside = b.cmp("GREATER_THAN", b.math("MAXIMUM", b.math("MAXIMUM", ox, oy), oz), 0.0)
        return b.node("GeometryNodeDeleteGeometry", {"Geometry": points, "Selection": outside}, domain="POINT").o

    def flatten(points):
        """Project points onto the mid-plane of the thinnest axis when Flat is on."""
        flat_pos = b.vmath("ADD", b.vmath("MULTIPLY", b.pos(), in_plane), b.vmath("MULTIPLY", center, thin))
        return b.set_pos(points, position=b.switch("VECTOR", flat, b.pos(), flat_pos))

    # ---- cell points given from outside: the vertices of a mesh or the points of a point cloud
    join_extra = b.tree.nodes.new("GeometryNodeJoinGeometry")
    b.link(b.node("GeometryNodeMeshToPoints", {"Mesh": extra_in}, mode="VERTICES").o, join_extra.inputs[0])
    b.link(b.node("GeometryNodeSeparateComponents", {"Geometry": extra_in})["Point Cloud"], join_extra.inputs[0])
    extra_pts = b.node("GeometryNodeTransform", {"Geometry": join_extra.outputs[0], "Scale": inv_stretch}).o
    has_extra = b.cmp("GREATER_THAN", b.node("GeometryNodeAttributeDomainSize", {"Geometry": extra_pts},
                                              component="POINTCLOUD")["Point Count"], 0, "INT")
    first_extra = b.node("GeometryNodeSampleIndex", {"Geometry": extra_pts, "Value": b.pos(), "Index": 0},
                         data_type="FLOAT_VECTOR", domain="POINT").o
    impact_s = b.switch("VECTOR", b.bmath("AND", has_extra, radial), impact_s, first_extra)
    extra_seeds = keep_in_box(flatten(extra_pts))

    # ---- radial pattern: a spider web around the impact point (glass, impact craters).
    # Seeds sit on rings x spokes. Every seed of a spoke has the same angle, so the border between two
    # neighbouring spokes is a nearly straight line through the impact point (a radial crack), and the
    # border between two rings is a chord across the spoke (a concentric crack). The angle is jittered
    # per spoke and the radius a little per seed: uneven sectors, rings that break up into steps.
    n_radial = b.switch("INT", radial, 0, b.math("MULTIPLY", rings, spokes))
    k = b.index()
    ring = b.math("FLOOR", b.math("DIVIDE", k, spokes))
    spoke = b.math("FLOORED_MODULO", k, spokes)
    jr = b.rand("FLOAT", -0.12, 0.12, b.math("ADD", seed, 404))
    jt = b.rand("FLOAT", -0.3, 0.3, b.math("ADD", seed, 505), id=spoke)
    rr = b.math("MULTIPLY", impact_radius,
                b.math("POWER", b.math("DIVIDE", b.math("ADD", b.math("ADD", ring, 0.5), jr), rings), 1.6))
    theta = b.math("MULTIPLY", b.math("DIVIDE", b.math("ADD", spoke, jt), spokes), 2.0 * math.pi)
    ca = b.math("MULTIPLY", rr, b.math("COSINE", theta))
    sa = b.math("MULTIPLY", rr, b.math("SINE", theta))
    ring_offset = b.switch("VECTOR", x_thin, b.switch("VECTOR", y_thin, b.comb(ca, sa, 0.0), b.comb(ca, 0.0, sa)),
                           b.comb(0.0, ca, sa))
    radial_pts = b.node("GeometryNodePoints", {"Count": n_radial, "Position": b.vmath("ADD", impact_s, ring_offset)}).o
    radial_pts = keep_in_box(flatten(radial_pts))

    # ---- scattered seeds: candidates in the bounding box, keep the first N that are inside the mesh
    n_scatter = b.math("MAXIMUM", b.math("SUBTRACT", pieces, n_radial), 0.0)
    n_cand = b.math("ADD", b.math("MULTIPLY", n_scatter, 12.0), 64.0)
    uniform = b.rand("FLOAT_VECTOR", bb["Min"], bb["Max"], seed)
    direction = b.vmath("NORMALIZE", b.rand("FLOAT_VECTOR", (-1.0, -1.0, -1.0), (1.0, 1.0, 1.0), b.math("ADD", seed, 101)))
    radius = b.math("MULTIPLY", impact_radius, b.rand("FLOAT", 0.0, 1.0, b.math("ADD", seed, 202)))
    near_impact = b.vmath("ADD", impact_s, b.vmath("SCALE", direction, scale=radius))
    pick_impact = b.cmp("LESS_THAN", b.rand("FLOAT", 0.0, 1.0, b.math("ADD", seed, 303)), impact_bias)
    cand_pos = b.switch("VECTOR", pick_impact, uniform, near_impact)
    cand = b.node("GeometryNodePoints", {"Count": n_cand, "Position": cand_pos}).o
    cand = keep_in_box(flatten(cand))

    ray = b.node("GeometryNodeRaycast", {
        "Target Geometry": src, "Ray Direction": (0.0, 0.0, 1.0),
        "Ray Length": b.math("ADD", b.math("MULTIPLY", diag, 4.0), 10.0),
    })
    inside_pt = b.bmath("AND", ray["Is Hit"], b.cmp("GREATER_THAN", b.sep(ray["Hit Normal"])[2], 0.0))
    # with the radial pattern on, scattered seeds stay out of the ring area so they do not break the pattern
    outside_rings = b.cmp("GREATER_THAN", b.vmath("DISTANCE", b.pos(), impact_s), impact_radius)
    keep_pt = b.bmath("AND", inside_pt, b.bmath("OR", b.bmath("NOT", radial), outside_rings))
    cand, cap = b.capture(cand, "POINT", keep=("BOOLEAN", keep_pt))
    inside_only = b.node("GeometryNodeDeleteGeometry", {"Geometry": cand, "Selection": b.bmath("NOT", cap["keep"])},
                         domain="POINT").o
    n_inside = b.node("GeometryNodeAttributeDomainSize", {"Geometry": inside_only}, component="POINTCLOUD")["Point Count"]
    # a mesh that is not watertight fails the inside test everywhere: fall back to all candidates
    usable = b.switch("GEOMETRY", b.bmath("OR", b.cmp("GREATER_THAN", n_inside, 0, "INT"), radial), cand, inside_only)
    scattered = b.node("GeometryNodeDeleteGeometry",
                       {"Geometry": usable, "Selection": b.cmp("GREATER_EQUAL", b.index(), n_scatter, "INT")},
                       domain="POINT").o
    scattered = b.switch("GEOMETRY", b.bmath("AND", has_extra, b.bmath("NOT", radial)), scattered, extra_seeds)
    join_seeds = b.tree.nodes.new("GeometryNodeJoinGeometry")
    b.link(radial_pts, join_seeds.inputs[0])
    b.link(scattered, join_seeds.inputs[0])
    primary = join_seeds.outputs[0]

    # ---- secondary fracture: some seeds get a handful of extra seeds close by, which splits that
    # cell (and a little of its neighbours) into small pieces. Like the H-Style second fracture level.
    nearest = b.node("GeometryNodeIndexOfNearest")
    near_pos = b.node("GeometryNodeFieldAtIndex", {"Value": b.pos(), "Index": nearest["Index"]},
                      data_type="FLOAT_VECTOR", domain="POINT").o
    # a lone seed has no neighbour to measure against: give its children a quarter of the object to roam
    spacing = b.switch("FLOAT", nearest["Has Neighbor"], b.math("MULTIPLY", diag, 0.25),
                       b.vmath("DISTANCE", b.pos(), near_pos))
    picked = b.cmp("LESS_THAN", b.rand("FLOAT", 0.0, 1.0, b.math("ADD", seed, 606)), sec_ratio)
    primary, cap = b.capture(primary, "POINT", spacing=("FLOAT", spacing), picked=("BOOLEAN", picked))
    parents = b.node("GeometryNodeDeleteGeometry", {"Geometry": primary, "Selection": b.bmath("NOT", cap["picked"])},
                     domain="POINT").o
    children = b.node("GeometryNodeDuplicateElements", {"Geometry": parents, "Amount": sec_pieces}, domain="POINT")["Geometry"]
    wander = b.vmath("NORMALIZE", b.rand("FLOAT_VECTOR", (-1.0, -1.0, -1.0), (1.0, 1.0, 1.0), b.math("ADD", seed, 707)))
    # within half the distance to the nearest other seed a point is certainly still inside the parent cell
    reach = b.math("MULTIPLY", b.math("MULTIPLY", cap["spacing"], 0.5), b.rand("FLOAT", 0.35, 0.95, b.math("ADD", seed, 808)))
    children = b.set_pos(children, offset=b.vmath("SCALE", wander, scale=reach))
    children = keep_in_box(flatten(children))
    join_all = b.tree.nodes.new("GeometryNodeJoinGeometry")
    b.link(primary, join_all.inputs[0])
    b.link(children, join_all.inputs[0])
    # two seeds in the same spot would each build the same cell: two identical pieces on top of each other
    seeds = b.node("GeometryNodeMergeByDistance",
                   {"Geometry": join_all.outputs[0], "Distance": b.math("ADD", b.math("MULTIPLY", diag, 1e-5), 1e-7)}).o
    # every seed can be filtered away (a radial pattern entirely outside the object): keep the mesh in one piece
    n_seeds = b.node("GeometryNodeAttributeDomainSize", {"Geometry": seeds}, component="POINTCLOUD")["Point Count"]
    lone = b.node("GeometryNodePoints", {"Count": 1, "Position": center}).o
    seeds = b.switch("GEOMETRY", b.cmp("GREATER_THAN", n_seeds, 0, "INT"), lone, seeds)

    # ---- one iteration per seed: build its cell, cut the mesh with it
    fi = b.tree.nodes.new("GeometryNodeForeachGeometryElementInput")
    fo = b.tree.nodes.new("GeometryNodeForeachGeometryElementOutput")
    fi.pair_with_output(fo)
    fo.domain = "POINT"
    fo.input_items.new("VECTOR", "Seed Position")
    b.link(seeds, fi.inputs["Geometry"])
    b.link(b.pos(), find_socket(fi.inputs, "Seed Position"))
    s = find_socket(fi.outputs, "Seed Position")

    d = b.vmath("SUBTRACT", b.pos(), s)
    len2 = b.vmath("DOT_PRODUCT", d, d)
    others = b.node("GeometryNodeDeleteGeometry", {"Geometry": seeds, "Selection": b.cmp("LESS_THAN", len2, 1e-12)},
                    domain="POINT").o
    dual_seeds = b.set_pos(others, position=b.vmath("SCALE", d, scale=b.math("DIVIDE", 2.0, len2)))

    axes = b.node("GeometryNodeMeshToPoints",
                  {"Mesh": b.node("GeometryNodeMeshCube", {"Size": (2.0, 2.0, 2.0)})["Mesh"]}, mode="FACES").o
    q = b.pos()
    q_pos = b.vmath("MAXIMUM", q, (0.0, 0.0, 0.0))
    q_neg = b.vmath("MAXIMUM", b.vmath("SCALE", q, scale=-1.0), (0.0, 0.0, 0.0))
    dist = b.math("ADD", b.vmath("DOT_PRODUCT", q_pos, b.vmath("SUBTRACT", bmax, s)),
                  b.vmath("DOT_PRODUCT", q_neg, b.vmath("SUBTRACT", s, bmin)))
    dual_box = b.set_pos(axes, position=b.vmath("SCALE", q, scale=b.math("DIVIDE", 1.0, dist)))

    join = b.tree.nodes.new("GeometryNodeJoinGeometry")
    b.link(dual_seeds, join.inputs[0])
    b.link(dual_box, join.inputs[0])
    hull = b.node("GeometryNodeConvexHull", {"Geometry": join.outputs[0]}).o
    nrm = b.node("GeometryNodeInputNormal")["Normal"]
    offset = b.vmath("DOT_PRODUCT", nrm, b.pos())
    hull, cap = b.capture(hull, "FACE", vert=("VECTOR", b.vmath("SCALE", nrm, scale=b.math("DIVIDE", 1.0, offset))))
    cell = b.node("GeometryNodeDualMesh", {"Mesh": hull}).o
    cell = b.set_pos(cell, position=b.vmath("ADD", cap["vert"], s))

    def boolean(solver, source):
        n = b.node("GeometryNodeMeshBoolean", operation="INTERSECT", solver=solver)
        target = find_socket(n.node.inputs, "Mesh 2")
        b.link(source, target)
        b.link(cell, target)
        return n["Mesh"]

    # The fast solver returns nothing for a mesh that is not manifold (text, meshes with interior
    # faces, open shells). Then, or when asked to, the slow exact solver takes over for this cell.
    # With Robust on the fast solver is handed an empty mesh: Blender 5.2 was seen to run it now and
    # then although its result is not used (about one freshly built node group in four), which put a
    # "not manifold" warning on the modifier.
    fast = boolean("MANIFOLD", b.switch("GEOMETRY", robust, src, None))
    fast_faces = b.node("GeometryNodeAttributeDomainSize", {"Geometry": fast}, component="MESH")["Face Count"]
    exact = boolean("EXACT", src)
    automatic = b.switch("GEOMETRY", b.cmp("EQUAL", fast_faces, 0, "INT"), fast, exact)
    piece = b.switch("GEOMETRY", robust, automatic, exact)   # nested so that Robust never runs the fast solver
    b.link(piece, find_socket(fo.inputs, "Generation_0"))
    pieces_geo = find_socket(fo.outputs, "Generation_0")

    # ---- back to the real space, tag pieces and cut faces
    cut = b.node("GeometryNodeTransform", {"Geometry": pieces_geo, "Scale": stretch}).o
    # "Use Loose Parts": nothing is cut, the islands of the mesh are the pieces. The switch is lazy,
    # so the cell loop above is not even evaluated then.
    as_is = b.store(geo_in, _ATTR_OUTER, "BOOLEAN", "FACE", True)
    g = b.switch("GEOMETRY", loose, cut, as_is)
    island = b.node("GeometryNodeInputMeshIsland")["Island Index"]
    g = b.store(g, ATTR_PIECE, "INT", "POINT", island)
    # faces that came from the source mesh carry the tag through the boolean; everything else is a cut face
    g = b.store(g, ATTR_INSIDE, "BOOLEAN", "FACE", b.bmath("NOT", b.named(_ATTR_OUTER, "BOOLEAN")))
    g = b.node("GeometryNodeRemoveAttribute", {"Geometry": g, "Name": _ATTR_OUTER}).o
    g = b.store(g, ATTR_REST, "FLOAT_VECTOR", "POINT", b.pos())
    # Painted anchors. Attributes of the source do not survive the cut, so every vertex takes the
    # weight of the nearest point on the source surface: a piece behind a painted face counts too.
    # Loose parts are not cut and keep their own weights (parts that touch must not read each other's).
    sampled = b.node("GeometryNodeSampleNearestSurface",
                     {"Mesh": geo_in, "Value": b.named(anchor_name, "FLOAT"), "Sample Position": b.pos()},
                     data_type="FLOAT")["Value"]
    weight = b.switch("FLOAT", loose, sampled, b.named(anchor_name, "FLOAT"))
    # one value per piece (the average over its corners), taken here, before the cut faces are
    # subdivided: how finely they are subdivided must not decide whether a piece is anchored
    piece_now = b.named(ATTR_PIECE, "INT")
    weight = b.math("DIVIDE",
                    b.node("GeometryNodeAccumulateField", {"Value": weight, "Group ID": piece_now},
                           data_type="FLOAT", domain="POINT")["Total"],
                    b.node("GeometryNodeAccumulateField", {"Value": 1.0, "Group ID": piece_now},
                           data_type="FLOAT", domain="POINT")["Total"])
    has_anchor = b.cmp("GREATER_THAN", b.node("FunctionNodeStringLength", {"String": anchor_name}).o, 0, "INT")
    g = b.switch("GEOMETRY", has_anchor, g, b.store(g, ATTR_ANCHOR, "FLOAT", "POINT", weight))
    is_inside = b.named(ATTR_INSIDE, "BOOLEAN")

    # box-projected UVs for the cut faces
    n_abs = b.vmath("ABSOLUTE", b.node("GeometryNodeInputNormal")["True Normal"])
    nx, ny, nz = b.sep(n_abs)
    x_dom = b.bmath("AND", b.cmp("GREATER_EQUAL", nx, ny), b.cmp("GREATER_EQUAL", nx, nz))
    y_dom = b.bmath("AND", b.bmath("NOT", x_dom), b.cmp("GREATER_EQUAL", ny, nz))
    px, py, pz = b.sep(b.pos())
    u = b.switch("FLOAT", x_dom, px, py)
    v = b.switch("FLOAT", b.bmath("OR", x_dom, y_dom), py, pz)
    uv = b.vmath("SCALE", b.comb(u, v, 0.0), scale=uv_scale)
    g = b.node("GeometryNodeStoreNamedAttribute",
               {"Geometry": g, "Name": uv_name, "Value": uv, "Selection": is_inside},
               data_type="FLOAT2", domain="CORNER").o

    with_mat = b.node("GeometryNodeSetMaterial", {"Geometry": g, "Selection": is_inside, "Material": inner_mat}).o
    g = b.switch("GEOMETRY", use_inner, g, with_mat)

    # ---- interior detail: roughen the cut faces. The collision proxy keeps the flat shape (rbd_rest)
    split = b.node("GeometryNodeSeparateGeometry", {"Geometry": g, "Selection": is_inside}, domain="FACE")
    inner = b.node("GeometryNodeTriangulate", {"Mesh": split["Selection"]}).o
    inner = b.node("GeometryNodeSubdivideMesh", {"Mesh": inner, "Level": detail}).o
    prox = b.node("GeometryNodeProximity", {"Geometry": geo_in}, target_element="FACES")
    fade = b.node("ShaderNodeMapRange", {"Value": prox["Distance"], "From Min": 0.0, "From Max": noise_fade,
                                         "To Min": 0.0, "To Max": 1.0}, interpolation_type="SMOOTHSTEP").o
    noise = b.node("ShaderNodeTexNoise", {"Scale": noise_scale, "Detail": 2.0}, noise_dimensions="3D")["Color"]
    wobble = b.vmath("SCALE", b.vmath("SUBTRACT", noise, (0.5, 0.5, 0.5)),
                     scale=b.math("MULTIPLY", b.math("MULTIPLY", noise_amp, 2.0), fade))
    inner = b.set_pos(inner, offset=wobble)
    join_detail = b.tree.nodes.new("GeometryNodeJoinGeometry")
    b.link(split["Inverted"], join_detail.inputs[0])
    b.link(inner, join_detail.inputs[0])
    use_detail = b.bmath("AND", b.cmp("GREATER_THAN", detail, 0, "INT"), b.cmp("GREATER_THAN", noise_amp, 0.0))
    g = b.switch("GEOMETRY", use_detail, g, join_detail.outputs[0])

    # ---- shading: the outside keeps the normals of the model it was cut from, so that the pieces at
    # rest look exactly like the unbroken model, without a seam where two of them meet. Cut faces are
    # flat. Stored in tangent space: the normals turn with the pieces when they move.
    face_centre = b.node("GeometryNodeFieldOnDomain", {"Value": b.pos()}, data_type="FLOAT_VECTOR", domain="FACE").o
    # read a little inside the face: on a hard edge of the model a corner must get its own side
    probe = b.vmath("ADD", b.vmath("SCALE", b.pos(), scale=0.97), b.vmath("SCALE", face_centre, scale=0.03))
    model_normal = b.node("GeometryNodeSampleNearestSurface",
                          {"Mesh": geo_in, "Value": b.node("GeometryNodeInputNormal")["Normal"], "Sample Position": probe},
                          data_type="FLOAT_VECTOR")["Value"]
    custom = b.switch("VECTOR", b.named(ATTR_INSIDE, "BOOLEAN"), model_normal,
                      b.node("GeometryNodeInputNormal")["True Normal"])
    g = b.node("GeometryNodeSetMeshNormal", {"Mesh": g, "Custom Normal": custom}, mode="TANGENT_SPACE", domain="CORNER").o

    pid = b.named(ATTR_PIECE, "INT")
    total = b.node("GeometryNodeAccumulateField", {"Value": b.pos(), "Group ID": pid},
                   data_type="FLOAT_VECTOR", domain="POINT")["Total"]
    count = b.node("GeometryNodeAccumulateField", {"Value": 1.0, "Group ID": pid},
                   data_type="FLOAT", domain="POINT")["Total"]
    pivot = b.vmath("SCALE", total, scale=b.math("DIVIDE", 1.0, count))
    g = b.store(g, ATTR_PIVOT, "FLOAT_VECTOR", "POINT", pivot)
    push = b.vmath("SCALE", b.vmath("SUBTRACT", b.named(ATTR_PIVOT, "FLOAT_VECTOR"), b.vmath("MULTIPLY", center, stretch)),
                   scale=explode)
    g = b.set_pos(g, offset=push)

    b.output("Geometry", "geo", g)
    return b.finish()


def ensure():
    return ensure_group(KIND_FRACTURE, VERSION, build)
