#!/usr/bin/env bash
set -euo pipefail

# Verzeichnis des Scripts ermitteln
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
MANFILE="${SCRIPT_DIR}/../chatti/docs/man1/chatti.1"

if [[ ! -f "$MANFILE" ]]; then
  echo "Manpage nicht gefunden: $MANFILE" >&2
  exit 1
fi

# Wenn 'man' da ist: im Local-Mode (-l) anzeigen
if command -v man >/dev/null 2>&1; then
  # -l = „lies diese Datei, nicht aus MANPATH“
  MANPAGER="${MANPAGER:-less -R}" man -l "$MANFILE"
else
  # Fallback: direkt über groff rendern
  if command -v groff >/dev/null 2>&1; then
    groff -Tutf8 -man "$MANFILE" | less -R
  else
    echo "Weder 'man' noch 'groff' verfügbar – zeige Rohdatei:" >&2
    cat "$MANFILE"
  fi
fi
