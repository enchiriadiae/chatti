<#
chatti-start.ps1 — launcher for the Chatti TUI (Windows PowerShell)

#########################################################
#
# HINWEIS:
# -> Wenn PowerShell Scripts blockt:
#    Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
#
#########################################################

# -----------------------------------------------------------------------------
# README (Windows PowerShell) — chatti-start.ps1
#
# Start (im Projektordner):
#   .\chatti-start.ps1
#
# Optional: bestimmtes Python erzwingen:
#   $env:CHATTIPY="C:\Path\to\python.exe"
#   .\chatti-start.ps1
#
# Debug-Ausgabe:
#   $env:CHATTI_DEBUG="1"
#   .\chatti-start.ps1
#
# Wenn PowerShell Scripts blockiert (einmalig pro User):
#   Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
# -----------------------------------------------------------------------------

Usage:
  .\chatti-start.ps1 [args...]

Optional:
  $env:CHATTIPY="C:\Path\to\python.exe"; .\chatti-start.ps1
  $env:CHATTI_DEBUG="1"; .\chatti-start.ps1
#>

$ErrorActionPreference = "Stop"
if ($env:CHATTI_DEBUG -eq "1") { Set-PSDebug -Trace 1 }

function Die($msg) { Write-Error "❌ $msg"; exit 1 }
function Log($msg) { Write-Host $msg }

$ROOT = Split-Path -Parent $MyInvocation.MyCommand.Path
$VENV_DIR = Join-Path $ROOT ".venv"
$VENV_PY  = Join-Path $VENV_DIR "Scripts\python.exe"

function Get-FileHashHex($Path) {
  if (-not (Test-Path $Path)) { return $null }
  return (Get-FileHash -Algorithm SHA256 -Path $Path).Hash.ToLower()
}

function Pick-Python {
  if ($env:CHATTIPY) {
    if (-not (Test-Path $env:CHATTIPY)) { Die "CHATTIPY is set but not found: $env:CHATTIPY" }
    return $env:CHATTIPY
  }

  # Try python3 first, then python
  $cmd = Get-Command python3 -ErrorAction SilentlyContinue
  if ($cmd) { return $cmd.Source }

  $cmd = Get-Command python -ErrorAction SilentlyContinue
  if ($cmd) { return $cmd.Source }

  Die "No 'python3' or 'python' found. Install Python 3.12+ and ensure it's in PATH."
}

function Assert-PythonVersion($PyPath) {
  $pyver = & $PyPath -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
  $parts = $pyver.Split(".")
  $major = [int]$parts[0]
  $minor = [int]$parts[1]
  if (($major -lt 3) -or (($major -eq 3) -and ($minor -lt 12))) {
    Die "Gefundene Python-Version ist $pyver (via: $PyPath) – benötigt wird mindestens 3.12."
  }
}

function Ensure-Venv($PyPath) {
  if (-not (Test-Path $VENV_DIR)) {
    Log "🐍 No .venv found — creating one with: $PyPath"
    & $PyPath -m venv $VENV_DIR
  }

  if (-not (Test-Path $VENV_PY)) {
    Log "⚠️  .venv seems broken — recreating…"
    Remove-Item -Recurse -Force $VENV_DIR
    & $PyPath -m venv $VENV_DIR
  }

  & $VENV_PY -m pip install --upgrade pip setuptools wheel | Out-Null
}

function Install-RequirementsIfNeeded {
  $reqFile = Join-Path $ROOT "requirements.txt"
  if (-not (Test-Path $reqFile)) { return }

  $stamp = Join-Path $VENV_DIR ".requirements.stamp"
  $newHash = Get-FileHashHex $reqFile
  $oldHash = if (Test-Path $stamp) { (Get-Content $stamp -Raw).Trim() } else { "" }

  if ($newHash -ne $oldHash) {
    Log "📦 Installing requirements.txt (changed)…"
    & $VENV_PY -m pip install -r $reqFile
    Set-Content -Path $stamp -Value $newHash -NoNewline
  }


$PYBIN = Pick-Python
Assert-PythonVersion $PYBIN
Ensure-Venv $PYBIN
Install-RequirementsIfNeeded

$env:PYTHONUTF8 = "1"
& $VENV_PY -m scripts.chatti_go @args
exit $LASTEXITCODE