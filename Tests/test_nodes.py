"""Headless checks of the RBD nodes (the H-Style node groups).
Run: blender --background --factory-startup --python-exit-code 1 --python Tests/test_nodes.py -- <out_dir> [case ...]
"""
import os
import sys

import bpy
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as T  # noqa: E402
from Extension import core, graph, nodes_rbd, sim  # noqa: E402

args = sys.argv[sys.argv.index("--") + 1:]
OUT = args[0]
ONLY = set(args[1:])
REP = T.Report("test_nodes", OUT, "NODES")


def wanted(name):
    return not ONLY or name in ONLY


def network(ob, node_tree, inputs=None, output="Geometry"):
    """A modifier whose tree is: Group Input -> <node_tree as ONE node> -> Group Output (the chosen output)."""
    tree = bpy.data.node_groups.new("Test Network", "GeometryNodeTree")
    tree.interface.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    tree.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    gin, gout = tree.nodes.new("NodeGroupInput"), tree.nodes.new("NodeGroupOutput")
    node = tree.nodes.new("GeometryNodeGroup")
    node.node_tree = node_tree
    tree.links.new(gin.outputs[0], node.inputs["Geometry"])
    tree.links.new(node.outputs[output], gout.inputs[0])
    for name, value in (inputs or {}).items():
        node.inputs[name].default_value = value
    mod = ob.modifiers.new("RBD", "NODES")
    mod.node_group = tree
    return mod, tree, node


def show(tree, node, output):
    gout = next(n for n in tree.nodes if n.bl_idname == "NodeGroupOutput")
    tree.links.new(node.outputs[output], gout.inputs[0])
    bpy.context.view_layer.update()


def edges_of(ob):
    """Constraint geometry as numpy: piece at both ends, strength, area, anchor, end positions, face count."""
    dg = bpy.context.evaluated_depsgraph_get()
    me = ob.evaluated_get(dg).to_mesh()
    n_e = len(me.edges)
    ev = np.empty(n_e * 2, np.int32)
    me.edges.foreach_get("vertices", ev)
    piece = np.zeros(len(me.vertices), np.int32)
    me.attributes["piece_id"].data.foreach_get("value", piece)
    out = {}
    for name, width in (("strength", 1), ("area", 1), ("anchor", 3)):
        a = np.empty(n_e * width, np.float32)
        me.attributes[name].data.foreach_get("value" if width == 1 else "vector", a)
        out[name] = a.reshape(n_e, width) if width > 1 else a
    co = np.empty(len(me.vertices) * 3, np.float32)
    me.vertices.foreach_get("co", co)
    faces = len(me.polygons)
    ob.evaluated_get(dg).to_mesh_clear()
    ev = ev.reshape(-1, 2)
    return piece[ev], out["strength"], out["area"], out["anchor"], co.reshape(-1, 3)[ev], faces


def piece_sizes(em):
    size = np.zeros((em.n_pieces, 3))
    for k in range(3):
        lo, hi = np.full(em.n_pieces, np.inf), np.full(em.n_pieces, -np.inf)
        np.minimum.at(lo, em.piece, em.co[:, k])
        np.maximum.at(hi, em.piece, em.co[:, k])
        size[:, k] = hi - lo
    return size


# ---------------------------------------------------------------- RBD Material Fracture
if wanted("material_fracture"):
    c = REP.case("material_fracture")
    try:
        bpy.ops.wm.read_factory_settings(use_empty=True)
        group = nodes_rbd.material_fracture()
        iface = [(it.name, it.item_type, it.in_out if it.item_type == "SOCKET" else "") for it in group.interface.items_tree]
        c.set(inputs=len([i for i in iface if i[2] == "INPUT"]), panels=[i[0] for i in iface if i[1] == "PANEL"],
              outputs=[i[0] for i in iface if i[2] == "OUTPUT"], nodes_inside=len(group.nodes))
        c.check("three_streams_out", [i[0] for i in iface if i[2] == "OUTPUT"] == ["Geometry", "Constraint Geometry", "Proxy Geometry"])
        c.check("four_inputs_h_style", [i[0] for i in iface if i[2] == "INPUT"][:4]
                == ["Geometry", "Constraint Geometry", "Proxy Geometry", "Extra Points"])

        wall = T.add_object("Wall", T.box("Wall", (4.0, 0.4, 2.0), (0.0, 0.0, 1.0)))
        mod, tree, node = network(wall, group, {"Scatter Points": 60, "Random Seed": 3, "Primary Strength": 4.0})
        c.set(node_inputs=[s.name for s in node.inputs])
        bpy.context.view_layer.update()
        em = core.EvalMesh(wall)
        c.check("no_node_warnings", len(mod.node_warnings) == 0, [w.message for w in mod.node_warnings][:3])
        c.check("concrete_pieces", 55 <= em.n_pieces <= 60 and em.has_pieces and bool(em.inside.any()) and em.open_edges() == 0, em.n_pieces)
        vol = em.piece_volumes()
        c.check("volume_conserved", abs(float(vol.sum()) / (4.0 * 0.4 * 2.0) - 1.0) < 1e-3, round(float(vol.sum()), 5))

        # the constraint geometry, against the reference in the solver code (hashing of shared corners)
        ref = {(a, b): (point, area) for a, b, point, area in sim.adjacency(em, em.n_pieces)}
        show(tree, node, "Constraint Geometry")
        ends, strength, area, anchor, ends_co, faces = edges_of(wall)
        got = {(int(min(e)), int(max(e))): k for k, e in enumerate(ends)}
        mean_pivot = em.vertex_means()
        c.set(bonds=len(got), reference_bonds=len(ref),
              strength_range=[round(float(strength.min()), 2), round(float(strength.max()), 2)] if len(strength) else None)
        c.check("constraints_are_edges_only", faces == 0 and len(ends) > 100, [faces, len(ends)])
        c.check("one_edge_per_pair", len(got) == len(ends))
        c.check("same_pairs_as_reference", set(got) == set(ref), [len(set(got) - set(ref)), len(set(ref) - set(got))])
        if set(got) == set(ref):
            rel = max(abs(float(area[k]) / ref[p][1] - 1.0) for p, k in got.items())
            off = max(float(np.linalg.norm(anchor[k] - ref[p][0])) for p, k in got.items())
            c.set(worst_area_error=round(rel, 4), worst_anchor_error_m=round(off, 4))
            c.check("same_contact_areas", rel < 0.01, round(rel, 4))
            c.check("anchors_on_the_shared_faces", off < 0.05, round(off, 4))
        c.check("edges_run_from_pivot_to_pivot", float(np.abs(ends_co - mean_pivot[ends]).max()) < 1e-3,
                round(float(np.abs(ends_co - mean_pivot[ends]).max()), 5))
        expect = 4.0 * np.clip(np.sqrt(area / float(np.median(area))), 0.35, 2.5)
        c.check("strength_follows_area", float(np.abs(strength - expect).max()) < 1e-3, round(float(np.abs(strength - expect).max()), 5))
        node.inputs["Strength Variance"].default_value = 0.5
        node.inputs["Scale by Contact Area"].default_value = False
        bpy.context.view_layer.update()
        strength2 = edges_of(wall)[1]
        c.check("variance_spreads_strength", float(strength2.min()) >= 2.0 - 1e-4 and float(strength2.max()) <= 6.0 + 1e-4
                and float(np.std(strength2)) > 0.5, [round(float(strength2.min()), 2), round(float(strength2.max()), 2)])
        node.inputs["Constraints"].default_value = False
        bpy.context.view_layer.update()
        dg = bpy.context.evaluated_depsgraph_get()
        c.check("constraints_can_be_switched_off", len(wall.evaluated_get(dg).data.vertices) == 0)
        node.inputs["Constraints"].default_value = True

        # proxy geometry: the same pieces without interior detail
        node.inputs["Detail"].default_value = True
        node.inputs["Noise Amplitude"].default_value = 0.05
        show(tree, node, "Proxy Geometry")
        proxy = core.EvalMesh(wall)
        show(tree, node, "Geometry")
        rough = core.EvalMesh(wall)
        c.check("proxy_is_the_flat_shape", proxy.n_pieces == rough.n_pieces and len(proxy.co) == len(rough.co)
                and float(np.abs(proxy.co - rough.proxy_co).max()) < 1e-6 and float(np.abs(rough.co - rough.proxy_co).max()) > 0.01)
        node.inputs["Detail"].default_value = False

        # ---- Material Type: Glass (a pane), Wood (splinters)
        node.inputs["Material Type"].default_value = "Glass"
        node.inputs["Impact Point"].default_value = (0.5, 0.0, 1.2)
        node.inputs["Radial Crack Number"].default_value = 12
        node.inputs["Concentric Crack Number"].default_value = 5
        node.inputs["Impact Spread"].default_value = 3.0
        bpy.context.view_layer.update()
        glass = core.EvalMesh(wall)
        c.set(glass_pieces=glass.n_pieces)
        # a pane is cut straight through: every piece reaches both faces of the wall (y = -0.2 and y = +0.2)
        lo, hi = np.full(glass.n_pieces, np.inf), np.full(glass.n_pieces, -np.inf)
        np.minimum.at(lo, glass.piece, glass.co[:, 1])
        np.maximum.at(hi, glass.piece, glass.co[:, 1])
        c.check("glass_is_cut_through", 30 <= glass.n_pieces <= 60 and float(lo.max()) < -0.199 and float(hi.min()) > 0.199,
                [glass.n_pieces, round(float(lo.max()), 3), round(float(hi.min()), 3)])
        node.inputs["Material Type"].default_value = "Wood"
        node.inputs["Scatter Points"].default_value = 30
        bpy.context.view_layer.update()
        size = piece_sizes(core.EvalMesh(wall))
        c.set(wood_pieces=len(size), wood_median_size=[round(float(x), 2) for x in np.median(size, axis=0)])
        c.check("wood_splinters_along_the_longest_side", float(np.median(size[:, 0])) > 3.0 * float(np.median(size[:, 2])),
                [round(float(x), 2) for x in np.median(size, axis=0)])
        node.inputs["Fracture Direction"].default_value = "Z"
        bpy.context.view_layer.update()
        size = piece_sizes(core.EvalMesh(wall))
        c.check("grain_direction_can_be_chosen", float(np.median(size[:, 2])) > 1.5 * float(np.median(size[:, 0])),
                [round(float(x), 2) for x in np.median(size, axis=0)])

        # ---- Extra Points: the cell points come from upstream
        node.inputs["Material Type"].default_value = "Concrete"
        pts = bpy.data.meshes.new("Seeds")
        seeds = [(-1.5 + 0.6 * i, 0.0, 0.5 + 1.0 * (i % 2)) for i in range(6)]
        pts.from_pydata(seeds, [], [])
        seed_ob = bpy.data.objects.new("Seeds", pts)
        bpy.context.scene.collection.objects.link(seed_ob)
        info = tree.nodes.new("GeometryNodeObjectInfo")
        info.inputs["Object"].default_value = seed_ob
        tree.links.new(info.outputs["Geometry"], node.inputs["Extra Points"])
        bpy.context.view_layer.update()
        mine = core.EvalMesh(wall)
        centres = mine.piece_centroids()
        nearest = [int(np.argmin(np.linalg.norm(centres - np.array(s), axis=1))) for s in seeds]
        c.set(pieces_from_extra_points=mine.n_pieces)
        c.check("extra_points_are_the_cells", mine.n_pieces == 6 and len(set(nearest)) == 6
                and all(np.linalg.norm(centres[n] - np.array(s)) < 0.6 for n, s in zip(nearest, seeds)), mine.n_pieces)
    except Exception:
        c.error()
    c.done()


# ---------------------------------------------------------------- the chain of nodes, baked
def chain(ob, *kinds):
    """A modifier whose tree is Group Input -> one node per kind -> Group Output, the three streams wired through."""
    tree = bpy.data.node_groups.new("RBD " + ob.name, "GeometryNodeTree")
    tree.interface.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    tree.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    gin, gout = tree.nodes.new("NodeGroupInput"), tree.nodes.new("NodeGroupOutput")
    nodes, last = {}, None
    for kind in kinds:
        node = tree.nodes.new("GeometryNodeGroup")
        node.node_tree = nodes_rbd.NODES[kind][1]()
        if last is None:
            tree.links.new(gin.outputs[0], node.inputs["Geometry"])
        else:
            for name in ("Geometry", "Constraint Geometry", "Proxy Geometry"):
                if name in last.outputs and name in node.inputs:
                    tree.links.new(last.outputs[name], node.inputs[name])
        nodes[kind], last = node, node
    tree.links.new(last.outputs["Geometry"], gout.inputs[0])
    mod = ob.modifiers.new("RBD", "NODES")
    mod.node_group = tree
    return mod, tree, nodes


def fresh(frame_end=60):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.context.scene.frame_start, bpy.context.scene.frame_end = 1, frame_end


def played(ob, k):
    """The evaluated object at cache frame k against the cache itself: largest difference in metres."""
    pos, quat, piv, start = sim.read_cache(ob)
    rest = sim.rest_pieces(ob)[0]
    bpy.context.scene.frame_set(start + k)
    want = pos[k][rest.piece] + T.qrot(quat[k][rest.piece], rest.co - piv[rest.piece])
    return float(np.abs(core.EvalMesh(ob).co - want).max())


F, S, CFG, CON, CLU = (nodes_rbd.KIND_MATERIAL_FRACTURE, nodes_rbd.KIND_BULLET_SOLVER, nodes_rbd.KIND_CONFIGURE,
                       nodes_rbd.KIND_CONSTRAINT_PROPERTIES, nodes_rbd.KIND_CLUSTER)

if wanted("solver"):
    c = REP.case("solver")
    try:
        import time
        fresh(40)
        wall = T.add_object("Wall", T.box("Wall", (4.0, 0.4, 2.0), (0.0, 0.0, 1.0)))
        mod, tree, n = chain(wall, F, S)
        n[F].inputs["Scatter Points"].default_value = 60
        n[S].inputs["End Frame"].default_value = 40
        bpy.context.view_layer.update()
        c.check("no_node_warnings", len(mod.node_warnings) == 0, [w.message for w in mod.node_warnings][:3])
        visible = [s.name for s in n[S].inputs if s.enabled and not s.hide]
        c.check("solver_settings_stay_visible", all(name in visible for name in ("Bullet Substeps", "Density", "Ground Plane",
                                                                              "Collision Objects", "Gravity", "Start Frame")), visible)
        before = core.EvalMesh(wall)
        counts = T.datablock_counts()
        res = sim.bake_many(bpy.context, [wall])[0]
        pos, quat, piv, start = sim.read_cache(wall)
        added = {k: T.datablock_counts()[k] - counts[k] for k in counts if T.datablock_counts()[k] != counts[k]}
        c.set(pieces=res.pieces, frames=res.frames, glue=res.glue, moved=res.moved, bake_s=round(res.seconds, 2), added=added)
        c.check("baked_onto_the_node", bool(n[S].inputs["Baked"].default_value) and sim.is_baked(wall)
                and res.pieces == before.n_pieces and res.frames == 40 and added == {"objects": 2, "meshes": 2}, added)
        # the glue is the constraint geometry that arrives at the solver
        # (the reference in the solver code may miss a bond or two over a small shared face that the node finds)
        reference = {p[:2] for p in sim.adjacency(before, before.n_pieces)}
        wired = {p[:2] for p in sim.read_contacts(wall)}
        c.check("glue_from_the_constraint_geometry", res.glue == len(wired) > 100 and reference <= wired
                and len(wired - reference) <= 0.02 * len(reference), [res.glue, len(reference), len(wired - reference)])
        c.check("a_glued_wall_on_the_ground_stands", res.moved == 0 and res.events == 0, [res.moved, res.events])
        c.check("first_frame_is_rest", float(np.abs(pos[0] - piv).max()) < 1e-4)
        c.check("playback_matches_cache", max(played(wall, k) for k in (0, 10, 39)) < 1e-4)
        ts = []
        for k in range(1, 31):
            t = time.perf_counter()
            bpy.context.scene.frame_set(k)
            bpy.context.evaluated_depsgraph_get()
            ts.append(time.perf_counter() - t)
        ms = 1000 * sum(ts[1:]) / (len(ts) - 1)
        c.set(scrub_ms_per_frame=round(ms, 2))
        # the fracture upstream is not evaluated again while a bake is shown
        c.check("scrub_is_cheap", ms < 5.0, round(ms, 2))

        # ---- RBD Configure: velocity, activity, activation
        fresh(40)
        wall = T.add_object("Wall", T.box("Wall", (4.0, 0.4, 2.0), (0.0, 0.0, 3.0)))
        mod, tree, n = chain(wall, F, CFG, S)
        n[F].inputs["Scatter Points"].default_value = 40
        n[F].inputs["Constraints"].default_value = False
        n[S].inputs["End Frame"].default_value = 40
        n[S].inputs["Ground Plane"].default_value = False
        cfg = n[CFG]
        cfg.inputs["Set Initial Velocity"].default_value = True
        cfg.inputs["Velocity Type"].default_value = "Constant"
        cfg.inputs["Velocity"].default_value = (0.0, 0.0, 6.0)
        res = sim.bake_many(bpy.context, [wall])[0]
        pos, quat, piv, start = sim.read_cache(wall)
        step = pos[1] - pos[0]
        c.set(first_step_m=[round(float(step[:, 2].min()), 4), round(float(step[:, 2].max()), 4)], expected=round(6.0 / 24, 4))
        c.check("velocity_attribute_is_the_launch_speed", res.glue == 0 and float(np.abs(step - np.array([0.0, 0.0, 6.0 / 24])).max()) < 1e-4,
                round(float(np.abs(step - np.array([0.0, 0.0, 6.0 / 24])).max()), 6))
        apex = float((pos[..., 2].max(0) - piv[:, 2]).mean()) - 6.0 / 24
        c.check("flies_as_high_as_it_should", abs(apex / (36.0 / (2 * 9.81)) - 1.0) < 0.08, round(apex, 3))
        # the object turned: the velocity is given in the space of the object
        sim.free_cache(wall)
        c.check("free_clears_the_node", not n[S].inputs["Baked"].default_value and n[S].inputs["Cache"].default_value is None
                and not sim.is_baked(wall) and not [o for o in bpy.data.objects if o.name.startswith("RBD ")])
        wall.rotation_euler = (0.0, 1.5707963, 0.0)       # local +Z now points along world +X
        bpy.context.view_layer.update()
        sim.bake_many(bpy.context, [wall])
        pos, quat, piv, start = sim.read_cache(wall)
        step = pos[1] - pos[0]
        c.check("velocity_follows_the_object", float(np.abs(step - np.array([6.0 / 24, 0.0, 0.0])).max()) < 1e-4,
                [round(float(x), 4) for x in step.mean(0)])
        sim.free_cache(wall)
        wall.rotation_euler = (0.0, 0.0, 0.0)

        # inactive where the pivot is on the left: Selection is a field
        cfg.inputs["Set Initial Velocity"].default_value = False
        cfg.inputs["Set Active"].default_value = True
        cfg.inputs["Active"].default_value = False
        pivot = tree.nodes.new("GeometryNodeInputNamedAttribute")
        pivot.data_type = "FLOAT_VECTOR"
        pivot.inputs["Name"].default_value = "rbd_pivot"
        split = tree.nodes.new("ShaderNodeSeparateXYZ")
        less = tree.nodes.new("FunctionNodeCompare")
        less.operation = "LESS_THAN"
        tree.links.new(pivot.outputs["Attribute"], split.inputs[0])
        tree.links.new(split.outputs["X"], less.inputs[0])
        tree.links.new(less.outputs["Result"], cfg.inputs["Selection"])
        bpy.context.view_layer.update()
        res = sim.bake_many(bpy.context, [wall])[0]
        pos, quat, piv, start = sim.read_cache(wall)
        travel = np.linalg.norm(pos - piv[None], axis=-1).max(0)
        left = piv[:, 0] < 0.0
        c.set(inactive=int(left.sum()), anchored=res.anchored, moved=res.moved)
        c.check("inactive_pieces_stay", res.anchored == int(left.sum()) > 5 and float(travel[left].max()) == 0.0
                and float(travel[~left].min()) > 0.5, [res.anchored, int(left.sum())])
        sim.free_cache(wall)

        # activation as a wave from the left end: pieces are let go one after the other
        cfg.inputs["Set Active"].default_value = False
        for link in list(cfg.inputs["Selection"].links):
            tree.links.remove(link)
        cfg.inputs["Set Activation"].default_value = True
        cfg.inputs["Activation Type"].default_value = "Radial Wave"
        cfg.inputs["Wave Origin"].default_value = (-2.0, 0.0, 0.0)
        cfg.inputs["Wave Speed"].default_value = 4.0
        res = sim.bake_many(bpy.context, [wall])[0]
        pos, quat, piv, start = sim.read_cache(wall)
        moving = np.linalg.norm(pos - piv[None], axis=-1) > 1e-4
        first = np.where(moving.any(0), moving.argmax(0), 999)
        dist = np.linalg.norm(piv - np.array(wall.matrix_world.translation) - np.array([-2.0, 0.0, 0.0]), axis=1)
        expect = np.ceil(dist / 4.0 * 24 - 1e-6)              # the frame the wave arrives on
        c.set(first_moving_frame=[int(first.min()), int(first.max())])
        # (a piece cannot fall before it is let go; one resting on pieces that are still held starts a little later)
        # (the wave is timed from the pivot written by the fracture, the solver uses the centre of mass: a frame
        # of difference at most; a piece resting on pieces that are still held starts a little later)
        c.check("wave_releases_in_order", float(np.abs(first - expect).max()) <= 2.0 and float(np.corrcoef(first, dist)[0, 1]) > 0.97,
                [int((first - expect).min()), int((first - expect).max()), round(float(np.corrcoef(first, dist)[0, 1]), 3)])
        sim.free_cache(wall)

        # ---- constraints: properties, clusters
        fresh(40)
        wall = T.add_object("Wall", T.box("Wall", (4.0, 0.4, 2.0), (0.0, 0.0, 1.0)))
        mod, tree, n = chain(wall, F, CLU, CON, CFG, S)
        n[F].inputs["Scatter Points"].default_value = 60
        n[F].inputs["Primary Strength"].default_value = 2.0
        n[F].inputs["Scale by Contact Area"].default_value = False
        n[CLU].inputs["Size"].default_value = 0.8
        n[CLU].inputs["Strength Scale"].default_value = 10.0
        n[CON].inputs["Operation"].default_value = "Multiply By"
        n[CON].inputs["Strength"].default_value = 1.5
        n[S].inputs["End Frame"].default_value = 40
        bpy.context.view_layer.update()
        pairs, strength = graph.constraints(wall, mod, n[S])
        levels = sorted({round(float(x), 3) for x in strength})
        c.set(bonds=len(pairs), strength_levels=levels)
        c.check("cluster_and_properties_shape_the_strength", levels == [3.0, 30.0] and 0.1 < float((strength > 10).mean()) < 0.9,
                [levels, round(float((strength > 10).mean()), 2)])
        em = core.EvalMesh(wall)
        c.check("every_bond_arrives_at_the_solver", {p[:2] for p in sim.adjacency(em, em.n_pieces)} <= {p[:2] for p in pairs})
        # a blast from the middle: with the wall glued, fewer pieces come off than without
        n[CFG].inputs["Set Initial Velocity"].default_value = True
        n[CFG].inputs["Origin"].default_value = (0.0, -0.4, 1.0)
        n[CFG].inputs["Speed"].default_value = 6.0
        n[CFG].inputs["Falloff Radius"].default_value = 1.6
        glued = sim.bake_many(bpy.context, [wall])[0]
        c.check("glue_breaks_where_the_blast_is", glued.glue == len(pairs) and 0 < glued.events < glued.glue, [glued.events, glued.glue])
        sim.free_cache(wall)
        n[CON].inputs["Operation"].default_value = "Set To"
        n[CON].inputs["Strength"].default_value = 0.0
        loose = sim.bake_many(bpy.context, [wall])[0]
        c.set(cracks_glued=glued.events, cracks_without_strength=loose.events)
        c.check("constraint_strength_matters", loose.events > glued.events, [loose.events, glued.events])

        # ---- exports read the bake from the node
        from Extension import export
        info = export.export_fbx(bpy.context, wall, os.path.join(OUT, "nodes_wall.fbx"), merge=True)
        vat = export.export_vat(bpy.context, wall, OUT, "nodes_wall", "UNITY")
        c.check("exports_work", os.path.getsize(os.path.join(OUT, "nodes_wall.fbx")) > 10000 and info["pieces"] == loose.pieces
                and vat["piece_count"] == loose.pieces and vat["events"] == loose.events, [info["bones"], vat["piece_count"]])

        # ---- two objects with their own networks, one simulation; a failure while writing the second undoes the first
        fresh(40)
        a = T.add_object("A", T.box("A", (0.6, 0.6, 0.6), (-2.0, 0.0, 0.5)))
        b_ = T.add_object("B", T.box("B", (0.4, 2.0, 1.6), (0.0, 0.0, 0.8)))
        ma, ta, na = chain(a, F, CFG, S)
        mb, tb, nb = chain(b_, F, S)
        na[F].inputs["Scatter Points"].default_value = 14
        na[F].inputs["Constraints"].default_value = False
        na[CFG].inputs["Set Initial Velocity"].default_value = True
        na[CFG].inputs["Velocity Type"].default_value = "Constant"
        na[CFG].inputs["Velocity"].default_value = (10.0, 0.0, 1.0)
        nb[F].inputs["Scatter Points"].default_value = 40
        nb[F].inputs["Primary Strength"].default_value = 0.6
        nb[S].inputs["Start Asleep"].default_value = True
        for node in (na[S], nb[S]):
            node.inputs["End Frame"].default_value = 40
        alone = sim.bake_many(bpy.context, [b_])[0]
        both = sim.bake_many(bpy.context, [a, b_])
        c.set(wall_moved_alone=alone.moved, wall_moved_when_hit=both[1].moved)
        c.check("objects_collide_in_one_simulation", alone.moved == 0 and both[1].moved >= 5 and sim.is_baked(a) and sim.is_baked(b_),
                [alone.moved, both[1].moved])
        old = (na[S].inputs["Cache"].default_value, nb[S].inputs["Cache"].default_value)
        counts = T.datablock_counts()
        real, calls = sim._write_site, [0]

        def second_fails(*args, **kw):
            calls[0] += 1
            if calls[0] == 2:
                raise RuntimeError("injected while writing the second object")
            return real(*args, **kw)
        sim._write_site = second_fails
        try:
            sim.bake_many(bpy.context, [a, b_])
            raised = False
        except RuntimeError:
            raised = True
        finally:
            sim._write_site = real
        after = T.datablock_counts()
        c.check("failed_write_undoes_everything", raised and (na[S].inputs["Cache"].default_value, nb[S].inputs["Cache"].default_value) == old
                and after == counts and played(a, 20) < 1e-4, {k: after[k] - counts[k] for k in after if after[k] != counts[k]})
        # the wiring of the trees is as it was (reading the inputs rewires for a moment)
        gout = next(x for x in ta.nodes if x.bl_idname == "NodeGroupOutput")
        c.check("node_trees_left_as_they_were", gout.inputs[0].links[0].from_node == na[S] and len(ta.links) == 8, len(ta.links))
    except Exception:
        c.error()
    c.done()



# ---------------------------------------------------------------- pieces that are modelled, selections, painted groups
def brick_wall(name, cols=12, rows=10, size=(0.5, 0.25, 0.25), gap=0.0):
    """Bricks in running bond, each a loose part. `gap`: every brick is made smaller by this, on all sides half of it."""
    import bmesh
    bm = bmesh.new()
    column = []
    for j in range(rows):
        shift = 0.5 * size[0] if j % 2 else 0.0
        for i in range(cols):
            for v in bmesh.ops.create_cube(bm, size=1.0)["verts"]:
                v.co.x = (v.co.x * (size[0] - gap) / size[0] + 0.5 + i) * size[0] - cols * size[0] / 2 + shift
                v.co.y = v.co.y * (size[1] - gap)
                v.co.z = (v.co.z * (size[2] - gap) / size[2] + 0.5 + j) * size[2]
                column.append(i)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    ob = T.add_object(name, me)
    stay = ob.vertex_groups.new(name="Stay")        # both ends of the wall
    for v in me.vertices:
        stay.add([v.index], 1.0 if column[v.index] < 2 or column[v.index] >= cols - 2 else 0.0, "REPLACE")
    return ob


def box_contacts(em, reach):
    """{(a, b): area} for pieces that are boxes: the faces of a and b are closer than `reach` and overlap."""
    n = em.n_pieces
    lo, hi = np.full((n, 3), np.inf), np.full((n, 3), -np.inf)
    np.minimum.at(lo, em.piece, em.co)
    np.maximum.at(hi, em.piece, em.co)
    out = {}
    for a in range(n):
        over = np.minimum(hi[a], hi[a + 1:]) - np.maximum(lo[a], lo[a + 1:])     # below zero: a gap of that size
        for k, o in enumerate(over):
            apart = [x for x in range(3) if o[x] < 1e-5]
            if len(apart) == 1 and o[apart[0]] > -reach:
                rest = [x for x in range(3) if x != apart[0]]
                out[(a, a + 1 + k)] = float(o[rest[0]] * o[rest[1]])
    return out


def per_piece(ob, name):
    bpy.context.view_layer.update()
    em = core.EvalMesh(ob)
    return em, em.per_piece(name)


ASM, RULES, SEL = nodes_rbd.KIND_ASSEMBLE, nodes_rbd.KIND_CONSTRAINTS_FROM_RULES, nodes_rbd.KIND_SELECT

if wanted("pieces"):
    c = REP.case("pieces")
    try:
        import time
        # ---- RBD Assemble: the loose parts of a model are the pieces
        fresh(50)
        wall = brick_wall("Bricks")
        mod, tree, n = chain(wall, ASM, RULES, CFG, S)
        n[S].inputs["End Frame"].default_value = 50
        gout = next(x for x in tree.nodes if x.bl_idname == "NodeGroupOutput")
        tree.links.new(n[ASM].outputs["Geometry"], gout.inputs[0])
        bpy.context.view_layer.update()
        em = core.EvalMesh(wall)
        centres = em.piece_centroids()
        c.check("no_node_warnings", len(mod.node_warnings) == 0, [w.message for w in mod.node_warnings][:3])
        c.check("every_brick_is_a_piece", em.n_pieces == 120 and em.has_pieces and not em.inside.any()
                and float(np.abs(em.pivot_attr - centres[em.piece]).max()) < 1e-5 and float(np.abs(em.proxy_co - em.co).max()) == 0.0,
                em.n_pieces)
        tree.links.new(n[ASM].outputs["Proxy Geometry"], gout.inputs[0])
        bpy.context.view_layer.update()
        c.check("assemble_gives_proxy_geometry", core.EvalMesh(wall).n_pieces == 120)

        # ---- RBD Constraints From Rules: glue between pieces that touch
        expect = box_contacts(em, 0.02)
        t = time.perf_counter()
        pairs, strength = graph.constraints(wall, mod, n[S])
        seconds = time.perf_counter() - t
        got = {(a, b): area for a, b, _, area in pairs}
        c.set(bricks=em.n_pieces, bonds=len(got), expected_bonds=len(expect), constraints_s=round(seconds, 3))
        c.check("one_edge_per_pair", len(got) == len(pairs))
        c.check("touching_bricks_are_glued", set(got) == set(expect), [len(set(got) - set(expect)), len(set(expect) - set(got))])
        if set(got) == set(expect):
            rel = np.array([got[k] / expect[k] - 1.0 for k in expect])
            c.set(contact_area_error_median=round(float(np.median(np.abs(rel))), 3), contact_area_error_worst=round(float(np.abs(rel).max()), 3))
            # the areas are counted from scattered points: right on average, a rough number for one contact
            c.check("contact_areas_are_about_right", abs(float(rel.mean())) < 0.05 and float(np.median(np.abs(rel))) < 0.2,
                    [round(float(rel.mean()), 3), round(float(np.median(np.abs(rel))), 3)])
            anchors = {(a, b): point for a, b, point, _ in pairs}
            off = max(abs(float(anchors[k][2] - max(em.co[em.piece == k[0]][:, 2].min(), em.co[em.piece == k[1]][:, 2].min())))
                      for k in expect if abs(centres[k[0]][2] - centres[k[1]][2]) > 0.1)
            c.check("anchors_are_where_the_bricks_touch", off < 0.01, round(off, 4))
        n[RULES].inputs["Scale by Contact Area"].default_value = False
        n[RULES].inputs["Strength"].default_value = 3.0
        pairs, strength = graph.constraints(wall, mod, n[S])
        c.check("strength_is_set", len(strength) == len(expect) and float(np.abs(strength - 3.0).max()) < 1e-5)

        # bricks with mortar gaps of 1 cm: glued only when the search radius reaches across
        gappy = brick_wall("Gappy", gap=0.01)
        gappy.location.x = 20.0
        mod2, tree2, n2 = chain(gappy, ASM, RULES, S)
        bpy.context.view_layer.update()
        n2[RULES].inputs["Search Radius"].default_value = 0.005
        short = graph.constraints(gappy, mod2, n2[S])[0]
        n2[RULES].inputs["Search Radius"].default_value = 0.02
        far = {(a, b) for a, b, _, _ in graph.constraints(gappy, mod2, n2[S])[0]}
        c.set(bonds_across_gaps=[len(short), len(far)])
        c.check("search_radius_decides_across_gaps", len(short) == 0 and far == set(expect), [len(short), len(far ^ set(expect))])
        bpy.data.objects.remove(gappy)

        # ---- RBD Select: selections as fields, wired into RBD Configure
        sel = tree.nodes.new("GeometryNodeGroup")
        sel.node_tree = nodes_rbd.select()
        tree.links.new(sel.outputs["Selection"], n[CFG].inputs["Selection"])
        n[CFG].inputs["Set Active"].default_value = True
        n[CFG].inputs["Active"].default_value = False
        tree.links.new(n[CFG].outputs["Geometry"], gout.inputs[0])

        def chosen(**values):
            for name, value in values.items():
                sel.inputs[name].default_value = value
            return per_piece(wall, "active")[1] < 0.5
        low = chosen(Type="Below Height", Height=0.01)
        c.check("select_below_height", int(low.sum()) == 12 and bool((centres[low][:, 2] < 0.2).all()), int(low.sum()))
        box = chosen(Type="Box", Center=(0.0, 0.0, 1.25), Size=(2.0, 1.0, 1.0))
        want = (np.abs(centres[:, 0]) <= 1.0) & (np.abs(centres[:, 2] - 1.25) <= 0.5)
        c.check("select_box", np.array_equal(box, want) and 5 < int(box.sum()) < 60, [int(box.sum()), int(want.sum())])
        ball = chosen(Type="Sphere", Center=(0.0, 0.0, 1.25), Radius=0.8)
        want = np.linalg.norm(centres - np.array([0.0, 0.0, 1.25]), axis=1) <= 0.8
        c.check("select_sphere", np.array_equal(ball, want) and 5 < int(ball.sum()) < 60, [int(ball.sum()), int(want.sum())])
        ends = chosen(Type="Attribute", Attribute="Stay")
        want = (centres[:, 0] < -2.0) | (centres[:, 0] > 2.0 - 1e-6)
        c.check("select_vertex_group", int(ends.sum()) == 40 and bool((np.abs(centres[ends][:, 0]) > 1.9).all()), int(ends.sum()))
        c.check("select_invert", int(chosen(Invert=True).sum()) == 80)
        sel.inputs["Invert"].default_value = False

        # ---- baked: the bottom row is held, the wall is glued and stands; without glue a blast takes it apart
        chosen(Type="Below Height", Height=0.01)
        tree.links.new(n[S].outputs["Geometry"], gout.inputs[0])
        res = sim.bake_many(bpy.context, [wall])[0]
        c.set(anchored=res.anchored, glue=res.glue, moved=res.moved, bake_s=round(res.seconds, 2))
        c.check("modelled_pieces_bake", res.pieces == 120 and res.anchored == 12 and res.glue == len(expect) and res.moved == 0,
                [res.pieces, res.anchored, res.glue, res.moved])
        c.check("playback_matches_cache", max(played(wall, k) for k in (0, 20, 49)) < 1e-4)
        sim.free_cache(wall)

        # ---- what collides is the Proxy Geometry that arrives at the solver: with shapes that float 10 cm
        # above the bricks, the bricks come to rest 10 cm deep in the ground
        fresh(40)
        wall = brick_wall("Bricks", cols=4, rows=1)
        mod, tree, n = chain(wall, ASM, S)
        n[S].inputs["End Frame"].default_value = 40
        plain = sim.bake_many(bpy.context, [wall])[0]
        rise_plain = float((sim.read_cache(wall)[0][-1] - sim.read_cache(wall)[2])[:, 2].mean())
        sim.free_cache(wall)
        lower = tree.nodes.new("GeometryNodeSetPosition")
        lower.inputs["Offset"].default_value = (0.0, 0.0, 0.1)
        tree.links.new(n[ASM].outputs["Proxy Geometry"], lower.inputs["Geometry"])
        tree.links.new(lower.outputs["Geometry"], n[S].inputs["Proxy Geometry"])
        sim.bake_many(bpy.context, [wall])
        rise = float((sim.read_cache(wall)[0][-1] - sim.read_cache(wall)[2])[:, 2].mean())
        c.set(rise_with_own_shapes_m=round(rise_plain, 4), rise_with_raised_proxy_m=round(rise, 4))
        c.check("proxy_geometry_is_what_collides", abs(rise_plain) < 0.005 and abs(rise + 0.1) < 0.01, [round(rise_plain, 4), round(rise, 4)])
        for link in list(n[S].inputs["Proxy Geometry"].links):
            tree.links.remove(link)
        sim.free_cache(wall)
        sim.bake_many(bpy.context, [wall])
        rise = float((sim.read_cache(wall)[0][-1] - sim.read_cache(wall)[2])[:, 2].mean())
        c.check("without_proxy_the_pieces_collide", abs(rise) < 0.005, round(rise, 4))

        # ---- a painted vertex group survives RBD Material Fracture (Keep Vertex Group)
        fresh(30)
        slab = T.add_object("Slab", T.box("Slab", (4.0, 0.4, 2.0), (0.0, 0.0, 1.0)))
        left = slab.vertex_groups.new(name="Left")
        for v in slab.data.vertices:
            left.add([v.index], 1.0 if v.co.x < 0.0 else 0.0, "REPLACE")      # fades from 1 at the left end to 0 at the right
        mod, tree, n = chain(slab, F, CFG, S)
        n[F].inputs["Scatter Points"].default_value = 60
        n[F].inputs["Keep Vertex Group"].default_value = "Left"
        sel = tree.nodes.new("GeometryNodeGroup")
        sel.node_tree = nodes_rbd.select()
        sel.inputs["Type"].default_value = "Attribute"
        sel.inputs["Attribute"].default_value = "Left"
        tree.links.new(sel.outputs["Selection"], n[CFG].inputs["Selection"])
        n[CFG].inputs["Set Active"].default_value = True
        n[CFG].inputs["Active"].default_value = False
        gout = next(x for x in tree.nodes if x.bl_idname == "NodeGroupOutput")
        tree.links.new(n[CFG].outputs["Geometry"], gout.inputs[0])
        em, active = per_piece(slab, "active")
        held = active < 0.5
        x = em.piece_centroids()[:, 0]
        c.set(pieces=em.n_pieces, held_by_painted_group=int(held.sum()))
        c.check("no_node_warnings_fracture", len(mod.node_warnings) == 0, [w.message for w in mod.node_warnings][:3])
        c.check("painted_group_survives_the_fracture", bool(held[x < -0.4].all()) and not held[x > 0.4].any() and 15 < int(held.sum()) < 45,
                [int(held.sum()), em.n_pieces])
        tree.links.new(n[S].outputs["Geometry"], gout.inputs[0])
        res = sim.bake_many(bpy.context, [slab])[0]
        c.check("held_pieces_arrive_at_the_solver", res.anchored == int(held.sum()), [res.anchored, int(held.sum())])
    except Exception:
        c.error()
    c.done()



# ---------------------------------------------------------------- Blender's force fields; old files
def wind(strength, direction_x=True):
    """A Wind field blowing along world +X (a wind blows along the local Z of its object)."""
    import math
    bpy.ops.object.effector_add(type="WIND", location=(0.0, 0.0, 0.0), rotation=(0.0, math.pi / 2, 0.0))
    ob = bpy.context.object
    ob.field.strength = strength
    ob.field.flow = 0.0          # the wind pushes with its strength, whatever the speed of the piece
    ob.select_set(False)
    return ob


def floating_box(frames=24):
    """A box in eight pieces with nothing acting on it: no gravity, no ground, no damping, no glue."""
    fresh(frames)
    box = T.add_object("Box", T.box("Box", (1.0, 1.0, 1.0), (0.0, 0.0, 5.0)))
    mod, tree, n = chain(box, F, CFG, S)
    n[F].inputs["Scatter Points"].default_value = 8
    n[F].inputs["Constraints"].default_value = False
    for name, value in (("End Frame", frames), ("Ground Plane", False), ("Gravity", (0.0, 0.0, 0.0)),
                        ("Linear Damping", 0.0), ("Angular Damping", 0.0)):
        n[S].inputs[name].default_value = value
    return box, mod, tree, n


def drift(ob):
    """How the pieces moved as a whole: where their centre of mass ends up relative to where it started, its
    acceleration over the last frames, the number of pieces, their total mass. (The pieces of a box touch
    each other, and light ones are pushed harder than heavy ones: they jostle. What the field does to all of
    them together does not depend on that.)"""
    pos, quat, piv, start = sim.read_cache(ob)
    mass = sim.rest_pieces(ob)[0].piece_volumes() * 100.0
    centre = (pos * mass[None, :, None]).sum(1) / mass.sum()
    steps = np.diff(centre, axis=0)
    fps = bpy.context.scene.render.fps
    accel = (steps[-1] - steps[-7]) / 6.0 * fps * fps
    return centre[-1] - centre[0], accel, len(mass), float(mass.sum())


if wanted("forces"):
    c = REP.case("forces")
    try:
        fps, frames, strength = 24.0, 24, 60.0
        box, mod, tree, n = floating_box(frames)
        field = wind(strength)
        res = sim.bake_many(bpy.context, [box])[0]
        d, accel, count, total = drift(box)
        # what Blender's rigid bodies do with a field: every body feels strength / frame rate newtons
        felt = float(accel[0]) * total / count
        c.set(pieces=res.pieces, fields=res.fields, force_felt_per_piece_n=round(felt, 4), strength_over_fps=round(strength / fps, 4),
              drift_m=[round(float(x), 4) for x in d])
        c.check("field_is_reported", res.fields == 1 and any("force field" in note for note in res.notes), res.notes)
        c.check("wind_pushes_along_its_direction", float(d[0]) > 0.05 and float(np.abs(d[1:]).max()) < 0.01 * float(d[0]),
                [round(float(x), 5) for x in d])
        c.check("force_is_strength_over_frame_rate", abs(felt / (strength / fps) - 1.0) < 0.02, round(felt / (strength / fps), 4))
        sim.free_cache(box)

        n[S].inputs["Field Weight"].default_value = 2.0
        sim.bake_many(bpy.context, [box])
        c.check("field_weight_scales_the_force", abs(float(drift(box)[0][0]) / float(d[0]) - 2.0) < 0.02,
                round(float(drift(box)[0][0]) / float(d[0]), 4))
        sim.free_cache(box)
        n[S].inputs["Field Weight"].default_value = 1.0

        n[S].inputs["Force Fields"].default_value = False
        off = sim.bake_many(bpy.context, [box])[0]
        c.check("force_fields_can_be_switched_off", off.fields == 0 and float(np.abs(drift(box)[0]).max()) < 1e-4,
                float(np.abs(drift(box)[0]).max()))
        sim.free_cache(box)
        n[S].inputs["Force Fields"].default_value = True

        # only the fields of one collection
        some = bpy.data.collections.new("Fields")
        bpy.context.scene.collection.children.link(some)
        n[S].inputs["Limit To"].default_value = some
        left_out = sim.bake_many(bpy.context, [box])[0]
        without = float(np.abs(drift(box)[0]).max())
        sim.free_cache(box)
        some.objects.link(field)
        inside = sim.bake_many(bpy.context, [box])[0]
        c.check("effector_collection_limits_the_fields", left_out.fields == 0 and without < 1e-4 and inside.fields == 1
                and abs(float(drift(box)[0][0]) / float(d[0]) - 1.0) < 0.01, [left_out.fields, without, inside.fields])
        sim.free_cache(box)
        n[S].inputs["Limit To"].default_value = None

        # ---- an initial velocity and a field at the same time: the two motions add up
        n[CFG].inputs["Set Initial Velocity"].default_value = True
        n[CFG].inputs["Velocity Type"].default_value = "Constant"
        n[CFG].inputs["Velocity"].default_value = (0.0, 0.0, 3.0)
        sim.bake_many(bpy.context, [box])
        both = drift(box)[0]
        sim.free_cache(box)
        n[S].inputs["Force Fields"].default_value = False
        sim.bake_many(bpy.context, [box])
        only_v = drift(box)[0]
        sim.free_cache(box)
        n[S].inputs["Force Fields"].default_value = True
        c.set(velocity_and_field_m=[round(float(x), 4) for x in both], velocity_only_m=[round(float(x), 4) for x in only_v],
              field_only_m=[round(float(x), 4) for x in d])
        # Upwards exactly what the velocity alone gives. Sideways what the wind alone gives in one frame less:
        # a piece with an initial velocity is moved by it for one frame before the solver, and the fields, take over.
        share = float(both[0]) / float(d[0])
        c.set(wind_share_with_velocity=round(share, 4))
        c.check("velocity_and_field_add_up", abs(float(only_v[2]) - 3.0 * (frames - 1) / fps) < 0.005
                and abs(float(both[2]) - float(only_v[2])) < 0.002 and abs(float(both[1])) < 0.002 and 0.90 < share < 0.94,
                [round(float(both[2] - only_v[2]), 5), round(share, 4)])
        n[CFG].inputs["Set Initial Velocity"].default_value = False

        # ---- a collider that is a force field as well pushes once, not twice
        colliders = bpy.data.collections.new("Colliders")
        bpy.context.scene.collection.children.link(colliders)
        plate = T.add_object("Plate", T.box("Plate", (0.5, 0.5, 0.1), (30.0, 0.0, 0.0)))
        bpy.context.scene.collection.objects.unlink(plate)
        colliders.objects.link(plate)
        bpy.context.view_layer.objects.active = plate
        plate.select_set(True)
        bpy.ops.object.forcefield_toggle()
        plate.select_set(False)
        plate.field.type, plate.field.strength, plate.field.flow = "WIND", strength, 0.0
        plate.rotation_euler = field.rotation_euler
        bpy.data.objects.remove(field)
        n[S].inputs["Collision Objects"].default_value = colliders
        sim.bake_many(bpy.context, [box])
        once = float(drift(box)[0][0]) / float(d[0])
        c.check("collider_with_a_field_pushes_once", abs(once - 1.0) < 0.02, round(once, 4))
        c.check("users_field_object_is_left_alone", plate.field.type == "WIND" and plate.rigid_body is None
                and [col.name for col in plate.users_collection] == ["Colliders"])
        sim.free_cache(box)

        # ---- Start Asleep: a field wakes the pieces (as it does with Blender's own rigid bodies)
        n[S].inputs["Start Asleep"].default_value = True
        asleep = sim.bake_many(bpy.context, [box])[0]
        c.set(moved_when_asleep_in_a_field=asleep.moved)
        c.check("a_field_wakes_sleeping_pieces", asleep.moved == asleep.pieces and any("wakes" in note for note in asleep.notes), asleep.moved)

        # ---- one piece alone: the force acts on its centre (it does not start to turn), and not before the
        # piece is handed to the solver (Set Activation)
        box, mod, tree, n = floating_box(frames)
        n[F].inputs["Scatter Points"].default_value = 1
        wind(strength)
        n[CFG].inputs["Set Activation"].default_value = True
        n[CFG].inputs["Activation Type"].default_value = "At Time"
        n[CFG].inputs["Delay"].default_value = 0.5                     # 12 frames
        alone = sim.bake_many(bpy.context, [box])[0]
        pos, quat, piv, start = sim.read_cache(box)
        x = pos[:, 0, 0] - piv[0, 0]
        turned = float(np.abs(quat[:, 0] - quat[0, 0]).max())
        steps = np.diff(x)
        felt = float((steps[-1] - steps[-5]) / 4.0 * fps * fps) * float(sim.rest_pieces(box)[0].piece_volumes()[0] * 100.0)
        c.set(single_piece_force_n=round(felt, 4), held_until_frame=int(np.argmax(np.abs(x) > 1e-7)) + 1)
        c.check("a_field_does_not_turn_a_piece", alone.pieces == 1 and turned < 1e-5 and abs(felt / (strength / fps) - 1.0) < 0.01,
                [alone.pieces, turned, round(felt, 4)])
        # held for 12 frames, then 12 frames in the wind from rest: 0.5 * a * t^2 = 0.5 * 0.025 * 0.25 = 3.1 mm.
        # (Before pieces were held as "not Dynamic", the force piled up while they were held: 9 to 70 mm.)
        c.check("a_held_piece_does_not_feel_the_field", float(np.abs(x[:12]).max()) < 1e-7 and 0.0028 < float(x[-1]) < 0.0034,
                [float(np.abs(x[:12]).max()), round(float(x[-1]), 5)])

        # ---- a spin without a velocity (the w attribute, written here by a plain Store Named Attribute node):
        # the piece turns in place at that rate
        box, mod, tree, n = floating_box(frames)
        n[F].inputs["Scatter Points"].default_value = 1
        n[S].inputs["Force Fields"].default_value = False
        store = tree.nodes.new("GeometryNodeStoreNamedAttribute")
        store.data_type, store.domain = "FLOAT_VECTOR", "POINT"
        store.inputs["Name"].default_value = "w"
        store.inputs["Value"].default_value = (0.0, 0.0, 2.0)
        tree.links.new(n[F].outputs["Geometry"], store.inputs["Geometry"])
        tree.links.new(store.outputs["Geometry"], n[CFG].inputs["Geometry"])
        sim.bake_many(bpy.context, [box])
        pos, quat, piv, start = sim.read_cache(box)
        dots = np.abs(np.sum(quat[10:20, 0] * quat[11:21, 0], axis=1))
        rate = float(np.mean(2.0 * np.arccos(np.clip(dots, 0.0, 1.0)))) * fps
        c.set(spin_only_rate_rad_s=round(rate, 4), spin_only_drift_m=round(float(np.abs(pos[-1, 0] - piv[0]).max()), 5))
        c.check("a_spin_without_a_velocity_is_given", abs(rate / 2.0 - 1.0) < 0.05 and float(np.abs(pos[-1, 0] - piv[0]).max()) < 1e-3,
                [round(rate, 4), float(np.abs(pos[-1, 0] - piv[0]).max())])
    except Exception:
        c.error()
    c.done()


if wanted("upgrade"):
    c = REP.case("upgrade")
    try:
        # a network as a user leaves it: values typed in, a selection wired in, baked
        fresh(30)
        wall = T.add_object("Wall", T.box("Wall", (4.0, 0.4, 2.0), (0.0, 0.0, 3.0)))
        mod, tree, n = chain(wall, F, CLU, CFG, S)
        sel = tree.nodes.new("GeometryNodeGroup")
        sel.node_tree = nodes_rbd.select()
        sel.inputs["Height"].default_value = 2.5
        tree.links.new(sel.outputs["Selection"], n[CFG].inputs["Selection"])
        n[F].inputs["Scatter Points"].default_value = 37
        n[F].inputs["Material Type"].default_value = "Wood"
        n[F].inputs["Impact Point"].default_value = (0.5, 0.0, 1.5)
        n[F].inputs["Detail"].default_value = True
        n[F].inputs["Inside Material"].default_value = bpy.data.materials.new("Inner")
        n[CLU].inputs["Size"].default_value = 0.77
        n[CFG].inputs["Set Active"].default_value = True
        n[CFG].inputs["Active"].default_value = False
        n[S].inputs["End Frame"].default_value = 30
        n[S].inputs["Bullet Substeps"].default_value = 7
        n[S].inputs["Gravity"].default_value = (0.0, 0.0, -4.0)
        res = sim.bake_many(bpy.context, [wall])[0]
        frame20 = None
        bpy.context.scene.frame_set(20)
        frame20 = core.EvalMesh(wall).co.copy()

        def state():
            values = {}
            for node in tree.nodes:
                for sock in node.inputs:
                    if node.bl_idname == "GeometryNodeGroup" and hasattr(sock, "default_value"):
                        v = sock.default_value
                        values[(node.name, sock.name)] = tuple(round(x, 6) for x in v) if hasattr(v, "__len__") and not isinstance(v, str) else v
            links = sorted((l.from_node.name, l.from_socket.name, l.to_node.name, l.to_socket.name) for l in tree.links)
            return values, links
        before_values, before_links = state()
        # every group as an older version would have left it: marked outdated, then brought up to date
        from Extension import nodekit, nodes_fracture, nodes_playback
        groups = [g for g in bpy.data.node_groups if g.get(nodekit.KIND_PROP)]
        for g in groups:
            g[nodekit.VERSION_PROP] = -1
        rebuilt = nodes_rbd.refresh()
        after_values, after_links = state()
        c.set(groups=len(groups), rebuilt=len(rebuilt), values=len(before_values), links=len(before_links))
        c.check("every_group_was_rebuilt", len(rebuilt) == len(groups) >= 7 and all(g.get(nodekit.VERSION_PROP, -1) > 0 for g in groups),
                [len(rebuilt), len(groups)])
        lost = {k: (v, after_values.get(k)) for k, v in before_values.items() if after_values.get(k) != v}
        c.check("typed_values_survive", not lost and len(before_values) > 60, list(lost.items())[:4])
        c.check("wires_survive", after_links == before_links and len(before_links) == 12,
                [len(before_links), len(after_links), [l for l in before_links if l not in after_links][:3]])
        bpy.context.scene.frame_set(20)
        c.check("bake_survives", bool(n[S].inputs["Baked"].default_value) and sim.is_baked(wall)
                and float(np.abs(core.EvalMesh(wall).co - frame20).max()) < 1e-6 and played(wall, 20) < 1e-4)
        again = sim.bake_many(bpy.context, [wall])[0]
        c.check("rebake_after_upgrade", again.pieces == res.pieces and again.anchored == res.anchored and again.frames == 30,
                [again.pieces, res.pieces, again.anchored, res.anchored])
        c.check("refresh_does_nothing_when_up_to_date", nodes_rbd.refresh() == [])
    except Exception:
        c.error()
    c.done()

REP.finish()
