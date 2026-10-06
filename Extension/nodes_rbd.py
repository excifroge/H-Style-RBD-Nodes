# SPDX-License-Identifier: GPL-3.0-or-later
"""The RBD nodes: H-Style node groups.

Each of them is ONE node in the Geometry Nodes editor (or a modifier of its own): geometry goes
in, parameters sit on the node and in the sidebar, grouped the H-Style way, and the
result comes out with the attributes the next RBD node reads. As in H-Style they pass
three streams along: the geometry, the constraint geometry and the proxy geometry.

Attributes
    Geometry             piece_id   int, point    which piece a vertex belongs to (H-Style: name)
                         inside     bool, face    the face was made by the fracture (H-Style: inside group)
                         rbd_pivot  vector, point centre of the piece
                         rbd_rest   vector, point position before interior detail
    Constraint Geometry  one edge per pair of pieces that share a cut face, from pivot to pivot
                         piece_id   int, point    the piece that end of the edge holds on to
                         strength   float, edge   how much it takes to break the bond (H-Style: strength)
                         area       float, edge   size of the shared face
                         anchor     vector, edge  where the two pieces touch
"""
from . import nodes_fracture
from .nodekit import Builder, ensure_group

KIND_MATERIAL_FRACTURE = "material_fracture"
MATERIAL_FRACTURE = "RBD Material Fracture"
VERSION = 3
MATERIALS = ("Concrete", "Glass", "Wood")
DIRECTIONS = ("Auto", "X", "Y", "Z")


def _bonds(b, faces, strength, variance, by_area, seed, sliver):
    """Points, one per sighting of a contact between two pieces (rbd_c_a < rbd_c_b, rbd_c_key, the pivots
    rbd_c_pa / rbd_c_pb and the area rbd_c_area the sighting stands for), to constraint geometry: one edge
    per pair of pieces. A pair whose contact is smaller than `sliver` times the usual one is dropped."""
    # a contact is seen many times over: add it up, one point per pair of pieces
    group = b.named("rbd_c_key", "INT")
    area = b.named("rbd_c_area", "FLOAT")

    def total(data_type, value):
        return b.node("GeometryNodeAccumulateField", {"Value": value, "Group ID": group},
                      data_type=data_type, domain="POINT")
    whole = total("FLOAT", area)["Total"]
    anchor = b.vmath("SCALE", total("FLOAT_VECTOR", b.vmath("SCALE", b.pos(), scale=area))["Total"],
                     scale=b.math("DIVIDE", 1.0, b.math("MAXIMUM", whole, 1e-20)))
    first = b.cmp("EQUAL", total("INT", 1)["Leading"], 1, "INT")
    faces = b.store(faces, "rbd_c_anchor", "FLOAT_VECTOR", "POINT", anchor)     # before the areas are replaced by their sums
    faces = b.store(faces, "rbd_c_area", "FLOAT", "POINT", whole)
    pairs = b.node("GeometryNodeDeleteGeometry", {"Geometry": faces, "Selection": b.bmath("NOT", first)}, domain="POINT").o
    # touching along a sliver far smaller than the usual contact is not a bond
    usual = b.node("GeometryNodeAttributeStatistic", {"Geometry": pairs, "Attribute": b.named("rbd_c_area", "FLOAT")},
                   data_type="FLOAT", domain="POINT")["Median"]
    sliver = b.cmp("LESS_THAN", b.named("rbd_c_area", "FLOAT"), b.math("MULTIPLY", usual, sliver))
    pairs = b.node("GeometryNodeDeleteGeometry", {"Geometry": pairs, "Selection": sliver}, domain="POINT").o

    # strength: a bond over a small face is weaker than one over a large face (clamped so that one odd
    # face cannot dominate), then the random variance
    typical = b.node("GeometryNodeAttributeStatistic", {"Geometry": pairs, "Attribute": b.named("rbd_c_area", "FLOAT")},
                     data_type="FLOAT", domain="POINT")["Median"]
    size = b.math("SQRT", b.math("DIVIDE", b.named("rbd_c_area", "FLOAT"), b.math("MAXIMUM", typical, 1e-20)))
    size = b.switch("FLOAT", by_area, 1.0, b.math("MINIMUM", b.math("MAXIMUM", size, 0.35), 2.5))
    chance = b.rand("FLOAT", -1.0, 1.0, b.math("ADD", seed, 7), id=b.named("rbd_c_key", "INT"))
    bond = b.math("MAXIMUM", b.math("MULTIPLY", b.math("MULTIPLY", strength, size),
                                    b.math("ADD", 1.0, b.math("MULTIPLY", variance, chance))), 0.0)
    pairs = b.store(pairs, "rbd_c_strength", "FLOAT", "POINT", bond)

    # one edge per pair, from the pivot of one piece to the pivot of the other
    line = b.node("GeometryNodeMeshLine", {"Count": 2, "Offset": (0.0, 0.0, 1.0)}).o
    edges = b.node("GeometryNodeRealizeInstances",
                   {"Geometry": b.node("GeometryNodeInstanceOnPoints", {"Points": pairs, "Instance": line}).o}).o
    far_end = b.cmp("EQUAL", b.math("FLOORED_MODULO", b.index(), 2.0), 1.0)
    edges = b.set_pos(edges, position=b.switch("VECTOR", far_end, b.named("rbd_c_pa", "FLOAT_VECTOR"),
                                               b.named("rbd_c_pb", "FLOAT_VECTOR")))
    edges = b.store(edges, nodes_fracture.ATTR_PIECE, "INT", "POINT",
                    b.switch("INT", far_end, b.named("rbd_c_a", "INT"), b.named("rbd_c_b", "INT")))
    edges = b.store(edges, "strength", "FLOAT", "EDGE", b.named("rbd_c_strength", "FLOAT"))
    edges = b.store(edges, "area", "FLOAT", "EDGE", b.named("rbd_c_area", "FLOAT"))
    edges = b.store(edges, "anchor", "FLOAT_VECTOR", "EDGE", b.named("rbd_c_anchor", "FLOAT_VECTOR"))
    for temp in ("rbd_c_a", "rbd_c_b", "rbd_c_key", "rbd_c_pa", "rbd_c_pb", "rbd_c_area", "rbd_c_anchor", "rbd_c_strength"):
        edges = b.node("GeometryNodeRemoveAttribute", {"Geometry": edges, "Name": temp}).o
    return edges


def constraint_network(b, pieces, strength, variance, by_area, seed):
    """Constraint geometry for fractured pieces: one edge per pair of pieces that share a cut face.

    Two neighbours were cut apart by one plane, so the face each of them has on that plane is the
    same polygon. Every cut face therefore has a twin: the nearest other cut face, lying in the same
    plane and looking the other way. The piece that twin belongs to is the neighbour."""
    flat = b.set_pos(pieces, position=b.named(nodes_fracture.ATTR_REST, "FLOAT_VECTOR"))
    flat, cap = b.capture(flat, "FACE",
                          own=("INT", b.named(nodes_fracture.ATTR_PIECE, "INT")),
                          pivot=("VECTOR", b.named(nodes_fracture.ATTR_PIVOT, "FLOAT_VECTOR")),
                          normal=("VECTOR", b.node("GeometryNodeInputNormal")["True Normal"]),
                          area=("FLOAT", b.node("GeometryNodeInputMeshFaceArea").o))
    faces = b.node("GeometryNodeMeshToPoints",
                   {"Mesh": flat, "Selection": b.named(nodes_fracture.ATTR_INSIDE, "BOOLEAN")}, mode="FACES").o
    bb = b.node("GeometryNodeBoundBox", {"Geometry": flat})
    reach = b.vmath("LENGTH", b.vmath("SUBTRACT", bb["Max"], bb["Min"]))
    twin = b.node("GeometryNodeIndexOfNearest", {"Position": b.pos()})

    def of_twin(data_type, value):
        return b.node("GeometryNodeFieldAtIndex", {"Value": value, "Index": twin["Index"]},
                      data_type=data_type, domain="POINT").o
    other = of_twin("INT", cap["own"])
    other_pivot = of_twin("FLOAT_VECTOR", cap["pivot"])
    apart = b.vmath("SUBTRACT", of_twin("FLOAT_VECTOR", b.pos()), b.pos())
    in_plane = b.cmp("LESS_THAN", b.math("ABSOLUTE", b.vmath("DOT_PRODUCT", cap["normal"], apart)), b.math("MULTIPLY", reach, 1e-4))
    facing = b.cmp("LESS_THAN", b.vmath("DOT_PRODUCT", cap["normal"], of_twin("FLOAT_VECTOR", cap["normal"])), -0.99)
    found = b.bmath("AND", b.bmath("AND", twin["Has Neighbor"], in_plane), facing)
    # every shared face is seen from both sides: keep the side with the lower piece number
    keep = b.bmath("AND", found, b.cmp("LESS_THAN", cap["own"], other, "INT"))
    key = b.node("FunctionNodeIntegerMath", {0: cap["own"], 1: 100000, 2: other}, operation="MULTIPLY_ADD").o
    faces = b.store(faces, "rbd_c_a", "INT", "POINT", cap["own"])
    faces = b.store(faces, "rbd_c_b", "INT", "POINT", other)
    faces = b.store(faces, "rbd_c_key", "INT", "POINT", key)
    faces = b.store(faces, "rbd_c_pa", "FLOAT_VECTOR", "POINT", cap["pivot"])
    faces = b.store(faces, "rbd_c_pb", "FLOAT_VECTOR", "POINT", other_pivot)
    faces = b.store(faces, "rbd_c_area", "FLOAT", "POINT", cap["area"])
    faces = b.node("GeometryNodeDeleteGeometry", {"Geometry": faces, "Selection": b.bmath("NOT", keep)}, domain="POINT").o

    return _bonds(b, faces, strength, variance, by_area, seed, 1e-3), flat


def _or_position(b, name):
    """The vector attribute `name`, or the position where the geometry does not have it."""
    had = b.node("GeometryNodeInputNamedAttribute", {"Name": name}, data_type="FLOAT_VECTOR")
    return b.switch("VECTOR", had["Exists"], b.pos(), had["Attribute"])


def proximity_network(b, pieces, reach, samples, strength, variance, by_area, seed):
    """Constraint geometry for pieces of any origin: one edge per pair of pieces whose surfaces are
    closer than `reach`.

    Points are scattered over the surfaces. Each looks half the reach ahead, along the normal of its
    face, and asks which surface is nearest from there. If that is the surface of another piece, the
    two are neighbours. So that a face lying exactly on the face of a neighbour does not tie with it,
    the surfaces that are asked are pulled in a little: the neighbour's then is the nearer one."""
    flat = b.set_pos(pieces, position=_or_position(b, nodes_fracture.ATTR_REST))
    flat, cap = b.capture(flat, "FACE",
                          own=("INT", b.named(nodes_fracture.ATTR_PIECE, "INT")),
                          pivot=("VECTOR", _or_position(b, nodes_fracture.ATTR_PIVOT)),
                          area=("FLOAT", b.node("GeometryNodeInputMeshFaceArea").o))
    bb = b.node("GeometryNodeBoundBox", {"Geometry": flat})
    size = b.vmath("LENGTH", b.vmath("SUBTRACT", bb["Max"], bb["Min"]))
    ahead = b.math("MAXIMUM", b.math("MULTIPLY", reach, 0.5), b.math("MULTIPLY", size, 1e-4))
    surface = b.node("GeometryNodeAttributeStatistic", {"Geometry": flat, "Attribute": cap["area"]},
                     data_type="FLOAT", domain="FACE")["Sum"]
    count = b.math("ADD", b.node("GeometryNodeAttributeStatistic",
                                 {"Geometry": flat, "Attribute": b.named(nodes_fracture.ATTR_PIECE, "INT")},
                                 data_type="FLOAT", domain="POINT")["Max"], 1.0)
    density = b.math("DIVIDE", b.math("MULTIPLY", samples, count), b.math("MAXIMUM", surface, 1e-12))
    scatter = b.node("GeometryNodeDistributePointsOnFaces", {"Mesh": flat, "Density": density, "Seed": seed},
                     distribute_method="RANDOM")
    points = scatter["Points"]
    pulled_in = b.set_pos(flat, offset=b.vmath("SCALE", b.node("GeometryNodeInputNormal")["Normal"],
                                               scale=b.math("MULTIPLY", ahead, -0.1)))
    probe = b.vmath("ADD", b.pos(), b.vmath("SCALE", scatter["Normal"], scale=ahead))

    def nearest(data_type, value):
        return b.node("GeometryNodeSampleNearestSurface", {"Mesh": pulled_in, "Value": value, "Sample Position": probe},
                      data_type=data_type)["Value"]
    other = nearest("INT", cap["own"])
    other_pivot = nearest("FLOAT_VECTOR", cap["pivot"])
    # the same contact is seen from both pieces: the lower piece number comes first, whoever saw it
    lower = b.cmp("LESS_THAN", cap["own"], other, "INT")
    first = b.switch("INT", lower, other, cap["own"])
    second = b.switch("INT", lower, cap["own"], other)
    key = b.node("FunctionNodeIntegerMath", {0: first, 1: 100000, 2: second}, operation="MULTIPLY_ADD").o
    points = b.store(points, "rbd_c_a", "INT", "POINT", first)
    points = b.store(points, "rbd_c_b", "INT", "POINT", second)
    points = b.store(points, "rbd_c_key", "INT", "POINT", key)
    points = b.store(points, "rbd_c_pa", "FLOAT_VECTOR", "POINT", b.switch("VECTOR", lower, other_pivot, cap["pivot"]))
    points = b.store(points, "rbd_c_pb", "FLOAT_VECTOR", "POINT", b.switch("VECTOR", lower, cap["pivot"], other_pivot))
    # every point stands for the same share of the surface, and both sides of a contact are counted
    points = b.store(points, "rbd_c_area", "FLOAT", "POINT", b.math("DIVIDE", 0.5, b.math("MAXIMUM", density, 1e-12)))
    alone = b.cmp("EQUAL", cap["own"], other, "INT")
    points = b.node("GeometryNodeDeleteGeometry", {"Geometry": points, "Selection": alone}, domain="POINT").o
    return _bonds(b, points, strength, variance, by_area, seed, 0.05), flat


def build_material_fracture():
    kernel = nodes_fracture.ensure()
    b = Builder(MATERIAL_FRACTURE, KIND_MATERIAL_FRACTURE, VERSION)
    geo = b.input("Geometry", "geo", desc="The geometry to fracture")
    con_in = b.input("Constraint Geometry", "geo", desc="Constraints made upstream: passed on with the new ones")
    proxy_in = b.input("Proxy Geometry", "geo", desc="Proxy geometry made upstream: passed on with the new one")
    extra = b.input("Extra Points", "geo",
                    desc="Optional. Concrete and Wood: use these points as cell points instead of scattering. "
                         "Glass: the first point is the impact point")
    material = b.menu("Material Type", MATERIALS, "Concrete",
                      desc="Concrete: chunky pieces. Glass: radial and concentric cracks through a pane. "
                           "Wood: long splinters along the grain")
    seed = b.input("Random Seed", "int", 0, min=0)
    impact = b.input("Impact Point", "vec", (0.0, 0.0, 0.0), subtype="TRANSLATION",
                     desc="Where the object is hit, in its own space. Glass cracks start here; concrete breaks finer here")

    b.panel("Primary Fracture")
    scatter = b.input("Scatter Points", "int", 30, min=1, max=5000, desc="Number of cell points, about one piece each")
    scatter_seed = b.input("Scatter Seed", "int", 0, min=0)
    bias = b.input("Impact Bias", "float", 0.0, min=0.0, max=1.0, subtype="FACTOR",
                   desc="Share of the cell points gathered around the Impact Point")
    radius = b.input("Impact Radius", "float", 0.5, min=0.001, subtype="DISTANCE")
    cut_through = b.input("Cut Through", "bool", False,
                          desc="Every cut goes straight through the thinnest axis: slabs, ground, walls seen from the front")

    b.panel("Secondary Fracture", closed=True)
    sec_on = b.input("Enable Fracture", "bool", False, toggle=True)
    sec_ratio = b.input("Fracture Ratio", "float", 0.3, min=0.0, max=1.0, subtype="FACTOR",
                        desc="Share of the pieces that are fractured again")
    sec_points = b.input("Points per Piece", "int", 4, min=1, max=32)

    b.panel("Cracks")
    radial_n = b.input("Radial Crack Number", "int", 16, min=3, max=128, desc="Cracks running outward from the impact point")
    ring_n = b.input("Concentric Crack Number", "int", 6, min=1, max=64, desc="Rings of cracks around the impact point")
    spread = b.input("Impact Spread", "float", 1.5, min=0.001, subtype="DISTANCE",
                     desc="How far from the impact point the concentric cracks reach")

    b.panel("Grain")
    direction = b.menu("Fracture Direction", DIRECTIONS, "Auto", desc="Direction of the grain. Auto: the longest side of the object")
    splinter = b.input("Splinter Length", "float", 6.0, min=1.0, desc="How much longer than wide the splinters are")

    b.panel("Detail", closed=True)
    detail_on = b.input("Interior Detail", "bool", False, toggle=True)
    detail = b.input("Detail Level", "int", 1, min=1, max=5, desc="Subdivisions of the cut faces: every level is four times the polygons")
    noise_amp = b.input("Noise Amplitude", "float", 0.02, min=0.0, subtype="DISTANCE")
    noise_freq = b.input("Frequency", "float", 3.0, min=0.0)
    edge_fade = b.input("Edge Fade", "float", 0.05, min=0.0001, subtype="DISTANCE",
                        desc="The noise fades out over this distance from the original surface, so the outside stays closed")

    b.panel("Constraints")
    con_on = b.input("Create Constraints", "bool", True, toggle=True)
    strength = b.input("Primary Strength", "float", 5.0, min=0.0, desc="Strength of the glue between neighbouring pieces")
    variance = b.input("Strength Variance", "float", 0.0, min=0.0, max=1.0, subtype="FACTOR")
    by_area = b.input("Scale by Contact Area", "bool", True, desc="Pieces that share a small face are held together less strongly")

    b.panel("Output", closed=True)
    use_mat = b.input("Assign Inside Material", "bool", False)
    inside_mat = b.input("Inside Material", "mat")
    uv_name = b.input("UV Map", "str", "UVMap", desc="Cut faces get box-projected UVs in this UV map")
    uv_scale = b.input("Inside UV Scale", "float", 1.0, min=0.0)
    robust = b.input("Robust Boolean", "bool", False, desc="Always use the slow exact boolean (it is used automatically where the fast one fails)")
    keep_name = b.input("Keep Vertex Group", "str", "",
                        desc="A vertex group (or float attribute) of the input that the pieces keep under the same name, "
                             "to select pieces with further down: paint where pieces must stay, for example")

    # ---- the grain direction: the longest side of the object, unless one is chosen
    bb = b.node("GeometryNodeBoundBox", {"Geometry": geo})
    sx, sy, sz = b.sep(b.vmath("SUBTRACT", bb["Max"], bb["Min"]))
    x_long = b.bmath("AND", b.cmp("GREATER_EQUAL", sx, sy), b.cmp("GREATER_EQUAL", sx, sz))
    y_long = b.bmath("AND", b.bmath("NOT", x_long), b.cmp("GREATER_EQUAL", sy, sz))
    z_long = b.bmath("NOR", x_long, y_long)
    axis = direction("VECTOR", {"Auto": b.comb(x_long, y_long, z_long), "X": (1.0, 0.0, 0.0), "Y": (0.0, 1.0, 0.0),
                                "Z": (0.0, 0.0, 1.0)})
    stretch = b.vmath("ADD", (1.0, 1.0, 1.0), b.vmath("SCALE", axis, scale=b.math("SUBTRACT", splinter, 1.0)))

    # ---- what the material means for the cell points
    cells = b.math("MULTIPLY", radial_n, ring_n)      # glass: one cell point per crossing of the web
    pieces = b.group(kernel, {
        "Geometry": geo,
        "Extra Points": extra,
        "Pieces": material("INT", {"Concrete": scatter, "Glass": cells, "Wood": scatter}),
        "Seed": b.math("ADD", seed, scatter_seed),
        "Impact Bias": material("FLOAT", {"Concrete": bias, "Glass": 0.0, "Wood": 0.0}),
        "Impact Point": impact,
        "Impact Radius": material("FLOAT", {"Concrete": radius, "Glass": spread, "Wood": 0.5}),
        # (everything of a panel goes through the material: what a material does not use is then hidden on the node)
        "Secondary Ratio": material("FLOAT", {"Concrete": b.switch("FLOAT", sec_on, 0.0, sec_ratio), "Glass": 0.0, "Wood": 0.0}),
        "Secondary Pieces": material("INT", {"Concrete": sec_points, "Glass": 4, "Wood": 4}),
        "Cell Stretch": material("VECTOR", {"Concrete": (1.0, 1.0, 1.0), "Glass": (1.0, 1.0, 1.0), "Wood": stretch}),
        "Flat": material("BOOLEAN", {"Concrete": cut_through, "Glass": True, "Wood": False}),
        "Radial Cracks": material("BOOLEAN", {"Concrete": False, "Glass": True, "Wood": False}),
        "Rings": material("INT", {"Concrete": 5, "Glass": ring_n, "Wood": 5}),
        "Spokes": material("INT", {"Concrete": 12, "Glass": radial_n, "Wood": 12}),
        "Detail Level": b.switch("INT", detail_on, 0, detail),
        "Noise Height": b.switch("FLOAT", detail_on, 0.0, noise_amp),
        "Noise Scale": noise_freq,
        "Edge Fade": edge_fade,
        "Use Inner Material": use_mat,
        "Inner Material": inside_mat,
        "UV Map": uv_name,
        "Inner UV Scale": uv_scale,
        "Robust Boolean": robust,
    }).o

    # Attributes of the input do not survive the cut: every vertex of the pieces takes the value of the
    # nearest point on the surface it was cut from (a piece behind a painted face counts as painted too)
    kept = b.node("GeometryNodeSampleNearestSurface",
                  {"Mesh": geo, "Value": b.named(keep_name, "FLOAT"),
                   "Sample Position": b.named(nodes_fracture.ATTR_REST, "FLOAT_VECTOR")}, data_type="FLOAT")["Value"]
    with_kept = b.node("GeometryNodeStoreNamedAttribute", {"Geometry": pieces, "Name": keep_name, "Value": kept},
                       data_type="FLOAT", domain="POINT").o
    pieces = b.switch("GEOMETRY", b.cmp("GREATER_THAN", b.node("FunctionNodeStringLength", {"String": keep_name}).o, 0, "INT"),
                      pieces, with_kept)

    network, flat = constraint_network(b, pieces, strength, variance, by_area, seed)
    join_con = b.tree.nodes.new("GeometryNodeJoinGeometry")
    b.link(con_in, join_con.inputs[0])
    b.link(b.switch("GEOMETRY", con_on, None, network), join_con.inputs[0])
    join_proxy = b.tree.nodes.new("GeometryNodeJoinGeometry")
    b.link(proxy_in, join_proxy.inputs[0])
    b.link(flat, join_proxy.inputs[0])

    b.output("Geometry", "geo", pieces, desc="The pieces, with piece_id and inside")
    b.output("Constraint Geometry", "geo", join_con.outputs[0], desc="One edge per glue bond, with strength")
    b.output("Proxy Geometry", "geo", join_proxy.outputs[0], desc="The pieces without interior detail: what collides")
    return b.finish()


def material_fracture():
    return ensure_group(KIND_MATERIAL_FRACTURE, VERSION, build_material_fracture)


# ====================================================================== the other nodes of the family
KIND_CONFIGURE = "configure"
KIND_CONSTRAINT_PROPERTIES = "constraint_properties"
KIND_CLUSTER = "cluster"
KIND_EXPLODED_VIEW = "exploded_view"
KIND_BULLET_SOLVER = "bullet_solver"
CONFIGURE = "RBD Configure"
CONSTRAINT_PROPERTIES = "RBD Constraint Properties"
CLUSTER = "RBD Cluster"
EXPLODED_VIEW = "RBD Exploded View"
BULLET_SOLVER = "RBD Bullet Solver"
SOLVER_VERSION = 6

# attributes the solver reads from the pieces (all per piece: the average over the piece is used)
ATTR_ACTIVE = "active"              # bool: false = the piece never moves, but still collides (H-Style: active)
ATTR_VELOCITY = "v"                 # vector: velocity when the piece is handed to the solver (H-Style: v)
ATTR_SPIN = "w"                     # vector: angular velocity, radians per second (H-Style: w)
ATTR_ACTIVATE = "activate_time"     # float: seconds after the start frame at which the piece is handed over
ATTR_DENSITY, ATTR_FRICTION, ATTR_BOUNCE = "density", "friction", "bounce"
ATTR_CLUSTER = "cluster"


def _streams(b):
    """The three inputs every RBD node starts with."""
    return (b.input("Geometry", "geo", desc="The pieces"),
            b.input("Constraint Geometry", "geo", desc="One edge per glue bond"),
            b.input("Proxy Geometry", "geo", desc="What collides"))


def _streams_out(b, geo, con, proxy):
    b.output("Geometry", "geo", geo)
    b.output("Constraint Geometry", "geo", con)
    b.output("Proxy Geometry", "geo", proxy)


def build_configure():
    b = Builder(CONFIGURE, KIND_CONFIGURE, 3, modifier=False)
    geo, con, proxy = _streams(b)
    selection = b.input("Selection", "bool", True, desc="The pieces to configure. A piece counts as selected when most of it is")
    pivot = b.named(nodes_fracture.ATTR_PIVOT, "FLOAT_VECTOR")
    piece = b.named(nodes_fracture.ATTR_PIECE, "INT")

    def assign(geometry, name, data_type, value, unset):
        """Write `value` on the selected points. The others keep what they have; if the attribute is new,
        they get `unset`, which the solver reads as "nothing was set here"."""
        had = b.node("GeometryNodeInputNamedAttribute", {"Name": name}, data_type=data_type)
        kind = {"FLOAT_VECTOR": "VECTOR"}.get(data_type, data_type)
        keep = b.switch(kind, had["Exists"], unset, had["Attribute"])
        return b.store(geometry, name, data_type, "POINT", b.switch(kind, selection, keep, value))

    b.panel("Set Active")
    on = b.input("Set Active", "bool", False, toggle=True)
    active = b.input("Active", "bool", True, desc="Off: the selected pieces never move, but other pieces still collide with them")
    g = b.switch("GEOMETRY", on, geo, assign(geo, ATTR_ACTIVE, "BOOLEAN", active, True))

    b.panel("Set Initial Velocity", closed=True)
    on = b.input("Set Initial Velocity", "bool", False, toggle=True)
    mode = b.menu("Velocity Type", ("Constant", "Radial"), "Radial",
                  desc="Constant: the same velocity for every piece. Radial: away from a point, like an explosion")
    velocity = b.input("Velocity", "vec", (0.0, 0.0, 0.0), subtype="VELOCITY")
    origin = b.input("Origin", "vec", (0.0, 0.0, 0.0), subtype="TRANSLATION", desc="Centre of the blast, in the space of the object")
    speed = b.input("Speed", "float", 8.0, min=0.0, desc="Metres per second at the origin")
    falloff = b.input("Falloff Radius", "float", 0.0, min=0.0, subtype="DISTANCE", desc="The speed fades to zero at this distance. 0 = no fade")
    up = b.input("Up Bias", "float", 0.3, min=0.0, max=1.0, subtype="FACTOR", desc="0 = straight away from the origin, 1 = straight up")
    variance = b.input("Speed Variance", "float", 0.3, min=0.0, max=1.0, subtype="FACTOR")
    spin = b.input("Spin", "float", 3.0, min=0.0, desc="Random tumbling, radians per second")
    seed = b.input("Seed", "int", 0, min=0)
    away = b.vmath("SUBTRACT", pivot, origin)
    dist = b.vmath("LENGTH", away)
    aim = b.vmath("ADD", b.vmath("SCALE", b.vmath("NORMALIZE", away), scale=b.math("SUBTRACT", 1.0, up)),
                  b.vmath("SCALE", (0.0, 0.0, 1.0), scale=up))
    fade = b.switch("FLOAT", b.cmp("GREATER_THAN", falloff, 0.0), 1.0,
                    b.math("MAXIMUM", b.math("SUBTRACT", 1.0, b.math("DIVIDE", dist, b.math("MAXIMUM", falloff, 1e-6))), 0.0))
    jitter = b.math("ADD", 1.0, b.math("MULTIPLY", variance, b.rand("FLOAT", -1.0, 1.0, b.math("ADD", seed, 11), id=piece)))
    radial = b.vmath("SCALE", b.vmath("NORMALIZE", aim), scale=b.math("MULTIPLY", b.math("MULTIPLY", speed, fade), jitter))
    axis = b.vmath("NORMALIZE", b.rand("FLOAT_VECTOR", (-1.0, -1.0, -1.0), (1.0, 1.0, 1.0), b.math("ADD", seed, 12), id=piece))
    tumble = b.vmath("SCALE", axis, scale=b.math("MULTIPLY", b.math("MULTIPLY", spin, fade),
                                                 b.rand("FLOAT", 0.3, 1.0, b.math("ADD", seed, 13), id=piece)))
    v = mode("VECTOR", {"Constant": velocity, "Radial": radial})
    w = mode("VECTOR", {"Constant": (0.0, 0.0, 0.0), "Radial": tumble})
    with_v = assign(assign(g, ATTR_VELOCITY, "FLOAT_VECTOR", v, (0.0, 0.0, 0.0)), ATTR_SPIN, "FLOAT_VECTOR", w, (0.0, 0.0, 0.0))
    g = b.switch("GEOMETRY", on, g, with_v)

    b.panel("Set Activation", closed=True)
    on = b.input("Set Activation", "bool", False, toggle=True)
    wave = b.menu("Activation Type", ("At Time", "Radial Wave"), "Radial Wave",
                  desc="When the pieces are handed to the solver; until then they hold still. "
                       "Radial Wave: one after the other, by their distance from a point")
    delay = b.input("Delay", "float", 0.0, min=0.0, desc="Seconds after the start frame")
    wave_origin = b.input("Wave Origin", "vec", (0.0, 0.0, 0.0), subtype="TRANSLATION")
    wave_speed = b.input("Wave Speed", "float", 10.0, min=0.001, desc="Metres per second")
    reach = b.vmath("LENGTH", b.vmath("SUBTRACT", pivot, wave_origin))
    when = wave("FLOAT", {"At Time": delay, "Radial Wave": b.math("ADD", delay, b.math("DIVIDE", reach, wave_speed))})
    g = b.switch("GEOMETRY", on, g, assign(g, ATTR_ACTIVATE, "FLOAT", when, 0.0))

    b.panel("Set Physical Properties", closed=True)
    on = b.input("Set Physical Properties", "bool", False, toggle=True)
    density = b.input("Density", "float", 100.0, min=0.001, desc="Mass per cubic metre")
    friction = b.input("Friction", "float", 0.6, min=0.0)
    bounce = b.input("Bounce", "float", 0.05, min=0.0, max=1.0)
    # -1 = not set: the solver then uses the value on the solver node
    phys = assign(assign(assign(g, ATTR_DENSITY, "FLOAT", density, -1.0), ATTR_FRICTION, "FLOAT", friction, -1.0),
                  ATTR_BOUNCE, "FLOAT", bounce, -1.0)
    g = b.switch("GEOMETRY", on, g, phys)
    _streams_out(b, g, con, proxy)
    return b.finish()


def build_constraint_properties():
    b = Builder(CONSTRAINT_PROPERTIES, KIND_CONSTRAINT_PROPERTIES, 2, modifier=False)
    geo, con, proxy = _streams(b)
    selection = b.input("Selection", "bool", True, desc="The constraints to change (evaluated on the edges of the constraint geometry)")
    how = b.menu("Operation", ("Set To", "Multiply By"), "Set To")
    strength = b.input("Strength", "float", 5.0, min=0.0)
    value = how("FLOAT", {"Set To": strength, "Multiply By": b.math("MULTIPLY", b.named("strength", "FLOAT"), strength)})
    _streams_out(b, geo, b.store(con, "strength", "FLOAT", "EDGE", value, selection), proxy)
    return b.finish()


def build_cluster():
    b = Builder(CLUSTER, KIND_CLUSTER, 1, modifier=False)
    geo, con, proxy = _streams(b)
    size = b.input("Size", "float", 1.0, min=0.001, subtype="DISTANCE", desc="Rough size of a cluster")
    jitter = b.input("Jitter", "float", 1.0, min=0.0, max=1.0, subtype="FACTOR")
    seed = b.input("Seed", "int", 0, min=0)
    scale = b.input("Strength Scale", "float", 10.0, min=0.0, desc="Bonds inside a cluster are this many times stronger")

    def cluster_at(position):
        # the cell of a cellular noise the position falls in: its colour, squeezed into one number
        cell = b.node("ShaderNodeTexVoronoi",
                      {"Vector": b.vmath("ADD", position, b.vmath("SCALE", (17.3, 5.1, 9.7), scale=seed)),
                       "Scale": b.math("DIVIDE", 1.0, size), "Randomness": jitter},
                      voronoi_dimensions="3D", feature="F1")["Color"]
        r, g_, bl = b.sep(cell)
        return b.math("FLOOR", b.math("ADD", b.math("ADD", b.math("MULTIPLY", r, 1000.0), b.math("MULTIPLY", g_, 1000000.0)),
                                      b.math("MULTIPLY", bl, 97.0)))
    geo = b.store(geo, ATTR_CLUSTER, "INT", "POINT", cluster_at(b.named(nodes_fracture.ATTR_PIVOT, "FLOAT_VECTOR")))
    # the two ends of a constraint sit on the pivots of the pieces it holds together
    con = b.store(con, ATTR_CLUSTER, "INT", "POINT", cluster_at(b.pos()))
    ends = b.node("GeometryNodeInputMeshEdgeVertices")

    def end(index):
        return b.node("GeometryNodeFieldAtIndex", {"Value": b.named(ATTR_CLUSTER, "INT"), "Index": index},
                      data_type="INT", domain="POINT").o
    same = b.cmp("EQUAL", end(ends["Vertex Index 1"]), end(ends["Vertex Index 2"]), "INT")
    con = b.store(con, "strength", "FLOAT", "EDGE", b.math("MULTIPLY", b.named("strength", "FLOAT"), scale), same)
    _streams_out(b, geo, con, proxy)
    return b.finish()


def build_exploded_view():
    b = Builder(EXPLODED_VIEW, KIND_EXPLODED_VIEW, 1, modifier=False)
    geo = b.input("Geometry", "geo", desc="The pieces")
    scale = b.input("Scale", "float", 0.3, min=0.0, desc="How far the pieces are pushed apart")
    bb = b.node("GeometryNodeBoundBox", {"Geometry": geo})
    centre = b.vmath("SCALE", b.vmath("ADD", bb["Min"], bb["Max"]), scale=0.5)
    push = b.vmath("SCALE", b.vmath("SUBTRACT", b.named(nodes_fracture.ATTR_PIVOT, "FLOAT_VECTOR"), centre), scale=scale)
    b.output("Geometry", "geo", b.set_pos(geo, offset=push))
    return b.finish()


def build_bullet_solver():
    from . import nodes_playback
    playback = nodes_playback.ensure()
    b = Builder(BULLET_SOLVER, KIND_BULLET_SOLVER, SOLVER_VERSION, modifier=False)
    geo, con, proxy = _streams(b)
    # The simulation itself is run by the Bake button (Bullet cannot run inside a node tree): these
    # values are read from the node then. `read` collects them, see below.
    read = [b.input("Start Frame", "int", 1, desc="The frame the simulation starts on"),
            b.input("End Frame", "int", 120, desc="The last frame that is baked")]
    time_scale = b.input("Time Scale", "float", 1.0, min=0.0, desc="Playback speed of the bake: 0.5 is slow motion")
    b.panel("Simulation")
    read += [b.input("Bullet Substeps", "int", 10, min=1, max=200, desc="Solver steps per frame. Raise for fast or thin pieces"),
             b.input("Constraint Iterations", "int", 10, min=1, max=200),
             b.input("Glue Iterations", "int", 30, min=0, max=500,
                     desc="Iterations spent on every glue bond: more makes glued pieces stiffer. 0 = as Constraint Iterations")]
    b.panel("Properties")
    read += [b.input("Density", "float", 100.0, min=0.001, desc="Mass per cubic metre, for pieces without a density attribute"),
             b.input("Bounce", "float", 0.05, min=0.0, max=1.0),
             b.input("Friction", "float", 0.6, min=0.0),
             b.input("Collision Padding", "float", 0.0, min=0.0, subtype="DISTANCE"),
             b.input("Linear Damping", "float", 0.04, min=0.0, max=1.0, subtype="FACTOR"),
             b.input("Angular Damping", "float", 0.1, min=0.0, max=1.0, subtype="FACTOR"),
             b.input("Start Asleep", "bool", False, desc="Pieces rest until something hits them")]
    b.panel("Collision")
    colliders = b.input("Collision Objects", "col", desc="Objects the pieces collide with. They follow their own animation")
    read += [b.input("Ground Plane", "bool", True),
             b.input("Ground Height", "float", 0.0, subtype="DISTANCE", desc="World height of the ground plane")]
    b.panel("Forces")
    read.append(b.vmath("LENGTH", b.input("Gravity", "vec", (0.0, 0.0, -9.81), subtype="ACCELERATION")))
    read += [b.input("Force Fields", "bool", True,
                     desc="The force fields of the scene (Force, Wind, Vortex, Turbulence ...) act on the pieces, "
                          "the way they act on Blender's own rigid bodies. Works together with initial velocities"),
             b.input("Field Weight", "float", 1.0, min=0.0, max=200.0,
                     desc="Every force field is multiplied by this. Blender's rigid bodies feel a field of strength 1 "
                          "as a force of 1 / frame rate newtons, so heavy pieces need strong fields")]
    effectors = b.input("Limit To", "col", desc="Only the force fields in this collection act. Empty: every force field of the scene")
    b.panel("Cache", closed=True, desc="Filled in by Bake. Free the bake to clear it", always_closed=True)
    baked = b.input("Baked", "bool", False, desc="The node plays the baked simulation instead of passing its input on")
    cache = b.input("Cache", "obj")
    frozen = b.input("Frozen Pieces", "obj", desc="The pieces as they were when the simulation was baked")
    count = b.input("Piece Count", "int", 0, min=0)
    frames = b.input("Frame Count", "int", 0, min=0)
    start = b.input("Cache Start Frame", "int", 1)
    offset = b.input("Frame Offset", "float", 0.0, desc="Shift the baked motion in time, in frames")
    # The baked motion is played on the pieces frozen at bake time. The input geometry must only meet the
    # switch below: wired into the playback group as well, it was computed on every frame (measured: 25 ms
    # per frame instead of 0.3 for a 60 piece fracture upstream), although nothing used it.
    pieces = b.node("GeometryNodeObjectInfo", {"Object": frozen}, transform_space="ORIGINAL")["Geometry"]
    played = b.group(playback, {"Geometry": pieces, "Use Frozen Pieces": False, "Cache": cache,
                                "Piece Count": count, "Frame Count": frames, "Start Frame": start,
                                "Speed": time_scale, "Frame Offset": offset}).o
    out = b.switch("GEOMETRY", baked, geo, played)
    # Blender hides the inputs of a node that have no effect on its outputs, and nothing in this tree
    # uses the solver settings. So they are wired into a switch that never switches (a value times
    # zero is never above one): they count as used, and nothing is computed for it.
    total = read[0]
    for value in read[1:]:
        total = b.math("ADD", total, value)
    # (the collection counts through the number of instances it comes in as: one, nothing is realised)
    for collection in (colliders, effectors):
        total = b.math("ADD", total, b.node("GeometryNodeAttributeDomainSize",
                                            {"Geometry": b.node("GeometryNodeCollectionInfo", {"Collection": collection}).o},
                                            component="INSTANCES")["Instance Count"])
    never = b.cmp("GREATER_THAN", b.math("MULTIPLY", b.math("MINIMUM", total, 1.0), 0.0), 1.0)
    out = b.switch("GEOMETRY", never, out, None)
    _streams_out(b, out, con, proxy)
    return b.finish()


KIND_ASSEMBLE = "assemble"
KIND_CONSTRAINTS_FROM_RULES = "constraints_from_rules"
KIND_SELECT = "select"
ASSEMBLE = "RBD Assemble"
CONSTRAINTS_FROM_RULES = "RBD Constraints From Rules"
SELECT = "RBD Select"
SELECT_TYPES = ("Below Height", "Box", "Sphere", "Attribute")


def build_assemble():
    b = Builder(ASSEMBLE, KIND_ASSEMBLE, 1)
    geo = b.input("Geometry", "geo", desc="A model that is already in pieces: bricks, planks, hand-cut debris")
    con = b.input("Constraint Geometry", "geo", desc="Constraints made upstream: passed on")
    proxy_in = b.input("Proxy Geometry", "geo", desc="Proxy geometry made upstream: passed on with the new one")
    # nothing is cut: every loose part (connected island) of the mesh is one piece
    g = b.store(geo, nodes_fracture.ATTR_PIECE, "INT", "POINT", b.node("GeometryNodeInputMeshIsland")["Island Index"])
    g = b.store(g, nodes_fracture.ATTR_INSIDE, "BOOLEAN", "FACE", False)
    g = b.store(g, nodes_fracture.ATTR_REST, "FLOAT_VECTOR", "POINT", b.pos())
    piece = b.named(nodes_fracture.ATTR_PIECE, "INT")
    total = b.node("GeometryNodeAccumulateField", {"Value": b.pos(), "Group ID": piece},
                   data_type="FLOAT_VECTOR", domain="POINT")["Total"]
    count = b.node("GeometryNodeAccumulateField", {"Value": 1.0, "Group ID": piece}, data_type="FLOAT", domain="POINT")["Total"]
    g = b.store(g, nodes_fracture.ATTR_PIVOT, "FLOAT_VECTOR", "POINT", b.vmath("SCALE", total, scale=b.math("DIVIDE", 1.0, count)))
    join_proxy = b.tree.nodes.new("GeometryNodeJoinGeometry")
    b.link(proxy_in, join_proxy.inputs[0])
    b.link(g, join_proxy.inputs[0])
    b.output("Geometry", "geo", g, desc="The pieces, with piece_id")
    b.output("Constraint Geometry", "geo", con)
    b.output("Proxy Geometry", "geo", join_proxy.outputs[0])
    return b.finish()


def build_constraints_from_rules():
    b = Builder(CONSTRAINTS_FROM_RULES, KIND_CONSTRAINTS_FROM_RULES, 1, modifier=False)
    geo, con_in, proxy = _streams(b)
    reach = b.input("Search Radius", "float", 0.02, min=0.0, subtype="DISTANCE",
                    desc="Pieces whose surfaces are closer to each other than this are glued together")
    strength = b.input("Strength", "float", 5.0, min=0.0, desc="Strength of the glue between neighbouring pieces")
    variance = b.input("Strength Variance", "float", 0.0, min=0.0, max=1.0, subtype="FACTOR")
    by_area = b.input("Scale by Contact Area", "bool", True, desc="Pieces that touch over a small area are held together less strongly")
    keep = b.input("Keep Incoming Constraints", "bool", False,
                   desc="Add to the constraints that come in. Off: they are replaced")
    b.panel("Advanced", closed=True)
    samples = b.input("Samples per Piece", "int", 200, min=8, max=5000,
                      desc="Points scattered on every piece to find its neighbours. More finds smaller contacts")
    seed = b.input("Seed", "int", 0, min=0)
    network, _ = proximity_network(b, geo, reach, samples, strength, variance, by_area, seed)
    join = b.tree.nodes.new("GeometryNodeJoinGeometry")
    b.link(b.switch("GEOMETRY", keep, None, con_in), join.inputs[0])
    b.link(network, join.inputs[0])
    _streams_out(b, geo, join.outputs[0], proxy)
    return b.finish()


def build_select():
    """A selection of pieces, as a field: wire it into the Selection of RBD Configure or RBD Constraint Properties."""
    b = Builder(SELECT, KIND_SELECT, 1, modifier=False)
    kind = b.menu("Type", SELECT_TYPES, "Below Height",
                  desc="Below Height: pieces that reach down to a height, to hold the bottom of a wall in place. "
                       "Box, Sphere: pieces whose centre is inside. Attribute: a vertex group or attribute")
    height = b.input("Height", "float", 0.1, subtype="DISTANCE", desc="In the space of the object")
    centre = b.input("Center", "vec", (0.0, 0.0, 0.0), subtype="TRANSLATION", desc="In the space of the object")
    size = b.input("Size", "vec", (1.0, 1.0, 1.0), min=0.0, subtype="XYZ")
    radius = b.input("Radius", "float", 1.0, min=0.0, subtype="DISTANCE")
    name = b.input("Attribute", "str", "", desc="Name of a vertex group or attribute. After a fracture: one named in its Keep Vertex Group")
    threshold = b.input("Threshold", "float", 0.5, desc="Selected where the attribute is at least this")
    whole = b.input("Whole Pieces", "bool", True,
                    desc="Decide per piece: by its lowest point, its centre, the average of the attribute. "
                         "Off: per vertex (a piece then counts as selected when most of it is)")
    invert = b.input("Invert", "bool", False)
    piece = b.named(nodes_fracture.ATTR_PIECE, "INT")
    pivot = b.node("GeometryNodeInputNamedAttribute", {"Name": nodes_fracture.ATTR_PIVOT}, data_type="FLOAT_VECTOR")
    # (constraint geometry has no rbd_pivot: there the selection is always per element)
    per_piece = b.bmath("AND", whole, pivot["Exists"])
    where = b.switch("VECTOR", per_piece, b.pos(), pivot["Attribute"])
    z = b.sep(b.pos())[2]
    lowest = b.node("GeometryNodeFieldMinAndMax", {"Value": z, "Group ID": piece}, data_type="FLOAT", domain="POINT")["Min"]
    below = b.cmp("LESS_EQUAL", b.switch("FLOAT", per_piece, z, lowest), height)
    dx, dy, dz = b.sep(b.vmath("ABSOLUTE", b.vmath("SUBTRACT", where, centre)))
    hx, hy, hz = b.sep(b.vmath("SCALE", size, scale=0.5))
    in_box = b.bmath("AND", b.bmath("AND", b.cmp("LESS_EQUAL", dx, hx), b.cmp("LESS_EQUAL", dy, hy)), b.cmp("LESS_EQUAL", dz, hz))
    in_sphere = b.cmp("LESS_EQUAL", b.vmath("LENGTH", b.vmath("SUBTRACT", where, centre)), radius)
    weight = b.named(name, "FLOAT")
    mean = b.math("DIVIDE",
                  b.node("GeometryNodeAccumulateField", {"Value": weight, "Group ID": piece}, data_type="FLOAT", domain="POINT")["Total"],
                  b.node("GeometryNodeAccumulateField", {"Value": 1.0, "Group ID": piece}, data_type="FLOAT", domain="POINT")["Total"])
    painted = b.cmp("GREATER_EQUAL", b.switch("FLOAT", per_piece, weight, mean), threshold)
    chosen = kind("BOOLEAN", {"Below Height": below, "Box": in_box, "Sphere": in_sphere, "Attribute": painted})
    b.output("Selection", "bool", b.bmath("XOR", chosen, invert), desc="True on the selected pieces")
    return b.finish()


def assemble():
    return ensure_group(KIND_ASSEMBLE, 1, build_assemble)


def constraints_from_rules():
    return ensure_group(KIND_CONSTRAINTS_FROM_RULES, 1, build_constraints_from_rules)


def select():
    return ensure_group(KIND_SELECT, 1, build_select)


def configure():
    return ensure_group(KIND_CONFIGURE, 3, build_configure)


def constraint_properties():
    return ensure_group(KIND_CONSTRAINT_PROPERTIES, 2, build_constraint_properties)


def cluster():
    return ensure_group(KIND_CLUSTER, 1, build_cluster)


def exploded_view():
    return ensure_group(KIND_EXPLODED_VIEW, 1, build_exploded_view)


def bullet_solver():
    return ensure_group(KIND_BULLET_SOLVER, SOLVER_VERSION, build_bullet_solver)


def refresh():
    """Bring the RBD node groups that are in the file up to date with this version of the add-on: a file made
    with an older version has older groups, without the inputs added since. The nodes that use them keep the
    values typed into them and their wires. Returns the names of the groups that were rebuilt."""
    from . import nodes_playback
    from .nodekit import VERSION_PROP, find_group
    rebuilt = []
    for kind, ensure in ((nodes_fracture.KIND_FRACTURE, nodes_fracture.ensure), (nodes_playback.KIND_PLAYBACK, nodes_playback.ensure),
                         *((kind, entry[1]) for kind, entry in NODES.items())):
        group = find_group(kind)
        if group is None:
            continue
        before = group.get(VERSION_PROP)
        ensure()
        if group.get(VERSION_PROP) != before:
            rebuilt.append(group.name)
    return rebuilt


NODES = {
    KIND_MATERIAL_FRACTURE: (MATERIAL_FRACTURE, material_fracture),
    KIND_ASSEMBLE: (ASSEMBLE, assemble),
    KIND_CONSTRAINTS_FROM_RULES: (CONSTRAINTS_FROM_RULES, constraints_from_rules),
    KIND_CONFIGURE: (CONFIGURE, configure),
    KIND_CONSTRAINT_PROPERTIES: (CONSTRAINT_PROPERTIES, constraint_properties),
    KIND_CLUSTER: (CLUSTER, cluster),
    KIND_SELECT: (SELECT, select),
    KIND_EXPLODED_VIEW: (EXPLODED_VIEW, exploded_view),
    KIND_BULLET_SOLVER: (BULLET_SOLVER, bullet_solver),
}
