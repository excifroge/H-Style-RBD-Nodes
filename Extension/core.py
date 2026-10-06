# SPDX-License-Identifier: GPL-3.0-or-later
"""Shared helpers: modifier input access, evaluated-mesh readout, naming."""
import bpy
import numpy as np

MOD_FRACTURE = "RBD Fracture"
MOD_PLAYBACK = "RBD Playback"
KIND_PROP = "hrbd_kind"       # custom property that marks a node group as ours
VERSION_PROP = "hrbd_version"
KIND_FRACTURE = "fracture"
# point attributes of the pieces that the solver looks at (see nodes_rbd)
PIECE_ATTRIBUTES = ("active", "v", "w", "activate_time", "density", "friction", "bounce")
KIND_PLAYBACK = "playback"


def input_identifier(tree, name):
    for it in tree.interface.items_tree:
        if it.item_type == "SOCKET" and it.in_out == "INPUT" and it.name == name:
            return it.identifier
    raise KeyError(f"{tree.name!r} has no input named {name!r}")


def set_input(mod, name, value):
    """Set a Geometry Nodes modifier input by its display name (Blender 5.2 API, with pre-5.2 fallback)."""
    ident = input_identifier(mod.node_group, name)
    props = getattr(mod, "properties", None)
    if props is not None and hasattr(props, "inputs"):
        props.inputs[ident]["value"] = value
    else:
        mod[ident] = value
    mod.id_data.update_tag()


def get_input(mod, name):
    ident = input_identifier(mod.node_group, name)
    props = getattr(mod, "properties", None)
    if props is not None and hasattr(props, "inputs"):
        return props.inputs[ident]["value"]
    return mod[ident]


def find_modifier(ob, kind):
    """The first Geometry Nodes modifier whose node group is one of ours of the given kind.
    Identified by a marker on the group, so renaming the group or the modifier does not lose it."""
    for m in ob.modifiers:
        if m.type == "NODES" and m.node_group is not None and m.node_group.get(KIND_PROP) == kind:
            return m
    return None


def open_edges_above(ob, mod):
    """How many edges of the mesh that `mod` receives are not shared by exactly two faces.
    0 means it is a closed surface. Evaluates the stack with `mod` and everything after it switched off."""
    before = [(m, m.show_viewport) for m in ob.modifiers]
    try:
        below = False
        for m in ob.modifiers:
            below = below or m == mod
            if below:
                m.show_viewport = False
        bpy.context.view_layer.update()
        return EvalMesh(ob).open_edges()
    finally:
        for m, vis in before:
            m.show_viewport = vis
        bpy.context.view_layer.update()


class EvalMesh:
    """Numpy snapshot of a mesh in world space, with per-piece helpers.

    Reads `ob`'s evaluated mesh, or `mesh` (a Mesh in local space) placed with `matrix`.
    """

    def __init__(self, ob, depsgraph=None, mesh=None, matrix=None):
        oe = None
        if mesh is None:
            dg = depsgraph or bpy.context.evaluated_depsgraph_get()
            oe = ob.evaluated_get(dg)
            me, matrix = oe.to_mesh(), oe.matrix_world
        else:
            me = mesh
            matrix = ob.matrix_world if matrix is None else matrix
        try:
            self.matrix = np.array(matrix, np.float64)
            self.co = self._world(self._vectors(me.vertices, "co", len(me.vertices)))
            self._read(me)
        finally:
            if oe is not None:
                oe.to_mesh_clear()

    @staticmethod
    def _vectors(collection, prop, n):
        a = np.empty(n * 3, np.float32)
        collection.foreach_get(prop, a)
        return a.reshape(-1, 3)

    def _world(self, co):
        return (co.astype(np.float64) @ self.matrix[:3, :3].T + self.matrix[:3, 3]).astype(np.float32)

    def _read(self, me):
        nv = len(me.vertices)
        self.piece = np.zeros(nv, np.int32)
        a = me.attributes.get("piece_id")
        self.has_pieces = a is not None and a.domain == "POINT" and a.data_type == "INT"
        if self.has_pieces:
            a.data.foreach_get("value", self.piece)
        # flat, pre-detail positions: what collision shapes are built from
        a = me.attributes.get("rbd_rest")
        if a is not None and a.domain == "POINT" and a.data_type == "FLOAT_VECTOR":
            self.proxy_co = self._world(self._vectors(a.data, "vector", nv))
        else:
            self.proxy_co = self.co
        self.anchor = None   # painted anchor weight per vertex, when the fracture was given an Anchor Group
        a = me.attributes.get("rbd_anchor")
        if a is not None and a.domain == "POINT" and a.data_type == "FLOAT":
            self.anchor = np.empty(nv, np.float32)
            a.data.foreach_get("value", self.anchor)
        # what RBD Configure and friends wrote on the points, by name: {name: array [vertices] or [vertices, 3]}
        self.extra = {}
        for name in PIECE_ATTRIBUTES:
            a = me.attributes.get(name)
            if a is None or a.domain != "POINT":
                continue
            if a.data_type == "FLOAT_VECTOR":
                self.extra[name] = self._vectors(a.data, "vector", nv)
            elif a.data_type in ("FLOAT", "INT", "BOOLEAN"):
                values = np.zeros(nv, {"FLOAT": np.float32, "INT": np.int32, "BOOLEAN": bool}[a.data_type])
                a.data.foreach_get("value", values)
                self.extra[name] = values.astype(np.float32)
        self.pivot_attr = None
        a = me.attributes.get("rbd_pivot")
        if a is not None and a.domain == "POINT":
            self.pivot_attr = self._world(self._vectors(a.data, "vector", nv))
        npoly = len(me.polygons)
        self.inside = np.zeros(npoly, bool)
        a = me.attributes.get("inside")
        if a is not None and a.domain == "FACE":
            a.data.foreach_get("value", self.inside)
        self.loop_vert = np.empty(len(me.loops), np.int32)
        me.loops.foreach_get("vertex_index", self.loop_vert)
        self.loop_edge = np.empty(len(me.loops), np.int32)
        me.loops.foreach_get("edge_index", self.loop_edge)
        self.loop_total = np.empty(npoly, np.int32)
        me.polygons.foreach_get("loop_total", self.loop_total)
        self.n_edges = len(me.edges)
        me.calc_loop_triangles()
        self.tris = np.empty(len(me.loop_triangles) * 3, np.int32)
        me.loop_triangles.foreach_get("vertices", self.tris)
        self.tris = self.tris.reshape(-1, 3)

    def per_piece(self, name):
        """The average of a point attribute over every piece ([pieces] or [pieces, 3]), or None if it is not there."""
        values = self.extra.get(name)
        if values is None:
            return None
        n = self.n_pieces
        count = np.maximum(np.bincount(self.piece, minlength=n), 1)
        if values.ndim == 1:
            return np.bincount(self.piece, weights=values, minlength=n) / count
        return np.stack([np.bincount(self.piece, weights=values[:, k], minlength=n) for k in range(3)], axis=1) / count[:, None]

    @property
    def n_pieces(self):
        return int(self.piece.max()) + 1 if len(self.piece) else 0

    def vertex_means(self, co=None):
        co = self.co if co is None else co
        n = self.n_pieces
        cnt = np.maximum(np.bincount(self.piece, minlength=n), 1)[:, None]
        out = np.stack([np.bincount(self.piece, weights=co[:, k].astype(np.float64), minlength=n)
                        for k in range(3)], axis=1)
        return out / cnt

    def _tetra_sums(self, co=None):
        """Signed volume and first moment of every piece, measured from a nearby reference point in
        float64 so objects far from the world origin do not lose their volume to cancellation.
        `co` selects which vertex positions to use (default: the visible ones)."""
        co = self.co if co is None else co
        n = self.n_pieces
        ref = co.mean(0).astype(np.float64) if len(co) else np.zeros(3)
        p = co.astype(np.float64) - ref
        a, b, c = p[self.tris[:, 0]], p[self.tris[:, 1]], p[self.tris[:, 2]]
        vol = np.einsum("ij,ij->i", a, np.cross(b, c)) / 6.0
        if np.linalg.det(self.matrix[:3, :3]) < 0.0:
            vol = -vol   # a mirrored object (negative scale) turns every triangle around
        owner = self.piece[self.tris[:, 0]]
        volume = np.bincount(owner, weights=vol, minlength=n)
        moment = np.stack([np.bincount(owner, weights=vol * (a[:, k] + b[:, k] + c[:, k]) / 4.0, minlength=n)
                           for k in range(3)], axis=1)
        return volume, moment, ref

    def piece_volumes(self, co=None):
        return self._tetra_sums(co)[0]

    def piece_centroids(self, co=None):
        """Centre of mass of every piece (uniform density). Falls back to the vertex average for
        pieces whose volume is not usable (open or inside-out geometry)."""
        co = self.co if co is None else co
        n = self.n_pieces
        volume, moment, ref = self._tetra_sums(co)
        means = self.vertex_means(co)
        lo = np.full((n, 3), np.inf)
        hi = np.full((n, 3), -np.inf)
        np.minimum.at(lo, self.piece, co)
        np.maximum.at(hi, self.piece, co)
        with np.errstate(divide="ignore", invalid="ignore"):
            com = moment / volume[:, None] + ref
        ok = (volume > 1e-12) & np.all(np.isfinite(com), axis=1) & np.all((com >= lo) & (com <= hi), axis=1)
        return np.where(ok[:, None], com, means).astype(np.float32)

    def open_edges(self):
        """Edges not shared by exactly two faces (0 means every piece is watertight)."""
        use = np.bincount(self.loop_edge, minlength=self.n_edges)
        return int((use != 2).sum())
