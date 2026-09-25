"""Minimal RAR5 block walker: lists blocks per volume and finds stored-file payload ranges."""
import struct, sys, os, zlib

def vint(b, p):
    v = 0; s = 0
    while True:
        c = b[p]; p += 1
        v |= (c & 0x7F) << s; s += 7
        if not c & 0x80: return v, p

def walk(path, maxblocks=50):
    out = []
    size = os.path.getsize(path)
    with open(path, "rb") as f:
        sig = f.read(8)
        assert sig == b"Rar!\x1a\x07\x01\x00", sig
        pos = 8
        while pos < size and len(out) < maxblocks:
            f.seek(pos)
            head = f.read(64)
            crc = struct.unpack("<I", head[:4])[0]
            hsize, p = vint(head, 4)          # size of header from after this vint
            hstart = 4 + (p - 4)               # offset within block where header body starts
            # re-read full header body for parsing
            f.seek(pos + p)
            body = f.read(hsize)
            htype, q = vint(body, 0)
            flags, q = vint(body, q)
            extra = 0; dsize = 0
            if flags & 1: extra, q = vint(body, q)
            if flags & 2: dsize, q = vint(body, q)
            info = {"pos": pos, "hdr_end": pos + p + hsize, "type": htype, "flags": flags, "dsize": dsize}
            if htype == 1:  # main
                aflags, q = vint(body, q)
                info["archive_flags"] = aflags
                if aflags & 2:
                    vn, q = vint(body, q); info["volnum"] = vn
            elif htype in (2, 3):  # file / service
                fflags, q = vint(body, q)
                usize, q = vint(body, q)
                attrs, q = vint(body, q)
                if fflags & 2: q += 4  # mtime
                if fflags & 4: info["datacrc"] = struct.unpack("<I", body[q:q+4])[0]; q += 4
                comp, q = vint(body, q)
                hos, q = vint(body, q)
                nlen, q = vint(body, q)
                info["name"] = body[q:q+nlen].decode("utf8", "replace"); q += nlen
                info["fflags"] = fflags; info["usize"] = usize
            out.append(info)
            pos = info["hdr_end"] + dsize
            if htype == 5: break
    return out

if __name__ == "__main__":
    for p in sys.argv[1:]:
        print("==", os.path.basename(p), os.path.getsize(p))
        for b in walk(p): print("  ", b)
