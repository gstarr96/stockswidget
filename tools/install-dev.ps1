<#
.SYNOPSIS
    Links the repo's skin into Rainmeter's Skins folder for development.

.DESCRIPTION
    Creates a directory junction so Rainmeter loads the skin straight from this
    repo: edits show up after a skin refresh, with no copying. Then refreshes
    Rainmeter and loads the widget.

.PARAMETER Force
    Replace an existing Skins\AIStockNews folder. A real folder is renamed to a
    timestamped backup, never deleted.
#>
[CmdletBinding()]
param([switch]$Force)

$ErrorActionPreference = 'Stop'
$SkinName = 'AIStockNews'

$repoSkin = (Resolve-Path (Join-Path $PSScriptRoot "..\Skins\$SkinName")).Path

$skinsPath = Join-Path ([Environment]::GetFolderPath('MyDocuments')) 'Rainmeter\Skins'
$rainmeterIni = Join-Path $env:APPDATA 'Rainmeter\Rainmeter.ini'
if (Test-Path $rainmeterIni) {
    $match = Select-String -Path $rainmeterIni -Pattern '^SkinPath=(.+)$' | Select-Object -First 1
    if ($match) { $skinsPath = $match.Matches[0].Groups[1].Value.TrimEnd('\') }
}
New-Item -ItemType Directory -Force -Path $skinsPath | Out-Null
$link = Join-Path $skinsPath $SkinName

if (Test-Path $link) {
    $item = Get-Item $link -Force
    $isJunction = $item.LinkType -eq 'Junction'
    if ($isJunction -and (@($item.Target) -contains $repoSkin)) {
        Write-Host "Already linked: $link -> $repoSkin"
    }
    elseif (-not $Force) {
        throw "$link already exists. Re-run with -Force to replace it (real folders are backed up)."
    }
    elseif ($isJunction) {
        [System.IO.Directory]::Delete($link)
    }
    else {
        $backup = "$link.backup-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
        Rename-Item -Path $link -NewName (Split-Path $backup -Leaf)
        Write-Host "Existing folder moved to $backup"
    }
}

if (-not (Test-Path $link)) {
    New-Item -ItemType Junction -Path $link -Target $repoSkin | Out-Null
    Write-Host "Linked $link -> $repoSkin"
}

$rainmeter = Join-Path $env:ProgramFiles 'Rainmeter\Rainmeter.exe'
if (Test-Path $rainmeter) {
    & $rainmeter '!RefreshApp'
    Start-Sleep -Seconds 2
    & $rainmeter '!ActivateConfig' $SkinName "$SkinName.ini"
    Write-Host 'Rainmeter refreshed and the widget loaded.'
}
else {
    Write-Warning 'Rainmeter.exe not found. Load the skin manually from the Rainmeter manager.'
}
