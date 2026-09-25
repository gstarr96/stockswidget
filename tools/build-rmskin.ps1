<#
.SYNOPSIS
    Builds dist\AIStockNews_<version>.rmskin, the installer users double-click.

.DESCRIPTION
    An .rmskin file is a zip archive (RMSKIN.ini + Skins\...) followed by a
    16-byte footer: the archive size as a little-endian int64, a flags byte,
    and the ASCII key "RMSKIN" plus a NUL. Runtime data and caches are excluded.
#>
[CmdletBinding()]
param([string]$OutputDir)

$ErrorActionPreference = 'Stop'
if (-not $OutputDir) { $OutputDir = Join-Path $PSScriptRoot '..\dist' }
Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem

$SkinName = 'AIStockNews'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$skinDir = Join-Path $repoRoot "Skins\$SkinName"

$versionFile = Join-Path $skinDir '@Resources\backend\stocknews\__init__.py'
$versionMatch = Select-String -Path $versionFile -Pattern '__version__ = "([^"]+)"'
if (-not $versionMatch) { throw "Could not read __version__ from $versionFile" }
$version = $versionMatch.Matches[0].Groups[1].Value

New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
$OutputDir = (Resolve-Path $OutputDir).Path
$staging = Join-Path $OutputDir 'staging'
if (Test-Path $staging) { Remove-Item -Recurse -Force $staging }
$stagedSkin = Join-Path $staging "Skins\$SkinName"
New-Item -ItemType Directory -Force -Path $stagedSkin | Out-Null

$excludedDirs = @('data', '__pycache__')
Get-ChildItem -Path $skinDir -Recurse -File | Where-Object {
    $relative = $_.FullName.Substring($skinDir.Length + 1)
    $parts = $relative -split '\\'
    -not ($parts | Where-Object { $excludedDirs -contains $_ }) -and
    $_.Extension -notin @('.pyc', '.tmp', '.log') -and
    $_.Name -ne 'config.ini'
} | ForEach-Object {
    $relative = $_.FullName.Substring($skinDir.Length + 1)
    $destination = Join-Path $stagedSkin $relative
    New-Item -ItemType Directory -Force -Path (Split-Path $destination) | Out-Null
    Copy-Item -Path $_.FullName -Destination $destination
}

$rmskinIni = @"
[rmskin]
Name=AI Stock News
Author=gstarr96
Version=$version
MinimumRainmeter=4.5.0
MinimumWindows=10.0
LoadType=Skin
Load=$SkinName\$SkinName.ini
VariableFiles=$SkinName\@Resources\Variables.inc
"@
[System.IO.File]::WriteAllText((Join-Path $staging 'RMSKIN.ini'), ($rmskinIni -replace "`r?`n", "`r`n"))

$zipPath = Join-Path $OutputDir "${SkinName}_$version.zip"
$rmskinPath = Join-Path $OutputDir "${SkinName}_$version.rmskin"
Remove-Item -Force -ErrorAction SilentlyContinue $zipPath, $rmskinPath
$zip = [System.IO.Compression.ZipFile]::Open($zipPath, [System.IO.Compression.ZipArchiveMode]::Create)
try {
    # Explicit entries so paths use '/' as the zip spec requires, whichever PowerShell runs this.
    Get-ChildItem -Path $staging -Recurse -File | ForEach-Object {
        $entryName = $_.FullName.Substring($staging.Length + 1).Replace('\', '/')
        [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile($zip, $_.FullName, $entryName) | Out-Null
    }
}
finally { $zip.Dispose() }

$zipSize = (Get-Item $zipPath).Length
$footer = New-Object byte[] 16
[BitConverter]::GetBytes([int64]$zipSize).CopyTo($footer, 0)
$footer[8] = 0
[System.Text.Encoding]::ASCII.GetBytes("RMSKIN").CopyTo($footer, 9)

$stream = [System.IO.File]::Open($zipPath, [System.IO.FileMode]::Append)
try { $stream.Write($footer, 0, $footer.Length) } finally { $stream.Dispose() }

Move-Item -Path $zipPath -Destination $rmskinPath
Remove-Item -Recurse -Force $staging
Write-Host "Built $rmskinPath"
