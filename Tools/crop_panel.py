"""Crop the screenshots of Tools/ui_screenshot.py to the sidebar and a strip of the viewport.
    python Tools/crop_panel.py <in.png> <out.png> [width of the strip kept on the right, pixels]
Needs Pillow (an ordinary Python, not Blender's)."""
import sys
from PIL import Image

src, dst = sys.argv[1], sys.argv[2]
keep = int(sys.argv[3]) if len(sys.argv) > 3 else 560
im = Image.open(src).convert("RGB")
im.crop((im.width - keep, 0, im.width, im.height)).save(dst, optimize=True)
print("PANEL", dst, im.width, "x", im.height, "->", keep, "x", im.height)
