"""Timing on a production-sized mesh (not a pass/fail test).

    blender --background --factory-startup --python Tests/bench_heavy.py
"""
import json
import os
import sys
import time

import bpy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as T  # noqa: E402
from Extension import core, sim  # noqa: E402

for subdiv, pieces, detail in ((5, 100, 0), (6, 100, 0), (6, 500, 0), (6, 500, 2), (7, 200, 0)):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.frame_start, scene.frame_end = 1, 60
    ob = T.add_object("Rock", T.icosphere("Rock", 1.0, subdiv), location=(0.0, 0.0, 1.2))
    tris = len(ob.data.polygons)
    T.add_fracture(ob, Pieces=pieces, Detail_Level=detail, Noise_Height=0.02)
    t = time.perf_counter()
    bpy.context.view_layer.update()
    em = core.EvalMesh(ob)
    t_fracture = time.perf_counter() - t
    r = {"source_tris": tris, "pieces_asked": pieces, "detail": detail, "pieces": em.n_pieces, "out_verts": len(em.co),
         "fracture_s": round(t_fracture, 2), "open_edges": em.open_edges() if detail == 0 else None,
         "volume_ratio": round(float(em.piece_volumes().sum() / (4.0 / 3.0 * 3.14159265 * 1.0)), 4)}
    st = sim.SimSettings(frame_end=60, start_asleep=False, use_glue=False, burst_speed=4.0, burst_origin=(0.0, 0.0, 1.0))
    res = sim.bake(bpy.context, ob, st)
    r["bake_s"] = round(res.seconds, 2)
    ts = []
    for f in range(1, 31):
        t = time.perf_counter()
        scene.frame_set(f)
        bpy.context.evaluated_depsgraph_get()
        ts.append(time.perf_counter() - t)
    r["scrub_ms"] = round(1000 * sum(ts[1:]) / (len(ts) - 1), 2)
    print("HEAVY", json.dumps(r), flush=True)
