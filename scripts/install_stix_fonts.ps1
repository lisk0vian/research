# install_stix_fonts.ps1 — install the fonts the elsevier-cas PDF uses into the
# current user's Windows Fonts (no admin rights needed), so Word renders the
# DOCX with the same faces and metrics as the PDF:
#
#   STIX (text)          body, headings, front matter (cas-sc.cls uses stix)
#   STIX Math            equations (Word's OMML math font)
#   LM Sans 9 / 10       \sffamily\small: tables, captions, running heads;
#                        Latin Modern has the metrics of the cm-super
#                        SFSS0900/SFSX0900 fonts pdfTeX embeds
#   LM Mono 8 / 10       \ttfamily (emails, DOIs, URLs): cm-super SFTT0800
#
# Usage (from the repository root):
#   powershell -ExecutionPolicy Bypass -File scripts/install_stix_fonts.ps1
#
# The fonts are NOT redistributed by this repository: they are copied from the
# local TeX distribution (TinyTeX or MiKTeX). Word must be restarted afterwards.
# Re-running is safe: files already installed (and possibly in use) are kept.

$ErrorActionPreference = "Stop"

$roots = @(
  "$env:USERPROFILE\AppData\Roaming\TinyTeX\texmf-dist\fonts\opentype\public",
  "$env:ProgramFiles\MiKTeX\fonts\opentype\public",
  "$env:LOCALAPPDATA\Programs\MiKTeX\fonts\opentype\public"
)
$root = $roots | Where-Object { Test-Path (Join-Path $_ "stix") } | Select-Object -First 1
if (-not $root) {
  Write-Error "STIX OpenType fonts not found (looked in TinyTeX and MiKTeX)."
  exit 1
}

$fonts = @()
$fonts += Get-ChildItem (Join-Path $root "stix\STIX-*.otf")
$fonts += Get-ChildItem (Join-Path $root "stix\STIXMath-Regular.otf") -ErrorAction SilentlyContinue
foreach ($name in "lmsans9-regular", "lmsans9-oblique", "lmsans10-regular",
                  "lmsans10-bold", "lmsans10-oblique", "lmsans10-boldoblique",
                  "lmmono8-regular", "lmmono10-regular", "lmmono10-italic") {
  $f = Join-Path $root "lm\$name.otf"
  if (Test-Path $f) { $fonts += Get-Item $f } else { Write-Warning "missing $f" }
}

$dest = Join-Path $env:LOCALAPPDATA "Microsoft\Windows\Fonts"
New-Item -ItemType Directory -Force -Path $dest | Out-Null

$reg = "HKCU:\Software\Microsoft\Windows NT\CurrentVersion\Fonts"
if (-not (Test-Path $reg)) { New-Item -Path $reg -Force | Out-Null }

foreach ($f in $fonts) {
  $target = Join-Path $dest $f.Name
  if ((Test-Path $target) -and ((Get-Item $target).Length -eq $f.Length)) {
    Write-Host "kept      $($f.Name)"
  } else {
    Copy-Item $f.FullName $target -Force
    Write-Host "installed $($f.Name)"
  }
  # Entry name must be unique per file; Word reads the value as the file path.
  $entry = "$($f.BaseName) (TrueType)"
  New-ItemProperty -Path $reg -Name $entry -Value $target -PropertyType String -Force | Out-Null
}

Write-Host ""
Write-Host "Fonts installed for the current user. Restart Word to pick them up."
Write-Host "Families used by the DOCX template: 'STIX', 'STIX Math', 'LM Sans 9',"
Write-Host "'LM Sans 10', 'LM Mono 8', 'LM Mono 10' (fallback: Times New Roman)."
