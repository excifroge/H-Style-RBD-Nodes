"""Shared helpers for the headless tests: test shapes, piece colouring, rendering."""
import math
import os
import sys

import bmesh
import bpy
import numpy as np
from mathutils import Vector

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
from Extension import core, nodes_fracture  # noqa: E402
from Extension.nodekit import Builder  # noqa: E402


def mesh_from_bmesh(name, fn):
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    fn(bm)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(me)
    bm.free()
    return me


def box(name, size, center=(0.0, 0.0, 0.0)):
    def f(bm):
        bmesh.ops.create_cube(bm, size=1.0)
        bmesh.ops.scale(bm, vec=size, verts=bm.verts)
        bmesh.ops.translate(bm, vec=center, verts=bm.verts)
    return mesh_from_bmesh(name, f)


def icosphere(name, radius, subdivisions=3):
    return mesh_from_bmesh(name, lambda bm: bmesh.ops.create_icosphere(bm, subdivisions=subdivisions, radius=radius))


def torus(name, R=1.0, r=0.4, U=32, V=16):
    def f(bm):
        vs = [[bm.verts.new(((R + r * math.cos(2 * math.pi * j / V)) * math.cos(2 * math.pi * i / U),
                             (R + r * math.cos(2 * math.pi * j / V)) * math.sin(2 * math.pi * i / U),
                             r * math.sin(2 * math.pi * j / V))) for j in range(V)] for i in range(U)]
        for i in range(U):
            for j in range(V):
                bm.faces.new((vs[i][j], vs[(i + 1) % U][j], vs[(i + 1) % U][(j + 1) % V], vs[i][(j + 1) % V]))
    return mesh_from_bmesh(name, f)


def add_object(name, data, location=(0.0, 0.0, 0.0)):
    ob = bpy.data.objects.new(name, data)
    ob.location = location
    bpy.context.scene.collection.objects.link(ob)
    return ob


def add_fracture(ob, **inputs):
    mod = ob.modifiers.new(core.MOD_FRACTURE, "NODES")
    mod.node_group = nodes_fracture.ensure()
    for k, v in inputs.items():
        core.set_input(mod, k.replace("_", " "), v)
    return mod


def color_group():
    name = "Test Piece Color"
    if name in bpy.data.node_groups:
        return bpy.data.node_groups[name]
    b = Builder(name)
    g = b.input("Geometry", "geo")
    col = b.rand("FLOAT_VECTOR", (0.15, 0.15, 0.15), (1.0, 1.0, 1.0), 7, id=b.named("piece_id", "INT"))
    dark = b.vmath("SCALE", col, scale=b.switch("FLOAT", b.named("inside", "BOOLEAN"), 1.0, 0.45))
    b.output("Geometry", "geo", b.store(g, "Col", "FLOAT_COLOR", "CORNER", dark))
    return b.finish()


def add_piece_colors(ob):
    m = ob.modifiers.new("Color", "NODES")
    m.node_group = color_group()
    return m


def setup_render(res=(960, 540)):
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.render.resolution_x, scene.render.resolution_y = res
    sh = scene.display.shading
    sh.light, sh.color_type, sh.show_cavity, sh.show_shadows = "STUDIO", "VERTEX", True, True
    if scene.world is None:
        scene.world = bpy.data.worlds.new("TestWorld")
    scene.world.color = (0.22, 0.23, 0.25)
    cam = bpy.data.objects.get("TestCam")
    if cam is None:
        cam = bpy.data.objects.new("TestCam", bpy.data.cameras.new("TestCam"))
        scene.collection.objects.link(cam)
    cam.data.clip_end = 2000
    scene.camera = cam
    return cam


def aim_camera(cam, target, direction=(1.0, -1.3, 0.8), distance=10.0):
    d = Vector(direction).normalized()
    cam.location = Vector(target) + d * distance
    cam.rotation_euler = (-d).to_track_quat("-Z", "Y").to_euler()


def render_still(path, frame=None):
    scene = bpy.context.scene
    if frame is not None:
        scene.frame_set(frame)
    scene.render.filepath = path
    bpy.ops.render.render(write_still=True)


def contact_sheet(paths, out, cols=2):
    """Paste rendered stills into one image so a whole sequence can be eyeballed at once."""
    imgs = [bpy.data.images.load(p) for p in paths]
    w, h = imgs[0].size
    rows = (len(imgs) + cols - 1) // cols
    sheet = np.zeros((rows * h, cols * w, 4), np.float32)
    for k, im in enumerate(imgs):
        a = np.empty(w * h * 4, np.float32)
        im.pixels.foreach_get(a)
        r, c = k // cols, k % cols
        sheet[(rows - 1 - r) * h:(rows - r) * h, c * w:(c + 1) * w] = a.reshape(h, w, 4)
    res = bpy.data.images.new("sheet", cols * w, rows * h, alpha=True)
    res.pixels.foreach_set(sheet.reshape(-1))
    res.file_format = "PNG"
    res.filepath_raw = out
    res.save()
    for im in imgs:
        bpy.data.images.remove(im)
    bpy.data.images.remove(res)


def qrot(q, v):
    w, u = q[..., :1], q[..., 1:]
    t = 2 * np.cross(u, v)
    return v + w * t + np.cross(u, t)


# ---------------------------------------------------------------- pass / fail bookkeeping
def source_hash():
    """Hash of the extension sources, written into every result so a result can be tied to the code it tested."""
    import hashlib
    h = hashlib.sha1()
    for folder, kinds in (("Extension", (".py", ".toml")), ("Unity", (".hlsl", ".shader", ".cs")), ("Tests", (".py", ".sh"))):
        base = os.path.join(ROOT, folder)
        for name in sorted(os.listdir(base)):
            if name.endswith(kinds):
                with open(os.path.join(base, name), "rb") as fh:
                    h.update((folder + "/" + name).encode() + b"\0" + fh.read().replace(b"\r\n", b"\n"))
    return h.hexdigest()[:12]


class Report:
    """Collects measurements and hard checks of one test file. `finish()` writes the JSON and makes
    Blender exit non-zero when any check failed (run Blender with --python-exit-code 1)."""

    def __init__(self, name, out_dir, tag):
        self.name, self.out_dir, self.tag = name, out_dir, tag
        self.cases, self.failed = {}, []
        self.source = source_hash()
        os.makedirs(out_dir, exist_ok=True)

    def case(self, case):
        self.cases[case] = {"checks": {}}
        return _Case(self, case)

    def write(self):
        import json
        doc = {"source_hash": self.source, "blender": bpy.app.version_string, "failed": self.failed, "cases": self.cases}
        with open(os.path.join(self.out_dir, self.name + ".json"), "w", encoding="utf-8") as fh:
            json.dump(doc, fh, indent=1, default=str)

    def finish(self):
        self.write()
        total = sum(len(c["checks"]) for c in self.cases.values())
        print(f"{self.tag} SUMMARY {self.name}: {total - len(self.failed)}/{total} checks passed"
              + (f"; FAILED: {self.failed}" if self.failed else ""), flush=True)
        if self.failed:
            raise SystemExit(f"{len(self.failed)} checks failed")


class _Case:
    def __init__(self, report, case):
        self.report, self.case_name = report, case
        self.data = report.cases[case]

    def set(self, **values):
        self.data.update(values)

    def check(self, label, ok, value=None):
        ok = bool(ok)
        self.data["checks"][label] = {"ok": ok, "value": value}
        if not ok:
            self.report.failed.append(f"{self.case_name}:{label}")
        return ok

    def error(self):
        import traceback
        self.data["error"] = traceback.format_exc()[-1800:]
        self.report.failed.append(f"{self.case_name}:exception")

    def done(self):
        import json
        bad = [k for k, v in self.data["checks"].items() if not v["ok"]]
        flat = {k: v for k, v in self.data.items() if k != "checks"}
        flat["checks_passed"] = f"{len(self.data['checks']) - len(bad)}/{len(self.data['checks'])}"
        if bad:
            flat["FAILED"] = {k: self.data["checks"][k]["value"] for k in bad}
        print(self.report.tag, self.case_name, json.dumps(flat, default=str), flush=True)
        self.report.write()


def datablock_counts():
    return {k: len(getattr(bpy.data, k)) for k in
            ("objects", "meshes", "scenes", "actions", "collections", "armatures", "images", "node_groups")}
