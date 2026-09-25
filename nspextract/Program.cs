using System.Text.RegularExpressions;
using LibHac;
using LibHac.Common;
using LibHac.Common.Keys;
using LibHac.Fs;
using LibHac.Fs.Fsa;
using LibHac.FsSystem;
using LibHac.Spl;
using LibHac.Tools.Es;
using Path = System.IO.Path;
using LibHac.Tools.Fs;
using LibHac.Tools.FsSystem;
using LibHac.Tools.FsSystem.NcaUtils;

// nspextract: pull the RomFS of a Switch title (base NSP + optional update NSP) out of NSPs using prod.keys.
//   nspextract ncas   <nsp>
//   nspextract list   --base <nsp> [--update <nsp>] [--filter <regex>] [--dlc <nsp>]
//   nspextract extract --base <nsp> [--update <nsp>] [--dlc <nsp>] --out <dir> [--filter <regex>]
//   nspextract exefs  --base <nsp> [--update <nsp>] --out <dir>
static class P
{
    static string Keys = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData), "Ryujinx", "system", "prod.keys");
    static string TitleKeys = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData), "Ryujinx", "system", "title.keys");

    static KeySet MakeKeys()
    {
        var ks = ExternalKeyReader.ReadKeyFile(Keys, TitleKeys);
        return ks;
    }

    static PartitionFileSystem OpenNsp(string path)
    {
        var storage = new LocalStorage(path, FileAccess.Read);
        var pfs = new PartitionFileSystem();
        pfs.Initialize(storage).ThrowIfFailure();
        return pfs;
    }

    static void ImportTickets(KeySet ks, PartitionFileSystem pfs)
    {
        foreach (var e in pfs.EnumerateEntries("/", "*.tik"))
        {
            using var f = new UniqueRef<IFile>();
            pfs.OpenFile(ref f.Ref, e.FullPath.ToU8Span(), OpenMode.Read).ThrowIfFailure();
            var tik = new Ticket(new BinaryReader(f.Get.AsStream()));
            var key = tik.GetTitleKey(ks);
            if (key != null)
                ks.ExternalKeySet.Add(new RightsId(tik.RightsId), new AccessKey(key)).ThrowIfFailure();
        }
    }

    static List<(Nca nca, string name)> LoadNcas(KeySet ks, PartitionFileSystem pfs)
    {
        ImportTickets(ks, pfs);
        var list = new List<(Nca, string)>();
        foreach (var e in pfs.EnumerateEntries("/", "*.nca"))
        {
            var f = new UniqueRef<IFile>();
            pfs.OpenFile(ref f.Ref, e.FullPath.ToU8Span(), OpenMode.Read).ThrowIfFailure();
            try
            {
                var nca = new Nca(ks, f.Release().AsStorage());
                list.Add((nca, e.Name));
            }
            catch (Exception ex) { Console.Error.WriteLine($"skip {e.Name}: {ex.Message}"); }
        }
        return list;
    }

    static Dictionary<string, List<string>> ParseArgs(string[] a, int start)
    {
        var d = new Dictionary<string, List<string>>();
        for (int i = start; i < a.Length; i++)
        {
            if (a[i].StartsWith("--"))
            {
                var k = a[i].Substring(2);
                if (!d.ContainsKey(k)) d[k] = new();
                if (i + 1 < a.Length && !a[i + 1].StartsWith("--")) { d[k].Add(a[++i]); }
            }
        }
        return d;
    }

    static IFileSystem OpenRomfs(KeySet ks, string basePath, string? updatePath, IntegrityCheckLevel level = IntegrityCheckLevel.None)
    {
        var basePfs = OpenNsp(basePath);
        var baseNcas = LoadNcas(ks, basePfs);
        var baseMain = baseNcas.Where(n => n.nca.Header.ContentType == NcaContentType.Program).OrderByDescending(n => n.nca.Header.NcaSize).First().nca;
        if (updatePath == null)
            return baseMain.OpenFileSystem(NcaSectionType.Data, level);
        var updPfs = OpenNsp(updatePath);
        var updNcas = LoadNcas(ks, updPfs);
        var updMain = updNcas.Where(n => n.nca.Header.ContentType == NcaContentType.Program).OrderByDescending(n => n.nca.Header.NcaSize).First().nca;
        return baseMain.OpenFileSystemWithPatch(updMain, NcaSectionType.Data, level);
    }

    static IEnumerable<(string path, long size)> Enumerate(IFileSystem fs)
    {
        foreach (var e in fs.EnumerateEntries("/", "*", SearchOptions.RecurseSubdirectories))
            if (e.Type == DirectoryEntryType.File) yield return (e.FullPath, e.Size);
    }

    static void CopyOut(IFileSystem fs, string path, string outDir)
    {
        var dest = Path.Combine(outDir, path.TrimStart('/').Replace('/', Path.DirectorySeparatorChar));
        Directory.CreateDirectory(Path.GetDirectoryName(dest)!);
        using var f = new UniqueRef<IFile>();
        fs.OpenFile(ref f.Ref, path.ToU8Span(), OpenMode.Read).ThrowIfFailure();
        f.Get.GetSize(out long size).ThrowIfFailure();
        using var o = File.Create(dest);
        var buf = new byte[1 << 20];
        long off = 0;
        while (off < size)
        {
            f.Get.Read(out long read, off, buf.AsSpan(0, (int)Math.Min(buf.Length, size - off)), ReadOption.None).ThrowIfFailure();
            if (read <= 0) break;
            o.Write(buf, 0, (int)read);
            off += read;
        }
    }

    static int Main(string[] args)
    {
        if (args.Length == 0) { Console.WriteLine("usage: ncas|list|extract|exefs ..."); return 1; }
        var ks = MakeKeys();
        var cmd = args[0];
        if (cmd == "ncas")
        {
            var pfs = OpenNsp(args[1]);
            foreach (var (nca, name) in LoadNcas(ks, pfs))
                Console.WriteLine($"{name}  type={nca.Header.ContentType}  tid={nca.Header.TitleId:X16}  size={nca.Header.NcaSize}  rightsId={Convert.ToHexString(nca.Header.RightsId.ToArray())}");
            return 0;
        }
        var o = ParseArgs(args, 1);
        var basePath = o["base"][0];
        var updPath = o.ContainsKey("update") ? o["update"][0] : null;
        Regex? filt = o.ContainsKey("filter") && o["filter"].Count > 0 ? new Regex(o["filter"][0], RegexOptions.IgnoreCase) : null;
        if (cmd == "exefs")
        {
            var basePfs = OpenNsp(basePath);
            var main = LoadNcas(ks, basePfs).Where(n => n.nca.Header.ContentType == NcaContentType.Program).OrderByDescending(n => n.nca.Header.NcaSize).First().nca;
            var efs = updPath == null ? main.OpenFileSystem(NcaSectionType.Code, IntegrityCheckLevel.None)
                                     : main.OpenFileSystemWithPatch(LoadNcas(ks, OpenNsp(updPath)).Where(n => n.nca.Header.ContentType == NcaContentType.Program).OrderByDescending(n => n.nca.Header.NcaSize).First().nca, NcaSectionType.Code, IntegrityCheckLevel.None);
            foreach (var (p, s) in Enumerate(efs)) { Console.WriteLine($"{s,12} {p}"); CopyOut(efs, p, o["out"][0]); }
            return 0;
        }

        if (cmd == "verify")
        {
            // Read every byte of the romfs through the NCA's hash tree and report files with invalid blocks.
            var fs0 = OpenRomfs(ks, basePath, updPath, IntegrityCheckLevel.ErrorOnInvalid);
            int badFiles = 0, files = 0; long badBlocks = 0;
            var buf = new byte[16384];
            foreach (var (p, s) in Enumerate(fs0))
            {
                files++;
                using var f = new UniqueRef<IFile>();
                fs0.OpenFile(ref f.Ref, p.ToU8Span(), OpenMode.Read).ThrowIfFailure();
                f.Get.GetSize(out long size).ThrowIfFailure();
                var badOffsets = new List<long>();
                for (long off = 0; off < size; off += buf.Length)
                {
                    int nb = (int)Math.Min(buf.Length, size - off);
                    try
                    {
                        var r = f.Get.Read(out long read, off, buf.AsSpan(0, nb), ReadOption.None);
                        if (r.IsFailure()) badOffsets.Add(off);
                    }
                    catch (Exception) { badOffsets.Add(off); }
                }
                if (badOffsets.Count > 0)
                {
                    badFiles++; badBlocks += badOffsets.Count;
                    Console.WriteLine($"BAD {p} size={size} badBlocks={badOffsets.Count} firstOffsets={string.Join(",", badOffsets.Take(3))}");
                }
                if (files % 500 == 0) Console.Error.WriteLine($"  verified {files} files...");
            }
            Console.WriteLine($"verified {files} files, {badFiles} damaged ({badBlocks} bad 16KiB blocks)");
            return 0;
        }

        if (cmd == "peek")
        {
            // copy a byte range of one romfs file: peek --base X [--update Y] --path /bf3.ard --offset N --length M --out FILE
            var fsP = OpenRomfs(ks, basePath, updPath);
            using var pf = new UniqueRef<IFile>();
            fsP.OpenFile(ref pf.Ref, o["path"][0].ToU8Span(), OpenMode.Read).ThrowIfFailure();
            long off0 = long.Parse(o["offset"][0]), len0 = long.Parse(o["length"][0]);
            using var po = File.Create(o["out"][0]);
            var pb = new byte[1 << 20];
            long done = 0;
            while (done < len0)
            {
                int want = (int)Math.Min(pb.Length, len0 - done);
                pf.Get.Read(out long got, off0 + done, pb.AsSpan(0, want), ReadOption.None).ThrowIfFailure();
                if (got <= 0) break;
                po.Write(pb, 0, (int)got);
                done += got;
            }
            Console.WriteLine($"wrote {done} bytes");
            return 0;
        }
        IFileSystem fs;
        if (o.ContainsKey("dlc"))
        {
            // DLC NSP: a Data NCA holding its own romfs
            var pfs = OpenNsp(o["dlc"][0]);
            var d = LoadNcas(ks, pfs).First(n => n.nca.Header.ContentType == NcaContentType.PublicData || n.nca.Header.ContentType == NcaContentType.Data).nca;
            fs = d.OpenFileSystem(NcaSectionType.Data, IntegrityCheckLevel.None);
        }
        else fs = OpenRomfs(ks, basePath, updPath);
        long total = 0; int n = 0;
        foreach (var (p, s) in Enumerate(fs))
        {
            if (filt != null && !filt.IsMatch(p)) continue;
            n++; total += s;
            if (cmd == "list") Console.WriteLine($"{s,12} {p}");
            else if (cmd == "extract")
            {
                CopyOut(fs, p, o["out"][0]);
                if (n % 200 == 0) Console.Error.WriteLine($"  {n} files, {total / 1048576} MB...");
            }
        }
        Console.Error.WriteLine($"{n} files, {total / 1048576} MB");
        return 0;
    }
}
