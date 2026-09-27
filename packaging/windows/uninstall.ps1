# Removes what install.ps1 put down, and nothing else.
#
# The save is left alone on purpose: someone's Pokedex should not vanish
# because they uninstalled the viewer. Delete %APPDATA%\poketokenbar by hand to
# be rid of it.

$ErrorActionPreference = 'Stop'

$root = Join-Path $env:LOCALAPPDATA 'PokeTokenBar'
$startup = [Environment]::GetFolderPath('Startup')

foreach ($name in @('poketokend', 'poketokenbar')) {
  Get-Process -Name pythonw -ErrorAction SilentlyContinue |
    Where-Object { $_.Path -like "$root*" } | Stop-Process -Force
  Remove-Item -Force -ErrorAction SilentlyContinue (Join-Path $startup "$name.lnk")
}
# The Start Menu and Desktop shortcuts, which the login entries are not.
Remove-Item -Force -ErrorAction SilentlyContinue `
  (Join-Path ([Environment]::GetFolderPath('Programs')) 'PokeTokenBar.lnk')
Remove-Item -Force -ErrorAction SilentlyContinue `
  (Join-Path ([Environment]::GetFolderPath('Desktop')) 'PokeTokenBar.lnk')

Remove-Item -Recurse -Force -ErrorAction SilentlyContinue $root

Write-Host "removed $root, the login entries and the shortcuts."
Write-Host "your save is still at $env:APPDATA\poketokenbar — delete it by hand if you want it gone."
