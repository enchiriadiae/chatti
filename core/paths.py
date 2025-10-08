# core/paths.py
from __future__ import annotations

import json
import os
import pathlib
import platform
import shlex
import shutil
import stat
import unicodedata
from urllib.parse import unquote, urlparse

_ZERO_WIDTH = ("\u200B", "\u200C", "\u200D", "\uFEFF")

# -----------------------------
# Basisinfos
# -----------------------------
HOME = pathlib.Path.home()
SYSTEM = platform.system()  # "Windows", "Darwin", "Linux"

# --- Helper: Projekt-Root heuristisch finden (funktioniert im Git-Clone und bei lokalem Layout) ---
def _guess_project_root(start: pathlib.Path | None = None) -> pathlib.Path | None:
    """
    Geht vom aktuellen Dateiort (oder 'start') nach oben und sucht Marker,
    die auf das Repo/Projekt hindeuten. Gibt den Root zurück oder None.
    """
    here = (start or pathlib.Path(__file__)).resolve()
    cur = here.parent
    markers = {".git", "pyproject.toml", "setup.cfg", "README.md", "README.txt"}
    # 6 Ebenen sollten für praktisch alle Layouts reichen
    for _ in range(6):
        try:
            names = {p.name for p in cur.iterdir()}
        except Exception:
            names = set()
        if markers & names:
            return cur
        if cur.parent == cur:
            break
        cur = cur.parent
    return None

# -----------------------------
# XDG-/AppData-Basis für per-user Config (X Desktop Group-Standard für Pfade)
# -----------------------------
if SYSTEM == "Windows":
    # z.B. C:\Users\<User>\AppData\Roaming
    XDG_BASE = pathlib.Path(os.getenv("APPDATA", HOME / "AppData" / "Roaming"))
else:
    # z.B. ~/.config (wenn XDG_CONFIG_HOME nicht gesetzt ist)
    XDG_BASE = pathlib.Path(os.getenv("XDG_CONFIG_HOME", HOME / ".config"))

# -----------------------------
# Projekt-Root (optional, z. B. für dev)
# -----------------------------
PROJECT_ROOT = pathlib.Path(os.getenv("CHATTI_PROJECT_ROOT", pathlib.Path.cwd()))

# -----------------------------
# Private Config/Secrets (verschlüsselt)
# Default: ~/.config/chatti-cli/chatti-secrets.conf
# ENV-Overrides (Prio): CHATTICLI_CONFIG_DIR > CHATTI_CONF_DIR
# -----------------------------
CONF_DIR = pathlib.Path(
    os.getenv("CHATTICLI_CONFIG_DIR") or os.getenv("CHATTI_CONF_DIR") or (XDG_BASE / "chatti-cli")
)
SECRETS_FILE = CONF_DIR / "chatti-secrets.conf"

# -----------------------------
# Öffentliche Config (sichtbar/editierbar)
# Default: chatti.conf in CONF_DIR
# -----------------------------
PUBLIC_CONF = pathlib.Path(
    os.getenv("CHATTI_PUBLIC_CONF") or (CONF_DIR / "chatti.conf")
)

# -----------------------------
# Datenverzeichnis (History, Attachments, Caches …)
# Default: ~/.local/share/chatti-cli  (Windows: %LOCALAPPDATA%)
# ENV-Overrides (Prio): CHATTICLI_DATA_DIR > CHATTI_DATA_DIR
# -----------------------------
if SYSTEM == "Windows":
    local_base = pathlib.Path(os.getenv("LOCALAPPDATA", HOME / "AppData" / "Local"))
    DATA_DIR_DEFAULT = local_base / "chatti-cli"
else:
    DATA_DIR_DEFAULT = HOME / ".local" / "share" / "chatti-cli"

DATA_DIR = pathlib.Path(
    os.getenv("CHATTICLI_DATA_DIR") or os.getenv("CHATTI_DATA_DIR") or DATA_DIR_DEFAULT
)

# -----------------------------
# Help-Files, readme, *.md...
# -----------------------------
DOCS_DIR = DATA_DIR / "docs"

def _ensure_dir_secure(path: pathlib.Path) -> pathlib.Path:
    if SYSTEM == "Windows":
        path.mkdir(parents=True, exist_ok=True)  # ACL erbt vom Profil
    else:
        # Verzeichnis 0700 (umask umgehen) + ggf. nachschärfen
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
        try:
            st = path.stat()
            if stat.S_IMODE(st.st_mode) != 0o700:
                os.chmod(path, 0o700)
        except Exception:
            pass
    return path

def _init_history_file_if_missing(path: pathlib.Path) -> None:
    """
    Legt eine History-JSONL an, falls sie fehlt.
    Fügt eine erste Kommentar-Zeile als JSON-Objekt ein.
    """
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    header_obj = {
        "_comment": "This file is part of the chatti-client project. Do not edit manually!"
    }
    path.write_text(json.dumps(header_obj, ensure_ascii=False) + "\n", encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except Exception:
        pass

# ---------- Multi-User-Struktur ----------
USERS_CONF_DIR = CONF_DIR / "users"
USERS_DATA_DIR = DATA_DIR / "users"

def user_data_dir(uid: str) -> pathlib.Path:
    return _ensure_dir_secure(USERS_DATA_DIR / uid)

def user_history_file(uid: str) -> pathlib.Path:
    return user_data_dir(uid) / "history.jsonl"

def user_inputs_file(uid: str) -> pathlib.Path:
    return user_data_dir(uid) / "inputs.jsonl"

def user_cmds_file(uid: str) -> pathlib.Path:
    return user_data_dir(uid) / "commands.jsonl"

def user_attachments_dir(uid: str) -> pathlib.Path:
    return _ensure_dir_secure(user_data_dir(uid) / "attachments")

def user_attachments_manifest(uid: str) -> pathlib.Path:
    return user_attachments_dir(uid) / "manifest.json"

def user_attachments_files_dir(uid: str) -> pathlib.Path:
    return _ensure_dir_secure(user_attachments_dir(uid) / "files")

def user_support_dir(uid: str) -> pathlib.Path:
    return user_support_dir(uid) / "ticket.txt"

# --- EINDEUTIGE Definition für User-Config (docker-freundlich) ---
def user_conf_dir(uid: str) -> pathlib.Path:
    """
    Konfig-Ordner für einen User.
    Basis ist per ENV überschreibbar:
      CHATTI_USER_CONF_BASE=/app/config/users
    → /app/config/users/<uid>/conf
    Fallback: ~/.config/chatti-cli/users/<uid>/conf
    """
    base = pathlib.Path(os.getenv("CHATTI_USER_CONF_BASE", str(USERS_CONF_DIR)))
    return _ensure_dir_secure(base / uid / "conf")

def user_conf_file(uid: str) -> pathlib.Path:
    return user_conf_dir(uid) / "chatti.conf"

def repo_prompts_dir() -> pathlib.Path:
    """
    Quelle der mitgelieferten Beispiel-Prompts.
    Priority:
      1) CHATTI_REPO_PROMPTS (explizit gesetzt)
      2) erkannter Projekt-Root /docs/prompts
      3) Fallback auf global_prompts_dir() (damit Aufrufer immer einen Pfad bekommen)
    """
    # 1) Explizit via ENV
    env = os.getenv("CHATTI_REPO_PROMPTS")
    if env:
        p = normalize_user_path(env)
        if p.exists():
            return p

    # 2) Heuristisch Projekt-Root finden (Git-Clone / Entwicklungsordner)
    root = _guess_project_root()
    if root:
        candidate = root / "docs" / "prompts"
        if candidate.exists() and candidate.is_dir():
            return candidate

    # 3) Fallback: globaler Prompt-Ordner (damit ensure_global_prompts_seed() nie crasht)
    return global_prompts_dir()

def global_prompts_dir() -> pathlib.Path:
    """Repo-unabhängiger Ort für mitgelieferte Beispiel-Prompts."""
    d = CONF_DIR / "docs" / "prompts"   # ~/.config/chatti-cli/docs/prompts
    return _ensure_dir_secure(d)

def user_prompts_dir(uid: str) -> pathlib.Path:
    """Benutzerindividuelle Prompts (schreibbar)."""
    d = user_conf_dir(uid) / "prompts"  # ~/.config/chatti-cli/users/<uid>/conf/prompts
    return _ensure_dir_secure(d)

def ensure_global_prompts_seed(copy_max: int | None = None) -> None:
    """
    Initialisiert den globalen Prompt-Ordner (~/.config/chatti-cli/docs/prompts)
    mit Beispielen aus dem Repo (docs/prompts).
    Kopiert nur, wenn im globalen Ordner noch keine Dateien liegen.
    """
    dst = global_prompts_dir()
    try:
        # wenn schon Dateien da sind → fertig
        if any(p.is_file() for p in dst.iterdir()):
            return

        src = repo_prompts_dir()
        # Self-copy vermeiden oder fehlende Quelle
        if not src.exists() or src.resolve() == dst.resolve():
            return

        count = 0
        for p in sorted(src.iterdir()):
            if p.is_file() and not p.name.startswith("."):
                (dst / p.name).write_bytes(p.read_bytes())
                count += 1
                if copy_max and count >= copy_max:
                    break
    except Exception:
        # Onboarding darf hier nie hart crashen
        pass

def ensure_user_prompts_initialized(uid: str, *, copy_max: int = 3) -> None:
    """
    Kopiert bis zu `copy_max` globale Beispiel-Prompts in den User-Prompts-Ordner,
    aber nur, wenn dieser Ordner noch leer ist. So hat der User sofort etwas Greifbares.
    """
    try:
        dst = user_prompts_dir(uid)         # ~/.config/chatti-cli/users/<uid>/conf/prompts
        # nur wenn der Ordner leer ist → "Seed"
        if any(p.is_file() for p in dst.iterdir()):
            return
        src = global_prompts_dir()          # ~/.config/chatti-cli/docs/prompts
        if not src.exists():
            return

        count = 0
        for p in sorted(src.iterdir()):
            if p.is_file() and not p.name.startswith("."):
                (dst / p.name).write_bytes(p.read_bytes())
                count += 1
                if count >= max(1, copy_max):
                    break
    except Exception:
        # bewusst still – Onboarding soll nie an Prompts scheitern
        pass

def ensure_global_docs_dir() -> None:
    """Legt das zentrale docs/-Verzeichnis an (read-only gedacht)."""
    try:
        DOCS_DIR.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass

# Verwaiste User-Directories löschen und aus den Secrets entfernen (nächste Methode)
def prune_orphan_user_dirs(
    verbose: bool = True, *, allow_when_no_secrets: bool = True
) -> int:
    """
    Entfernt alle User-Verzeichnisse in config/data, deren UID
    nicht mehr in den Secrets existiert. Gibt die Anzahl der
    entfernten UID-Ordner zurück.
    """
    # 1) UIDs direkt aus der Secrets-Datei parsen (ohne security.load_secrets)
    valid_uids: set[str] = set()
    try:
        txt = SECRETS_FILE.read_text(encoding="utf-8")
        for line in txt.splitlines():
            raw = line.strip()
            if not raw or raw.startswith(("#", ";")) or "=" not in raw:
                continue
            key = raw.split("=", 1)[0].strip()
            # Keys wie: user.<UID>.<feld>
            if key.startswith("user.") and key.count(".") >= 2:
                # nur das 2. Segment ist die UID
                uid = key.split(".", 2)[1]
                if uid:
                    valid_uids.add(uid)
    except FileNotFoundError:
        if not allow_when_no_secrets:
            if verbose:
                print("⚠️  Keine Secrets gefunden – breche Bereinigung ab.")
            return 0
        valid_uids = set()

    except Exception:
        # defensiv: im Zweifel nichts löschen
        if verbose:
            print("⚠️  Konnte Secrets nicht lesen – breche Bereinigung ab.")
        return 0

    # 2) Verwaiste Ordner unter users/ in CONF & DATA entfernen
    removed = 0
    for base in (USERS_CONF_DIR, USERS_DATA_DIR):
        try:
            if not base.exists():
                continue
            for child in base.iterdir():
                if not child.is_dir():
                    continue
                if child.name not in valid_uids:
                    if verbose:
                        print(f"🧹 Entferne verwaisten User-Ordner: {child}")
                    shutil.rmtree(child, ignore_errors=True)
                    removed += 1
        except Exception as e:
            if verbose:
                print(f"⚠️  prune_orphan_user_dirs Fehler in {base}: {e}")
    return removed

def prune_orphan_secret_entries(verbose: bool = False) -> int:
    """
    Entfernt alle user.<UID>.* Einträge aus den Secrets, für die es
    keine User-Verzeichnisse mehr gibt. Gibt die Anzahl betroffener UIDs zurück.
    """

    # valid UIDs = Schnittmenge der Ordner unter conf/ und data/
    valid_uids = set()
    for base in (USERS_CONF_DIR, USERS_DATA_DIR):
        if base.exists():
            valid_uids |= {p.name for p in base.iterdir() if p.is_dir()}

    # Secrets roh lesen
    text = SECRETS_FILE.read_text(encoding="utf-8") if SECRETS_FILE.exists() else ""
    lines = text.splitlines()
    keep: list[str] = []
    seen_bad_uids: set[str] = set()

    for raw in lines:
        line = raw.strip()
        if not line or line.startswith(("#",";")) or "=" not in raw:
            keep.append(raw); continue
        key = raw.split("=", 1)[0].strip()
        if key.startswith("user.") and key.count(".") >= 2:
            uid = key.split(".", 2)[1]
            if uid and uid not in valid_uids:
                seen_bad_uids.add(uid)
                continue  # drop this line
        keep.append(raw)

    if seen_bad_uids:
        SECRETS_FILE.write_text("\n".join(keep) + "\n", encoding="utf-8")
        if verbose:
            print(f"🧹 Entfernt verwaiste Secret-Einträge für: {', '.join(sorted(seen_bad_uids))}")
    return len(seen_bad_uids)


# -----------------------------
# Prompt-Suchpfade + Resolver
# -----------------------------

def prompt_search_paths(uid: str | None = None) -> list[pathlib.Path]:
    """
    Suchreihenfolge für Prompts:
      1) User-spezifisch (~/.config/chatti-cli/users/<uid>/conf/prompts)
      2) Global bereitgestellte Beispiele (~/.config/chatti-cli/docs/prompts)
      3) Optionale Extra-Pfade via ENV CHATTI_PROMPTS_EXTRA (getrennt per os.pathsep)
    """
    paths: list[pathlib.Path] = []
    seen: set[str] = set()

    def add(p: pathlib.Path) -> None:
        key = str(p.resolve()) if p.exists() else str(p)
        if key not in seen:
            paths.append(p)
            seen.add(key)

    if uid:
        try: add(user_prompts_dir(uid))
        except Exception: pass

    try: add(global_prompts_dir())
    except Exception: pass

    extra = os.getenv("CHATTI_PROMPTS_EXTRA", "").strip()
    if extra:
        for chunk in extra.split(os.pathsep):
            p = normalize_user_path(chunk)
            try:
                if p.exists() and p.is_dir():
                    add(p)
            except Exception:
                pass
    return paths

def resolve_prompt(name: str, uid: str | None = None) -> pathlib.Path | None:
    """
    Sucht eine Prompt-Datei nach Name (ohne/mit Endung) in prompt_search_paths(uid).
    Probiert automatisch .txt / .md, falls keine Endung angegeben ist.
    Rückgabe: gefundener Pfad oder None.
    """
    nm = (name or "").strip()
    if not nm:
        return None

    # Kandidatenliste: wenn keine Endung → .txt, .md ergänzen
    candidates: list[str]
    if "." in pathlib.Path(nm).name:
        candidates = [nm]
    else:
        candidates = [nm + ".txt", nm + ".md", nm]

    for base in prompt_search_paths(uid):
        for c in candidates:
            p = base / c
            try:
                if p.exists() and p.is_file():
                    return p
            except Exception:
                continue
    return None


def list_prompts(uid: str | None = None) -> dict[str, list[str]]:
    """
    Listet verfügbare Prompts getrennt nach 'user' und 'global'.
    Nur reguläre Dateien, keine Hidden-Files. Alphabetisch sortiert.
    """
    out = {"user": [], "global": []}

    # user
    if uid:
        try:
            up = user_prompts_dir(uid)
            out["user"] = sorted(
                p.name for p in up.iterdir() if p.is_file() and not p.name.startswith(".")
            )
        except Exception:
            pass

    # global
    try:
        gp = global_prompts_dir()
        out["global"] = sorted(
            p.name for p in gp.iterdir() if p.is_file() and not p.name.startswith(".")
        )
    except Exception:
        pass

    return out


def _strip_outer_quotes(s: str) -> str:
    s = s.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in ("'", '"'):
        return s[1:-1]
    return s

def _strip_zero_width(s: str) -> str:
    for z in _ZERO_WIDTH:
        s = s.replace(z, "")
    return s

def _unshell_escape(s: str) -> str:
    try:
        parts = shlex.split(s, posix=True)
        if len(parts) == 1:
            return parts[0]
    except Exception:
        pass
    # Fallback: nur gängige Backslash-Escapes entschärfen
    return s.replace(r"\ ", " ").replace(r"\,", ",").replace(r"\(", "(").replace(r"\)", ")")

# === zentrale Normalisierung von Pfadnamen
def normalize_user_path(p: str | pathlib.Path) -> pathlib.Path:
    s = str(p)
    s = _strip_zero_width(_strip_outer_quotes(s))

    if s.startswith("file://"):
        u = urlparse(s)
        s = unquote(u.path)

    s = _unshell_escape(s)
    s = os.path.expanduser(os.path.expandvars(s))

    # Unicode-Normalisierung (macOS: NFD, sonst NFC)
    if SYSTEM == "Darwin":
        s = unicodedata.normalize("NFD", s)
    else:
        s = unicodedata.normalize("NFC", s)

    pth = pathlib.Path(s)
    if not pth.is_absolute():
        pth = pathlib.Path.cwd() / pth
    try:
        pth = pth.resolve(strict=False)
    except Exception:
        pass
    return pth

def same_path(a: str | pathlib.Path, b: str | pathlib.Path) -> bool:
    """Vergleicht zwei User-Pfade robust (inkl. Unicode-Normalisierung)."""
    return normalize_user_path(a) == normalize_user_path(b)

# ---------- Kommunikation mit User über Tickets, sofern nötig ----------
def user_ticket_file(uid: str) -> pathlib.Path:
    d = user_data_dir(uid) / "support"
    d.mkdir(parents=True, exist_ok=True)
    return d

# --- Home-Portal: sichtbarer Ordner im Benutzer-Home mit Links zu Config/Data ---
def _write_url_shortcut(dst: pathlib.Path, target: pathlib.Path) -> None:
    """Windows-Fallback: .url-Datei, die den Ordner/Datei im Explorer öffnet."""
    url = "file:///" + str(target).replace("\\", "/")
    dst.write_text(f"[InternetShortcut]\nURL={url}\n", encoding="utf-8")

def _mk_link(dst: pathlib.Path, target: pathlib.Path) -> None:
    """
    Erzeugt einen Link:
      - Unix/macOS: Symlink
      - Windows: Symlink, bei Fehler .url-Shortcut
    Überschreibt vorhandene Symlinks, lässt echte Dateien/Ordner unangetastet.
    """
    try:
        if dst.exists() or dst.is_symlink():
            # Wenn es bereits ein Symlink auf dasselbe Ziel ist: nichts tun
            try:
                if dst.is_symlink() and dst.resolve() == target.resolve():
                    return
            except Exception:
                pass
            # Existiert, aber kein Symlink → nicht anfassen (Sicherheit)
            if not dst.is_symlink():
                return
            try:
                dst.unlink()
            except Exception:
                return

        if SYSTEM == "Windows":
            try:
                os.symlink(str(target), str(dst), target_is_directory=target.is_dir())
            except Exception:
                # Fallback: .url (klickbar im Explorer)
                if dst.suffix.lower() != ".url":
                    dst = dst.with_suffix(".url")
                _write_url_shortcut(dst, target)
        else:
            os.symlink(str(target), str(dst))
    except Exception:
        # bewusst still – nur Komfort
        pass

def ensure_user_home_portal(uid: str, *, name: str = "Chatti") -> pathlib.Path:
    """
    Legt ~/Chatti (oder <name>) an und erzeugt darin klickbare Links zu:
      - Config (…/users/<uid>/conf)
      - Data   (…/users/<uid>)
      - Support (…/users/<uid>/support)
      - Attachments (…/users/<uid>/attachments)
      - History.jsonl (Direktlink auf Datei)
    """
    portal = HOME / name
    try:
        portal.mkdir(exist_ok=True)
        # Ziele
        cfg_dir  = user_conf_dir(uid)
        data_dir = user_data_dir(uid)
        sup_dir  = data_dir / "support"
        docs_dir = DOCS_DIR
        att_dir  = user_attachments_dir(uid)
        hist     = user_history_file(uid)

        # Links (oder .url auf Windows)
        _mk_link(portal / "Config", cfg_dir)
        _mk_link(portal / "Data", data_dir)
        _mk_link(portal / "Docs", docs_dir)
        _mk_link(portal / "Support", sup_dir)
        _mk_link(portal / "Attachments", att_dir)
        _mk_link(portal / "History.jsonl", hist)
        if docs_dir.exists():
            _mk_link(portal / "Docs (global)", docs_dir)

    except Exception:
        pass
    return portal

# ---------- Verzeichnisse sicherstellen ----------
_ensure_dir_secure(CONF_DIR)
_ensure_dir_secure(DATA_DIR)
_ensure_dir_secure(USERS_CONF_DIR)
_ensure_dir_secure(USERS_DATA_DIR)
