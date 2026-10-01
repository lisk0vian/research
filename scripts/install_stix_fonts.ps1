# install_stix_fonts.ps1 — install the STIX fonts that ship with TeX into the
# current user's Windows Fonts (no admin rights needed), so Word renders the
# elsevier-cas DOCX with the same typeface as the PDF (cas-sc.cls uses stix).
#
# Usage (from the repository root):
#   powershell -ExecutionPolicy Bypass -File scripts/install_stix_fonts.ps1
#
# The fonts are NOT redistributed by this repository: they are copied from the
# local TeX distribution (TinyTeX or MiKTeX). Word must be restarted afterwards.

$ErrorActionPreference = "Stop"

$candidates = @(
  "$env:USERPROFILE\AppData\Roaming\TinyTeX\texmf-dist\fonts\opentype\public\stix",
  "$env:ProgramFiles\MiKTeX\fonts\opentype\public\stix",
  "$env:LOCALAPPDATA\Programs\MiKTeX\fonts\opentype\public\stix"
)
$src = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $src) {
  Write-Error "STIX OpenType fonts not found (looked in TinyTeX and MiKTeX)."
  exit 1
}

$dest = Join-Path $env:LOCALAPPDATA "Microsoft\Windows\Fonts"
New-Item -ItemType Directory -Force -Path $dest | Out-Null

$reg = "HKCU:\Software\Microsoft\Windows NT\CurrentVersion\Fonts"
if (-not (Test-Path $reg)) { New-Item -Path $reg -Force | Out-Null }

$fonts = Get-ChildItem (Join-Path $src "STIX-*.otf")  # text fonts only; Word math uses Cambria Math
if (-not $fonts) { Write-Error "No STIX-*.otf under $src"; exit 1 }

foreach ($f in $fonts) {
  $target = Join-Path $dest $f.Name
  Copy-Item $f.FullName $target -Force
  # Entry name must be unique per file; Word reads the value as the file path.
  $entry = "$($f.BaseName) (TrueType)"
  New-ItemProperty -Path $reg -Name $entry -Value $target -PropertyType String -Force | Out-Null
  Write-Host "installed $($f.Name)"
}

Write-Host ""
Write-Host "STIX installed for the current user. Restart Word to pick the fonts up."
Write-Host "Family name used by the DOCX template: 'STIX' (fallback: Times New Roman)."
