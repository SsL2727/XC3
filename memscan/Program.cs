// Fast process-memory scanner used to locate emulated-game structures inside Ryujinx (read-only).
//
//   memscan <pid> counters <lo> <hi> <align> <out.bin>      snapshot every aligned u32 in [lo,hi] (addr,value) of the big RW mapped regions
//   memscan <pid> follow <in.bin> <seconds-min> <seconds-max> <out.txt>
//                                                          re-read the snapshot addresses; keep those whose value grew by [min,max]
//   memscan <pid> find <hexpattern>                          all addresses of a byte pattern in the big regions
using System.Runtime.InteropServices;

static class K
{
    [DllImport("kernel32.dll", SetLastError = true)] public static extern IntPtr OpenProcess(uint access, bool inherit, int pid);
    [DllImport("kernel32.dll", SetLastError = true)] public static extern bool ReadProcessMemory(IntPtr h, IntPtr addr, byte[] buf, IntPtr size, out IntPtr read);
    [DllImport("kernel32.dll", SetLastError = true)] public static extern IntPtr VirtualQueryEx(IntPtr h, IntPtr addr, out MBI mbi, IntPtr len);
    [StructLayout(LayoutKind.Sequential)]
    public struct MBI { public IntPtr Base, AllocBase; public uint AllocProtect; public ushort Part; public UIntPtr Size; public uint State, Protect, Type; }
}

static class P
{
    static IntPtr h;

    static List<(long b, long s)> Regions(int count)
    {
        var l = new List<(long, long)>();
        long a = 0;
        while (K.VirtualQueryEx(h, (IntPtr)a, out var m, (IntPtr)Marshal.SizeOf<K.MBI>()) != IntPtr.Zero)
        {
            long b = (long)m.Base, s = (long)m.Size;
            if (m.State == 0x1000 && m.Type == 0x40000 && (m.Protect & 4) != 0 && s >= 256L << 20) l.Add((b, s));
            a = b + s;
            if (a >= 0x7FFFFFFFFFFF) break;
        }
        return l.OrderByDescending(x => x.Item2).Take(count).ToList();
    }

    static List<(long b, long s)> AllRegions()
    {
        var l = new List<(long, long)>();
        long a = 0;
        while (K.VirtualQueryEx(h, (IntPtr)a, out var m, (IntPtr)Marshal.SizeOf<K.MBI>()) != IntPtr.Zero)
        {
            long b = (long)m.Base, s = (long)m.Size;
            bool readable = (m.Protect & 0xEE) != 0 || (m.Protect & 0x02) != 0 || (m.Protect & 0x04) != 0;
            if (m.State == 0x1000 && (m.Protect & 0x101) == 0 && readable && s >= (1L << 20)) l.Add((b, s));
            a = b + s;
            if (a >= 0x7FFFFFFFFFFF) break;
        }
        return l;
    }

    static bool Read(long addr, byte[] buf, int n)
    {
        return K.ReadProcessMemory(h, (IntPtr)addr, buf, (IntPtr)n, out var got) && (long)got == n;
    }

    static int Main(string[] a)
    {
        int pid = int.Parse(a[0]);
        h = K.OpenProcess(0x0410, false, pid);
        if (h == IntPtr.Zero) { Console.WriteLine("cannot open"); return 1; }
        var regs = Regions(3);
        foreach (var r in regs) Console.WriteLine($"region {r.b:x} {r.s >> 20} MB");
        const int CH = 8 << 20;
        var buf = new byte[CH];
        if (a[1] == "counters")
        {
            uint lo = uint.Parse(a[2]), hi = uint.Parse(a[3]); int align = int.Parse(a[4]);
            using var w = new BinaryWriter(File.Create(a[5]));
            long n = 0;
            foreach (var (b, s) in regs)
                for (long off = 0; off < s; off += CH)
                {
                    int len = (int)Math.Min(CH, s - off);
                    if (!Read(b + off, buf, len)) continue;
                    for (int i = 0; i + 4 <= len; i += align)
                    {
                        uint v = BitConverter.ToUInt32(buf, i);
                        if (v >= lo && v <= hi) { w.Write(b + off + i); w.Write(v); n++; }
                    }
                }
            Console.WriteLine($"candidates {n}");
        }
        else if (a[1] == "follow")
        {
            long dmin = long.Parse(a[3]), dmax = long.Parse(a[4]);
            var lines = new List<string>();
            var b4 = new byte[4];
            using var r = new BinaryReader(File.OpenRead(a[2]));
            long n = 0, kept = 0;
            while (r.BaseStream.Position < r.BaseStream.Length)
            {
                long addr = r.ReadInt64(); uint v0 = r.ReadUInt32(); n++;
                if (!Read(addr, b4, 4)) continue;
                long v1 = BitConverter.ToUInt32(b4, 0);
                if (v1 - v0 >= dmin && v1 - v0 <= dmax) { kept++; lines.Add($"{addr:x} {v0} {v1}"); }
            }
            File.WriteAllLines(a[5], lines);
            Console.WriteLine($"checked {n}, grew {dmin}..{dmax}: {kept}");
        }
        else if (a[1] == "findall")
        {
            var pat = Convert.FromHexString(a[2]);
            long total = 0;
            foreach (var (b, s) in AllRegions())
            {
                total += s;
                for (long off = 0; off < s; off += CH - pat.Length)
                {
                    int len = (int)Math.Min(CH, s - off);
                    if (!Read(b + off, buf, len)) continue;
                    var span = new ReadOnlySpan<byte>(buf, 0, len);
                    int idx = 0;
                    while (true)
                    {
                        int f = span.Slice(idx).IndexOf(pat);
                        if (f < 0) break;
                        Console.WriteLine($"{b + off + idx + f:x} (region {b:x} {s >> 20}MB)");
                        idx += f + 1;
                    }
                }
            }
            Console.WriteLine($"scanned {total >> 20} MB");
        }
        else if (a[1] == "find")
        {
            var pat = Convert.FromHexString(a[2]);
            foreach (var (b, s) in regs)
                for (long off = 0; off < s; off += CH - pat.Length)
                {
                    int len = (int)Math.Min(CH, s - off);
                    if (!Read(b + off, buf, len)) continue;
                    var span = new ReadOnlySpan<byte>(buf, 0, len);
                    int idx = 0;
                    while (true)
                    {
                        int f = span.Slice(idx).IndexOf(pat);
                        if (f < 0) break;
                        Console.WriteLine($"{b + off + idx + f:x}");
                        idx += f + 1;
                    }
                }
        }
        return 0;
    }
}
