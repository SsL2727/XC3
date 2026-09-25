"""Carve named xbc1 (zstd) blocks out of a raw XC3 bf3.ard byte range (the archive index bf3.arh is unavailable).

usage: python carve_xbc1.py <ard_range.bin> <out_dir> [--only-ext .bdat,.wilay]
Each block header is: 'xbc1' u32 version u32 decompressed_size u32 compressed_size u32 hash char[28] name, then the data.
"""
import mmap
import os
import re
import struct
import sys
import zlib

import zstandard

src, out = sys.argv[1], sys.argv[2]
index_only = "--index-only" in sys.argv
only = None
if "--only-ext" in sys.argv:
    only = tuple(sys.argv[sys.argv.index("--only-ext") + 1].split(","))
name_re = re.compile(sys.argv[sys.argv.index("--name-regex") + 1]) if "--name-regex" in sys.argv else None
os.makedirs(out, exist_ok=True)

dctx = zstandard.ZstdDecompressor()
total = ok = bad = 0
names_seen = {}
listing = open(os.path.join(out, "_index.tsv"), "w", encoding="utf-8")
with open(src, "rb") as f, mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as mm:
    pos = 0
    while True:
        pos = mm.find(b"xbc1", pos)
        if pos < 0:
            break
        hdr = mm[pos:pos + 48]
        if len(hdr) < 48:
            break
        ver, dsz, csz, _h = struct.unpack("<IIII", hdr[4:20])
        name = hdr[20:48].split(b"\0")[0].decode("latin1", "replace")
        if ver != 3 or csz == 0 or csz > (1 << 30) or dsz == 0 or dsz > (1 << 31) or not re.fullmatch(r"[\w.\-]{1,27}", name or "?"):
            pos += 4
            continue
        total += 1
        keep = (only is None or name.endswith(only)) and (name_re is None or name_re.search(name) is not None)
        if index_only:
            listing.write("\t".join(map(str, (pos, dsz, csz, name))) + chr(10))
            ok += 1
        elif keep:
            data = mm[pos + 48:pos + 48 + csz]
            try:
                raw = dctx.decompress(data, max_output_size=dsz + 16)
                if len(raw) != dsz:
                    raise ValueError("size mismatch")
                n = names_seen.get(name, 0)
                names_seen[name] = n + 1
                fn = name if n == 0 else f"{os.path.splitext(name)[0]}~{pos}{os.path.splitext(name)[1]}"
                with open(os.path.join(out, fn), "wb") as w:
                    w.write(raw)
                listing.write(f"{pos}\t{dsz}\t{csz}\t{name}\n")
                ok += 1
            except Exception:
                bad += 1
        pos += 48 + csz
listing.close()
print(f"xbc1 blocks: {total}, carved ok: {ok}, failed: {bad}")
