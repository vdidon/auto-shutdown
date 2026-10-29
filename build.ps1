<#
.SYNOPSIS
    Builds the standalone auto-shutdown.exe executable.

.DESCRIPTION
    Regenerates the icon, then assembles a single executable with no console.
    The result is placed in dist\auto-shutdown.exe and does not depend on any
    Python installed on the target machine.

.PARAMETER OneDir
    Produces a folder instead of a single file. Startup is noticeably faster,
    because nothing is extracted to %TEMP% on each launch.

.EXAMPLE
    .\build.ps1
    .\build.ps1 -OneDir
#>
[CmdletBinding()]
param(
    [switch]$OneDir
)

$ErrorActionPreference = 'Stop'
Set-Location -Path $PSScriptRoot

Write-Host '==> Dependencies' -ForegroundColor Cyan
uv sync --group build

Write-Host '==> Icon' -ForegroundColor Cyan
uv run python tools/make_ico.py

Write-Host '==> Build' -ForegroundColor Cyan
$mode = if ($OneDir) { '--onedir' } else { '--onefile' }
uv run pyinstaller `
    --noconfirm `
    --clean `
    $mode `
    --windowed `
    --name auto-shutdown `
    --icon assets/auto-shutdown.ico `
    --add-data 'assets/auto-shutdown.ico;assets' `
    launcher.py

if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller failed (code $LASTEXITCODE)"
}

$exe = if ($OneDir) { 'dist\auto-shutdown\auto-shutdown.exe' } else { 'dist\auto-shutdown.exe' }
$size = [math]::Round((Get-Item $exe).Length / 1MB, 1)
Write-Host ''
Write-Host "==> $exe ($size MB)" -ForegroundColor Green
Write-Host 'To launch at sign-in: place a shortcut in shell:startup'
