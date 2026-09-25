"""Extract named xbc1 blocks by name using the offsets in carve_xbc1.py's _index.tsv (no full-archive scan).

usage: python carve_at.py <ard> <_index.tsv> <out_dir> <name> [<name> ...]     (all blocks of those names; duplicates get ~<pos>)
"""
import os
import struct
import sys

import zstandard

ard, idx, out = sys.argv[1:4]
names = set(sys.argv[4:])
os.makedirs(out, exist_ok=True)
dctx = zstandard.ZstdDecompressor()
with open(ard, "rb") as f:
    for line in open(idx, encoding="utf-8"):
        pos, dsz, csz, name = line.rstrip("\n").split("\t")
        if name not in names:
            continue
        pos, dsz, csz = int(pos), int(dsz), int(csz)
        f.seek(pos)
        blk = f.read(48 + csz)
        assert blk[:4] == b"xbc1"
        raw = dctx.decompress(blk[48:], max_output_size=dsz + 16)
        base, ext = os.path.splitext(name)
        fn = os.path.join(out, name if not os.path.exists(os.path.join(out, name)) else f"{base}~{pos}{ext}")
        open(fn, "wb").write(raw)
        print(fn, len(raw))
