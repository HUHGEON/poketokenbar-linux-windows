# Installs PokeTokenBar on Windows: the daemon, the tray app, and a login entry.
#
# Everything lands under the user's profile. Nothing here needs an
# administrator, and nothing is written outside %LOCALAPPDATA% and the
# per-user Startup folder.
#
#   powershell -ExecutionPolicy Bypass -File packaging\windows\install.ps1

$ErrorActionPreference = 'Stop'

$repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$root = Join-Path $env:LOCALAPPDATA 'PokeTokenBar'
$app  = Join-Path $root 'app'
$venv = Join-Path $root 'venv'

Write-Host "==> installing to $root"
New-Item -ItemType Directory -Force -Path $app | Out-Null
Copy-Item -Recurse -Force (Join-Path $repo 'poketokenbar') $app

# The shortcut icon travels with the install: only the package directory is
# copied, so an icon left in the repo is one the shortcuts cannot point at
# once the repo is deleted — and a shortcut whose icon is missing silently
# falls back to the interpreter's.
$icon = Join-Path $root 'poketokenbar.ico'
Copy-Item -Force (Join-Path $PSScriptRoot 'poketokenbar.ico') $icon

# Which commit this install came from, so the app can tell whether GitHub has a
# newer one without carrying a git checkout around. Unknown is written as empty
# rather than guessed: an install that cannot say what it is must not be
# offered an update it cannot verify is newer.
$revision = ''
try { $revision = (& git -C $repo rev-parse HEAD 2>$null) } catch { }
if ($LASTEXITCODE -ne 0) { $revision = '' }
[IO.File]::WriteAllText((Join-Path $app 'REVISION'), "$revision".Trim())
Write-Host "    revision $(if ($revision) { $revision.Trim() } else { 'unknown' })"

Write-Host "==> creating venv"
if (-not (Test-Path $venv)) { python -m venv $venv }
$py = Join-Path $venv 'Scripts\python.exe'
& $py -m pip install --quiet --upgrade pip
# PySide6 is the tray application; orjson is an optional parsing speedup.
& $py -m pip install --quiet PySide6-Essentials
& $py -m pip install --quiet orjson

# pythonw, not python: the console host would otherwise flash a black window
# every time either process starts.
$pyw = Join-Path $venv 'Scripts\pythonw.exe'

# A .vbs shim rather than a .bat: Windows shows a console window for a batch
# file even when what it starts has no console of its own.
#
# Built from a single-quoted here-string and Replace, never by interpolation.
# VBScript escapes a quote inside a string by doubling it, so the Run line needs
# `"""..."" -m ..."` — three quotes, then two. Interpolating the path into that
# is how the first version shipped one quote short and every launch died with
# "Expected end of statement".
$vbsTemplate = @'
Set shell = CreateObject("WScript.Shell")
shell.Environment("Process")("PYTHONPATH") = "__APP__"
shell.Run """__PYW__"" -m __MODULE__", 0, False
'@

$launchers = @{
  'poketokend.vbs'   = 'poketokenbar.daemon'
  'poketokenbar.vbs' = 'poketokenbar.ui.app'
}

foreach ($name in $launchers.Keys) {
  $target = Join-Path $root $name
  $vbsTemplate.
    Replace('__APP__', $app).
    Replace('__PYW__', $pyw).
    Replace('__MODULE__', $launchers[$name]) |
    Set-Content -Encoding ASCII $target
  Write-Host "    wrote $target"
}

# The icon the shortcuts wear — the companion's own egg, built by
# tools/make_icon.py and committed, so installing needs no network for it.
if (-not (Test-Path $icon)) { $icon = $pyw }

function New-Shortcut($path, $target, $iconPath) {
  $shortcut = (New-Object -ComObject WScript.Shell).CreateShortcut($path)
  $shortcut.TargetPath = $target
  $shortcut.WorkingDirectory = Split-Path $target
  $shortcut.IconLocation = "$iconPath,0"
  $shortcut.Description = 'PokeTokenBar'
  $shortcut.Save()
  Write-Host "    $path"
}

Write-Host "==> registering both at login"
$startup = [Environment]::GetFolderPath('Startup')
foreach ($name in $launchers.Keys) {
  New-Shortcut (Join-Path $startup ($name -replace '\.vbs$', '.lnk')) `
               (Join-Path $root $name) $icon
}

# Somewhere to start it by hand. Without these the only way back after
# quitting the tray was to open PowerShell and run the installer again.
Write-Host "==> making shortcuts"
$programs = Join-Path ([Environment]::GetFolderPath('Programs')) 'PokeTokenBar.lnk'
$desktop = Join-Path ([Environment]::GetFolderPath('Desktop')) 'PokeTokenBar.lnk'
foreach ($link in @($programs, $desktop)) {
  # Starts the tray, which is the half with a window; the daemon is already
  # running from login and starting a second one is harmless but pointless.
  New-Shortcut $link (Join-Path $root 'poketokenbar.vbs') $icon
}

Write-Host "==> starting"
foreach ($name in $launchers.Keys) {
  Start-Process -FilePath (Join-Path $root $name)
}

Write-Host ""
Write-Host "done. The companion is in the notification area."
Write-Host "state file: $env:APPDATA\poketokenbar\state.json"
