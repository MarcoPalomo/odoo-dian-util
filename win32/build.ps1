#Requires -Version 5.1
<#
.SYNOPSIS
  Build RUT Pipeline.exe pour Windows 10/11.

.DESCRIPTION
  - Crée ou réutilise le venv Python à la racine du projet (.venv)
  - Installe les dépendances (pyproject.toml) + PyInstaller
  - Génère icon.ico
  - Lance PyInstaller → dist\RUT Pipeline\RUT Pipeline.exe
  - Crée un raccourci sur le Bureau

.PARAMETER Action
  build   (défaut) — build complet
  run     — lancer en mode dev sans build
  clean   — supprimer build/ dist/ icon.ico

.EXAMPLE
  .\build.ps1
  .\build.ps1 run
  .\build.ps1 clean
#>

param(
    [ValidateSet("build", "run", "clean")]
    [string]$Action = "build"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$WIN32 = $PSScriptRoot
$ROOT  = (Resolve-Path "$WIN32\..").Path
$VENV  = "$ROOT\.venv"
$PY    = "$VENV\Scripts\python.exe"
$PIP   = "$VENV\Scripts\pip.exe"
$PYI   = "$VENV\Scripts\pyinstaller.exe"

function Write-Step([string]$msg) {
    Write-Host ""
    Write-Host "  >> $msg" -ForegroundColor Cyan
}

function Assert-Python {
    # 1. Commandes dans le PATH
    foreach ($cmd in @("py", "python3", "python")) {
        if (Get-Command $cmd -ErrorAction SilentlyContinue) { return $cmd }
    }
    # 2. Installation MS Store / registre (HKCU et HKLM)
    foreach ($hive in @("HKCU", "HKLM")) {
        $keys = Get-ItemProperty "${hive}:\SOFTWARE\Python\PythonCore\*\InstallPath" -ErrorAction SilentlyContinue
        foreach ($key in @($keys)) {
            $exe = $key.ExecutablePath
            if ($exe -and (Test-Path $exe)) { return $exe }
        }
    }
    throw "Python 3.11+ introuvable.`nInstallez-le depuis https://python.org ou le Microsoft Store."
}

# ── clean ─────────────────────────────────────────────────────────────────────

if ($Action -eq "clean") {
    Write-Step "Nettoyage..."
    foreach ($path in @("$WIN32\build", "$WIN32\dist", "$WIN32\icon.ico")) {
        if (Test-Path $path) {
            Remove-Item -Recurse -Force $path
            Write-Host "  Supprimé : $path" -ForegroundColor DarkGray
        }
    }
    Write-Host ""
    Write-Host "  OK  Nettoyé." -ForegroundColor Green
    exit 0
}

# ── run (mode dev) ────────────────────────────────────────────────────────────

if ($Action -eq "run") {
    Write-Step "Lancement en mode dev..."
    if (-not (Test-Path $PY)) {
        throw "Venv introuvable — lancez d'abord : .\build.ps1 build"
    }
    & $PY "$WIN32\launcher.py"
    exit $LASTEXITCODE
}

# ── build ─────────────────────────────────────────────────────────────────────

Write-Host ""
Write-Host "  RUT Pipeline — Build Windows" -ForegroundColor White
Write-Host "  ==============================" -ForegroundColor DarkGray

# 1. Venv
if (-not (Test-Path $VENV)) {
    Write-Step "Création du venv Python..."
    $pythonCmd = Assert-Python
    & $pythonCmd -m venv $VENV
    Write-Host "  Venv créé : $VENV" -ForegroundColor DarkGray
} else {
    Write-Host ""
    Write-Host "  Venv existant : $VENV" -ForegroundColor DarkGray
}

# 2. Dépendances
Write-Step "Installation des dépendances..."
& $PIP install -q --upgrade pip
& $PIP install -q -r "$WIN32\requirements.txt"
& $PIP install -q pyinstaller

if ($LASTEXITCODE -ne 0) {
    throw "Echec pip install"
}

# 3. Icône
Write-Step "Génération de l'icône..."
Set-Location $WIN32
& $PY make_icon.py
if (-not (Test-Path "$WIN32\icon.ico")) {
    throw "icon.ico non généré"
}

# 4. PyInstaller
Write-Step "Build PyInstaller..."
& $PYI --noconfirm RUTPipeline.spec

if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller a échoué"
}

$EXE = "$WIN32\dist\RUT Pipeline\RUT Pipeline.exe"
if (-not (Test-Path $EXE)) {
    throw "Exécutable introuvable après build : $EXE"
}

# 5. Raccourci Bureau
Write-Step "Création du raccourci Bureau..."
try {
    $Desktop  = [System.Environment]::GetFolderPath("Desktop")
    $WScript  = New-Object -ComObject WScript.Shell
    $Shortcut = $WScript.CreateShortcut("$Desktop\RUT Pipeline.lnk")
    $Shortcut.TargetPath       = $EXE
    $Shortcut.WorkingDirectory = "$WIN32\dist\RUT Pipeline"
    $Shortcut.IconLocation     = $EXE
    $Shortcut.Description      = "RUT Pipeline — Industrias Pico"
    $Shortcut.Save()
    Write-Host "  Raccourci créé sur le Bureau." -ForegroundColor DarkGray
} catch {
    Write-Host "  (raccourci Bureau ignoré : $_)" -ForegroundColor DarkYellow
}

Write-Host ""
Write-Host "  OK  Build terminé !" -ForegroundColor Green
Write-Host ""
Write-Host "  Executable  : $EXE" -ForegroundColor Yellow
Write-Host "  Raccourci   : Bureau\RUT Pipeline.lnk" -ForegroundColor Yellow
Write-Host ""
Write-Host "  Avant le premier lancement, créez votre config :" -ForegroundColor White
Write-Host "    %APPDATA%\RUTPipeline\.env" -ForegroundColor Yellow
Write-Host "  (copiez win32\.env.example comme modèle)" -ForegroundColor DarkGray
Write-Host ""
