"""Look inside .blend files for text that should not be published: local paths, user names, any word you name.

    python Tools/blend_strings.py <file.blend> [more files ...] [-- word ...]

A .blend is usually Zstandard compressed, so a plain search of the file finds nothing. This unpacks it
(needs the zstandard module: Blender's own Python has it) and lists drive paths, home folders and the words given after --.
"""
import io
import re
import sys

import zstandard

args = sys.argv[1:]
words = [b"Users", b"/home/"]
if "--" in args:
    k = args.index("--")
    words += [w.encode() for w in args[k + 1:]]
    args = args[:k]
bad = 0
for path in args:
    raw = open(path, "rb").read()
    if raw[:4] == b"\x28\xb5\x2f\xfd":
        # (Blender writes many frames, and a table to seek in them at the end)
        raw = zstandard.ZstdDecompressor().stream_reader(io.BytesIO(raw), read_across_frames=True).read()
    found = {w.decode(): raw.count(w) for w in words if raw.count(w)}
    paths = sorted(set(m.group(0).decode("latin-1") for m in re.finditer(rb"[A-Za-z]:[\\/][\x20-\x7e]{8,120}", raw)))
    paths = [p for p in paths if "\\" in p[2:] or "/" in p[2:]]
    bad += len(found) + len(paths)
    print(f"BLEND {path}: {len(raw) / 1e6:.1f} MB unpacked, words {found or 'none'}, paths {paths[:6] or 'none'}")
sys.exit(1 if bad else 0)
