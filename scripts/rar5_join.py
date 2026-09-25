import sys, zlib, os
sys.path.insert(0, os.path.dirname(__file__))
from rar5_blocks import walk
vols = sys.argv[1:-1]; out = sys.argv[-1]
os.makedirs(os.path.dirname(out), exist_ok=True)
with open(out, "wb") as o:
    for v in vols:
        blocks = walk(v)
        fb = [b for b in blocks if b["type"] == 2][0]
        start, n = fb["hdr_end"], fb["dsize"]
        crc = 0
        with open(v, "rb") as f:
            f.seek(start); left = n
            while left:
                chunk = f.read(min(left, 64 << 20)); assert chunk
                crc = zlib.crc32(chunk, crc); o.write(chunk); left -= len(chunk)
        print(f"{os.path.basename(v)}: {n} bytes crc={crc:08X} expected={fb['datacrc']:08X} {'OK' if crc==fb['datacrc'] else 'MISMATCH'}", flush=True)
print("done", flush=True)
