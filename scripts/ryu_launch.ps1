param([Parameter(Mandatory=$true)][string]$Game, [string]$Root = "F:\XCAP\work\ryu_root")
# Launch the user's Ryujinx build against an ISOLATED data root (never touches the user's own config/saves).
Get-Process Ryujinx -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowTitle -match "" -and $_.Path -like "D:\Emulators\ryujinx-1.3.3*" } | ForEach-Object { }
$p = Start-Process "D:\Emulators\ryujinx-1.3.3-win_x64\publish\Ryujinx.exe" -ArgumentList @("-r", "`"$Root`"", "`"$Game`"") -PassThru
Write-Output "pid=$($p.Id)"
