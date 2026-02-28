#!/usr/bin/env bash
# scripts/run_all.sh — One-command QA for Chatti
# Runs lint, format, (optional) tests, and smoke checks.
# Usage: ./scripts/run_all.sh
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "== Python =="$(python3 --version || true)
echo "== PWD     =="$PWD

# Try to activate venv if present
if [[ -f ".venv/bin/activate" ]]; then
  echo "== Activating .venv =="
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

# 1) Ruff lint (focused rules only) + auto-fix
echo "== Ruff check (focused rules) =="
ruff --version || { echo "Ruff not found. pip install ruff"; exit 1; }
ruff check . --select F401,F821,F841,ARG,UP --fix

# 2) Ruff format (like black)
echo "== Ruff format =="
ruff format .

# 3) Optional: pytest if tests exist and pytest is installed
if [[ -d "tests" ]]; then
  if python -c "import pytest" 2>/dev/null; then
    echo "== Pytest =="
    pytest -q || { echo 'pytest reported failures'; exit 1; }
  else
    echo "(skip) pytest not installed"
  fi
else
  echo "(skip) tests/ not found"
fi

# 4) Release smoke (if available)
if [[ -x "scripts/release_smoke.sh" ]]; then
  echo "== Release smoke =="
  bash scripts/release_smoke.sh
else
  echo "(skip) scripts/release_smoke.sh not found or not executable"
fi

# 5) Doctor quick pass (no token probe)
if [[ -f "scripts/chatti_go.py" ]]; then
  echo "== Doctor (fast, no probe) =="
  CHATTI_DOCTOR_NO_PROBE=1 python -X utf8 scripts/chatti_go.py --doc || true
else
  echo "(skip) scripts/chatti_go.py not found"
fi

# 6) Optional build (if pyproject exists and 'build' is installed)
if [[ -f "pyproject.toml" ]]; then
  if python -c "import build" 2>/dev/null; then
    echo "== Build (sdist+wheel) =="
    python -m build
  else
    echo "(skip) python-build not installed (pip install build)"
  fi
else
  echo "(skip) pyproject.toml not found"
fi

echo "== All done ✅ =="
