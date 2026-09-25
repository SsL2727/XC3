"""Assemble the BDAT input folder the Series Randomizer expects for XC3 from the carved-archive index.

usage: python build_xc3_bdat_input.py <bf3.ard> <_index.tsv> <out_dir>
Layout: <out>/{des,btl,evt,fld,map,prg,qst,sys,mnu}.bdat and <out>/gb/game/{autotalk,battle,field,menu,quest,system}.bdat (English copy = the
third of the nine language copies by archive position).  zzz.bdat / dlc.bdat are not in the base archive index and are skipped (the bridge tolerates that).
"""
import os
import sys

import zstandard

ard, idx, out = sys.argv[1:4]
MAIN = ["des", "btl", "evt", "fld", "map", "prg", "qst", "sys", "mnu"]
TEXT = ["autotalk", "battle", "field", "menu", "quest", "system"]
entries = {}
for line in open(idx, encoding="utf-8"):
    pos, dsz, csz, name = line.rstrip("\n").split("\t")
    entries.setdefault(name, []).append((int(pos), int(dsz), int(csz)))
dctx = zstandard.ZstdDecompressor()
os.makedirs(os.path.join(out, "gb", "game"), exist_ok=True)
with open(ard, "rb") as f:
    def dump(name, which, dest):
        pos, dsz, csz = sorted(entries[name + ".bdat"])[which]
        f.seek(pos)
        blk = f.read(48 + csz)
        raw = dctx.decompress(blk[48:], max_output_size=dsz + 16)
        open(dest, "wb").write(raw)
        print(dest, len(raw))
    for n in MAIN:
        dump(n, 0, os.path.join(out, n + ".bdat"))
    for n in TEXT:
        dump(n, 2, os.path.join(out, "gb", "game", n + ".bdat"))
