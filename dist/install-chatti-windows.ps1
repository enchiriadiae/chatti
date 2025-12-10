# install-chatti.ps1
# Einfacher Installer für Chatti unter Windows
# - sucht eine passende Python-Version (>= 3.12)
# - legt eine venv unter %LOCALAPPDATA%\chatti-venv an (falls nötig)
# - installiert das Wheel dort hinein
# - kann optional den Pfad zur venv in den Benutzer-PATH eintragen

$ErrorActionPreference = "Stop"

Write-Host ">>> Chatti-Installation für Windows (Wheel)" -ForegroundColor Cyan

# 1) Python suchen (bevorzugt py-Launcher)
$pythonCandidates = @(
    "py -3.12",
    "py -3",
    "python",
    "python3"
)

$pyCmd = $null
foreach ($cmd in $pythonCandidates) {
    try {
        $first = $cmd.Split(" ")[0]
        if (Get-Command $first -ErrorAction SilentlyContinue) {
            $pyCmd = $cmd
            break
        }
    } catch {
        # ignore
    }
}

if (-not $pyCmd) {
    Write-Host "❌ Kein Python gefunden." -ForegroundColor Red
    Write-Host "   Bitte installiere zuerst Python 3.12 oder neuer:"
    Write-Host "   https://www.python.org/downloads/" -ForegroundColor Yellow
    exit 1
}

Write-Host "→ Verwende Python-Befehl: $pyCmd"

# 2) Version prüfen (mindestens 3.12)
$pyVersion = & $pyCmd -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"

try {
    $verObj = [version]$pyVersion
} catch {
    Write-Host "❌ Konnte Python-Version nicht auswerten: '$pyVersion'" -ForegroundColor Red
    exit 1
}

$minVersion = [version]"3.12"
if ($verObj -lt $minVersion) {
    Write-Host "❌ Gefundene Python-Version ist $pyVersion – benötigt wird mindestens 3.12." -ForegroundColor Red
    Write-Host "   Bitte aktualisiere Python: https://www.python.org/downloads/" -ForegroundColor Yellow
    exit 1
}

Write-Host "→ Python-Version ok: $pyVersion"

# 3) Wheel lokalisieren (im selben Ordner wie dieses Script)
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$wheelName = "chatti_client-0.9.1-py3-none-any.whl"
$wheelPath = Join-Path $scriptDir $wheelName

if (-not (Test-Path $wheelPath)) {
    Write-Host "❌ Konnte Wheel-Datei nicht finden:" -ForegroundColor Red
    Write-Host "   $wheelPath"
    Write-Host "   Bitte lege $wheelName in dasselbe Verzeichnis wie dieses Script." -ForegroundColor Yellow
    exit 1
}

Write-Host "→ Gefundenes Wheel: $wheelPath"

# 4) Prüfen, ob wir schon in einer venv sind
$inVenv = & $pyCmd -c "import sys; print('1' if sys.prefix != getattr(sys, 'base_prefix', sys.prefix) else '0')"

if ($inVenv -eq "1") {
    Write-Host "↪ Virtuelle Umgebung erkannt – installiere Chatti in die aktive venv …"
    & $pyCmd -m pip install --upgrade pip
    & $pyCmd -m pip install "$wheelPath"

    Write-Host ""
    Write-Host "✅ Fertig! Starte Chatti jetzt mit:" -ForegroundColor Green
    Write-Host "   chatti --help"
    exit 0
}

# 5) Eigene venv im Benutzerbereich anlegen
#    Beispiel: C:\Users\<Name>\AppData\Local\chatti-venv
$venvDir = Join-Path $env:LOCALAPPDATA "chatti-venv"
$venvPython = Join-Path $venvDir "Scripts\python.exe"
$venvScripts = Join-Path $venvDir "Scripts"

if (-not (Test-Path $venvDir)) {
    Write-Host "↪ Keine venv gefunden – lege eigene Umgebung an:"
    Write-Host "   → Erzeuge venv unter: $venvDir"
    & $pyCmd -m venv "$venvDir"
} else {
    Write-Host "↪ Verwende vorhandene venv unter: $venvDir"
}

if (-not (Test-Path $venvPython)) {
    Write-Host "❌ Konnte python.exe in der venv nicht finden:" -ForegroundColor Red
    Write-Host "   $venvPython"
    exit 1
}

Write-Host "   → Aktualisiere pip in der venv …"
& $venvPython -m pip install --upgrade pip

Write-Host "   → Installiere Chatti in der venv …"
& $venvPython -m pip install "$wheelPath"

Write-Host ""
Write-Host "✅ Installation abgeschlossen!" -ForegroundColor Green
Write-Host "   Du kannst Chatti jetzt so starten:"
Write-Host "     `"$venvScripts\chatti.exe`" --help"
Write-Host ""

# 6) Optional: venv-Scripts-Verzeichnis in den Benutzer-PATH eintragen
$answer = Read-Host "   Chatti dauerhaft zum Benutzer-PATH hinzufügen, so dass 'chatti' überall funktioniert? (y/N)"
if ($answer -match '^[YyJj]') {
    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    if ($userPath -and ($userPath -split ';') -contains $venvScripts) {
        Write-Host "   → Pfad bereits im Benutzer-PATH eingetragen."
    } else {
        $newPath = if ($userPath) { "$userPath;$venvScripts" } else { $venvScripts }
        [Environment]::SetEnvironmentVariable("Path", $newPath, "User")
        Write-Host "   → Pfad hinzugefügt. In neuen Terminals reicht dann einfach: chatti"
    }
} else {
    Write-Host "   → Kein PATH-Eintrag vorgenommen."
}

Write-Host ""
Write-Host "   Hinweis: Öffne ein neues PowerShell- oder Terminal-Fenster, damit der PATH neu eingelesen wird."