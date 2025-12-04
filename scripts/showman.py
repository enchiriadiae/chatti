# chatti/scripts/showman.py

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


def _find_base_dir() -> Path:
    """
    Versucht, das Installations-/Projektverzeichnis von chatti zu finden.

    - Im entwickelnden Repo:    .../Dev/chatti/chatti/scripts/showman.py
                                → base = .../Dev/chatti
    - Im installierten Package: .../site-packages/chatti/scripts/showman.py
                                → base = .../site-packages/chatti
    """
    here = Path(__file__).resolve()
    # .../chatti/scripts/showman.py → .../chatti
    return here.parent.parent


def _find_manpage() -> Path | None:
    """
    Sucht nach der Manpage chatti.1 an typischen Orten.
    """
    base = _find_base_dir()

    candidates = [
        # Entwicklung: docs/man1/chatti.1 (im Projekt-Root)
        base.parent / "docs" / "man1" / "chatti.1",
        # Installiertes Package (falls du docs irgendwann unter chatti/docs packst)
        base / "docs" / "man1" / "chatti.1",
    ]

    for p in candidates:
        if p.is_file():
            return p

    return None


def _find_readme() -> Path | None:
    """
    Fallback: README, wenn keine Manpage gefunden wird.
    """
    base = _find_base_dir()
    candidates = [
        base.parent / "README.md",
        base.parent / "README.txt",
        base / "README.md",
        base / "README.txt",
    ]
    for p in candidates:
        if p.is_file():
            return p
    return None


def _run_pager_for_file(path: Path) -> int:
    """
    Datei mit dem bevorzugten Pager anzeigen.
    """
    pager = os.environ.get("PAGER") or "less"
    # Für Farben / UTF-8: -R, falls less
    if "less" in pager:
        cmd = [pager, "-R", str(path)]
    else:
        cmd = [pager, str(path)]
    try:
        return subprocess.call(cmd)
    except FileNotFoundError:
        # Fallback: einfach auf stdout drucken
        try:
            sys.stdout.write(path.read_text(encoding="utf-8", errors="replace"))
            sys.stdout.flush()
            return 0
        except Exception as e:  # pragma: no cover - sehr defensiv
            print(f"Fehler beim Lesen von {path}: {e}", file=sys.stderr)
            return 1


def main(argv: list[str] | None = None) -> int:
    """
    CLI-Einstieg für `chatti-showman`.

    Strategie:
    1. Wenn `man` verfügbar UND chatti.1 gefunden → `man -l chatti.1`
    2. Sonst: README finden und mit $PAGER anzeigen.
    """
    argv = argv or sys.argv[1:]

    man_path = _find_manpage()
    man_bin = shutil.which("man")

    if man_bin and man_path:
        # Benutzt die lokale Datei direkt, unabhängig von MANPATH
        try:
            return subprocess.call([man_bin, "-l", str(man_path)])
        except FileNotFoundError:
            # Fallback weiter unten
            pass

    # Fallback: README / Textdatei
    readme = _find_readme()
    if readme:
        return _run_pager_for_file(readme)

    print("Konnte weder Manpage (chatti.1) noch README finden.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
