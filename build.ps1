<#
.SYNOPSIS
    Construit l'exécutable autonome auto-shutdown.exe.

.DESCRIPTION
    Régénère l'icône, puis assemble un exécutable unique et sans console.
    Le résultat est déposé dans dist\auto-shutdown.exe et ne dépend d'aucun
    Python installé sur la machine cible.

.PARAMETER OneDir
    Produit un dossier au lieu d'un fichier unique. Le démarrage est nettement
    plus rapide, car rien n'est extrait dans %TEMP% à chaque lancement.

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

Write-Host '==> Dépendances' -ForegroundColor Cyan
uv sync --group build

Write-Host '==> Icône' -ForegroundColor Cyan
uv run python tools/make_ico.py

Write-Host '==> Assemblage' -ForegroundColor Cyan
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
    throw "PyInstaller a échoué (code $LASTEXITCODE)"
}

$exe = if ($OneDir) { 'dist\auto-shutdown\auto-shutdown.exe' } else { 'dist\auto-shutdown.exe' }
$size = [math]::Round((Get-Item $exe).Length / 1MB, 1)
Write-Host ''
Write-Host "==> $exe ($size Mo)" -ForegroundColor Green
Write-Host 'Pour lancer au démarrage de session : placer un raccourci dans shell:startup'
