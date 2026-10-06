"""Produce a small VAT + bone FBX export together with ground truth, for checking the import in Unity.

    blender --background --factory-startup --python Tests/unity_export.py -- <out_dir>

truth.json holds, for a sample of vertices, where Blender says they are at a few frames. The Unity
side decodes the same vertices from the imported mesh + textures and compares.
"""
import json
import os
import sys

import bpy
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as T  # noqa: E402
from Extension import export, sim  # noqa: E402

OUT = sys.argv[sys.argv.index("--") + 1]
os.makedirs(OUT, exist_ok=True)

bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
scene.frame_start, scene.frame_end = 1, 48
# deliberately lopsided: off-centre, rotated, different size on every axis, so a wrong axis shows up
ob = T.add_object("Totem", T.box("Totem", (1.2, 0.8, 1.6), (0.2, 0.3, 0.8)), location=(0.5, 1.5, 0.0))
ob.rotation_euler = (0.0, 0.0, 0.52)
T.add_fracture(ob, Pieces=40, Seed=3)
st = sim.SimSettings(frame_end=48, start_asleep=False, use_glue=False, burst_speed=5.0,
                     burst_origin=(0.5, 1.5, 0.2), burst_up=0.45)
sim.bake(bpy.context, ob, st)
pos, quat, piv, start = sim.read_cache(ob)
F, N = pos.shape[:2]
rest, _ = sim.rest_pieces(ob)

vat = export.export_vat(bpy.context, ob, OUT, "unity_vat", "UNITY")
fbx = export.export_fbx(bpy.context, ob, os.path.join(OUT, "unity_bones.fbx"))

frames = [0, 12, 30, F - 1]
sample = np.unique(np.linspace(0, len(rest.co) - 1, 300).astype(int))
truth = {
    "note": "positions are in Blender world axes (x right, y back, z up), metres",
    "frames": frames, "fps": 24.0, "piece_count": N, "frame_count": F,
    "rest": rest.co[sample].round(6).tolist(),
    "piece": rest.piece[sample].tolist(),
    "at_frame": {str(k): (pos[k][rest.piece[sample]] + T.qrot(quat[k][rest.piece[sample]],
                                                              rest.co[sample] - piv[rest.piece[sample]])).round(6).tolist()
                 for k in frames},
    "pivot_at_frame": {str(k): pos[k].round(6).tolist() for k in frames},
    "bounds_min": rest.co.min(0).round(6).tolist(), "bounds_max": rest.co.max(0).round(6).tolist(),
}
with open(os.path.join(OUT, "truth.json"), "w", encoding="utf-8") as fh:
    json.dump(truth, fh)
print("UNITY_EXPORT", json.dumps({"pieces": N, "frames": F, "verts": len(rest.co), "samples": len(sample),
                                  "vat": [os.path.basename(p) for p in vat["files"]],
                                  "tex": f"{vat['width']}x{vat['height']}", "bones": fbx["bones"],
                                  "shader_data_first4": export.piece_shader_data(pos, quat, piv, 24.0, [0.5, 1.5, 0.2])[:4].round(4).tolist()}), flush=True)

# A second export whose cracks open over time (glued wall, blast in the middle), for checking
# HStyleRbdVatPlayer.cs: events_truth.txt lists the cracks in Blender world axes, straight from the bake.
wall = T.add_object("Wall", T.box("Wall", (4.0, 0.4, 2.0), (0.0, 0.0, 1.0)), location=(-3.0, 0.5, 0.0))
wall.rotation_euler = (0.0, 0.0, -0.3)
T.add_fracture(wall, Pieces=60, Seed=3)
bpy.context.view_layer.update()
sim.bake(bpy.context, wall, sim.SimSettings(frame_end=48, glue_strength=2.0, anchor_bottom=True, burst_speed=5.0,
                                            burst_origin=(-3.0, 0.0, 1.0), burst_radius=1.8, seed=4))
wall_vat = export.export_vat(bpy.context, wall, OUT, "unity_wall", "UNITY")
events = sim.read_events(wall)
with open(os.path.join(OUT, "events_truth.txt"), "w", encoding="utf-8") as fh:
    fh.write(f"{len(events)} 24.0 48\n")
    for e in events:
        fh.write(" ".join(f"{x:.6f}" for x in e[:5]) + "\n")
print("UNITY_EXPORT_WALL", json.dumps({"cracks": len(events), "frames_with_cracks": sorted({int(e[0]) for e in events}),
                                       "json_events": wall_vat["events"]}), flush=True)
