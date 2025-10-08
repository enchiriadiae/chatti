# === ticket.py
#
from datetime import datetime
from pathlib import Path

from core.paths import USERS_DATA_DIR, user_ticket_file


def append_ticket(uid: str, text: str) -> Path:
    """Hängt eine Zeile mit Zeitstempel an ticket.txt an (wird erstellt, falls fehlend)."""
    p = user_ticket_file(uid)
    ts = datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
    line = f"[{ts}] {text.strip()}\n"
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(line)
    return p

def collect_tickets() -> list[tuple[str, Path, str]]:
    """
    Sammelt alle ticket.txt unter users/*/support.
    Rückgabe: [(uid, path, first_line_or_empty)]
    """
    out = []
    try:
        if USERS_DATA_DIR.exists():
            for child in USERS_DATA_DIR.iterdir():
                if not child.is_dir():
                    continue
                uid = child.name
                p = child / "support" / "ticket.txt"
                if p.exists() and p.is_file():
                    first = ""
                    try:
                        with p.open("r", encoding="utf-8") as f:
                            first = (f.readline() or "").rstrip("\n")
                    except Exception:
                        pass
                    out.append((uid, p, first))
    except Exception:
        pass
    return sorted(out, key=lambda t: t[0])
