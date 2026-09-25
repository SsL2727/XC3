param(
    [string]$Pack = "",
    [Parameter(Mandatory=$true)][string]$Out,
    [int]$Wait = 8,
    [string]$ApHost = "",
    [string]$ApSlot = "",
    [string]$Clicks = "",      # "x,y;x,y" in window-relative pixels, executed before the screenshot
    [string]$Size = "",       # e.g. 1700x1000: resize the window before the click/screenshot
    [switch]$NoLaunch
)
# Isolated PopTracker screenshot: uses a scratch copy of poptracker.exe (portable settings) so the user's own instance is untouched.
$src = "G:\Archipelago\poptracker"
$scratch = "F:\XCAP\work\pt_test"
if (-not (Test-Path "$scratch\poptracker.exe")) {
    New-Item -ItemType Directory -Force $scratch | Out-Null
    Copy-Item "$src\poptracker.exe" $scratch
    Copy-Item "$src\assets" $scratch -Recurse
    Set-Content "$scratch\portable.txt" "portable"
}
Add-Type @"
using System; using System.Runtime.InteropServices; using System.Drawing;
public class W {
  [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern bool SetWindowPos(IntPtr h, IntPtr after, int x, int y, int cx, int cy, uint flags);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int cmd);
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
  [DllImport("user32.dll")] public static extern void mouse_event(uint f, uint dx, uint dy, uint d, IntPtr e);
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int L, T, R, B; }
}
"@ -ReferencedAssemblies System.Drawing
Add-Type -AssemblyName System.Drawing
[W]::SetProcessDPIAware() | Out-Null

# kill only the scratch copy
if ($NoLaunch) {
    $p = Get-Process poptracker -ErrorAction SilentlyContinue | Where-Object { $_.Path -like "$scratch*" } | Select-Object -First 1
    if (-not $p) { Write-Output "NO RUNNING SCRATCH INSTANCE"; exit 1 }
} else {
    Get-Process poptracker -ErrorAction SilentlyContinue | Where-Object { $_.Path -like "$scratch*" } | Stop-Process -Force
    Start-Sleep -Milliseconds 500
    if (Test-Path "$scratch\portable-config-template") {   # clean config (update-check dialog answered, default window size)
        if (Test-Path "$scratch\portable-config") { Remove-Item -Recurse -Force "$scratch\portable-config" }
        Copy-Item "$scratch\portable-config-template" "$scratch\portable-config" -Recurse -Force
    }
    $args = @()
    if ($ApHost) { $args += @("--ap-host", $ApHost, "--ap-slot", $ApSlot) }
    $args += @($Pack)   # NOTE: the pack path must come after the options
    $p = Start-Process "$scratch\poptracker.exe" -ArgumentList $args -PassThru -WorkingDirectory $scratch
    Start-Sleep -Seconds $Wait
}
$p.Refresh()
$h = $p.MainWindowHandle
if ($h -eq [IntPtr]::Zero) { Write-Output "NO WINDOW"; $p | Stop-Process -Force; exit 1 }
[W]::ShowWindow($h, 9) | Out-Null
[W]::SetWindowPos($h, [IntPtr]::new(-1), 0, 0, 0, 0, 0x0043) | Out-Null   # HWND_TOPMOST, NOMOVE|NOSIZE|SHOWWINDOW
[W]::SetForegroundWindow($h) | Out-Null
if ($Size) {
    $wh = $Size.Split('x')
    [W]::SetWindowPos($h, [IntPtr]::new(-1), 20, 20, [int]$wh[0], [int]$wh[1], 0x0040) | Out-Null
    Start-Sleep -Seconds 2
}
Start-Sleep -Milliseconds 400
$r = New-Object W+RECT
[W]::GetWindowRect($h, [ref]$r) | Out-Null
if ($Clicks) {
    foreach ($c in $Clicks.Split(";")) {
        $xy = $c.Split(",")
        [W]::SetCursorPos($r.L + [int]$xy[0], $r.T + [int]$xy[1]) | Out-Null
        Start-Sleep -Milliseconds 150
        [W]::mouse_event(0x0002, 0, 0, 0, [IntPtr]::Zero); [W]::mouse_event(0x0004, 0, 0, 0, [IntPtr]::Zero)
        Start-Sleep -Milliseconds 700
    }
}
$w = $r.R - $r.L; $hh = $r.B - $r.T
$bmp = New-Object System.Drawing.Bitmap $w, $hh
$g = [System.Drawing.Graphics]::FromImage($bmp)
$g.CopyFromScreen($r.L, $r.T, 0, 0, (New-Object System.Drawing.Size $w, $hh))
$bmp.Save($Out, [System.Drawing.Imaging.ImageFormat]::Png)
$g.Dispose(); $bmp.Dispose()
Write-Output "saved $Out ($w x $hh)"
if (-not $env:PT_KEEP -and -not $NoLaunch) { $p | Stop-Process -Force }
