"""Drive the add-on the way a user does: through its operators and the values on the RBD nodes.

Run A (source tree):   blender --background --factory-startup --python-exit-code 1 --python Tests/test_addon.py -- <out_dir>
Run B (installed zip): blender --background --python-exit-code 1 --python Tests/test_addon.py -- <out_dir> installed
"""
import os
import sys

import bmesh
import bpy
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as T  # noqa: E402

args = sys.argv[sys.argv.index("--") + 1:]
OUT = args[0]
INSTALLED = len(args) > 1 and args[1] == "installed"
MODE = "installed" if INSTALLED else "source"
REP = T.Report(f"test_addon_{MODE}", OUT, "ADDON")
c = REP.case(MODE)


def rbd(ob, kind):
    """The RBD node of this kind in the node tree of the object (found by the marker on its node group)."""
    for m in ob.modifiers:
        if m.type == "NODES" and m.node_group is not None:
            for node in m.node_group.nodes:
                if node.bl_idname == "GeometryNodeGroup" and node.node_tree is not None \
                        and node.node_tree.get("hrbd_kind") == kind:
                    return node
    return None


def pieces(ob):
    bpy.context.view_layer.update()
    dg = bpy.context.evaluated_depsgraph_get()
    m = ob.evaluated_get(dg).to_mesh()
    ids = np.zeros(len(m.vertices), np.int32)
    m.attributes["piece_id"].data.foreach_get("value", ids)
    co = np.empty(len(m.vertices) * 3, np.float32)
    m.vertices.foreach_get("co", co)
    info = (int(ids.max()) + 1, [x.name if x else None for x in m.materials], [u.name for u in m.uv_layers], co)
    ob.evaluated_get(dg).to_mesh_clear()
    return info


def pillar(name, x=0.0):
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bm.loops.layers.uv.new("MyUV")
    bmesh.ops.create_cube(bm, size=1.0, calc_uvs=True)
    bmesh.ops.scale(bm, vec=(0.6, 0.6, 3.0), verts=bm.verts)
    bmesh.ops.translate(bm, vec=(x, 0, 1.5), verts=bm.verts)
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(ob)
    return ob


def only(*obs):
    bpy.context.view_layer.update()         # objects made or removed a moment ago
    for o in bpy.context.view_layer.objects:
        if o is not None:
            o.select_set(o in obs)
    bpy.context.view_layer.objects.active = obs[0]


try:
    if INSTALLED:
        import addon_utils
        mods = [m.__name__ for m in addon_utils.modules() if m.__name__.endswith(".h_style_rbd_nodes")]
        c.set(module=mods)
        c.check("extension_enabled", len(mods) == 1 and addon_utils.check(mods[0])[1], mods)
    else:
        import Extension
        Extension.register()

    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o)
    scene = bpy.context.scene
    scene.frame_start, scene.frame_end = 1, 50
    ob = pillar("Pillar")
    only(ob)

    c.check("panels_and_menu_registered", all(hasattr(bpy.types, name) for name in
                                              ("HRBD_PT_main", "HRBD_PT_node_editor", "NODE_MT_hrbd_add")))
    c.check("translation_registered", bpy.app.translations.pgettext("Bake Simulation") is not None)
    c.check("nothing_to_bake_yet", not bpy.ops.hrbd.bake.poll() and not bpy.ops.hrbd.free_bake.poll()
            and not bpy.ops.hrbd.export_fbx.poll())

    # ---- RBD Network: one click gives the object a fracture node wired into a solver node
    c.check("setup", bpy.ops.hrbd.setup() == {"FINISHED"} and len(ob.modifiers) == 1)
    fracture, solver = rbd(ob, "material_fracture"), rbd(ob, "bullet_solver")
    tree = ob.modifiers[0].node_group
    c.check("network_is_two_rbd_nodes", fracture is not None and solver is not None and len(tree.nodes) == 4
            and all(solver.inputs[n].is_linked for n in ("Geometry", "Constraint Geometry", "Proxy Geometry")),
            [n.name for n in tree.nodes])
    c.check("solver_takes_the_scene_range", solver.inputs["Start Frame"].default_value == 1 and solver.inputs["End Frame"].default_value == 50)
    c.check("fractured_at_once", pieces(ob)[0] > 20, pieces(ob)[0])

    # ---- the parameters are the inputs of the nodes
    fracture.inputs["Scatter Points"].default_value = 45
    c.check("scatter_points_changes_the_pieces", 40 <= pieces(ob)[0] <= 45, pieces(ob)[0])
    fracture.inputs["Material Type"].default_value = "Wood"
    n_wood, _, _, co = pieces(ob)
    fracture.inputs["Material Type"].default_value = "Concrete"
    fracture.inputs["Assign Inside Material"].default_value = True
    fracture.inputs["Inside Material"].default_value = bpy.data.materials.new("Inner")
    fracture.inputs["UV Map"].default_value = "MyUV"
    n, mats, uvs, _ = pieces(ob)
    c.check("material_type_is_a_menu", n_wood >= 30)
    c.check("inside_material_assigned", "Inner" in mats, mats)
    c.check("uses_existing_uv_map", uvs == ["MyUV"], uvs)

    # ---- a position from the 3D cursor, in the space of the object
    ob.location = (1.0, 0.0, 0.0)
    scene.cursor.location = (1.5, 0.25, 2.0)
    bpy.context.view_layer.update()
    done = bpy.ops.hrbd.cursor_to_input(modifier=ob.modifiers[0].name, node=fracture.name, input="Impact Point")
    c.check("impact_point_from_cursor", done == {"FINISHED"}
            and max(abs(a - b) for a, b in zip(fracture.inputs["Impact Point"].default_value, (0.5, 0.25, 2.0))) < 1e-6,
            tuple(round(x, 3) for x in fracture.inputs["Impact Point"].default_value))
    ob.location = (0.0, 0.0, 0.0)

    # ---- bake: the button next to the solver node
    c.check("bake_possible_now", bpy.ops.hrbd.bake.poll())
    solver.inputs["End Frame"].default_value = 40
    ob.location.z = 2.0                     # dropped from two metres, so that something happens
    counts = T.datablock_counts()
    c.check("bake", bpy.ops.hrbd.bake() == {"FINISHED"} and bool(solver.inputs["Baked"].default_value))
    c.check("baked_node_holds_the_cache", solver.inputs["Cache"].default_value is not None
            and solver.inputs["Frame Count"].default_value == 40 and solver.inputs["Piece Count"].default_value == n)
    for op, ext in (("export_fbx", ".fbx"), ("export_alembic", ".abc"), ("export_vat", ".json")):
        path = os.path.join(OUT, f"addon_{MODE}_pillar" + ext)
        if os.path.exists(path):
            os.remove(path)
        ok = getattr(bpy.ops.hrbd, op)(filepath=path) == {"FINISHED"}
        c.check(op, ok and os.path.exists(path) and os.path.getsize(path) > 500, os.path.getsize(path) if os.path.exists(path) else None)
    c.check("rebake_twice", bpy.ops.hrbd.bake() == {"FINISHED"} and bpy.ops.hrbd.bake() == {"FINISHED"})
    after = T.datablock_counts()
    c.check("rebakes_do_not_pile_up", after["objects"] == counts["objects"] + 2 and after["meshes"] == counts["meshes"] + 2
            and after["actions"] == counts["actions"], {k: after[k] - counts[k] for k in after})
    # the parameters of a baked network can still be turned: the bake stays as it is until Re-Bake
    before_edit = pieces(ob)[3]
    fracture.inputs["Scatter Points"].default_value = 10
    c.check("bake_is_not_touched_by_edits", np.array_equal(pieces(ob)[3], before_edit))
    fracture.inputs["Scatter Points"].default_value = 45

    # ---- save, reopen: the bake must still play
    blend = os.path.join(OUT, f"addon_{MODE}_pillar.blend")
    scene.frame_set(20)
    before_co = pieces(ob)[3]
    bpy.ops.wm.save_as_mainfile(filepath=blend)
    bpy.ops.wm.open_mainfile(filepath=blend)
    scene = bpy.context.scene
    ob = bpy.data.objects["Pillar"]
    scene.frame_set(20)
    after_co = pieces(ob)[3]
    c.check("bake_survives_save_and_reload", len(before_co) == len(after_co) and float(np.abs(before_co - after_co).max()) < 1e-6)
    scene.frame_set(1)
    c.check("reloaded_bake_is_moving", float(np.abs(pieces(ob)[3] - after_co).max()) > 0.01)

    # ---- two objects with their own networks, selected together: one simulation, a bake on each
    other = pillar("Other", 2.0)
    plain = pillar("Plain", -3.0)
    only(other)
    bpy.ops.hrbd.setup()
    only(ob, other, plain)
    c.check("bake_together", bpy.ops.hrbd.bake() == {"FINISHED"}
            and bool(rbd(ob, "bullet_solver").inputs["Baked"].default_value)
            and bool(rbd(other, "bullet_solver").inputs["Baked"].default_value) and len(plain.modifiers) == 0)

    # ---- a model that is already in pieces: the other template; a node added from a script
    me = bpy.data.meshes.new("Parts")
    bm = bmesh.new()
    for k in range(3):
        for v in bmesh.ops.create_cube(bm, size=0.5)["verts"]:
            v.co.x += 6.0 + 0.5 * k
            v.co.z += 0.25
    bm.to_mesh(me)
    bm.free()
    parts = bpy.data.objects.new("Parts", me)
    scene.collection.objects.link(parts)
    only(parts)
    c.check("setup_existing_pieces", bpy.ops.hrbd.setup(template="PIECES") == {"FINISHED"}
            and all(rbd(parts, k) is not None for k in ("assemble", "constraints_from_rules", "bullet_solver"))
            and rbd(parts, "material_fracture") is None and pieces(parts)[0] == 3, pieces(parts)[0])
    c.check("add_node_from_a_script", bpy.ops.hrbd.add_node(kind="select") == {"FINISHED"} and rbd(parts, "select") is not None
            and parts.modifiers[-1].node_group.nodes.active == rbd(parts, "select"))
    c.check("existing_pieces_bake", bpy.ops.hrbd.bake() == {"FINISHED"} and bpy.ops.hrbd.free_bake() == {"FINISHED"})

    # ---- free
    for o in (other, ob):
        only(o)
        c.check(f"free_{o.name}", bpy.ops.hrbd.free_bake() == {"FINISHED"} and not rbd(o, "bullet_solver").inputs["Baked"].default_value)
    c.check("nothing_left_after_freeing", not [o for o in bpy.data.objects if o.name.startswith("RBD ")],
            [o.name for o in bpy.data.objects])
    c.check("free_gives_the_fracture_back", pieces(ob)[0] > 20 and not bpy.ops.hrbd.export_fbx.poll())
    if not INSTALLED:
        Extension.unregister()
        c.check("unregistered_cleanly", not hasattr(bpy.types, "HRBD_PT_main") and not hasattr(bpy.types, "NODE_MT_hrbd_add"))
except Exception:
    c.error()
c.done()
REP.finish()
