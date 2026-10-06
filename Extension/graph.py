# SPDX-License-Identifier: GPL-3.0-or-later
"""Finding the RBD nodes in the node tree of an object, and reading what flows into them.

A node group cannot hand its inputs to Python. To read the geometry that arrives at an input of a
node, the output of the modifier is wired to the source of that input for a moment, the object is
evaluated, and the wiring is put back.
"""
from contextlib import contextmanager

import bpy
import numpy as np

from . import core, nodes_rbd


def rbd_nodes(tree, kind):
    """The nodes of this kind directly in `tree`, in the order they were made."""
    if tree is None:
        return []
    return [n for n in tree.nodes if n.bl_idname == "GeometryNodeGroup" and n.node_tree is not None
            and n.node_tree.get(core.KIND_PROP) == kind]


def sites(ob, kind=nodes_rbd.KIND_BULLET_SOLVER):
    """[(modifier, node)] for every node of this kind in the Geometry Nodes modifiers of the object."""
    out = []
    if ob is None or ob.type != "MESH":
        return out
    for m in ob.modifiers:
        if m.type == "NODES" and m.node_group is not None:
            out += [(m, n) for n in rbd_nodes(m.node_group, kind)]
    return out


def solver_site(ob):
    """(modifier, RBD Bullet Solver node) of the object, or None. The first one counts."""
    found = sites(ob)
    return found[0] if found else None


def value(node, name):
    """What is typed into an input of a node. An input that is wired cannot be read: it has no single value."""
    sock = node.inputs[name]
    if sock.is_linked:
        raise RuntimeError(f'"{name}" of {node.name} is wired to another node. The solver needs a plain value there')
    v = sock.default_value
    return tuple(v) if hasattr(v, "__len__") and not isinstance(v, str) else v


def set_value(node, name, v):
    node.inputs[name].default_value = v
    node.id_data.update_tag()


@contextmanager
def shown(ob, mod, socket):
    """While inside: the object evaluates to what flows into `socket` (an input of a node in the tree of
    `mod`). Everything after the modifier is switched off. The wiring and visibilities are put back."""
    tree = mod.node_group
    out = next((n for n in tree.nodes if n.bl_idname == "NodeGroupOutput" and n.is_active_output), None)
    if out is None:
        raise RuntimeError(f"{tree.name} has no Group Output")
    target = next((s for s in out.inputs if s.type == "GEOMETRY"), None)
    if target is None:
        raise RuntimeError(f"{tree.name} does not output geometry")
    before = [link.from_socket for link in target.links]
    source = socket.links[0].from_socket if socket.is_linked else None
    visible = [(m, m.show_viewport) for m in ob.modifiers]
    try:
        for link in list(target.links):
            tree.links.remove(link)
        if source is not None:
            tree.links.new(source, target)
        after = False
        for m in ob.modifiers:
            if after:
                m.show_viewport = False
            after = after or m == mod
        mod.show_viewport = True
        bpy.context.view_layer.update()
        yield
    finally:
        for link in list(target.links):
            tree.links.remove(link)
        for s in before:
            tree.links.new(s, target)
        for m, state in visible:
            m.show_viewport = state


def pieces(ob, mod, node, want_mesh=False):
    """(EvalMesh, Mesh copy or None) of the geometry arriving at the Geometry input of the node."""
    with shown(ob, mod, node.inputs["Geometry"]):
        dg = bpy.context.evaluated_depsgraph_get()
        em = core.EvalMesh(ob, dg)
        me = None
        if want_mesh:
            me = bpy.data.meshes.new_from_object(ob.evaluated_get(dg), preserve_all_data_layers=True, depsgraph=dg)
        return em, me


def proxy(ob, mod, node):
    """The proxy geometry arriving at the node: {piece: world positions of its points}. Empty if nothing
    is wired to the Proxy Geometry input, or what is wired has no piece_id."""
    socket = node.inputs["Proxy Geometry"]
    if not socket.is_linked:
        return {}
    with shown(ob, mod, socket):
        em = core.EvalMesh(ob)
    if not em.has_pieces or len(em.co) == 0:
        return {}
    order = np.argsort(em.piece, kind="stable")
    bounds = np.append(0, np.cumsum(np.bincount(em.piece)))
    return {i: em.co[order[bounds[i]:bounds[i + 1]]] for i in range(len(bounds) - 1) if bounds[i + 1] - bounds[i] >= 4}


def open_edges(ob, mod, node):
    """How many edges of the mesh arriving at the Geometry input of the node are not shared by exactly two
    faces. 0 = a closed surface, which is what a fracture needs."""
    with shown(ob, mod, node.inputs["Geometry"]):
        return core.EvalMesh(ob).open_edges()


def constraints(ob, mod, node):
    """The constraint geometry arriving at the node: ([(piece a, piece b, anchor in world space, area)], strength[]).
    None if nothing is wired to the Constraint Geometry input."""
    socket = node.inputs["Constraint Geometry"]
    if not socket.is_linked:
        return None
    with shown(ob, mod, socket):
        dg = bpy.context.evaluated_depsgraph_get()
        oe = ob.evaluated_get(dg)
        me = oe.to_mesh()
        try:
            n_e = len(me.edges)
            piece = me.attributes.get("piece_id")
            if n_e == 0 or piece is None or piece.domain != "POINT":
                return [], np.zeros(0)
            ends = np.empty(n_e * 2, np.int32)
            me.edges.foreach_get("vertices", ends)
            ids = np.zeros(len(me.vertices), np.int32)
            piece.data.foreach_get("value", ids)
            ends = ids[ends.reshape(-1, 2)]

            def edge_attr(name, width, default):
                a = me.attributes.get(name)
                if a is None or a.domain != "EDGE":
                    return np.full((n_e, width), default, np.float32)
                out = np.empty(n_e * width, np.float32)
                a.data.foreach_get("value" if width == 1 else "vector", out)
                return out.reshape(n_e, width)
            strength = edge_attr("strength", 1, 1.0)[:, 0]
            area = edge_attr("area", 1, 1.0)[:, 0]
            anchor = edge_attr("anchor", 3, 0.0).astype(np.float64)
            m = np.array(oe.matrix_world, np.float64)
            anchor = anchor @ m[:3, :3].T + m[:3, 3]
        finally:
            oe.to_mesh_clear()
    keep = ends[:, 0] != ends[:, 1]
    pairs = [(int(min(a, b)), int(max(a, b)), anchor[k].copy(), float(area[k]))
             for k, (a, b) in enumerate(ends.tolist()) if keep[k]]
    return pairs, strength[keep].astype(np.float64)
