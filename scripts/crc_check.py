import zlib,sys
f=sys.argv[1]; bounds=[int(x) for x in sys.argv[2].split(",")]; exp=[int(x,16) for x in sys.argv[3].split(",")]
crc=0; pos=0
with open(f,"rb") as fh:
    for b,e in zip(bounds,exp):
        while pos<b:
            chunk=fh.read(min(64<<20,b-pos)); assert chunk; crc=zlib.crc32(chunk,crc); pos+=len(chunk)
        print(f"cumulative crc at {b}: {crc:08X} expected {e:08X} {'OK' if crc==e else 'MISMATCH'}",flush=True)
