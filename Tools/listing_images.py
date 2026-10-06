"""Render the pictures for the extension's page on extensions.blender.org from the example files.

    blender --background --factory-startup --python Tools/listing_images.py -- <out_dir> [video]

Writes featured.png (1920 x 1080, the page asks for at least that, 16:9), four previews, icon.png (256 x 256,
a close view of the block as it bursts) and, with "video", wall_smash.mp4. The examples are opened and not saved. Nothing is stored in
the pictures besides the pixels: the render stamps (date, file name, ...) are switched off.
"""
import os
import sys

import bpy

OUT = sys.argv[sys.argv.index("--") + 1]
VIDEO = "video" in sys.argv[sys.argv.index("--") + 2:]
EXAMPLES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "Examples")
os.makedirs(OUT, exist_ok=True)

# (file, frame, name, width, height, icon)
SHOTS = [
    ("01_wall_smash", 15, "featured", 1920, 1080, False),
    ("01_wall_smash", 24, "preview_wall", 1920, 1080, False),
    ("03_explosion", 6, "preview_explosion", 1920, 1080, False),
    ("02_ground_crack", 24, "preview_ground", 1920, 1080, False),
    ("04_glass", 12, "preview_glass", 1920, 1080, False),
    ("03_explosion", 5, "icon", 256, 256, True),
]


def prepare(scene):
    scene.render.engine = "BLENDER_WORKBENCH"
    sh = scene.display.shading
    sh.light, sh.color_type, sh.show_cavity, sh.show_shadows = "STUDIO", "MATERIAL", True, True
    scene.display.render_aa = "16"
    scene.world = bpy.data.worlds.new("World")
    scene.world.color = (0.55, 0.57, 0.6)
    scene.render.resolution_percentage = 100
    scene.render.use_stamp = False
    for name in dir(scene.render):
        if name.startswith("use_stamp_"):
            setattr(scene.render, name, False)


opened = None
for file, frame, name, width, height, icon in SHOTS:
    if file != opened:
        bpy.ops.wm.open_mainfile(filepath=os.path.join(EXAMPLES, file + ".blend"))
        opened = file
    scene = bpy.context.scene
    prepare(scene)
    scene.render.resolution_x, scene.render.resolution_y = width, height
    if icon:
        scene.camera.data.lens *= 2.1          # the block fills the square
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGB"
    scene.frame_set(frame)
    scene.render.filepath = os.path.join(OUT, name + ".png")
    bpy.ops.render.render(write_still=True)
    print(f"LISTING {name}.png {width}x{height} from {file} frame {frame}, {os.path.getsize(scene.render.filepath)} bytes", flush=True)

if VIDEO:
    bpy.ops.wm.open_mainfile(filepath=os.path.join(EXAMPLES, "01_wall_smash.blend"))
    scene = bpy.context.scene
    prepare(scene)
    scene.render.resolution_x, scene.render.resolution_y = 1280, 720
    scene.render.film_transparent = False
    scene.frame_start, scene.frame_end = 1, 96
    settings = scene.render.image_settings
    if hasattr(settings, "media_type"):
        settings.media_type = "VIDEO"
    settings.file_format = "FFMPEG"
    scene.render.ffmpeg.format = "MPEG4"
    scene.render.ffmpeg.codec = "H264"
    scene.render.ffmpeg.constant_rate_factor = "HIGH"
    scene.render.ffmpeg.audio_codec = "NONE"
    scene.render.filepath = os.path.join(OUT, "wall_smash.mp4")
    bpy.ops.render.render(animation=True)
    made = [f for f in os.listdir(OUT) if f.startswith("wall_smash")]
    print("LISTING video", made, flush=True)
