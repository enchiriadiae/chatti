#!/usr/bin/env bash
# Minimal-invasive Release-Prüfung für Chatti-Client
# - Ruff (nur sinnvolle Regeln)
# - Import-Smoketest
# - CLI-Hilfe
# - Doctor (ohne Tokenprobe)
# Optional per Flags:
#   --with-mypy        → mypy light
#   --with-probe       → Doctor + Mini-Probe (max_output_tokens=16)
#   --with-install     → fehlende Dev-Tools (ruff/mypy) on-the-fly installieren

set -Eeuo pipefail

WITH_MYPY=0
WITH_PROBE=0
WITH_INSTALL=0

for arg in "$@"; do
  case "$arg" in
    --with-mypy)    WITH_MYPY=1 ;;
    --with-probe)   WITH_PROBE=1 ;;
    --with-install) WITH_INSTALL=1 ;;
    *) echo "Unknown flag: $arg" >&2; exit 2 ;;
  esac
done

say()  { printf "\033[1;36m== %s ==\033[0m\n" "$*"; }
ok()   { printf "\033[1;32m✔ %s\033[0m\n" "$*"; }
warn() { printf "\033[1;33m⚠ %s\033[0m\n" "$*"; }
err()  { printf "\033[1;31m✖ %s\033[0m\n" "$*"; }

need() {
  if ! command -v "$1" >/dev/null 2>&1; then
    if [ "$WITH_INSTALL" -eq 1 ]; then
      say "Install $1"
      python -m pip install -q "$1"
    else
      warn "$1 not found (skip). Use --with-install to auto-install."
      return 1
    fi
  fi
  return 0
}

say "Python"
python -V || { err "Python not found"; exit 1; }

if need ruff; then
  say "Ruff"
  ruff check . --select F401,F821,F841,ARG,UP --fix
  ok "ruff passed"
fi

say "Import smoke"
python - <<'PY'
import sys
mods = [
  "core.paths",
  "core.security",
  "core.api",
  "core.attachments",
  "core.usage",
  "core.history",
  "core.pdf_utils",
  "core.tickets",
  "tools.chatti_doctor",
]
failed = []
for m in mods:
    try:
        __import__(m)
    except Exception as e:
        failed.append((m, f"{type(e).__name__}: {e}"))
if failed:
    for m, why in failed:
        print(f"[FAIL] import {m}: {why}")
    sys.exit(1)
print("imports ok")
PY
ok "imports ok"

say "CLI --help"
./chatti --help >/dev/null
ok "CLI help works"

say "Doctor (fast, no probe)"
# Begrenze Anzahl gelisteter Modelle und vermeide Tokenverbrauch
CHATTI_DOCTOR_MAX=15 ./chatti --doc --no-probe >/dev/null || warn "doctor (no-probe) returned nonzero"

if [ "$WITH_PROBE" -eq 1 ]; then
  say "Doctor (with probe: max_output_tokens=16)"
  CHATTI_DOCTOR_MAX=10 ./chatti --doc --probe >/dev/null || warn "doctor (probe) returned nonzero"
fi

if [ "$WITH_MYPY" -eq 1 ]; then
  if need mypy; then
    say "mypy (light)"
    mypy . --ignore-missing-imports --follow-imports=skip || warn "mypy warnings"
  fi
fi

say "Done"
