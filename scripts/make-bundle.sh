#!/usr/bin/env bash
set -euo pipefail

echo ">>> Chatti Release-Build (Wheel + sdist + Bundle-ZIP)"

# 1) Projektwurzel ermitteln (Verzeichnis, in dem pyproject.toml liegt)
PROJECT_ROOT="$(cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$PROJECT_ROOT"

# 2) Version aus pyproject.toml lesen
VERSION="$(
  python3 - << 'PY'
import pathlib, tomllib

py = pathlib.Path("pyproject.toml")
data = tomllib.loads(py.read_text(encoding="utf-8"))
print(data["project"]["version"])
PY
)"

echo "   → Gefundene Version: $VERSION"

# 3) dist/-Ordner neu aufsetzen
echo "   → Bereinige dist/-Ordner …"
rm -rf dist
mkdir -p dist

# 4) Wheel + sdist bauen (nutzt deine hatchling-Konfig)
echo "   → Baue Wheel + sdist mit: python -m build"
python3 -m build

# Erwartete Artefaktnamen
WHEEL="dist/chatti_client-${VERSION}-py3-none-any.whl"
SDIST="dist/chatti_client-${VERSION}.tar.gz"

if [[ ! -f "$WHEEL" || ! -f "$SDIST" ]]; then
  echo "❌ Konnte Wheel oder sdist nicht finden:"
  echo "   $WHEEL"
  echo "   $SDIST"
  exit 1
fi

echo "   → Gefundene Artefakte:"
echo "      - $WHEEL"
echo "      - $SDIST"

# 5) Install-/Uninstall-Skripte und kurze README in dist/ bereitstellen
#    (falls du sie im Repo z.B. unter scripts/ oder docs/ liegen hast)
# cp scripts/install-chatti.sh dist/
# cp scripts/uninstall-chatti.sh dist/
# cp docs/README-bundle.txt dist/README.txt

# 6) Bundle-ZIP bauen
BUNDLE="dist/chatti_client-${VERSION}-bundle.zip"
echo "   → Baue Bundle-ZIP: $BUNDLE"

# -j = flache Struktur im ZIP (keine Verzeichnispfade)
zip -j "$BUNDLE" \
  "$WHEEL" \
  "$SDIST" \
  dist/install-chatti.sh \
  dist/uninstall-chatti.sh \
  dist/README.txt

echo
echo "✅ Fertig!"
echo "   Inhalte von $BUNDLE:"
zipinfo "$BUNDLE" || true
echo
echo "   → Dieses ZIP kannst du 1:1 auf deinen Server legen."
echo "   → Git enthält weiterhin nur die Quellen + Skripte."