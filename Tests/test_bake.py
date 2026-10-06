"""Headless checks of fracture -> bake -> cached playback, with hard pass/fail thresholds.

Scenarios: a glued wall hit by an animated ball, a ground slab cracking outward, an explosion,
piles of 500 pieces with and without glue, plus the state-handling cases a review asked for
(failed bake, re-bake, object moved after the bake, rename / duplicate, burst speed accuracy).
Run: blender --background --factory-startup --python-exit-code 1 --python Tests/test_bake.py -- <out_dir> [case ...]
"""
import os
import sys
import time

import bpy
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as T  # noqa: E402
from Extension import core, sim  # noqa: E402

args = sys.argv[sys.argv.index("--") + 1:]
OUT = args[0]
ONLY = set(args[1:])
REP = T.Report("test_bake", OUT, "BAKE")
S = sim.SimSettings


def wanted(name):
    return not ONLY or name in ONLY


def fresh(frame_end=100):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.frame_start, scene.frame_end = 1, frame_end
    return scene


def expected_world(ob, em_rest, k):
    """Where every rest vertex must be at cache frame k, straight from the cache arrays."""
    pos, quat, piv, _ = sim.read_cache(ob)
    return pos[k][em_rest.piece] + T.qrot(quat[k][em_rest.piece], em_rest.co - piv[em_rest.piece])


def playback_error(ob, em_rest, fractions=(0.0, 0.25, 0.5, 1.0)):
    pos, _, _, start = sim.read_cache(ob)
    f = pos.shape[0]
    worst = 0.0
    for frac in fractions:
        k = int(round(frac * (f - 1)))
        bpy.context.scene.frame_set(start + k)
        worst = max(worst, float(np.abs(core.EvalMesh(ob).co - expected_world(ob, em_rest, k)).max()))
    return worst


def scrub_ms(start, frames):
    scene = bpy.context.scene
    ts = []
    for k in range(frames):
        t = time.perf_counter()
        scene.frame_set(start + k)
        bpy.context.evaluated_depsgraph_get()
        ts.append(time.perf_counter() - t)
    return 1000 * sum(ts[1:]) / max(1, len(ts) - 1)


def leftovers(before, allow):
    """Datablocks that exist now but did not before, beyond what the bake is allowed to add."""
    after = T.datablock_counts()
    return {k: after[k] - before[k] - allow.get(k, 0) for k in after if after[k] - before[k] - allow.get(k, 0) != 0}


BAKE_ADDS = {"objects": 2, "meshes": 2, "node_groups": 1}   # cache + frozen pieces (+ the playback group, once)


def common_checks(c, ob, em_rest, res, before, max_speed):
    pos, quat, piv, start = sim.read_cache(ob)
    fps = bpy.context.scene.render.fps
    speed = np.linalg.norm(np.diff(pos, axis=0), axis=-1) * fps
    c.set(pieces=res.pieces, frames=res.frames, glue=res.glue, glue_separated=res.glue_separated,
          anchored=res.anchored, moved=res.moved, clusters=res.clusters, notes=res.notes,
          bake_s=round(res.seconds, 2), bake_ms_per_frame=round(1000 * res.seconds / res.frames, 1),
          max_speed_m_s=round(float(speed.max()), 2), final_mean_speed_m_s=round(float(speed[-1].mean()), 3),
          lowest_pivot_z=round(float(pos[..., 2].min()), 3), at_rest_at_end=int((speed[-1] < 0.05).sum()))
    c.check("nothing_left_behind", not leftovers(before, BAKE_ADDS), leftovers(before, BAKE_ADDS))
    c.check("finite", bool(np.isfinite(pos).all() and np.isfinite(quat).all()))
    c.check("unit_quaternions", float(np.abs(np.linalg.norm(quat, axis=-1) - 1.0).max()) < 1e-3)
    c.check("first_frame_is_rest", float(np.abs(pos[0] - piv).max()) < 1e-4, round(float(np.abs(pos[0] - piv).max()), 6))
    err = playback_error(ob, em_rest)
    c.set(playback_max_error_m=round(err, 6))
    c.check("playback_matches_cache", err < 1e-4, round(err, 6))
    ms = scrub_ms(start, min(res.frames, 60))
    c.set(scrub_ms_per_frame=round(ms, 2))
    c.check("scrub_is_cheap", ms < 5.0, round(ms, 2))
    c.check("no_runaway_speed", float(speed.max()) < max_speed, round(float(speed.max()), 2))
    c.check("stays_above_ground", float(pos[..., 2].min()) > -0.02, round(float(pos[..., 2].min()), 3))
    return pos, speed


def render_sheet(name, ob, stills, cam_target, cam_dist, cam_dir=(1.0, -1.3, 0.8)):
    T.add_piece_colors(ob)
    cam = T.setup_render()
    T.aim_camera(cam, cam_target, cam_dir, cam_dist)
    paths = []
    for f in stills:
        p = os.path.join(OUT, f"bake_{name}_f{f:03d}.png")
        T.render_still(p, f)
        paths.append(p)
    T.contact_sheet(paths, os.path.join(OUT, f"bake_{name}_sheet.png"))
    for p in paths:
        os.remove(p)
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(OUT, f"bake_{name}.blend"))


def add_ball(radius, start, end, frames):
    col = bpy.data.collections.new("Colliders")
    bpy.context.scene.collection.children.link(col)
    ball = bpy.data.objects.new("Ball", T.icosphere("Ball", radius))
    col.objects.link(ball)
    ball.location = start
    ball.keyframe_insert("location", frame=frames[0])
    ball.location = end
    ball.keyframe_insert("location", frame=frames[1])
    return col, ball


# ---------------------------------------------------------------- scenario: glued wall, hit by a ball
if wanted("wall"):
    c = REP.case("wall")
    try:
        fresh(100)
        wall = T.add_object("Wall", T.box("Wall", (6.0, 0.5, 3.0), (0.0, 0.0, 1.5)))
        T.add_fracture(wall, Pieces=200, Seed=2, Impact_Bias=0.5, Impact_Point=(0.0, 0.0, 1.6), Impact_Radius=1.5,
                       Detail_Level=1, Noise_Height=0.02)
        col, ball = add_ball(0.6, (0.0, -8.0, 1.6), (0.0, 8.0, 1.6), (1, 25))
        n_user_actions = len(bpy.data.actions)
        bpy.context.view_layer.update()
        em = core.EvalMesh(wall)
        before = T.datablock_counts()
        st = S(frame_end=100, anchor_bottom=True, glue_strength=4.0, glue_variation=0.3, collider_collection=col)
        res = sim.bake(bpy.context, wall, st)
        pos, speed = common_checks(c, wall, em, res, before, max_speed=60.0)
        c.check("glue_made", res.glue > res.pieces, res.glue)
        c.check("glue_partly_broken", 0 < res.glue_separated < res.glue, res.glue_separated)
        c.check("anchors_exist", res.anchored > 0, res.anchored)
        zmin = np.full(res.pieces, np.inf)
        np.minimum.at(zmin, em.piece, em.co[:, 2])
        anchored = zmin <= em.co[:, 2].min() + st.anchor_height
        c.check("anchors_never_move", float(np.abs(pos[:, anchored] - pos[0, anchored]).max()) < 1e-4)
        c.check("still_before_impact", float(speed[:5].max()) < 0.05, round(float(speed[:5].max()), 4))
        c.check("ball_not_touched", ball.rigid_body is None and len(bpy.data.actions) == n_user_actions)
        render_sheet("wall", wall, (1, 14, 30, 100), (0, 0, 1.4), 11.0)
    except Exception:
        c.error()
    c.done()

# ---------------------------------------------------------------- scenario: ground crack (radial wave + burst)
if wanted("ground_crack"):
    c = REP.case("ground_crack")
    try:
        fresh(90)
        slab = T.add_object("Ground", T.box("Ground", (8.0, 8.0, 0.3), (0.0, 0.0, 0.15)))
        T.add_fracture(slab, Pieces=150, Flat=True, Impact_Bias=0.55, Impact_Point=(0.0, 0.0, 0.15), Impact_Radius=2.5)
        bpy.context.view_layer.update()
        em = core.EvalMesh(slab)
        before = T.datablock_counts()
        st = S(frame_end=90, start_asleep=False, use_glue=False, activation="RADIAL",
               activation_origin=(0.0, 0.0, 0.15), activation_speed=8.0,
               burst_speed=7.0, burst_origin=(0.0, 0.0, -0.5), burst_radius=4.5, burst_up=0.75)
        res = sim.bake(bpy.context, slab, st)
        pos, speed = common_checks(c, slab, em, res, before, max_speed=7.0 * 1.3 * 1.5)
        # pieces near the centre must start moving before pieces far away
        dist = np.linalg.norm(pos[0, :, :2], axis=1)
        moving = speed > 0.3
        first = np.where(moving.any(0), moving.argmax(0), -1)
        ok = first >= 0
        corr = float(np.corrcoef(dist[ok], first[ok])[0, 1])
        c.set(wave_correlation=round(corr, 3))
        c.check("wave_spreads_outward", corr > 0.7, round(corr, 3))
        c.check("settles", float(speed[-1].mean()) < 0.3, round(float(speed[-1].mean()), 3))
        render_sheet("ground_crack", slab, (1, 12, 30, 90), (0, 0, 1.0), 17.0, (1.0, -1.2, 0.75))
    except Exception:
        c.error()
    c.done()

# ---------------------------------------------------------------- scenario: explosion (burst only)
if wanted("explosion"):
    c = REP.case("explosion")
    try:
        fresh(90)
        block = T.add_object("Block", T.box("Block", (2.0, 2.0, 2.0), (0.0, 0.0, 1.0)))
        T.add_fracture(block, Pieces=120, Seed=4, Detail_Level=2, Noise_Height=0.03)
        bpy.context.view_layer.update()
        em = core.EvalMesh(block)
        before = T.datablock_counts()
        st = S(frame_end=90, start_asleep=False, use_glue=False, burst_speed=9.0, burst_origin=(0.0, 0.0, 0.6), burst_up=0.25)
        res = sim.bake(bpy.context, block, st)
        pos, speed = common_checks(c, block, em, res, before, max_speed=9.0 * 1.3 * 1.6)
        c.check("everything_flies", res.moved == res.pieces, res.moved)
        spread = float(np.linalg.norm(pos[-1, :, :2], axis=1).max())
        c.check("debris_spreads", spread > 3.0, round(spread, 2))
        render_sheet("explosion", block, (1, 8, 20, 90), (0, 0, 1.5), 16.0)
    except Exception:
        c.error()
    c.done()

# ---------------------------------------------------------------- 500 pieces, loose and glued
for name, glued in (("pile500", False), ("glued500", True)):
    if not wanted(name):
        continue
    c = REP.case(name)
    try:
        fresh(100)
        block = T.add_object("Block", T.box("Block", (3.0, 3.0, 3.0), (0.0, 0.0, 2.5)))
        T.add_fracture(block, Pieces=500, Seed=9)
        bpy.context.view_layer.update()
        em = core.EvalMesh(block)
        if glued:
            col, ball = add_ball(0.8, (0.0, -9.0, 2.5), (0.0, 9.0, 2.5), (1, 30))
            st = S(frame_end=100, start_asleep=True, use_glue=True, glue_strength=3.0, cluster_pieces=8,
                   collider_collection=col)
        else:
            st = S(frame_end=100, start_asleep=False, use_glue=False)
        before = T.datablock_counts()
        res = sim.bake(bpy.context, block, st)
        pos, speed = common_checks(c, block, em, res, before, max_speed=60.0)
        c.check("piece_count", res.pieces >= 500, res.pieces)
        c.check("bake_time_ok", res.seconds < 120.0, round(res.seconds, 1))
        if glued:
            c.check("glue_made", res.glue > 1500, res.glue)
            c.check("clusters_made", res.clusters > 10, res.clusters)
            c.check("some_bonds_hold", res.glue_separated < res.glue, res.glue_separated)
        else:
            c.check("settles", int((speed[-1] < 0.05).sum()) > 0.9 * res.pieces)
        render_sheet(name, block, (1, 20, 45, 100), (0, 0, 1.2), 11.0)
    except Exception:
        c.error()
    c.done()

# ---------------------------------------------------------------- glue adjacency, checked a second way
if wanted("adjacency"):
    c = REP.case("adjacency")
    try:
        from mathutils import kdtree

        def reference(em):
            """Contact area of every pair of pieces, found without hashing: an exact proximity search
            for coincident vertices, then the hull area of what each pair shares (own implementation)."""
            kd = kdtree.KDTree(len(em.co))
            for i, p in enumerate(em.co):
                kd.insert(p, i)
            kd.balance()
            span = float(np.linalg.norm(em.co.max(0) - em.co.min(0)))
            shared = {}
            for i, p in enumerate(em.co):
                for _, j, _ in kd.find_range(p, span * 1e-4):
                    a, b = int(em.piece[i]), int(em.piece[j])
                    if a < b:
                        shared.setdefault((a, b), []).append(em.co[i])
            areas = {}
            for pair, pts in shared.items():
                p = np.array(pts, np.float64)
                if len(p) < 3:
                    continue
                q = p - p.mean(0)
                vt = np.linalg.svd(q, full_matrices=False)[2]
                xy = q @ vt[:2].T
                # area of the convex hull by gift wrapping (a different algorithm from the add-on's)
                start = int(np.argmin(xy[:, 0]))
                hull, cur = [], start
                for _ in range(len(xy) + 1):
                    hull.append(cur)
                    nxt = (cur + 1) % len(xy)
                    for k in range(len(xy)):
                        cr = np.cross(xy[nxt] - xy[cur], xy[k] - xy[cur])
                        if cr < -1e-14 or (abs(cr) <= 1e-14 and np.linalg.norm(xy[k] - xy[cur]) > np.linalg.norm(xy[nxt] - xy[cur])):
                            nxt = k
                    cur = nxt
                    if cur == start:
                        break
                hx, hy = xy[hull, 0], xy[hull, 1]
                areas[pair] = 0.5 * abs(float(np.dot(hx, np.roll(hy, -1)) - np.dot(hy, np.roll(hx, -1))))
            return areas

        report = {}
        for label, make, inputs in (("cube", lambda: T.box("Cube", (2.0, 2.0, 2.0)), dict(Pieces=60, Seed=1)),
                                    ("sphere", lambda: T.icosphere("Ball", 1.0, 3), dict(Pieces=50, Seed=3)),
                                    ("torus", lambda: T.torus("Torus"), dict(Pieces=40, Seed=1)),
                                    ("slab_flat", lambda: T.box("Slab", (4.0, 4.0, 0.2)), dict(Pieces=60, Flat=True)),
                                    ("cube_secondary", lambda: T.box("Cube2", (2.0, 2.0, 2.0)), dict(Pieces=30, Secondary_Ratio=0.5))):
            fresh(10)
            ob = T.add_object(label, make())
            T.add_fracture(ob, **inputs)
            bpy.context.view_layer.update()
            em = core.EvalMesh(ob)
            ours = {(a, b): area for a, b, _, area in sim.adjacency(em, em.n_pieces)}
            ref = reference(em)
            typical = float(np.median([v for v in ref.values() if v > 0]))
            # clear-cut contacts: well above / well below the sliver limit (the band in between may go either way)
            must = {p for p, v in ref.items() if v > 3 * sim.SLIVER * typical}
            must_not = {p for p, v in ref.items() if v < 0.3 * sim.SLIVER * typical}
            both = [p for p in ours if p in ref and ref[p] > 0]
            area_err = max(abs(ours[p] - ref[p]) / ref[p] for p in both) if both else 0.0
            report[label] = {"pieces": em.n_pieces, "bonds": len(ours), "reference_contacts": len(must),
                             "missed": len(must - set(ours)), "false": len(set(ours) & must_not) + len(set(ours) - set(ref)),
                             "max_area_error": round(float(area_err), 4)}
            c.check(f"{label}_no_real_contact_missed", not (must - set(ours)), sorted(must - set(ours))[:5])
            c.check(f"{label}_no_false_bond", not (set(ours) & must_not) and not (set(ours) - set(ref)),
                    sorted((set(ours) & must_not) | (set(ours) - set(ref)))[:5])
            c.check(f"{label}_contact_areas_agree", area_err < 0.02, round(float(area_err), 4))
            degree = np.bincount(np.array(sorted(ours)).reshape(-1), minlength=em.n_pieces)
            c.check(f"{label}_every_piece_has_a_neighbour", int(degree.min()) >= 1, int(degree.min()))
        c.set(shapes=report)
    except Exception:
        c.error()
    c.done()

# ---------------------------------------------------------------- the glue preview shows what the bake uses
if wanted("glue_preview"):
    c = REP.case("glue_preview")
    try:
        fresh(40)
        ob = T.add_object("Wall", T.box("Wall", (4.0, 0.4, 2.0), (0.0, 0.0, 1.0)))
        T.add_fracture(ob, Pieces=80, Seed=5)
        st = S(frame_end=40, glue_strength=3.0, glue_variation=0.4, cluster_pieces=6, seed=11)
        bpy.context.view_layer.update()
        preview, plan = sim.build_glue_preview(bpy.context, ob, st)
        strength = np.empty(len(preview.data.edges), np.float32)
        preview.data.attributes["strength"].data.foreach_get("value", strength)
        c.set(bonds=len(plan.pairs), clusters=plan.n_clusters, strength_range=[round(float(strength.min()), 2), round(float(strength.max()), 2)])
        c.check("one_edge_per_bond", len(preview.data.edges) == len(plan.pairs) > 100 and len(preview.data.vertices) >= 80)
        c.check("clusters_shown", plan.n_clusters > 5 and len(set(plan.cluster_of.tolist())) == plan.n_clusters)
        c.check("cluster_bonds_are_stronger", float(strength.max()) > 5 * float(np.median(strength[strength < 3.0 * 2.5 * 1.4 + 1e-6])))
        again = sim.glue_plan(sim.rest_pieces(ob)[0], sim.rest_pieces(ob)[0].piece_centroids(sim.rest_pieces(ob)[0].proxy_co), st)
        c.check("plan_is_reproducible", np.allclose(again.strength, plan.strength) and [p[:2] for p in again.pairs] == [p[:2] for p in plan.pairs])
        res = sim.bake(bpy.context, ob, st)
        c.check("bake_uses_the_same_plan", res.glue == len(plan.pairs) and res.clusters == plan.n_clusters, [res.glue, res.clusters])
        c.check("preview_survives_bake", ob.get(sim.REF_GLUE) == preview and preview.name in bpy.data.objects)
        sim.free_cache(ob)
        c.check("preview_survives_free", ob.get(sim.REF_GLUE) == preview)
        sim.remove_glue_preview(ob)
        c.check("preview_removed", sim.REF_GLUE not in ob and not [o for o in bpy.data.objects if o.name.startswith("RBD ")]
                and not [m for m in bpy.data.meshes if m.name.startswith("RBD ")])
        none_preview, none_plan = sim.build_glue_preview(bpy.context, ob, S(use_glue=False))
        c.check("no_glue_no_preview", none_preview is None and not none_plan.pairs)

        def previews():
            return [o for o in bpy.data.objects if o.get(sim.GLUE_MARK)]

        # the lines follow the object
        preview, _ = sim.build_glue_preview(bpy.context, ob, st)
        bpy.context.view_layer.update()
        before = preview.matrix_world @ preview.data.vertices[0].co
        ob.location.x += 2.5
        bpy.context.view_layer.update()
        after = preview.matrix_world @ preview.data.vertices[0].co
        c.check("preview_follows_the_object", abs((after - before).x - 2.5) < 1e-5 and abs((after - before).y) < 1e-6,
                [round(v, 4) for v in (after - before)])
        # drawing again replaces the old lines instead of piling them up
        again, _ = sim.build_glue_preview(bpy.context, ob, st)
        c.check("update_replaces", previews() == [again] and ob.get(sim.REF_GLUE) == again, len(previews()))
        # a duplicate of the object shows the same lines: removing them on one must not take them from the other
        twin = ob.copy()
        bpy.context.scene.collection.objects.link(twin)
        sim.remove_glue_preview(ob)
        c.check("duplicate_keeps_its_preview", previews() == [again] and twin.get(sim.REF_GLUE) == again and sim.REF_GLUE not in ob)
        own, _ = sim.build_glue_preview(bpy.context, ob, st)
        c.check("each_object_its_own", len(previews()) == 2 and ob.get(sim.REF_GLUE) == own and twin.get(sim.REF_GLUE) == again)
        # the lines of a deleted object go with the next preview action
        bpy.data.objects.remove(twin)
        sim.remove_glue_preview(ob)
        c.check("deleted_object_leaves_no_lines", previews() == [] and not [m for m in bpy.data.meshes if m.name.startswith(sim.GLUE_PREFIX)],
                [o.name for o in previews()])
        # pushed apart for inspection, the pieces share no corners any more: preview and bake still see them together
        frac_wall = core.find_modifier(ob, core.KIND_FRACTURE)
        core.set_input(frac_wall, "Exploded View", 0.5)
        bpy.context.view_layer.update()
        apart, apart_plan = sim.build_glue_preview(bpy.context, ob, st)
        c.check("exploded_view_does_not_change_the_glue", len(apart_plan.pairs) == len(plan.pairs)
                and abs(core.get_input(frac_wall, "Exploded View") - 0.5) < 1e-6, [len(apart_plan.pairs), len(plan.pairs)])
        res = sim.bake(bpy.context, ob, st)
        c.check("exploded_view_does_not_change_the_bake", res.glue == len(plan.pairs) and not any("deformed" in n for n in res.notes),
                [res.glue, res.notes])
        sim.free_cache(ob)
        core.set_input(frac_wall, "Exploded View", 0.0)
        bpy.context.view_layer.update()
        sim.remove_glue_preview(ob)

        # a failed update keeps what was shown
        shown, _ = sim.build_glue_preview(bpy.context, ob, st)
        real_plan = sim.glue_plan
        sim.glue_plan = lambda *a: (_ for _ in ()).throw(RuntimeError("injected"))
        try:
            sim.build_glue_preview(bpy.context, ob, st)
            failed_quietly = True
        except RuntimeError:
            failed_quietly = False
        finally:
            sim.glue_plan = real_plan
        c.check("failed_update_keeps_the_old_lines", not failed_quietly and previews() == [shown] and ob.get(sim.REF_GLUE) == shown)
        # with a deformer after the fracture the preview uses the deformed shape, exactly like the bake
        sim.remove_glue_preview(ob)
        bend = ob.modifiers.new("Bend", "SIMPLE_DEFORM")
        bend.deform_method, bend.deform_axis, bend.angle = "BEND", "Y", 0.6
        bpy.context.view_layer.update()
        bent, bent_plan = sim.build_glue_preview(bpy.context, ob, st)
        res = sim.bake(bpy.context, ob, st)
        pos, _, piv, _ = sim.read_cache(ob)
        lines = np.array([bent.matrix_world @ v.co for v in bent.data.vertices], np.float32)
        c.check("preview_matches_bake_when_deformed", res.glue == len(bent_plan.pairs) and any("deformed" in n for n in res.notes)
                and float(np.abs(lines - piv).max()) < 1e-4, [res.glue, len(bent_plan.pairs), round(float(np.abs(lines - piv).max()), 6)])
        sim.free_cache(ob)
        sim.remove_glue_preview(ob)
    except Exception:
        c.error()
    c.done()

# ---------------------------------------------------------------- crack events
if wanted("events"):
    c = REP.case("events")
    try:
        from mathutils import Quaternion, Vector
        fresh(60)
        ob = T.add_object("Wall", T.box("Wall", (4.0, 0.4, 2.0), (0.0, 0.0, 1.0)))
        T.add_fracture(ob, Pieces=60, Seed=3)
        bpy.context.view_layer.update()
        res = sim.bake(bpy.context, ob, S(frame_end=40, glue_strength=1e6, anchor_bottom=True))
        c.check("still_wall_has_no_cracks", res.events == 0 and len(sim.read_events(ob)) == 0 and res.moved == 0,
                [res.events, res.moved])

        def reference(ob):
            """The same definition, written out pair by pair with mathutils instead of numpy."""
            pos, quat, piv, _ = sim.read_cache(ob)
            em = sim.rest_pieces(ob)[0]
            found = []
            for a, b, point, area in sim.adjacency(em, em.n_pieces):
                tol = max(0.05 * area ** 0.5, 0.002)
                mids, gaps = [], []
                for k in range(len(pos)):
                    pa = Vector(pos[k, a]) + Quaternion(quat[k, a]) @ (Vector(point) - Vector(piv[a]))
                    pb = Vector(pos[k, b]) + Quaternion(quat[k, b]) @ (Vector(point) - Vector(piv[b]))
                    mids.append((pa + pb) / 2)
                    gaps.append((pa - pb).length)
                if gaps[-1] > tol:
                    k = len(gaps) - 1
                    while k > 1 and gaps[k - 1] > tol:
                        k -= 1
                    found.append((k, *mids[k], area ** 0.5))
            found.sort(key=lambda e: e[0])
            return np.array(found, np.float32).reshape(-1, 5), pos

        st = S(frame_end=60, glue_strength=2.0, anchor_bottom=True, burst_speed=5.0, burst_origin=(0.0, -0.5, 1.0),
               burst_radius=1.8, seed=4)
        res = sim.bake(bpy.context, ob, st)
        ev = sim.read_events(ob)
        ref, pos = reference(ob)
        c.set(glue=res.glue, glue_separated=res.glue_separated, cracks=res.events,
              first_and_last_frame=[int(ev[:, 0].min()), int(ev[:, 0].max())] if len(ev) else None)
        c.check("blast_opens_cracks", res.events == len(ev) > 30 and res.events < res.glue, [res.events, res.glue])
        c.check("count_matches_reference", len(ev) == len(ref), [len(ev), len(ref)])
        if len(ev) == len(ref):
            c.check("frames_match_reference", bool((ev[:, 0] == ref[:, 0]).all()))
            c.check("places_match_reference", float(np.abs(ev[:, 1:4] - ref[:, 1:4]).max()) < 1e-4,
                    round(float(np.abs(ev[:, 1:4] - ref[:, 1:4]).max()), 6))
            c.check("sizes_match_reference", float(np.abs(ev[:, 4] - ref[:, 4]).max()) < 1e-5)
        c.check("sorted_and_in_range", bool((np.diff(ev[:, 0]) >= 0).all()) and ev[:, 0].min() >= 1 and ev[:, 0].max() <= len(pos) - 1)
        lo, hi = pos.reshape(-1, 3).min(0) - 1.0, pos.reshape(-1, 3).max(0) + 1.0
        c.check("inside_the_scene", bool((ev[:, 1:4] >= lo).all() and (ev[:, 1:4] <= hi).all()))
        c.check("opening_speed_positive", bool((ev[:, 5] > 0).all()), round(float(ev[:, 5].min()), 4))
        # worked out a few pairs at a time (as for very long bakes) the answer is the same
        em_ev = sim.rest_pieces(ob)[0]
        contacts = sim.adjacency(em_ev, em_ev.n_pieces)
        whole = sim.crack_events(pos, sim.read_cache(ob)[1], sim.read_cache(ob)[2], contacts, 24.0)
        chunk = sim.EVENT_CHUNK
        sim.EVENT_CHUNK = 7 * len(pos)
        try:
            pieces_at_a_time = sim.crack_events(pos, sim.read_cache(ob)[1], sim.read_cache(ob)[2], contacts, 24.0)
        finally:
            sim.EVENT_CHUNK = chunk
        c.check("chunked_events_identical", len(contacts) > 100 and np.array_equal(whole, pieces_at_a_time)
                and np.array_equal(whole[:, :5], ev[:, :5]), [len(contacts), len(whole), len(pieces_at_a_time)])
        # the blast is at the wall's centre: the cracks of the first moving frame are closer to it than the late ones
        d = np.linalg.norm(ev[:, 1:4] - np.array(st.burst_origin, np.float32), axis=1)
        early = ev[:, 0] <= ev[:, 0].min() + 1
        if early.all() or not early.any():
            c.check("early_cracks_near_blast", False, "every crack is on the same frame")
        else:
            c.check("early_cracks_near_blast", float(d[early].mean()) < float(d[~early].mean()),
                    [round(float(d[early].mean()), 2), round(float(d[~early].mean()), 2)])

        # without glue the neighbours are still known, so cracks are still reported
        res = sim.bake(bpy.context, ob, S(frame_end=40, use_glue=False, start_asleep=False, burst_speed=4.0,
                                          burst_origin=(0.0, 0.0, 1.0)))
        ev2 = sim.read_events(ob)
        ref2, _ = reference(ob)
        c.set(cracks_without_glue=res.events)
        c.check("unglued_reports_cracks", res.glue == 0 and res.events == len(ev2) == len(ref2) > 100, [res.glue, res.events, len(ref2)])
        c.check("rebake_replaces_events", len(ev2) != len(ev) or not np.array_equal(ev2, ev))
        sim.free_cache(ob)
        c.check("free_drops_events", sim.read_events(ob) is None)
    except Exception:
        c.error()
    c.done()

# ---------------------------------------------------------------- loose parts as pieces, painted anchors
if wanted("parts_and_anchor"):
    c = REP.case("parts_and_anchor")
    try:
        import bmesh

        def brick_wall(cols=5, rows=4, size=(0.4, 0.2, 0.2), base=1.0):
            """Bricks in a plain grid, touching: one mesh, every brick its own island."""
            bm = bmesh.new()
            for i in range(cols):
                for j in range(rows):
                    made = bmesh.ops.create_cube(bm, size=1.0)["verts"]
                    for v in made:
                        v.co.x = (v.co.x + 0.5 + i) * size[0] - cols * size[0] / 2
                        v.co.y = v.co.y * size[1]
                        v.co.z = (v.co.z + 0.5 + j) * size[2] + base
            me = bpy.data.meshes.new("Bricks")
            bm.to_mesh(me)
            bm.free()
            return me

        fresh(40)
        ob = T.add_object("Bricks", brick_wall())
        n_verts = len(ob.data.vertices)
        before_co = np.array([v.co[:] for v in ob.data.vertices], np.float32)
        mod = T.add_fracture(ob, Use_Loose_Parts=True, Pieces=50, Detail_Level=2, Noise_Height=0.05)
        bpy.context.view_layer.update()
        em = core.EvalMesh(ob)
        c.set(bricks=em.n_pieces, verts=len(em.co))
        c.check("no_node_warnings", len(mod.node_warnings) == 0, [w.message for w in mod.node_warnings][:3])
        c.check("one_piece_per_brick", em.n_pieces == 20 and em.has_pieces, em.n_pieces)
        c.check("nothing_is_cut", len(em.co) == n_verts and int(em.inside.sum()) == 0
                and float(np.abs(np.sort(em.co, axis=0) - np.sort(before_co, axis=0)).max()) < 1e-6, len(em.co))
        vols = em.piece_volumes()
        c.check("brick_volumes", float(np.abs(vols - 0.4 * 0.2 * 0.2).max()) < 1e-6, [round(float(vols.min()), 5), round(float(vols.max()), 5)])
        pairs = sim.adjacency(em, em.n_pieces)
        areas = sorted({round(p[3], 4) for p in pairs})
        c.set(touching_pairs=len(pairs), contact_areas=areas)
        # 4 rows x 4 side-by-side pairs + 3 x 5 stacked pairs; side faces are 0.2 x 0.2, top faces 0.4 x 0.2
        c.check("bricks_that_share_a_face_are_neighbours", len(pairs) == 31 and areas == [0.04, 0.08], [len(pairs), areas])
        counts = T.datablock_counts()
        res = sim.bake(bpy.context, ob, S(frame_end=40, use_glue=True, glue_strength=1e6, anchor_bottom=True, anchor_height=0.01))
        c.check("glued_bricks_hold", res.pieces == 20 and res.glue == 31 and res.anchored == 5 and res.moved == 0,
                [res.pieces, res.glue, res.anchored, res.moved])
        res = sim.bake(bpy.context, ob, S(frame_end=40, use_glue=False, start_asleep=False))
        pos, _, piv, _ = sim.read_cache(ob)
        c.check("loose_bricks_fall", res.moved == 20 and float(pos[-1, :, 2].max()) < float(piv[:, 2].max()) - 0.5, res.moved)
        c.check("playback_of_parts", playback_error(ob, sim.rest_pieces(ob)[0]) < 1e-4)
        sim.free_cache(ob)

        # ---- bricks laid in a running bond (every other row shifted by half a brick): no corner of a brick
        # coincides with a corner of the row above, the faces only overlap
        bond = T.add_object("Running Bond", brick_wall())
        for v in bond.data.vertices:
            if (v.index // 8) % 4 % 2 == 1:
                v.co.x += 0.2
        T.add_fracture(bond, Use_Loose_Parts=True)
        bpy.context.view_layer.update()
        em_bond = core.EvalMesh(bond)
        pairs = sim.adjacency(em_bond, em_bond.n_pieces)
        areas = sorted({round(p[3], 4) for p in pairs})
        # 4 rows x 4 side-by-side pairs, and between two rows every brick lies on two bricks (5 + 4 overlaps),
        # each overlap half a brick long: 0.2 x 0.2
        c.set(running_bond_pairs=len(pairs), running_bond_areas=areas)
        c.check("overlapping_faces_are_neighbours", len(pairs) == 16 + 3 * 9 and areas == [0.04], [len(pairs), areas])
        centre = em_bond.vertex_means()
        c.check("contact_points_lie_between_the_bricks",
                all(abs(np.linalg.norm(p[2] - centre[p[0]]) - np.linalg.norm(p[2] - centre[p[1]])) < 1e-4 for p in pairs))
        res = sim.bake(bpy.context, bond, S(frame_end=30, glue_strength=1e6, anchor_bottom=True, anchor_height=0.01))
        c.check("running_bond_holds_when_glued", res.glue == 43 and res.moved == 0 and res.events == 0, [res.glue, res.moved, res.events])
        res = sim.bake(bpy.context, bond, S(frame_end=30, use_glue=False, start_asleep=False, burst_speed=4.0,
                                            burst_origin=(0.0, -1.0, 1.4)))
        c.check("running_bond_reports_cracks", res.glue == 0 and res.events > 30, res.events)
        sim.free_cache(bond)
        bpy.data.objects.remove(bond)

        # ---- bricks with mortar gaps (every brick shrunk by 2 %: 8 mm between neighbours side by side, 4 mm
        # between rows): not touching at the default, touching when the distance is raised
        gaps = T.add_object("Gaps", brick_wall())
        for k in range(len(gaps.data.vertices) // 8):
            vs = gaps.data.vertices[8 * k:8 * k + 8]
            centre = sum((v.co for v in vs), vs[0].co * 0.0) / 8
            for v in vs:
                v.co = centre + (v.co - centre) * 0.98
        T.add_fracture(gaps, Use_Loose_Parts=True)
        bpy.context.view_layer.update()
        em_gaps = core.EvalMesh(gaps)
        near = len(sim.adjacency(em_gaps, em_gaps.n_pieces, 0.002))
        rows_only = len(sim.adjacency(em_gaps, em_gaps.n_pieces, 0.005))
        far = len(sim.adjacency(em_gaps, em_gaps.n_pieces, 0.01))
        c.set(pairs_at_2mm_5mm_10mm=[near, rows_only, far])
        c.check("touch_distance_decides", near == 0 and rows_only == 15 and far == 31, [near, rows_only, far])
        res = sim.bake(bpy.context, gaps, S(frame_end=10, glue_distance=0.01, glue_strength=1e6, anchor_bottom=True, anchor_height=0.01))
        c.check("touch_distance_reaches_the_bake", res.glue == 31, res.glue)
        sim.free_cache(gaps)
        bpy.data.objects.remove(gaps)

        # ---- painted anchors on the bricks: the two left columns are painted (8 vertices per brick, 4 bricks
        # per column). The painted bricks touch unpainted ones: those must not pick up the paint.
        vg = ob.vertex_groups.new(name="Pin")
        for v in ob.data.vertices:
            vg.add([v.index], 1.0 if v.index // 8 // 4 < 2 else 0.0, "REPLACE")
        bpy.context.view_layer.update()
        c.check("no_group_no_attribute", core.EvalMesh(ob).anchor is None)
        core.set_input(mod, "Anchor Group", "Pin")
        bpy.context.view_layer.update()
        em = core.EvalMesh(ob)
        mean = np.bincount(em.piece, weights=em.anchor, minlength=20) / np.bincount(em.piece, minlength=20)
        left = em.vertex_means()[:, 0] < -0.2
        c.check("weights_reach_the_pieces", em.anchor is not None and bool(((mean >= 0.5) == left).all()) and int(left.sum()) == 8,
                [int((mean >= 0.5).sum()), int(left.sum())])
        res = sim.bake(bpy.context, ob, S(frame_end=40, use_glue=False, start_asleep=False))
        pos, quat, piv, _ = sim.read_cache(ob)
        travel = np.linalg.norm(pos - piv[None], axis=-1).max(0)
        c.set(painted=int(left.sum()), anchored=res.anchored, moved=res.moved)
        c.check("painted_bricks_stay", res.anchored == 8 and float(travel[left].max()) == 0.0, [res.anchored, float(travel[left].max())])
        c.check("unpainted_bricks_fall", res.moved == 12 and float(travel[~left].min()) > 0.3, [res.moved, round(float(travel[~left].min()), 3)])
        sim.free_cache(ob)
        core.set_input(mod, "Anchor Group", "No Such Group")
        bpy.context.view_layer.update()
        res = sim.bake(bpy.context, ob, S(frame_end=20, use_glue=False, start_asleep=False))
        c.check("empty_group_is_reported", res.anchored == 0 and any("anchor group" in note for note in res.notes), res.notes)
        sim.free_cache(ob)

        # ---- painted anchors through a real cut: the left end of a beam is painted
        fresh(40)
        beam = T.add_object("Beam", T.box("Beam", (4.0, 0.5, 0.5), (0.0, 0.0, 2.0)))
        vg = beam.vertex_groups.new(name="Wall End")
        for v in beam.data.vertices:
            vg.add([v.index], 1.0 if v.co.x < 0.0 else 0.0, "REPLACE")
        T.add_fracture(beam, Pieces=40, Seed=2, Anchor_Group="Wall End")
        bpy.context.view_layer.update()
        em = core.EvalMesh(beam)
        # the weight of a box painted on one end is a straight ramp along x. Vertices on the long sides
        # must have exactly that; vertices inside take the nearest surface point, which near an end is the
        # end cap (weight 0 or 1): at most a quarter of the beam's thickness off the ramp.
        # A piece carries one value: the average over its corners. Every corner on the long sides has
        # exactly the ramp; a corner inside takes the nearest surface point, which near an end is the
        # end cap (0 or 1), at most a quarter of the beam's thickness off the ramp.
        ramp = np.clip(0.5 - em.co[:, 0] / 4.0, 0.0, 1.0)
        n_beam = em.n_pieces
        per_piece = np.bincount(em.piece, weights=ramp, minlength=n_beam) / np.bincount(em.piece, minlength=n_beam)
        lo = np.full(n_beam, np.inf)
        hi = np.full(n_beam, -np.inf)
        np.minimum.at(lo, em.piece, em.anchor)
        np.maximum.at(hi, em.piece, em.anchor)
        c.check("one_weight_per_piece", float((hi - lo).max()) < 1e-6, round(float((hi - lo).max()), 7))
        c.check("weights_follow_the_paint", float(np.abs(lo - per_piece).max()) < 0.25 / 4.0 + 1e-4,
                round(float(np.abs(lo - per_piece).max()), 4))
        # subdividing and roughening the cut faces adds many vertices to them: the decision must not move
        flat_choice = lo >= 0.5
        frac_beam = core.find_modifier(beam, core.KIND_FRACTURE)
        core.set_input(frac_beam, "Detail Level", 2)
        core.set_input(frac_beam, "Noise Height", 0.02)
        bpy.context.view_layer.update()
        em_detail = core.EvalMesh(beam)
        fine = np.bincount(em_detail.piece, weights=em_detail.anchor, minlength=n_beam) / np.bincount(em_detail.piece, minlength=n_beam)
        c.set(beam_vertices=[len(em.co), len(em_detail.co)])
        c.check("detail_does_not_move_the_anchors", len(em_detail.co) > 3 * len(em.co) and em_detail.n_pieces == n_beam
                and bool(((fine >= 0.5) == flat_choice).all()) and float(np.abs(fine - lo).max()) < 1e-5,
                [len(em_detail.co), round(float(np.abs(fine - lo).max()), 6)])
        core.set_input(frac_beam, "Detail Level", 0)
        bpy.context.view_layer.update()
        res = sim.bake(bpy.context, beam, S(frame_end=40, use_glue=False, start_asleep=False))
        pos, _, piv, _ = sim.read_cache(beam)
        travel = np.linalg.norm(pos - piv[None], axis=-1).max(0)
        stays = travel == 0.0
        c.set(beam_pieces=res.pieces, beam_anchored=res.anchored)
        c.check("half_the_beam_stays", res.anchored == int(stays.sum()) and 0.3 * res.pieces < res.anchored < 0.7 * res.pieces,
                [res.anchored, res.pieces])
        c.check("the_painted_half", float(piv[stays, 0].max()) < 0.35 and float(piv[~stays, 0].min()) > -0.35,
                [round(float(piv[stays, 0].max()), 3), round(float(piv[~stays, 0].min()), 3)])
        c.check("frozen_pieces_keep_the_weights", sim.rest_pieces(beam)[0].anchor is not None)
    except Exception:
        c.error()
    c.done()

# ---------------------------------------------------------------- colliders that change shape
if wanted("deforming_colliders"):
    c = REP.case("deforming_colliders")
    try:
        def pile(name, x):
            ob = T.add_object(name, T.box(name, (0.6, 0.6, 0.6), (x, 0.0, 0.3)))
            T.add_fracture(ob, Pieces=12, Seed=1)
            return ob

        # 1. a shape key pushes one face of a block through the pile: the object itself never moves
        scene = fresh(40)
        target = pile("Pile", 0.0)
        col = bpy.data.collections.new("Colliders")
        scene.collection.children.link(col)
        piston = bpy.data.objects.new("Piston", T.box("Piston", (0.5, 1.2, 1.2), (-1.5, 0.0, 0.6)))
        col.objects.link(piston)
        piston.shape_key_add(name="Basis")
        key = piston.shape_key_add(name="Push")
        for i, v in enumerate(piston.data.vertices):
            if v.co.x > -1.4:
                key.data[i].co.x += 1.6          # the front face travels from x = -1.25 to x = 0.35
        key.value = 0.0
        key.keyframe_insert("value", frame=5)
        key.value = 1.0
        key.keyframe_insert("value", frame=20)
        bpy.context.view_layer.update()
        st = S(frame_end=40, use_glue=False, collider_collection=col)
        res = sim.bake(bpy.context, target, st)
        pos, _, piv, _ = sim.read_cache(target)
        push = np.sort(pos[-1, :, 0] - piv[:, 0])
        c.set(shape_key_push_m=[round(float(x), 2) for x in push], moved=res.moved)
        # measured: 11 of 12 pieces are pushed ahead (2.6 to 4.3 m; a rigid piston doing the same gives 2.0 to 3.5 m),
        # one slips through the jumping surface. So: it works, roughly, and the bake says so.
        c.check("shape_key_collider_pushes", res.moved == res.pieces and int((push > 1.0).sum()) >= 10 and float(push.max()) < 8.0,
                [res.moved, int((push > 1.0).sum()), round(float(push.max()), 2)])
        c.check("deforming_collider_is_reported", any("change shape" in note and "Piston" in note for note in res.notes), res.notes)
        # a collider that only has a mesh-building modifier, or only a Basis shape key, keeps its shape
        steady = bpy.data.objects.new("Steady", T.icosphere("Steady", 0.3))
        steady.modifiers.new("Subdivision", "SUBSURF")
        steady.shape_key_add(name="Basis")
        off = bpy.data.objects.new("Switched Off", T.icosphere("Switched Off", 0.3))
        off.modifiers.new("Wave", "WAVE").show_viewport = False
        waving = bpy.data.objects.new("Waving", T.icosphere("Waving", 0.3))
        waving.modifiers.new("Wave", "WAVE")
        c.check("only_real_deformers_count", not sim._changes_shape(steady) and not sim._changes_shape(off)
                and sim._changes_shape(waving) and sim._changes_shape(piston),
                [sim._changes_shape(o) for o in (steady, off, waving, piston)])
        c.check("user_collider_untouched", piston.rigid_body is None and piston.data.shape_keys.key_blocks["Push"].value == 1.0)

        # 2. layered simulations: the debris of one baked object hits the next one
        scene = fresh(50)
        thrown = pile("Thrown", -2.0)
        thrown.location.z = 0.2
        target = pile("Target", 0.0)
        bpy.context.view_layer.update()
        res_a = sim.bake(bpy.context, thrown, S(frame_end=50, use_glue=False, start_asleep=False, burst_speed=6.0,
                                                burst_origin=(-3.0, 0.0, 0.3), burst_up=0.15, burst_spin=0.0))
        col = bpy.data.collections.new("Colliders")
        scene.collection.children.link(col)
        alone = sim.bake(bpy.context, target, S(frame_end=50, use_glue=False, collider_collection=col))
        col.objects.link(thrown)
        scene.collection.objects.unlink(thrown) if thrown.name in scene.collection.objects else None
        hit = sim.bake(bpy.context, target, S(frame_end=50, use_glue=False, collider_collection=col))
        pos, _, piv, _ = sim.read_cache(target)
        c.set(thrown_moved=res_a.moved, target_moved_alone=alone.moved, target_moved_when_hit=hit.moved,
              target_push_m=round(float((pos[-1, :, 0] - piv[:, 0]).max()), 3))
        # Measured, not promised: in fresh files this collider is not felt at all in 1 to 4 bakes out of 12
        # (and when it is, the target is thrown about 19 m: see the piston above). So the only things
        # checked are that the bake goes through, says so, and leaves the collider alone. The numbers
        # above are in the report for whoever reads it; baking the two together is the supported way.
        c.check("baked_object_as_collider_is_reported", alone.moved == 0 and hit.pieces == 12
                and any("not a reliable collider" in note and "Thrown" in note for note in hit.notes), hit.notes)
        c.check("collider_bake_untouched", sim.is_baked(thrown) and thrown.rigid_body is None)
    except Exception:
        c.error()
    c.done()

# ---------------------------------------------------------------- several objects in one simulation
if wanted("together"):
    c = REP.case("together")
    try:
        def scene_with_two():
            fresh(50)
            thrown = T.add_object("Thrown", T.box("Thrown", (0.6, 0.6, 0.6), (-2.0, 0.0, 0.5)))
            T.add_fracture(thrown, Pieces=14, Seed=1)
            wall = T.add_object("Wall", T.box("Wall", (0.4, 2.0, 1.6), (0.0, 0.0, 0.8)))
            T.add_fracture(wall, Pieces=40, Seed=2)
            bpy.context.view_layer.update()
            return thrown, wall

        # the block is thrown at the wall; glue only matters for the wall (the block's bonds break in the blast)
        # the blast reaches the block (0.9 to 1.5 m away) but not the wall (3 m away)
        st = S(frame_end=50, glue_strength=0.6, burst_speed=16.0, burst_origin=(-3.2, 0.0, 0.5), burst_radius=2.6,
               burst_up=0.1, burst_spin=2.0, burst_variation=0.3)
        thrown, wall = scene_with_two()
        alone = sim.bake(bpy.context, wall, st)
        c.check("wall_alone_stands", alone.moved == 0 and alone.events == 0, [alone.moved, alone.events])
        sim.free_cache(wall)
        counts = T.datablock_counts()
        res_t, res_w = sim.bake_many(bpy.context, [thrown, wall], st)
        c.set(thrown_pieces=res_t.pieces, wall_pieces=res_w.pieces, wall_moved=res_w.moved, wall_cracks=res_w.events,
              wall_glue=res_w.glue, seconds=round(res_w.seconds, 2))
        added = {k: T.datablock_counts()[k] - counts[k] for k in counts if T.datablock_counts()[k] != counts[k]}
        c.check("one_cache_per_object", sim.is_baked(thrown) and sim.is_baked(wall) and added == {"objects": 4, "meshes": 4},
                added)
        c.check("thrown_pieces_fly", res_t.moved == res_t.pieces, [res_t.moved, res_t.pieces])
        c.check("wall_is_hit_by_the_other_object", res_w.moved >= 5 and res_w.events >= 5, [res_w.moved, res_w.events])
        pos_t, quat_t, piv_t, _ = sim.read_cache(thrown)
        pos_w, quat_w, piv_w, _ = sim.read_cache(wall)
        c.check("first_frame_is_rest", float(np.abs(pos_t[0] - piv_t).max()) < 1e-4 and float(np.abs(pos_w[0] - piv_w).max()) < 1e-4)
        speed_t = np.linalg.norm(np.diff(pos_t, axis=0), axis=-1) * 24
        speed_w = np.linalg.norm(np.diff(pos_w, axis=0), axis=-1) * 24
        c.set(thrown_max_speed=round(float(speed_t.max()), 2), wall_max_speed=round(float(speed_w.max()), 2))
        # a real collision: nothing leaves faster than what came in (the first moving frame is the blast itself)
        v_in = float(speed_t[0].max())
        c.set(blast_speed=round(v_in, 2))
        c.check("no_energy_from_nowhere", 5.0 < v_in < 16.0 and float(speed_t.max()) < 1.2 * v_in + 3.0 and float(speed_w.max()) < 1.2 * v_in,
                [round(v_in, 2), round(float(speed_t.max()), 2), round(float(speed_w.max()), 2)])
        # the thrown pieces are stopped or deflected by the wall: most of them end up short of where they fly without it
        x_with_wall = np.sort(pos_t[-1, :, 0])
        c.check("playback_of_both", playback_error(thrown, sim.rest_pieces(thrown)[0]) < 1e-4
                and playback_error(wall, sim.rest_pieces(wall)[0]) < 1e-4)
        # the first object draws the same random numbers as when baked alone: same start for its pieces
        thrown2, wall2 = scene_with_two()
        solo = sim.bake(bpy.context, thrown2, st)
        pos_solo, _, _, _ = sim.read_cache(thrown2)
        # (the frame of the blast itself; after it the solver works on more bodies and rounds differently)
        quat_solo = sim.read_cache(thrown2)[1]
        c.check("same_start_as_alone", float(np.abs(pos_solo[:2] - pos_t[:2]).max()) < 1e-5 and float(np.abs(pos_t[1] - pos_t[0]).max()) > 0.1
                and float(np.abs(quat_solo[:2] - quat_t[:2]).max()) < 1e-5 and float(np.abs(quat_t[1] - quat_t[0]).max()) > 1e-3,
                round(float(np.abs(pos_solo[:2] - pos_t[:2]).max()), 6))
        x_free = np.sort(pos_solo[-1, :, 0])
        c.set(thrown_end_x_median=[round(float(np.median(x_with_wall)), 2), round(float(np.median(x_free)), 2)])
        c.check("wall_stops_the_thrown_pieces", float(np.median(x_with_wall)) < float(np.median(x_free)) - 0.5,
                [round(float(np.median(x_with_wall)), 2), round(float(np.median(x_free)), 2)])

        # a failure anywhere leaves both objects as they were
        thrown, wall = scene_with_two()
        sim.bake(bpy.context, wall, S(frame_end=20, glue_strength=1e6))
        old = sim.cache_info(wall)[0]
        broken = T.add_object("Not Fractured", T.box("Not Fractured", (1.0, 1.0, 1.0), (5.0, 0.0, 0.5)))
        counts = T.datablock_counts()
        try:
            sim.bake_many(bpy.context, [thrown, wall, broken], st)
            raised = None
        except RuntimeError as e:
            raised = str(e)
        c.check("one_bad_object_stops_all", raised is not None and "Not Fractured" in raised and not sim.is_baked(thrown)
                and sim.cache_info(wall)[0] == old and T.datablock_counts() == counts, raised)

        # the simulation succeeds but writing the SECOND object fails: the first one, already written, must
        # come back exactly as it was (its old bake playing), and nothing new may be left
        thrown, wall = scene_with_two()
        sim.bake_many(bpy.context, [thrown, wall], S(frame_end=20, glue_strength=1e6))
        old_t, old_w = sim.cache_info(thrown)[0], sim.cache_info(wall)[0]
        pos_before = sim.read_cache(thrown)[0].copy()
        rest_t = sim.rest_pieces(thrown)[0]
        counts = T.datablock_counts()
        real_freeze, calls = sim._freeze, [0]

        def freeze_fails_second(o, pm):
            calls[0] += 1
            if calls[0] == 2:
                raise RuntimeError("injected while writing the second object")
            return real_freeze(o, pm)
        sim._freeze = freeze_fails_second
        try:
            sim.bake_many(bpy.context, [thrown, wall], st)
            raised = False
        except RuntimeError:
            raised = True
        finally:
            sim._freeze = real_freeze
        after = T.datablock_counts()
        c.check("second_write_fails_first_is_undone", raised and calls[0] == 2 and sim.cache_info(thrown) is not None
                and sim.cache_info(thrown)[0] == old_t and sim.cache_info(wall)[0] == old_w
                and np.array_equal(sim.read_cache(thrown)[0], pos_before) and after == counts,
                [raised, calls[0], {k: after[k] - counts[k] for k in after if after[k] != counts[k]}])
        c.check("undone_object_still_plays", playback_error(thrown, rest_t) < 1e-4)
    except Exception:
        c.error()
    c.done()

# ---------------------------------------------------------------- pieces that came to rest are really still
if wanted("settle"):
    c = REP.case("settle")
    try:
        # made-up motion with a known answer: 0 never moves, 1 flies to the end, 2 lands at frame 20 and trembles
        # ever less (2 mm fading out), 3 lands, lies still, and is knocked away again at frame 30
        F = 40
        t = np.arange(F, dtype=np.float32)
        pos = np.zeros((F, 5, 3), np.float32)
        quat = np.zeros((F, 5, 4), np.float32)
        quat[..., 0] = 1.0
        pos[:, 1, 0] = 0.1 * t
        pos[:20, 2, 2] = 1.0 - t[:20] / 20.0
        pos[20:, 2, 2] = 0.002 * np.exp(-(t[20:] - 20.0) / 3.0) * np.cos(t[20:])
        pos[10:30, 3, 2] = 0.0
        pos[:10, 3, 2] = 1.0 - t[:10] / 10.0
        pos[30:, 3, 0] = 0.05 * (t[30:] - 29.0)
        pos[:, 4, 2] = 5.0 - 0.0003 * t / (F - 1)          # 4 sinks by 0.3 mm in all: it has not really moved
        before = pos.copy()
        locked = sim.settle(pos, quat)
        tail = np.abs(before[:, 2, 2] - before[-1, 2, 2])
        expected = int(np.flatnonzero(tail >= 5e-4).max()) + 1                 # the first frame after the last big tremble
        still_from = int(np.flatnonzero(np.abs(pos[:, 2] - pos[-1, 2]).max(axis=1) > 0).max()) + 1
        c.set(trembling_piece_locked_from_frame=still_from, expected=expected, locked=locked)
        c.check("locks_at_the_right_frame", still_from == expected and 20 < expected < 35, [still_from, expected])
        c.check("lock_is_exact_and_small", float(np.abs(pos[still_from:, 2] - pos[-1, 2]).max()) == 0.0
                and float(np.abs(pos - before).max()) < 5e-4, round(float(np.abs(pos - before).max()), 6))
        c.check("before_the_lock_untouched", np.array_equal(pos[:still_from, 2], before[:still_from, 2]))
        c.check("moving_and_resting_pieces_untouched", np.array_equal(pos[:, [0, 1, 3]], before[:, [0, 1, 3]]) and locked == 3,
                locked)
        # ... and such a piece keeps its FIRST pose: frame 0 must stay the unbroken model
        c.check("barely_moving_piece_keeps_its_first_pose", float(np.abs(pos[:, 4] - before[0, 4]).max()) == 0.0)
        # a real bake: what lies on the ground at the end has not moved at all for the last frames
        fresh(80)
        heap = T.add_object("Heap", T.box("Heap", (1.0, 1.0, 1.0), (0.0, 0.0, 1.5)))
        T.add_fracture(heap, Pieces=40, Seed=4)
        bpy.context.view_layer.update()
        res = sim.bake(bpy.context, heap, S(frame_end=80, start_asleep=False, use_glue=False))
        hpos, hquat, _, _ = sim.read_cache(heap)
        step = np.linalg.norm(np.diff(hpos, axis=0), axis=-1)                  # [F-1, N]
        resting = step[-10:].max(0) < 1e-4
        exact = (step[-10:].max(0) == 0.0) & (np.abs(np.diff(hquat[-11:], axis=0)).max(axis=(0, 2)) == 0.0)
        c.set(heap_pieces=res.pieces, resting_at_the_end=int(resting.sum()), exactly_still=int(exact.sum()))
        c.check("resting_pieces_are_exactly_still", int(resting.sum()) > 8 and bool((exact == resting).all()),
                [int(resting.sum()), int(exact.sum())])
    except Exception:
        c.error()
    c.done()

# ---------------------------------------------------------------- burst speed is what was asked for
if wanted("burst_speed"):
    c = REP.case("burst_speed")
    try:
        fresh(60)
        block = T.add_object("Block", T.box("Block", (1.0, 1.0, 1.0), (0.0, 0.0, 3.0)))
        T.add_fracture(block, Pieces=12)
        results = {}
        for substeps in (10, 20):
            st = S(frame_end=60, start_asleep=False, use_glue=False, use_ground=False, substeps=substeps,
                   burst_speed=6.0, burst_up=1.0, burst_variation=0.0, burst_spin=0.0,
                   linear_damping=0.0, angular_damping=0.0)
            sim.bake(bpy.context, block, st)
            pos, _, piv, _ = sim.read_cache(block)
            # one animated frame moves the piece v / fps, then it flies: the apex is v^2 / (2 g) above that
            rise = (pos[..., 2].max(0) - piv[:, 2]) - 6.0 / bpy.context.scene.render.fps
            g = abs(bpy.context.scene.gravity[2])
            results[substeps] = (float(rise.min()), float(rise.max()), 6.0 ** 2 / (2 * g))
        c.set(apex_rise_m={k: [round(x, 3) for x in v] for k, v in results.items()})
        for substeps, (lo, hi, want) in results.items():
            c.check(f"apex_within_8pct_substeps{substeps}", abs(lo / want - 1) < 0.08 and abs(hi / want - 1) < 0.08,
                    [round(lo, 3), round(hi, 3), round(want, 3)])
    except Exception:
        c.error()
    c.done()

# ---------------------------------------------------------------- state handling
if wanted("state"):
    c = REP.case("state")
    try:
        scene = fresh(40)
        ob = T.add_object("Crate", T.box("Crate", (1.5, 1.0, 1.0), (0.0, 0.0, 0.0)), location=(0.5, 0.0, 1.0))
        ob.rotation_euler = (0.0, 0.0, 0.4)
        T.add_fracture(ob, Pieces=25)
        frac = core.find_modifier(ob, core.KIND_FRACTURE)
        st = S(frame_end=40, start_asleep=False, use_glue=False, burst_speed=4.0, burst_origin=(0.5, 0.0, 0.8))
        bpy.context.view_layer.update()
        em = core.EvalMesh(ob)

        # 1. a failing bake changes nothing and leaves nothing behind
        before = T.datablock_counts()
        real_write = sim.write_cache

        def boom(*a, **k):
            raise RuntimeError("simulated failure")
        sim.write_cache = boom
        try:
            sim.bake(bpy.context, ob, st)
            failed = False
        except RuntimeError:
            failed = True
        finally:
            sim.write_cache = real_write
        c.check("failure_is_reported", failed)
        c.check("failed_first_bake_leaves_nothing", not leftovers(before, {}), leftovers(before, {}))
        c.check("failed_first_bake_keeps_stack", frac.show_viewport and len(ob.modifiers) == 1)

        # 2. bake, then a failing re-bake keeps the old bake working
        sim.bake(bpy.context, ob, st)
        pos1 = sim.read_cache(ob)[0].copy()
        before = T.datablock_counts()
        sim.write_cache = boom
        try:
            sim.bake(bpy.context, ob, S(frame_end=40, start_asleep=False, use_glue=False, burst_speed=8.0))
        except RuntimeError:
            pass
        finally:
            sim.write_cache = real_write
        c.check("failed_rebake_leaves_nothing", not leftovers(before, {}), leftovers(before, {}))
        c.check("failed_rebake_keeps_old_cache", sim.is_baked(ob) and np.array_equal(sim.read_cache(ob)[0], pos1))
        c.check("failed_rebake_keeps_freeze", not frac.show_viewport and sim.FROZEN_PROP in ob)
        c.check("old_bake_still_plays", playback_error(ob, em) < 1e-4)

        # 2b. failures in the middle of write_cache (not before it): every one must roll back completely
        def state_of():
            pm = core.find_modifier(ob, core.KIND_PLAYBACK)
            return {
                "inputs": {n: core.get_input(pm, n) for n in sim.PLAYBACK_INPUTS},
                "group": pm.node_group, "vis": [(m.show_viewport, m.show_render) for m in ob.modifiers],
                "frozen": {k: list(v) for k, v in dict(ob[sim.FROZEN_PROP]).items()},
                "refs": (ob.get(sim.REF_CACHE), ob.get(sim.REF_REST)),
                "counts": T.datablock_counts(),
            }
        good = state_of()
        other = S(frame_end=30, start_asleep=False, use_glue=False, burst_speed=8.0)   # different frame count on purpose

        def failing(target, name, when):
            real = getattr(target, name)
            calls = {"n": 0}

            def wrapper(*a, **k):
                calls["n"] += 1
                if calls["n"] == when:
                    raise RuntimeError("simulated failure")
                return real(*a, **k)
            return real, wrapper

        for label, target, name, when in (("freeze", sim, "_freeze", 1), ("third_input", core, "set_input", 3),
                                          ("last_input", core, "set_input", 6), ("ref", sim, "_set_ref", 1)):
            real, wrapper = failing(target, name, when)
            setattr(target, name, wrapper)
            try:
                sim.bake(bpy.context, ob, other)
                raised = False
            except RuntimeError:
                raised = True
            finally:
                setattr(target, name, real)
            now = state_of()
            same = raised and all(now[k] == good[k] for k in good)
            c.check(f"rollback_after_failure_in_{label}", same,
                    {k: "changed" for k in good if now[k] != good[k]} if raised else "no exception")
        c.check("old_bake_plays_after_failed_writes", playback_error(ob, em) < 1e-4)

        # 3. the baked destruction follows the object when it is moved afterwards
        want = expected_world(ob, em, 20)
        old_m = ob.matrix_world.copy()
        ob.location = (-3.0, 2.0, 0.5)
        ob.rotation_euler = (0.3, -0.2, 1.1)
        ob.scale = (1.5, 1.5, 1.5)
        scene.frame_set(21)
        delta = np.array(ob.matrix_world @ old_m.inverted(), np.float64)
        moved_want = want.astype(np.float64) @ delta[:3, :3].T + delta[:3, 3]
        err = float(np.abs(core.EvalMesh(ob).co - moved_want).max())
        c.check("bake_follows_moved_object", err < 1e-4, round(err, 6))

        # 4. a modifier added after the playback modifier is not baked in twice by a re-bake
        extra = ob.modifiers.new("Displace", "DISPLACE")
        extra.strength = 0.2
        n_frozen = len(sim.cache_info(ob)[1].data.vertices)
        sim.bake(bpy.context, ob, st)
        rest = sim.cache_info(ob)[1].data
        co = np.empty(len(rest.vertices) * 3, np.float32)
        rest.vertices.foreach_get("co", co)
        base = np.empty(len(ob.data.vertices) * 3, np.float32)
        ob.data.vertices.foreach_get("co", base)
        c.check("downstream_modifier_not_frozen", len(rest.vertices) == n_frozen
                and float(np.abs(co.reshape(-1, 3)).max()) <= float(np.abs(base.reshape(-1, 3)).max()) + 1e-4)
        c.check("downstream_modifier_still_on", extra.show_viewport and list(ob.modifiers)[-1] == extra)
        c.check("rebake_adds_nothing", not leftovers(before, {}), leftovers(before, {}))

        # 5. rename, then free: everything goes, the fracture is editable again
        ob.name = "Renamed"
        frac.name = "My Fracture"
        before_free = T.datablock_counts()
        sim.free_cache(ob)
        after = T.datablock_counts()
        c.check("free_removes_cache", after["objects"] == before_free["objects"] - 2 and after["meshes"] == before_free["meshes"] - 2,
                {k: after[k] - before_free[k] for k in ("objects", "meshes")})
        c.check("free_restores_stack", frac.show_viewport and frac.show_render and sim.FROZEN_PROP not in ob
                and core.find_modifier(ob, core.KIND_PLAYBACK) is None)

        # 6. a duplicate shares the bake; freeing one must not break the other
        sim.bake(bpy.context, ob, st)
        twin = ob.copy()
        scene.collection.objects.link(twin)
        sim.free_cache(ob)
        c.check("duplicate_keeps_its_bake", sim.is_baked(twin))
        sim.free_cache(twin)
        c.check("last_free_removes_shared_cache", not [o for o in bpy.data.objects if o.name.startswith("RBD ")],
                [o.name for o in bpy.data.objects])

        # 7. the playback modifier deleted by hand: the bake is seen as gone, free still repairs the stack
        sim.bake(bpy.context, ob, st)
        ob.modifiers.remove(core.find_modifier(ob, core.KIND_PLAYBACK))
        c.check("manual_delete_is_detected", not sim.is_baked(ob) and not frac.show_viewport)
        sim.free_cache(ob)
        c.check("free_repairs_after_manual_delete", frac.show_viewport and sim.FROZEN_PROP not in ob)
        c.check("free_after_manual_delete_removes_helpers", not [o.name for o in bpy.data.objects if o.name.startswith("RBD ")]
                and not [m.name for m in bpy.data.meshes if m.name.startswith("RBD ")],
                [o.name for o in bpy.data.objects] + [m.name for m in bpy.data.meshes])

        # 7b. hand-deleted playback modifier, then straight to a new bake: the old helpers must not pile up
        sim.bake(bpy.context, ob, st)
        ob.modifiers.remove(core.find_modifier(ob, core.KIND_PLAYBACK))
        sim.bake(bpy.context, ob, st)
        helpers = sorted(o.name for o in bpy.data.objects if o.name.startswith("RBD "))
        c.check("rebake_after_manual_delete_leaves_one_set", len(helpers) == 2, helpers)

        # 7c. Free must never delete an object the user put into the modifier
        mine = T.add_object("MyOwnMesh", T.box("MyOwnMesh", (1.0, 1.0, 1.0)))
        pm_now = core.find_modifier(ob, core.KIND_PLAYBACK)
        core.set_input(pm_now, "Cache", mine)
        sim.free_cache(ob)
        c.check("free_keeps_user_object", "MyOwnMesh" in bpy.data.objects and "MyOwnMesh" in bpy.data.meshes)
        c.check("free_still_removes_own_helpers", not [o.name for o in bpy.data.objects if o.name.startswith("RBD ")],
                [o.name for o in bpy.data.objects])
        bpy.data.objects.remove(bpy.data.objects["MyOwnMesh"])

        # 7d. the new bake is in place even if letting go of the old one fails
        sim.bake(bpy.context, ob, st)
        real_remove = sim._remove_unused

        def remove_boom(o):
            raise RuntimeError("simulated failure during clean-up")
        sim._remove_unused = remove_boom
        try:
            sim.bake(bpy.context, ob, st)
            survived = True
        except RuntimeError:
            survived = False
        finally:
            sim._remove_unused = real_remove
        # (the object has been moved and scaled since the start of this case: compare against its current rest)
        c.check("cleanup_failure_does_not_break_the_bake",
                survived and sim.is_baked(ob) and playback_error(ob, sim.rest_pieces(ob)[0]) < 1e-4)
        sim.free_cache(ob)
        for stray in [o for o in bpy.data.objects if o.name.startswith("RBD ")]:   # the one the failed clean-up left
            me_stray = stray.data
            bpy.data.objects.remove(stray)
            bpy.data.meshes.remove(me_stray)

        # 8. a deforming modifier between the fracture and the bake: collisions follow what is visible
        ob.modifiers.remove(extra)      # the Displace from step 4 would count as one too
        res_plain = sim.bake(bpy.context, ob, st)
        c.check("undeformed_mesh_raises_no_note", not any("deformed after the fracture" in n for n in res_plain.notes), res_plain.notes)
        sim.free_cache(ob)
        bend = ob.modifiers.new("Bend", "SIMPLE_DEFORM")
        bend.deform_method, bend.angle = "BEND", 0.6
        res_bent = sim.bake(bpy.context, ob, st)
        c.check("deformed_mesh_is_noticed", any("deformed after the fracture" in n for n in res_bent.notes), res_bent.notes)
        sim.free_cache(ob)
        ob.modifiers.remove(bend)

        # 9. interior noise on a scaled-up object is still just noise, not a deformation
        core.set_input(frac, "Detail Level", 2)
        core.set_input(frac, "Noise Height", 0.05)
        ob.scale = (4.0, 4.0, 4.0)
        res_noise = sim.bake(bpy.context, ob, st)
        c.check("noise_on_scaled_object_is_not_a_deformation",
                not any("deformed after the fracture" in n for n in res_noise.notes), res_noise.notes)
        # and the mass comes from the flat shape: same piece masses with and without the noise
        pos_noise = sim.read_cache(ob)[2].copy()
        core.set_input(frac, "Detail Level", 0)
        sim.free_cache(ob)
        sim.bake(bpy.context, ob, st)
        c.check("pivots_ignore_the_noise", float(np.abs(sim.read_cache(ob)[2] - pos_noise).max()) < 1e-4,
                round(float(np.abs(sim.read_cache(ob)[2] - pos_noise).max()), 6))
        sim.free_cache(ob)
        c.check("no_actions_leaked", len(bpy.data.actions) == 0, len(bpy.data.actions))
    except Exception:
        c.error()
    c.done()

REP.finish()
