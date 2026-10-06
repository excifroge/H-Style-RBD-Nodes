# SPDX-License-Identifier: GPL-3.0-or-later
"""Operators, the Add menu and the panels.

The workflow lives in the node tree of the object, as RBD nodes (see nodes_rbd). What is here:
adding those nodes, the Bake button that the RBD Bullet Solver node cannot have itself (Bullet does
not run inside a node tree), the exports, and panels that show the parameters of the RBD nodes of
the active object, so the node editor does not have to be open to change them.
"""
import os

import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, StringProperty
from bpy_extras.io_utils import ExportHelper

from . import core, export, graph, nodes_rbd, sim, translations

RBD_KINDS = tuple(nodes_rbd.NODES)
# text the panels draw by hand (the translation table is checked against this list)
PANEL_TEXT = (
    "Select a mesh object", "New RBD network:", "Fracture This Object", "Use Its Loose Parts", "Adds a Geometry Nodes modifier",
    "with the RBD nodes wired up", "Mesh is not closed", "Weld, close holes or Solidify", "Check Again",
    "No RBD Bullet Solver node:", "add one to simulate (Add > RBD)", "Bake", "Re-Bake", "Bake {n} Objects Together",
    "{pieces} pieces, {frames} frames", "{name} from 3D Cursor",
)


def _mesh_poll(context):
    ob = context.object
    return ob is not None and ob.type == "MESH" and context.mode == "OBJECT"


def _in_geometry_nodes(context):
    space = context.space_data
    return space is not None and space.type == "NODE_EDITOR" and space.tree_type == "GeometryNodeTree"


def rbd_nodes_of(ob):
    """[(modifier, node)] for every RBD node in the Geometry Nodes modifiers of the object, in a readable order:
    following the wires from the Group Input where that is possible."""
    out = []
    if ob is None or ob.type != "MESH":
        return out
    for m in ob.modifiers:
        if m.type != "NODES" or m.node_group is None:
            continue
        nodes = [n for n in m.node_group.nodes if n.bl_idname == "GeometryNodeGroup" and n.node_tree is not None
                 and n.node_tree.get(core.KIND_PROP) in RBD_KINDS]
        depth = {}

        def upstream(node, seen=()):
            if node in depth:
                return depth[node]
            best = 0
            for sock in node.inputs:
                for link in sock.links:
                    if link.from_node not in seen:
                        best = max(best, 1 + upstream(link.from_node, seen + (node,)))
            depth[node] = best
            return best
        out += [(m, n) for n in sorted(nodes, key=lambda n: (upstream(n), n.location.x))]
    return out


# ------------------------------------------------------------------ adding nodes
STREAMS = ("Geometry", "Constraint Geometry", "Proxy Geometry")
# what the RBD Network button builds, by where the pieces come from
TEMPLATES = {
    "FRACTURE": (nodes_rbd.KIND_MATERIAL_FRACTURE, nodes_rbd.KIND_BULLET_SOLVER),
    "PIECES": (nodes_rbd.KIND_ASSEMBLE, nodes_rbd.KIND_CONSTRAINTS_FROM_RULES, nodes_rbd.KIND_BULLET_SOLVER),
}


def rbd_node(tree, kind, location=(0.0, 0.0)):
    """A new RBD node of this kind in `tree`, not wired to anything."""
    node = tree.nodes.new("GeometryNodeGroup")
    node.node_tree = nodes_rbd.NODES[kind][1]()
    node.name = node.label = nodes_rbd.NODES[kind][0]
    node.width = 260.0
    node.location = location
    return node


def new_network(ob, kinds=TEMPLATES["FRACTURE"]):
    """A Geometry Nodes modifier on `ob`: Group Input -> one RBD node per kind -> Group Output, with the three
    streams wired from one RBD node to the next. Returns (modifier, [the nodes])."""
    tree = bpy.data.node_groups.new("RBD " + ob.name, "GeometryNodeTree")
    tree.is_modifier = True
    tree.interface.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    tree.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    gin, gout = tree.nodes.new("NodeGroupInput"), tree.nodes.new("NodeGroupOutput")
    nodes = [rbd_node(tree, kind, (-40.0 + 340.0 * k, 80.0)) for k, kind in enumerate(kinds)]
    gin.location, gout.location = (-300.0, 0.0), (-40.0 + 340.0 * len(kinds), 0.0)
    tree.links.new(gin.outputs[0], nodes[0].inputs["Geometry"])
    for a, b in zip(nodes, nodes[1:]):
        for name in STREAMS:
            tree.links.new(a.outputs[name], b.inputs[name])
    tree.links.new(nodes[-1].outputs["Geometry"], gout.inputs[0])
    scene = bpy.context.scene
    for node in nodes:
        if node.node_tree.get(core.KIND_PROP) == nodes_rbd.KIND_BULLET_SOLVER:
            node.inputs["Start Frame"].default_value = scene.frame_start
            node.inputs["End Frame"].default_value = scene.frame_end
    mod = ob.modifiers.new("RBD", "NODES")
    mod.node_group = tree
    return mod, nodes


class HRBD_OT_setup(bpy.types.Operator):
    bl_idname = "hrbd.setup"
    bl_label = "RBD Network"
    bl_description = ("Give the active object a Geometry Nodes modifier with the RBD nodes wired up. "
                      "Open the Geometry Nodes editor to add to it")
    bl_options = {"REGISTER", "UNDO"}

    template: EnumProperty(name="Pieces", items=(
        ("FRACTURE", "Fracture", "The object is one solid model: RBD Material Fracture cuts it into pieces"),
        ("PIECES", "Existing Pieces", "The object is already modelled in pieces (bricks, planks): RBD Assemble takes its "
                                      "loose parts as the pieces, RBD Constraints From Rules glues the ones that touch"),
    ), default="FRACTURE")

    @classmethod
    def poll(cls, context):
        return _mesh_poll(context)

    def execute(self, context):
        new_network(context.object, TEMPLATES[self.template])
        count = check_mesh(context.object)
        if count:
            self.report({"WARNING"}, f"The mesh is not a closed, welded volume ({count} open edges). If pieces come "
                                     "out open or missing: merge doubles, close holes, give flat sheets thickness (Solidify)")
        return {"FINISHED"}


class HRBD_OT_add_node(bpy.types.Operator):
    bl_idname = "hrbd.add_node"
    bl_label = "Add RBD Node"
    bl_description = "Add this RBD node to the node tree"
    bl_options = {"REGISTER", "UNDO"}

    kind: StringProperty(options={"HIDDEN"})

    @classmethod
    def poll(cls, context):
        if _in_geometry_nodes(context):
            return context.space_data.edit_tree is not None
        return _mesh_poll(context) and any(m.type == "NODES" and m.node_group is not None for m in context.object.modifiers)

    def invoke(self, context, event):
        if self.kind not in nodes_rbd.NODES:
            return {"CANCELLED"}
        if not _in_geometry_nodes(context):
            return self.execute(context)
        group = nodes_rbd.NODES[self.kind][1]()
        return bpy.ops.node.add_node("INVOKE_DEFAULT", type="GeometryNodeGroup", use_transform=True,
                                     settings=[{"name": "node_tree", "value": f"bpy.data.node_groups[{group.name!r}]"}])

    def execute(self, context):
        # from a script: the node is put into the tree (of the editor, or of the last Geometry Nodes modifier of
        # the active object), made the active node, and left for the script to wire
        if self.kind not in nodes_rbd.NODES:
            return {"CANCELLED"}
        if _in_geometry_nodes(context):
            tree = context.space_data.edit_tree
        else:
            tree = [m.node_group for m in context.object.modifiers if m.type == "NODES" and m.node_group is not None][-1]
        right = max((n.location.x for n in tree.nodes), default=0.0)
        node = rbd_node(tree, self.kind, (right, -420.0))
        for other in tree.nodes:
            other.select = other == node
        tree.nodes.active = node
        return {"FINISHED"}


class NODE_MT_hrbd_add(bpy.types.Menu):
    bl_idname = "NODE_MT_hrbd_add"
    bl_label = "RBD"

    def draw(self, context):
        for kind, (name, _) in nodes_rbd.NODES.items():
            self.layout.operator(HRBD_OT_add_node.bl_idname, text=name, translate=False).kind = kind


def _add_menu(self, context):
    if _in_geometry_nodes(context):
        self.layout.menu(NODE_MT_hrbd_add.bl_idname)


# positions typed into RBD nodes that are handy to take from the 3D cursor instead
CURSOR_INPUTS = {
    nodes_rbd.KIND_MATERIAL_FRACTURE: ("Impact Point",),
    nodes_rbd.KIND_CONFIGURE: ("Origin", "Wave Origin"),
    nodes_rbd.KIND_SELECT: ("Center",),
}


class HRBD_OT_cursor_to_input(bpy.types.Operator):
    bl_idname = "hrbd.cursor_to_input"
    bl_label = "From 3D Cursor"
    bl_description = "Set this position of the node to where the 3D cursor is (converted to the space of the object)"
    bl_options = {"REGISTER", "UNDO"}

    modifier: StringProperty(options={"HIDDEN"})
    node: StringProperty(options={"HIDDEN"})
    input: StringProperty(options={"HIDDEN"})

    @classmethod
    def poll(cls, context):
        return _mesh_poll(context)

    def execute(self, context):
        ob = context.object
        mod = ob.modifiers.get(self.modifier)
        node = mod.node_group.nodes.get(self.node) if mod is not None and mod.type == "NODES" and mod.node_group else None
        if node is None or self.input not in node.inputs:
            return {"CANCELLED"}
        if node.inputs[self.input].is_linked:
            self.report({"WARNING"}, f"{self.input} is wired to another node: its value comes from there")
            return {"CANCELLED"}
        graph.set_value(node, self.input, tuple(ob.matrix_world.inverted() @ context.scene.cursor.location))
        return {"FINISHED"}


OPEN_EDGES = "hrbd_open_edges"     # on the object: what Check Mesh found last time


def check_mesh(ob):
    """Count the open edges of the mesh that goes into the first RBD Material Fracture node, and remember it."""
    found = graph.sites(ob, nodes_rbd.KIND_MATERIAL_FRACTURE)
    count = graph.open_edges(ob, found[0][0], found[0][1]) if found else 0
    if count:
        ob[OPEN_EDGES] = count
    elif OPEN_EDGES in ob:
        del ob[OPEN_EDGES]
    return count


class HRBD_OT_check_mesh(bpy.types.Operator):
    bl_idname = "hrbd.check_mesh"
    bl_label = "Check Mesh"
    bl_description = "Look for open edges on the mesh that goes into the fracture. A fracture needs a closed, welded volume"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return _mesh_poll(context) and bool(graph.sites(context.object, nodes_rbd.KIND_MATERIAL_FRACTURE))

    def execute(self, context):
        count = check_mesh(context.object)
        if count:
            self.report({"WARNING"}, f"The mesh is not a closed, welded volume ({count} open edges). If pieces come "
                                     "out open or missing: merge doubles, close holes, give flat sheets thickness (Solidify)")
        else:
            self.report({"INFO"}, "The mesh is closed")
        return {"FINISHED"}


# ------------------------------------------------------------------ bake
def bake_targets(context):
    """What the Bake button simulates: the active object, and with it every other selected object that has an
    RBD Bullet Solver node. They go into one simulation and collide with each other; the settings are those
    on the solver node of the active object."""
    active = context.object
    others = [o for o in context.selected_objects
              if o != active and o.type == "MESH" and o.library is None and graph.solver_site(o) is not None]
    return [active] + others


class HRBD_OT_bake(bpy.types.Operator):
    bl_idname = "hrbd.bake"
    bl_label = "Bake Simulation"
    bl_description = ("Run the RBD Bullet Solver node of the active object and store the result on it. Other selected "
                      "objects that have a solver node are simulated in the same world, so they collide with each other")
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return _mesh_poll(context) and graph.solver_site(context.object) is not None

    def execute(self, context):
        obs = bake_targets(context)
        wm = context.window_manager
        wm.progress_begin(0, 100)
        try:
            results = sim.bake_many(context, obs, progress=lambda done, total: wm.progress_update(100 * done // max(total, 1)))
        except Exception as e:
            self.report({"ERROR"}, f"Bake failed, nothing was changed: {e}")
            return {"CANCELLED"}
        finally:
            wm.progress_end()
        first = results[0]
        if len(obs) > 1:
            self.report({"INFO"}, f"Baked {len(obs)} objects together: {sum(r.pieces for r in results)} pieces x "
                                  f"{first.frames} frames in {first.seconds:.1f} s")
        notes = []
        for o, res in zip(obs, results):
            msg = f"Baked {res.pieces} pieces x {res.frames} frames in {res.seconds:.1f} s" if len(obs) == 1 else \
                f"{o.name}: {res.pieces} pieces"
            if res.glue:
                msg += f" (about {res.glue_separated} of {res.glue} glue bonds came apart)"
            if res.events:
                msg += f", {res.events} cracks opened"
            self.report({"INFO"}, msg)
            notes += [note for note in res.notes if note not in notes]
        for note in notes:
            self.report({"WARNING" if "not" in note or "never" in note else "INFO"}, note)
        return {"FINISHED"}


class HRBD_OT_free(bpy.types.Operator):
    bl_idname = "hrbd.free_bake"
    bl_label = "Free Bake"
    bl_description = "Delete the baked motion: the solver node passes its input on again"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return _mesh_poll(context) and sim.is_baked(context.object)

    def execute(self, context):
        sim.free_cache(context.object)
        return {"FINISHED"}


# ------------------------------------------------------------------ export
MERGE = dict(name="Merge Unbroken Pieces", default=True,
             description="Pieces that stay together for the whole bake become one piece, and so does "
                         "everything that never moves; the cut faces hidden between them are removed. "
                         "Fewer bones or texture columns and fewer polygons, the same picture")
MERGE_DISTANCE = dict(name="Merge Tolerance", default=0.01, min=0.0001, soft_max=0.1, subtype="DISTANCE", precision=4,
                      description="A piece is merged only if that moves no point of it further than this "
                                  "from where the simulation had it. Glue flexes a little under load: "
                                  "with a very small value hardly anything merges")


class _ExportBase:
    @classmethod
    def poll(cls, context):
        return _mesh_poll(context) and sim.is_baked(context.object)

    def invoke(self, context, event):
        if not self.filepath:
            base = bpy.path.clean_name(context.object.name)
            folder = os.path.dirname(bpy.data.filepath) if bpy.data.filepath else os.path.expanduser("~")
            self.filepath = os.path.join(folder, base + self.filename_ext)
        return super().invoke(context, event)

    def run(self, context):
        raise NotImplementedError

    def execute(self, context):
        try:
            info = self.run(context)
        except (RuntimeError, OSError) as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}
        self.report({"INFO"}, f"Exported {info}")
        return {"FINISHED"}


class HRBD_OT_export_alembic(_ExportBase, bpy.types.Operator, ExportHelper):
    bl_idname = "hrbd.export_alembic"
    bl_label = "Export Alembic"
    bl_description = "Baked motion as an animated mesh (.abc)"
    filename_ext = ".abc"
    filter_glob: StringProperty(default="*.abc", options={"HIDDEN"})

    def run(self, context):
        return export.export_alembic(context, context.object, self.filepath)["file"]


class HRBD_OT_export_fbx(_ExportBase, bpy.types.Operator, ExportHelper):
    bl_idname = "hrbd.export_fbx"
    bl_label = "Export FBX (Bones)"
    bl_description = "One bone per piece, skinned mesh, baked animation (.fbx) for game engines"
    filename_ext = ".fbx"
    filter_glob: StringProperty(default="*.fbx", options={"HIDDEN"})
    keep_rig: BoolProperty(name="Keep Rig in Scene", default=False,
                           description="Leave the generated armature and skinned mesh in the scene")
    merge: BoolProperty(**MERGE)
    merge_distance: FloatProperty(**MERGE_DISTANCE)

    def run(self, context):
        info = export.export_fbx(context, context.object, self.filepath, keep_rig=self.keep_rig, merge=self.merge,
                                 merge_distance=self.merge_distance)
        if self.merge:
            self.report({"INFO"}, f"{info['pieces']} pieces on {info['bones'] - 1} bones, "
                                  f"{info['hidden_faces']} hidden faces removed")
        return info["file"]


class HRBD_OT_export_vat(_ExportBase, bpy.types.Operator, ExportHelper):
    bl_idname = "hrbd.export_vat"
    bl_label = "Export VAT"
    bl_description = "Rigid-body vertex animation textures: mesh .fbx, two .exr textures, .json and a shader include"
    filename_ext = ".json"
    filter_glob: StringProperty(default="*.json", options={"HIDDEN"})
    basis: EnumProperty(name="Target", default="UNITY", items=(
        ("UNITY", "Unity", "Data converted to Unity axes (-x, z, -y); mesh exported with Apply Transform"),
        ("BLENDER", "Blender Axes", "Data left in Blender axes"),
    ))
    merge: BoolProperty(**MERGE)
    merge_distance: FloatProperty(**MERGE_DISTANCE)

    def run(self, context):
        folder = os.path.dirname(self.filepath)
        name = os.path.splitext(os.path.basename(self.filepath))[0]
        info = export.export_vat(context, context.object, folder, name, self.basis, merge=self.merge,
                                 merge_distance=self.merge_distance)
        if self.merge:
            self.report({"INFO"}, f"{info['pieces']} pieces in {info['piece_count']} texture columns, "
                                  f"{info['hidden_faces']} hidden faces removed")
        return info["json"]


# ------------------------------------------------------------------ panels
def draw_solver(layout, context, ob):
    """Bake / Free and the exports, for an object that has a solver node."""
    info = sim.cache_info(ob)
    together = len(bake_targets(context)) if context.object == ob else 1
    row = layout.row(align=True)
    row.scale_y = 1.4
    if together > 1:
        label = bpy.app.translations.pgettext_iface("Bake {n} Objects Together").format(n=together)
        row.operator(HRBD_OT_bake.bl_idname, icon="REC", text=label, translate=False)
    else:
        row.operator(HRBD_OT_bake.bl_idname, icon="REC", text="Re-Bake" if info is not None else "Bake")
    row.operator(HRBD_OT_free.bl_idname, icon="TRASH", text="")
    if info is not None:
        label = bpy.app.translations.pgettext_iface("{pieces} pieces, {frames} frames").format(pieces=info[2], frames=info[3])
        layout.label(text=label, translate=False, icon="CHECKMARK")
    col = layout.column(align=True)
    col.operator(HRBD_OT_export_fbx.bl_idname, icon="ARMATURE_DATA")
    col.operator(HRBD_OT_export_vat.bl_idname, icon="TEXTURE")
    col.operator(HRBD_OT_export_alembic.bl_idname, icon="MESH_DATA")


def draw_network(layout, context, ob, with_parameters):
    nodes = rbd_nodes_of(ob)
    if not nodes:
        col = layout.column(align=True)
        col.label(text="New RBD network:")
        col.operator(HRBD_OT_setup.bl_idname, text="Fracture This Object", icon="MOD_EXPLODE").template = "FRACTURE"
        col.operator(HRBD_OT_setup.bl_idname, text="Use Its Loose Parts", icon="STICKY_UVS_DISABLE").template = "PIECES"
        layout.label(text="Adds a Geometry Nodes modifier", icon="INFO")
        layout.label(text="with the RBD nodes wired up")
        return
    if ob.get(OPEN_EDGES) and graph.sites(ob, nodes_rbd.KIND_MATERIAL_FRACTURE):
        warn = layout.column(align=True)
        warn.alert = True
        warn.label(text="Mesh is not closed", icon="ERROR")
        warn.label(text="Weld, close holes or Solidify")
        warn.operator(HRBD_OT_check_mesh.bl_idname, text="Check Again", icon="FILE_REFRESH")
    solver = None
    for mod, node in nodes:
        kind = node.node_tree.get(core.KIND_PROP)
        if kind == nodes_rbd.KIND_BULLET_SOLVER and solver is None:
            solver = node
        if not with_parameters:
            continue
        # one foldable section per node, with the same parameters as on the node itself
        header, body = layout.panel(f"hrbd_{mod.name}_{node.name}", default_closed=kind != nodes_rbd.KIND_MATERIAL_FRACTURE)
        header.label(text=node.label or node.name, translate=False, icon="NODE")
        if body is not None:
            body.use_property_split = False
            body.template_node_inputs(node)
            for name in CURSOR_INPUTS.get(kind, ()):
                sock = node.inputs.get(name)
                if sock is None or sock.is_linked or not sock.enabled or sock.is_inactive:
                    continue
                label = bpy.app.translations.pgettext_iface("{name} from 3D Cursor").format(name=bpy.app.translations.pgettext_iface(name))
                op = body.operator(HRBD_OT_cursor_to_input.bl_idname, text=label, translate=False, icon="PIVOT_CURSOR")
                op.modifier, op.node, op.input = mod.name, node.name, name
    if solver is None:
        layout.label(text="No RBD Bullet Solver node:", icon="INFO")
        layout.label(text="add one to simulate (Add > RBD)")
        return
    box = layout.box()
    box.label(text="RBD Bullet Solver", translate=False, icon="PHYSICS")
    draw_solver(box, context, ob)


class HRBD_PT_main(bpy.types.Panel):
    """3D Viewport > Sidebar > H-Style RBD Nodes: the RBD nodes of the active object, without opening the node editor."""
    bl_label = "H-Style RBD Nodes"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "H-Style RBD"

    def draw(self, context):
        ob = context.object
        if ob is None or ob.type != "MESH":
            self.layout.label(text="Select a mesh object", icon="INFO")
            return
        draw_network(self.layout, context, ob, with_parameters=True)


class HRBD_PT_node_editor(bpy.types.Panel):
    """Geometry Nodes editor > Sidebar > RBD: Bake and the exports next to the nodes."""
    bl_label = "H-Style RBD Nodes"
    bl_space_type = "NODE_EDITOR"
    bl_region_type = "UI"
    bl_category = "RBD"

    @classmethod
    def poll(cls, context):
        return _in_geometry_nodes(context)

    def draw(self, context):
        ob = context.object
        if ob is None or ob.type != "MESH":
            self.layout.label(text="Select a mesh object", icon="INFO")
            return
        draw_network(self.layout, context, ob, with_parameters=False)


CLASSES = (
    HRBD_OT_setup, HRBD_OT_add_node, NODE_MT_hrbd_add, HRBD_OT_check_mesh, HRBD_OT_cursor_to_input,
    HRBD_OT_bake, HRBD_OT_free,
    HRBD_OT_export_alembic, HRBD_OT_export_fbx, HRBD_OT_export_vat,
    HRBD_PT_main, HRBD_PT_node_editor,
)


@bpy.app.handlers.persistent
def _refresh_on_load(*_):
    # a file saved with an older version of the add-on: bring its RBD node groups up to date
    nodes_rbd.refresh()


def register():
    for c in CLASSES:
        bpy.utils.register_class(c)
    bpy.types.NODE_MT_geometry_node_add_all.append(_add_menu)
    bpy.app.handlers.load_post.append(_refresh_on_load)
    translations.register()


def unregister():
    translations.unregister()
    if _refresh_on_load in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_refresh_on_load)
    bpy.types.NODE_MT_geometry_node_add_all.remove(_add_menu)
    for c in reversed(CLASSES):
        bpy.utils.unregister_class(c)
