#!/usr/bin/env python3
"""Zeigt die Chatti-Doku an (Manpage oder Markdown) – auch aus dem Wheel heraus."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import chatti  # Paket selbst, um den Install-Pfad zu finden


def _docs_root() -> Path:
    """Ermittelt den Docs-Ordner relativ zum installierten chatti-Paket."""
    # chatti/__init__.py → .../site-packages/chatti/__init__.py
    pkg_dir = Path(chatti.__file__).resolve().parent
    return pkg_dir / "docs"


def _first_existing(paths: list[Path]) -> Path | None:
    for p in paths:
        if p.is_file():
            return p
    return None


def _page_file(path: Path) -> int:
    """Datei mit less/more anzeigen, falls vorhanden, sonst direkt auf STDOUT."""
    pager = shutil.which("less") or shutil.which("more")
    text = path.read_text(encoding="utf-8", errors="replace")

    if pager:
        # Für less optional -R, damit Farben/Escape-Sequenzen durchgehen
        cmd = [pager]
        if os.path.basename(pager) == "less":
            cmd.append("-R")
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
        proc.communicate(text.encode("utf-8", "replace"))
        return proc.returncode or 0

    # Fallback: stumpf auf STDOUT
    sys.stdout.write(text)
    return 0


def main(argv: list[str] | None = None) -> int:
    """Entry-Point für chatti-showman."""
    argv = argv or sys.argv[1:]

    docs = _docs_root()

    man_candidates = [
        docs / "man1" / "chatti.1",
    ]
    md_candidates = [
        docs / "MANUAL.md",
        docs / "README.md",
        docs / "installation-guide.md",
    ]

    manpage = _first_existing(man_candidates)
    mdfile = _first_existing(md_candidates)

    # 1) Bevorzugt: man(1), wenn manpage + man vorhanden
    if manpage and shutil.which("man"):
        env = os.environ.copy()
        # MANPATH auf unseren Docs-Ordner setzen, damit "man chatti" die Seite findet
        env["MANPATH"] = str(docs)
        return subprocess.call(["man", "chatti"], env=env)

    # 2) Fallback: Manpage direkt paginieren
    if manpage:
        return _page_file(manpage)

    # 3) Zweiter Fallback: Markdown (Manual / README / Install-Guide)
    if mdfile:
        return _page_file(mdfile)

    # 4) Nichts gefunden
    print("Konnte weder Manpage (chatti.1) noch README/MANUAL finden.")
    print(f"Gesucht wurde relativ zu: {docs}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())