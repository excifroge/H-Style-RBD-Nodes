# SPDX-License-Identifier: GPL-3.0-or-later
"""Tiny helper for building Geometry Nodes groups from Python.

The node groups this extension uses are generated at runtime instead of being
shipped inside a .blend file, so they stay reviewable and diffable as code.
"""
import bpy

SOCKET = {
    "geo": "NodeSocketGeometry", "float": "NodeSocketFloat", "int": "NodeSocketInt",
    "bool": "NodeSocketBool", "vec": "NodeSocketVector", "mat": "NodeSocketMaterial",
    "obj": "NodeSocketObject", "col": "NodeSocketCollection", "img": "NodeSocketImage",
    "str": "NodeSocketString", "rot": "NodeSocketRotation", "menu": "NodeSocketMenu",
}


def find_socket(sockets, name):
    if isinstance(name, int):
        return sockets[name]
    for s in sockets:
        if s.enabled and s.name == name:
            return s
    for s in sockets:
        if s.identifier == name:
            return s
    for s in sockets:
        if s.name == name:
            return s
    raise KeyError(f"socket {name!r} not found in {[s.name for s in sockets]}")


class N:
    """A node handle: n["Output Name"] is an output socket, n.o is the first enabled one."""

    def __init__(self, node):
        self.node = node

    def __getitem__(self, name):
        return find_socket(self.node.outputs, name)

    @property
    def o(self):
        for s in self.node.outputs:
            if s.enabled and s.bl_idname != "NodeSocketVirtual":
                return s
        return self.node.outputs[0]

    def inp(self, name):
        return find_socket(self.node.inputs, name)


def _as_socket(v):
    if isinstance(v, N):
        return v.o
    if isinstance(v, bpy.types.NodeSocket):
        return v
    return None


KIND_PROP = "hrbd_kind"
VERSION_PROP = "hrbd_version"


def find_group(kind):
    """Our node group of this kind, recognised by its marker (a user group with the same name is not ours)."""
    for g in bpy.data.node_groups:
        if g.bl_idname == "GeometryNodeTree" and g.get(KIND_PROP) == kind and g.library is None:
            return g
    return None


def ensure_group(kind, version, build):
    g = find_group(kind)
    if g is None or g.get(VERSION_PROP) != version:
        g = build()
    return g


def _modifier_inputs(mod):
    props = getattr(mod, "properties", None)
    return props.inputs if props is not None and hasattr(props, "inputs") else mod


def _snapshot_users(tree):
    """Input values of every modifier that uses `tree`, keyed by socket name, so they survive a rebuild."""
    saved = []
    names = {it.identifier: it.name for it in tree.interface.items_tree
             if it.item_type == "SOCKET" and it.in_out == "INPUT"}
    for ob in bpy.data.objects:
        for m in ob.modifiers:
            if m.type != "NODES" or m.node_group != tree:
                continue
            values = {}
            store = _modifier_inputs(m)
            for ident, name in names.items():
                try:
                    item = store[ident]
                    v = item["value"] if store is not m else item
                    values[name] = v.to_list() if hasattr(v, "to_list") else v
                except (KeyError, TypeError):
                    pass
            saved.append((m, values))
    return saved


def _socket_key(node, sock, rebuilt):
    """How to find a socket again after a rebuild: by name on a node whose sockets are made anew, else by identifier."""
    return (node.name, "name" if node in rebuilt else "id", sock.name if node in rebuilt else sock.identifier)


def _snapshot_nodes(tree):
    """Every node that uses `tree` in another node tree: the values typed into it and the wires going in and
    out of it. Rebuilding the group makes its sockets anew, which would drop both."""
    saved = []
    for user in bpy.data.node_groups:
        if user == tree or user.library is not None:
            continue
        rebuilt = {n for n in user.nodes if n.bl_idname == "GeometryNodeGroup" and n.node_tree == tree}
        if not rebuilt:
            continue
        values = {}
        for node in rebuilt:
            mine = {}
            for sock in node.inputs:
                if hasattr(sock, "default_value"):
                    v = sock.default_value
                    mine[sock.name] = tuple(v) if hasattr(v, "__len__") and not isinstance(v, str) else v
            values[node.name] = mine
        links = {(_socket_key(l.from_node, l.from_socket, rebuilt), _socket_key(l.to_node, l.to_socket, rebuilt))
                 for l in user.links if l.from_node in rebuilt or l.to_node in rebuilt}
        saved.append((user, values, sorted(links)))
    return saved


def _find_again(node, sockets, how, key):
    if how == "name":
        return sockets.get(key)
    return next((s for s in sockets if s.identifier == key), None)


def _restore_nodes(saved):
    for user, values, links in saved:
        for node_name, mine in values.items():
            node = user.nodes.get(node_name)
            if node is None:
                continue
            for name, v in mine.items():
                sock = node.inputs.get(name)
                if sock is None or not hasattr(sock, "default_value"):
                    continue
                try:
                    sock.default_value = v
                except (TypeError, ValueError, AttributeError):
                    pass                          # the input changed its type in the new version
        for (from_node, from_how, from_key), (to_node, to_how, to_key) in links:
            a, b = user.nodes.get(from_node), user.nodes.get(to_node)
            if a is None or b is None:
                continue
            src, dst = _find_again(a, a.outputs, from_how, from_key), _find_again(b, b.inputs, to_how, to_key)
            if src is not None and dst is not None:
                user.links.new(src, dst)
        user.update_tag()


# Set by the documentation screenshots (Tools/node_shots.py): build every group with all of its panels open.
OPEN_ALL_PANELS = False


class Builder:
    def __init__(self, name, kind="", version=1, modifier=True):
        old = find_group(kind) if kind else None
        self._saved = []
        self._saved_nodes = []
        if old is not None:
            # an older build of our own group: rebuild in place so modifiers and nodes using it keep working,
            # and give them their input values and wires back afterwards (socket identifiers change on rebuild)
            self._saved = _snapshot_users(old)
            self._saved_nodes = _snapshot_nodes(old)
            old.nodes.clear()
            old.interface.clear()
            self.tree = old
        else:
            self.tree = bpy.data.node_groups.new(name, "GeometryNodeTree")
        if kind:
            self.tree[KIND_PROP] = kind
        # the version is written last, in finish(): a build that fails half way must not look complete
        self.tree[VERSION_PROP] = 0
        self._version = version
        self.tree.is_modifier = modifier
        self._gin = None
        self._gout = None
        self._panel = None

    # ---- interface
    def panel(self, name, closed=False, parent=None, desc="", always_closed=False):
        """Start a panel: the inputs made from here on go into it. `parent` nests it in an earlier panel."""
        if not name:
            self._panel = None
            return None
        p = self.tree.interface.new_panel(name, default_closed=closed and (always_closed or not OPEN_ALL_PANELS), description=desc)
        if parent is not None:
            self.tree.interface.move_to_parent(p, parent, len(parent.interface_items))
        self._panel = p
        return p

    def menu(self, name, items, default=None, desc=""):
        """A drop-down input. Returns pick(data_type, {item: value}) -> socket.

        A menu socket takes its items from the one Menu Switch node it is wired to (wiring it to several
        leaves it undefined), so there is a single Menu Switch; its "this item is chosen" outputs drive
        ordinary Switch nodes."""
        it = self.tree.interface.new_socket(name, in_out="INPUT", socket_type="NodeSocketMenu", parent=self._panel)
        if desc:
            it.description = desc
        if self._gin is None:
            self._gin = self.tree.nodes.new("NodeGroupInput")
        n = self.tree.nodes.new("GeometryNodeMenuSwitch")
        n.data_type = "INT"
        n.enum_items.clear()
        for k, item in enumerate(items):
            n.enum_items.new(item)
        for k, item in enumerate(items):
            find_socket(n.inputs, item).default_value = k
        self.tree.links.new(find_socket(self._gin.outputs, it.identifier), n.inputs["Menu"])
        if default is not None:
            it.default_value = default               # possible only now that the items exist
        chosen = {item: n.outputs[item] for item in items}

        def pick(data_type, values):
            out = values[items[0]]
            for item in items[1:]:
                out = self.switch(data_type, chosen[item], out, values[item])
            return out
        return pick

    def input(self, name, kind, default=None, min=None, max=None, subtype=None, desc="", toggle=False):
        """`toggle`: a boolean that is the checkbox in the header of its panel (make it the panel's first input)."""
        it = self.tree.interface.new_socket(name, in_out="INPUT", socket_type=SOCKET[kind], parent=self._panel)
        if toggle:
            it.is_panel_toggle = True
        if default is not None:
            it.default_value = default
        if min is not None:
            it.min_value = min
        if max is not None:
            it.max_value = max
        if subtype:
            it.subtype = subtype
        if desc:
            it.description = desc
        if self._gin is None:
            self._gin = self.tree.nodes.new("NodeGroupInput")
        return find_socket(self._gin.outputs, it.identifier)

    def output(self, name, kind, value, desc=""):
        it = self.tree.interface.new_socket(name, in_out="OUTPUT", socket_type=SOCKET[kind])
        if desc:
            it.description = desc
        if self._gout is None:
            self._gout = self.tree.nodes.new("NodeGroupOutput")
            self._gout.is_active_output = True
        self.link(value, find_socket(self._gout.inputs, it.identifier))

    # ---- nodes
    def link(self, src, dst):
        self.tree.links.new(_as_socket(src), dst)

    def node(self, idname, inputs=None, **props):
        n = self.tree.nodes.new(idname)
        for k, v in props.items():
            setattr(n, k, v)
        if inputs:
            self.set(n, inputs)
        return N(n)

    def set(self, node, inputs):
        node = node.node if isinstance(node, N) else node
        for name, v in inputs.items():
            if v is None:
                continue
            sock = find_socket(node.inputs, name)
            src = _as_socket(v)
            if src is not None:
                self.tree.links.new(src, sock)
            else:
                sock.default_value = v

    def group(self, tree, inputs=None):
        n = self.tree.nodes.new("GeometryNodeGroup")
        n.node_tree = tree
        if inputs:
            self.set(n, inputs)
        return N(n)

    # ---- shorthands
    def math(self, op, a, b=None, c=None, clamp=False):
        return self.node("ShaderNodeMath", {0: a, 1: b, 2: c}, operation=op, use_clamp=clamp).o

    def vmath(self, op, a, b=None, c=None, scale=None):
        n = self.node("ShaderNodeVectorMath", {0: a, 1: b, 2: c, "Scale": scale}, operation=op)
        return n.o

    def cmp(self, op, a, b, data_type="FLOAT"):
        return self.node("FunctionNodeCompare", {"A": a, "B": b}, data_type=data_type, operation=op).o

    def bmath(self, op, a, b=None):
        return self.node("FunctionNodeBooleanMath", {0: a, 1: b}, operation=op).o

    def sep(self, v):
        n = self.node("ShaderNodeSeparateXYZ", {0: v})
        return n["X"], n["Y"], n["Z"]

    def comb(self, x=0.0, y=0.0, z=0.0):
        return self.node("ShaderNodeCombineXYZ", {"X": x, "Y": y, "Z": z}).o

    def switch(self, kind, cond, false, true):
        return self.node("GeometryNodeSwitch", {"Switch": cond, "False": false, "True": true}, input_type=kind).o

    def rand(self, data_type, lo, hi, seed=0, id=None):
        return self.node("FunctionNodeRandomValue", {"Min": lo, "Max": hi, "Seed": seed, "ID": id}, data_type=data_type).o

    def named(self, name, data_type):
        return self.node("GeometryNodeInputNamedAttribute", {"Name": name}, data_type=data_type)["Attribute"]

    def store(self, geo, name, data_type, domain, value, selection=None):
        return self.node(
            "GeometryNodeStoreNamedAttribute",
            {"Geometry": geo, "Name": name, "Value": value, "Selection": selection},
            data_type=data_type, domain=domain,
        ).o

    def pos(self):
        return self.node("GeometryNodeInputPosition").o

    def index(self):
        return self.node("GeometryNodeInputIndex").o

    def set_pos(self, geo, position=None, offset=None, selection=None):
        return self.node(
            "GeometryNodeSetPosition",
            {"Geometry": geo, "Position": position, "Offset": offset, "Selection": selection},
        ).o

    def capture(self, geo, domain, **items):
        """items: name=(TYPE, socket). Returns (geometry, {name: captured socket})."""
        n = self.tree.nodes.new("GeometryNodeCaptureAttribute")
        n.domain = domain
        for name, (typ, _) in items.items():
            n.capture_items.new(typ, name)
        self.tree.links.new(_as_socket(geo), n.inputs["Geometry"])
        out = {}
        for name, (_, src) in items.items():
            self.tree.links.new(_as_socket(src), find_socket(n.inputs, name))
            out[name] = find_socket(n.outputs, name)
        return n.outputs["Geometry"], out

    # ---- tidy up so the group is readable when a user opens it
    def finish(self):
        nodes = list(self.tree.nodes)
        depth = {n: 0 for n in nodes}
        for _ in range(len(nodes)):
            changed = False
            for l in self.tree.links:
                d = depth[l.to_node] + 1
                if depth[l.from_node] < d:
                    depth[l.from_node] = d
                    changed = True
            if not changed:
                break
        cols = {}
        for n in nodes:
            cols.setdefault(depth[n], []).append(n)
        for d, col in cols.items():
            y = 0.0
            for n in col:
                n.location = (-d * 220.0, y)
                y -= 60.0 + 22.0 * (len(n.inputs) + len(n.outputs))
        self._restore_users()
        _restore_nodes(self._saved_nodes)
        self.tree[VERSION_PROP] = self._version
        return self.tree

    def _restore_users(self):
        idents = {it.name: it.identifier for it in self.tree.interface.items_tree
                  if it.item_type == "SOCKET" and it.in_out == "INPUT"}
        for m, values in self._saved:
            store = _modifier_inputs(m)
            for name, v in values.items():
                ident = idents.get(name)
                if ident is None:
                    continue
                try:
                    if store is m:
                        m[ident] = v
                    else:
                        store[ident]["value"] = v
                except (KeyError, TypeError, ValueError):
                    pass
            m.id_data.update_tag()
