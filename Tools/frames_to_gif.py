"""Turn the frame folders written by Examples/make_examples.py into looping GIFs for the README.

    python Tools/frames_to_gif.py <frames folder> <output folder> [frames per second]

Needs Pillow, so it runs with an ordinary Python, not Blender's. The frames were rendered every
second frame of a 24 fps scene: 12 fps plays them at the simulated speed.
"""
import os
import sys

from PIL import Image

src, dst = sys.argv[1], sys.argv[2]
fps = float(sys.argv[3]) if len(sys.argv) > 3 else 12.0
os.makedirs(dst, exist_ok=True)
for name in sorted(os.listdir(src)):
    folder = os.path.join(src, name)
    files = sorted(f for f in os.listdir(folder) if f.endswith(".png")) if os.path.isdir(folder) else []
    if not files:
        continue
    frames = [Image.open(os.path.join(folder, f)).convert("RGB") for f in files]
    # one palette for the whole clip (taken from a strip of sample frames), so colours do not flicker
    picks = frames[:: max(1, len(frames) // 8)]
    strip = Image.new("RGB", (picks[0].width * len(picks), picks[0].height))
    for i, im in enumerate(picks):
        strip.paste(im, (i * im.width, 0))
    palette = strip.quantize(colors=128, method=Image.Quantize.MEDIANCUT)
    quantised = [im.quantize(palette=palette, dither=Image.Dither.NONE) for im in frames]
    out = os.path.join(dst, name + ".gif")
    durations = [int(round(1000 / fps))] * len(quantised)
    durations[-1] = 1200                       # hold the last frame before the loop
    quantised[0].save(out, save_all=True, append_images=quantised[1:], duration=durations, loop=0, optimize=True)
    print(f"GIF {name}: {len(frames)} frames, {os.path.getsize(out) / 1e6:.2f} MB")
