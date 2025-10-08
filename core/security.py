# -----------------------------------------------------------------------------
# core/security.py
#
# Secure storage and retrieval of API keys for the Chatti client.
#
# Responsibilities:
# - Provide file helpers to read/write the secrets file safely.
# - Store encrypted key-value pairs (api_key_enc, kdf_salt, etc.).
# - Implement PBKDF2-HMAC-SHA256 key derivation with configurable iterations.
#   possible Update in future: KDF-Layer: PBKDF2 → Argon2id
# - Use Fernet (symmetric encryption) to encrypt/decrypt API keys.
# - Provide an interactive onboarding fallback when no valid key is found:
#     * Prompt for OpenAI API key
#     * Prompt for master password (twice for confirmation)
#     * Encrypt + persist secrets for future runs
#
# In short: this module ensures that sensitive credentials are stored securely
# on disk and can only be decrypted with the correct master password.
# -----------------------------------------------------------------------------

from __future__ import annotations

import base64
import ctypes
import datetime
import hashlib
import hmac
import json
import os
import re
import tempfile
import unicodedata
from pathlib import Path

try:
    from zxcvbn import zxcvbn
    _HAVE_ZXCVBN = True
except Exception:
    _HAVE_ZXCVBN = False

# from typing import Optional
from getpass import getpass

# from typing import Literal, Optional, List
#from typing import Tuple

try:
    from cryptography.fernet import Fernet, InvalidToken
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    #from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
except Exception as e:
    raise RuntimeError(
        "The 'cryptography' package is required for encrypted API-key storage.\n"
        "Please install it in your virtualenv:\n\n"
        "   pip install cryptography\n"
        "\n(If you are packaging the app, ensure 'cryptography' is listed as a dependency.)"
    ) from e

from .paths import (
    SECRETS_FILE,
    SYSTEM,
    _init_history_file_if_missing,
    ensure_user_home_portal,
    user_attachments_dir,
    user_attachments_files_dir,
    user_attachments_manifest,
    user_cmds_file,
    user_conf_dir,
    user_data_dir,
    user_history_file,
    user_inputs_file,
)

# =============================================================================
# This module follows a **defensive programming style**:
#
# - Every external dependency (files, env vars, network, cryptography)
#   is treated as potentially missing or failing.
# - Errors are caught as early and locally as possible, and re-raised with
#   human-readable messages instead of raw stack traces.
# - The goal is robustness: a clean, predictable failure mode is better
#   than a silent crash or a cascade of follow-up errors.
#
# Think of it as "seatbelts and airbags for Python":
# slightly more boilerplate, but the system as a whole is far more reliable.
# =============================================================================

# ---------- password quality helpers (lightweight) ----------
_COMMON_WEAK = {
    "123456",
    "123456789",
    "12345",
    "1234",
    "password",
    "passwort",
    "schatz",
    "schatzilein",
    "111111",
    "123123",
    "iloveyou",
    "admin",
    "welcome",
    "letmein",
    "pw",
    "schnuki",
    "schnucki",
    "monkey",
    "dragon",
    "abc123",
    "1q2w3e4r",
    "000000",
    "asdfgh",
    "fred",
    "chatti",
    "fjodi",
}

# Ein paar typische Keyboard-Walks
_KEYBOARD_SEQ = (
    "qwerty",
    "qwer",
    "qwert",
    "qwertz",
    "asdf",
    "asdfg",
    "asdfgh",
    "zxcv",
    "azerty",
    "yxcv",
    "yxcvb",
    "yxcvbn",
)


def _char_classes(s: str) -> int:
    has_lower = any(c.islower() for c in s)
    has_upper = any(c.isupper() for c in s)
    has_digit = any(c.isdigit() for c in s)
    has_sym = any(not c.isalnum() for c in s)
    return sum((has_lower, has_upper, has_digit, has_sym))


def _looks_sequential(s: str, min_run: int = 5) -> bool:
    """Einfacher Check auf monotone Läufe (abcde, 12345, 54321)."""
    if len(s) < min_run:
        return False
    # Vorwärts
    run = 1
    for i in range(1, len(s)):
        if ord(s[i]) - ord(s[i - 1]) == 1:
            run += 1
            if run >= min_run:
                return True
        else:
            run = 1
    # Rückwärts
    run = 1
    for i in range(1, len(s)):
        if ord(s[i - 1]) - ord(s[i]) == 1:
            run += 1
            if run >= min_run:
                return True
        else:
            run = 1
    return False

def validate_master_password(pw: str) -> tuple[bool, str]:
    """
    Returns (ok, reason). Fast & dependency-friendly.
    Policy:
      - length >= 12
      - at least 3 character classes
      - not in a small weak list
      - not all same char
      - no simple sequences / keyboard walks
      - if zxcvbn is available: require score >= 2
    """
    # Mindestlänge immer prüfen
    if len(pw) < 12:
        return False, "Zu kurz (min. 12 Zeichen). Nutze z. B. eine Passphrase."

    # Wenn zxcvbn verfügbar ist, zuerst damit prüfen
    if _HAVE_ZXCVBN:
        try:
            res = zxcvbn(pw)
            if res["score"] < 2:
                fb = res.get("feedback", {})
                warn = fb.get("warning") or "Passwort zu schwach."
                sugg = " ".join(fb.get("suggestions", []))
                return False, (warn + (" " + sugg if sugg else "")).strip()
            return True, f"Stark genug (zxcvbn Score {res['score']}/4)."
        except Exception:
            # zxcvbn ist installiert, hat aber intern gezickt → Fallback nutzen
            pass

    # Fallback: Lightweight-Heuristiken (ohne zxcvbn)
    low = pw.casefold()
    if low in _COMMON_WEAK:
        return False, "Bekannt schwaches Passwort. Bitte wähle ein stärkeres!"
    if len(set(pw)) == 1:
        return False, "Alle Zeichen identisch."
    if _looks_sequential(low) or any(k in low for k in _KEYBOARD_SEQ):
        return False, "Wirkt wie einfache Sequenz/Keyboard-Walk."
    if _char_classes(pw) < 3:
        return False, "Bitte mind. 3 der 4 Klassen nutzen: Kleinbuchstaben, GROSSBUCHSTABEN, Ziffern, Symbole."

    return True, "OK (Basis-Checks)."

# ---------- File I/O helpers for the secrets file ----------

def _init_secrets_file_if_missing() -> None:
    """
    Legt die chatti-secrets.conf an, falls sie fehlt.
    Fügt oben einen Kommentarblock ein.
    """
    if SECRETS_FILE.exists():
        return
    header = (
        "# =========================================================\n"
        "# Chatti-Client Secrets File\n"
        "#\n"
        "# This file is part of the chatti-client project.\n"
        "# DO NOT EDIT MANUALLY!\n"
        "# Changes will be overwritten and may break functionality.\n"
        "# =========================================================\n"
    )
    _write_text(SECRETS_FILE, header + "\n")

def _read_text(path) -> str:
    # Read a whole file as UTF-8 text. Return empty string if file does not exist.
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""


def _write_text(path, text: str) -> None:
    # Ensure parent directory exists and write UTF-8 text atomically enough for our use.
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")

def write_secret_kv(key: str, value: str) -> None:
    """
    Set/replace a single `key = value` line inside SECRETS_FILE.

    - Keeps other lines and comments as-is.
    - Uses a regex that matches the exact key at line start (ignoring leading spaces),
      captures the left-hand side (`key = `) so we can re-use it,
      and replaces the right-hand side with the new value.
    - Uses a lambda in `re.sub` to avoid unintended backreference expansion in `value`.
    """
    _init_secrets_file_if_missing()
    txt = _read_text(SECRETS_FILE) or "# chatti-secrets.conf\n"
    pat = re.compile(rf"^(\s*{re.escape(key)}\s*=\s*)(.*)$", re.MULTILINE)
    if pat.search(txt):
        # Keep the original "left part" (indent + "key = ") and insert the raw value.
        # Using lambda prevents `\1`-style backreferences from being interpreted inside `value`.
        txt = pat.sub(lambda m: m.group(1) + value, txt, count=1)
    else:
        # Key not present → append a new line at the end (with a trailing newline).
        if not txt.endswith("\n"):
            txt += "\n"
        txt += f"{key} = {value}\n"
    _write_text(SECRETS_FILE, txt)
    try:
        os.chmod(SECRETS_FILE, 0o600)
    except Exception:
        pass


def redact(s: str, keep: int = 4) -> str:
    """
    Returns a redacted version of sensitive strings (like API keys).

    - Keeps the first `keep` characters, replaces the rest with "…".
    - Safe to call with None or short strings.
    - Can also be used to scrub secrets before logging / printing.

    Examples:
        redact("sk-1234567890abcdef")  -> "sk-1…"
        redact("mypassword", keep=2)   -> "my…"
    """
    if not s or not isinstance(s, str):
        return s
    if len(s) <= keep:
        return s
    return s[:keep] + "…"


def read_secrets() -> dict[str, str]:
    """
    Parse SECRETS_FILE into a simple dict of {key: value}.

    - Accepts lines like `key = value`.
    - Ignores blank lines and comment lines starting with `#` or `;`.
    - Splits only on the first `=`.
    """
    txt = _read_text(SECRETS_FILE)
    cfg: dict[str, str] = {}
    for line in txt.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith(";"):
            continue
        if "=" not in line:
            continue
        k, v = line.split("=", 1)
        cfg[k.strip()] = v.strip()
    return cfg


def conf_has_encrypted_key() -> bool:
    """
    Check whether the secrets file already contains both
    `api_key_enc` and `kdf_salt`.
    """
    sec = read_secrets()
    return bool(sec.get("api_key_enc")) and bool(sec.get("kdf_salt"))


# Reset corrupted pw/salt, if neccessary
RESET_KEYS = ("api_key_enc", "kdf_salt", "key_cache")


def reset_secrets(mode: str = "soft") -> None:
    """
    Reset credentials in the secrets file.
    mode = "soft"  -> remove only known keys (keeps comments/other lines)
    mode = "hard"  -> delete the secrets file entirely
    """
    if mode not in ("soft", "hard"):
        raise ValueError("Unterstützte Modi: 'soft' or 'hard'")

    if mode == "hard":
        try:
            SECRETS_FILE.unlink()
            print(f"✓ Secrets file gelöscht: \033[90m{SECRETS_FILE}\033[0m")
        except FileNotFoundError:
            print(f"• Secrets file nicht gefunden: \033[90m{SECRETS_FILE}\033[0m")
        return

    # soft: strip only known keys
    txt = _read_text(SECRETS_FILE)
    if not txt:
        print(f"• Secrets file ist leer oder fehlt: \033[90m{SECRETS_FILE}\033[0m")
        return

    lines_out = []
    for line in txt.splitlines():
        raw = line.strip()
        if not raw or raw.startswith("#") or raw.startswith(";"):
            lines_out.append(line)
            continue
        if "=" not in raw:
            lines_out.append(line)
            continue
        k, _ = raw.split("=", 1)
        if k.strip() in RESET_KEYS:
            # skip (removes this key)
            continue
        lines_out.append(line)

    new_txt = "\n".join(lines_out).rstrip() + "\n"
    _write_text(SECRETS_FILE, new_txt)

    try:
        os.chmod(SECRETS_FILE, 0o600)
    except Exception:
        pass
    print(f"✓ Secrets reset (soft) written to {SECRETS_FILE}")

# ---------- PBKDF2-based KDF & Fernet encryption helpers ----------
def _derive_key(password: str, salt: bytes, iterations: int = 200_000) -> bytes:
    """
    Derive a 32-byte key from a password and salt using PBKDF2-HMAC-SHA256.

    - `iterations` is deliberately high for offline brute-force resistance.
    - Fernet expects a base64-encoded 32-byte key, so we base64-encode it.
    """
    # Key Derivation Function
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=iterations,
    )
    key = kdf.derive(password.encode("utf-8"))
    return base64.urlsafe_b64encode(key)  # Fernet expects Base64 key material


def encrypt_api_key(
    plaintext_key: str, password: str, salt: bytes | None = None
) -> tuple[str, str]:
    """
    Encrypt the API key using a key derived from the given password.

    Returns:
      (ciphertext_b64, salt_b64)

    - If no salt is provided, we generate a random 16-byte salt.
    - The ciphertext is returned as a UTF-8 string (Fernet token).
    - The salt is returned base64-encoded (to store in text files).
    """
    if salt is None:
        salt = os.urandom(16)
    f = Fernet(_derive_key(password, salt))
    token = f.encrypt(plaintext_key.encode("utf-8"))
    return token.decode("utf-8"), base64.b64encode(salt).decode("utf-8")


def decrypt_api_key(ciphertext_b64: str, password: str, salt_b64: str) -> str:
    """
    Entschlüsselt den API-Key. Raises InvalidToken bei falschem Passwort/Salt.
    Hinweis: Entfernt aus Sicherheitsgründen CHATTI_MASTER aus os.environ,
    egal ob die Entschlüsselung gelingt oder nicht.
    """
    salt = base64.b64decode(salt_b64.encode("utf-8"))
    f = Fernet(_derive_key(password, salt))
    try:
        plain = f.decrypt(ciphertext_b64.encode("utf-8"))
        return plain.decode("utf-8")
    except InvalidToken as e:
        raise InvalidToken(
            "\033[91mEntschlüsselung fehlgeschlagen (Passwort/Salt prüfen).\033[0m"
        ) from e
    finally:
        # Best effort: Master-Passwort aus dem Prozess-Environment entfernen
        os.environ.pop("CHATTI_MASTER", None)
        # tiny hygiene: lokale Referenzen lösen (Python gibt eh den Frame frei)
        password = None  # noqa: F841


# ---------------------------------------------------------------------------
# Appendix: Secret masking utilities (safe to use in logs and history)
# ---------------------------------------------------------------------------

# # Sammle typische Muster:
# _RE = [
#     # 1) OpenAI Keys: sk-... (live & legacy)
#     (re.compile(r"\bsk-(?:live|test)?[A-Za-z0-9]{20,}\b"), "sk-***"),
#     # 2) Bearer-/JWT-ähnliche lange Tokens
#     (re.compile(r"\b(?:Bearer\s+)?[A-Za-z0-9_-]{24,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"), "JWT-***"),
#     # 3) Fernet-Token (beginnen oft mit gAAAAA, sind lang & base64-url):
#     (re.compile(r"\bgAAAAA[A-Za-z0-9_\-]{20,}\b"), "FERNET-***"),
#     # 4) URL-Parameter ?key=... / &token=... / ...=APIKEY
#     (re.compile(r"([?&](?:key|api[_-]?key|token|access[_-]?token)=)([^&\s]+)", re.IGNORECASE), r"\1***"),
#     # 5) Generische „verdächtig lange“ Base64-/Hex-Klötze (letzte Rettung)
#     (re.compile(r"\b[A-Za-z0-9_\-]{40,}\b"), "***"),
# ]

# Sammle typische Muster:
_RE = [
    # OpenAI Keys: sk-... (live & legacy)
    (re.compile(r"\bsk-(?:live|test)?[A-Za-z0-9]{20,}\b"), "sk-***"),
    # Fernet-Token (beginnen oft mit gAAAAA, sind lang & base64-url)
    (re.compile(r"\bgAAAAA[A-Za-z0-9_\-]{20,}\b"), "FERNET-***"),
]


def mask_secrets(s: str) -> str:
    """Maskiert häufige Secret-/Tokenmuster in s."""
    if not isinstance(s, str) or not s:
        return s
    out = s
    for rx, repl in _RE:
        out = rx.sub(repl, out)
    return out


# =========================================================================
#
# Version 0.2: Multi-User (neu)
#
# ====== Multi-User (kompatible Erweiterung) ==============================


# ====== Multi-User mit UID + verschlüsseltem Username (PBKDF2 + Fernet) ======
# Design:
# - uid: random 16B, base64-url gespeichert (keine Klarnamen im Dateischlüssel)
# - pro User eigener kdf_salt (random)
# - Feldschlüssel: HMAC-SHA256 über (pbkdf2_raw, "chatti|v2|uid:<uid>|field:<name>")
#   → daraus Fernet-Key (urlsafe b64)
# - Speicherschlüssel (Datei): user.<uid>.<field>  (z. B. user.abCD...api_key_enc)


def get_active_user_display(master: str | None = None) -> tuple[str | None, str | None]:
    """
    Liefert (uid, display_name|None). Name nur, wenn master vorhanden/korrekt.
    """
    uid = get_active_uid()
    if not uid:
        return None, None
    if not master:
        return uid, None
    try:
        users = dict(list_users_decrypted(master))  # {uid: name}
        return uid, users.get(uid)
    except Exception:
        return uid, None

def _now_iso() -> str:
    return datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def _norm_user(u: str) -> str:
    # Unicode robust machen
    u = unicodedata.normalize("NFKC", u)
    # Rand-Whitespace weg
    u = u.strip()
    # Innen-Whitespace auf ein einzelnes Space reduzieren
    u = " ".join(u.split())
    # Case-insensitive Vergleich
    return u.casefold()

def _derive_key_raw(password: str, salt: bytes, iterations: int = 200_000) -> bytes:
    # Rohes 32B-Material (ohne b64), im Gegensatz zu _derive_key()
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=iterations)
    return kdf.derive(password.encode("utf-8"))


def _b64u(b: bytes) -> str:
    # urlsafe ohne '=' Padding (optional); hier mit Padding (Fernet-kompatibel)
    return base64.urlsafe_b64encode(b).decode("ascii")


def _b64d_u(s: str) -> bytes:
    return base64.urlsafe_b64decode(s.encode("ascii"))


def _field_fernet(base_raw32: bytes, uid_b64u: str, field: str) -> Fernet:
    # Feld- & UID-gebundener Schlüssel; kein Klartextname nötig
    msg = ("chatti|v2|uid:" + uid_b64u + "|field:" + field).encode("utf-8")
    digest = hmac.new(base_raw32, msg, hashlib.sha256).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def _new_uid() -> str:
    # 16B zufällig, urlsafe, **ohne '='** (nur für UID!):
    # verhindert Parser-Konflikte in 'key = value' Zeilen - sonst bricht read_secrets an 'key = value'
    return base64.urlsafe_b64encode(os.urandom(16)).decode("ascii").rstrip("=")


def _users_in_file(sec: dict[str, str]) -> list[str]:
    # sammelt alle user.<uid>.<field> → liefert sortierte uid-Liste
    uids = set()
    for k in sec.keys():
        if k.startswith("user.") and k.count(".") >= 2:
            parts = k.split(".")
            if len(parts) >= 3:
                uids.add(parts[1])
    return sorted(uids)

def add_user(uid_display_name: str, master_password: str, api_key: str) -> str:
    """
    Legt einen neuen Benutzer an (ein API-Key pro User).
    - uid wird zufällig vergeben (kein Klartextname in Dateischlüsseln)
    - Username wird NUR verschlüsselt gespeichert.
    - Setzt user.active auf diesen uid.
    Gibt den uid (base64-url) zurück.
    """
    # --- NEU: vorab prüfen, ob dies der allererste User ist ---
    pre_sec = read_secrets()
    pre_uids = _users_in_file(pre_sec)
    is_first_user = (len(pre_uids) == 0)

    uid = _new_uid()
    salt = os.urandom(16)
    base_raw = _derive_key_raw(master_password, salt)

    f_user = _field_fernet(base_raw, uid, "username")
    f_key = _field_fernet(base_raw, uid, "api_key")

    token_user = f_user.encrypt(uid_display_name.encode("utf-8")).decode("utf-8")
    token_key = f_key.encrypt(api_key.encode("utf-8")).decode("utf-8")

    write_secret_kv("version", "2")
    write_secret_kv(f"user.{uid}.kdf_salt", _b64u(salt))
    write_secret_kv(f"user.{uid}.username_enc", token_user)
    write_secret_kv(f"user.{uid}.api_key_enc", token_key)
    write_secret_kv(f"user.{uid}.updated_at", _now_iso())
    write_secret_kv("user.active", uid)

    # Verzeichnis-/Dateistruktur für den User anlegen
    _touch_user_files(uid)

    # --- NEU: erster User wird automatisch Admin ---
    if is_first_user:
        set_admin(uid, True)

    return uid



# Helper zum Verwalten der Admin-Rechte (neu als Version 0.2)

def is_admin(uid: str) -> bool:
    sec = read_secrets()
    return str(sec.get(f"user.{uid}.is_admin", "0")).strip() in ("1", "true", "yes")

def get_admin_uids() -> list[str]:
    sec = read_secrets()
    uids = set()
    for k, v in sec.items():
        if k.startswith("user.") and k.endswith(".is_admin"):
            uid = k.split(".")[1]
            if str(v).strip() in ("1", "true", "yes"):
                uids.add(uid)
    return sorted(uids)

def set_admin(uid: str, value: bool) -> None:
    write_secret_kv(f"user.{uid}.is_admin", "1" if value else "0")


# Helper zum Anlegen & Absichern der Dateien/Ordner (neu als Version 0.2)

def _chmod_600(path: Path) -> None:
    try:
        os.chmod(path, 0o600)
    except Exception:
        pass


def _set_hidden_win(path: Path) -> None:
    if SYSTEM != "Windows":
        return
    try:
        FILE_ATTRIBUTE_HIDDEN = 0x2
        ctypes.windll.kernel32.SetFileAttributesW(str(path), FILE_ATTRIBUTE_HIDDEN)
    except Exception:
        pass


def _open_secure_write(path: Path):
    """
    Nur benutzen, wenn tatsächlich in die Datei geschrieben wird.
    POSIX: 0600 erzwingen (umask umgehen).
    Windows: normal öffnen – ACL-Vererbung schützt.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    if SYSTEM == "Windows":
        return open(path, "w", encoding="utf-8")
    else:
        fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        return os.fdopen(fd, "w", encoding="utf-8")


def _touch_empty(path: Path) -> None:
    """
    Leere Datei anlegen (falls fehlend) und Rechte setzen (POSIX);
    unter Windows optional als 'hidden' markieren.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        # minimal & portabel anlegen
        with open(path, "w", encoding="utf-8"):
            pass
        if SYSTEM == "Windows":
            _set_hidden_win(path)
        else:
            _chmod_600(path)

def _touch_user_files(uid: str) -> None:
    """
    Legt für einen neuen User die Verzeichnisstruktur & Basisdateien an:
      - config:  users/<uid>/conf/ (Datei wird bei der Ersteinrichtung separat angelegt)
      - data:    users/<uid>/{history.jsonl, inputs.jsonl, commands.jsonl}
      - attach:  users/<uid>/attachments/{Manifest-Datei, files/}
      - support: users/<uid>/support/
    """
    # Verzeichnisse
    base = user_data_dir(uid)  # i. d. R. users/<uid>
    user_conf_dir(uid)
    user_attachments_dir(uid)
    user_attachments_files_dir(uid)

    # Basisdaten-Dateien (leer)
    _init_history_file_if_missing(user_history_file(uid))
    _touch_empty(user_inputs_file(uid))
    _touch_empty(user_cmds_file(uid))

    # Attachments-Manifest (falls nicht vorhanden)
    manifest = user_attachments_manifest(uid)
    if not manifest.exists():
        _write_json_atomic(manifest, {"version": 1, "items": []})

    # Support-Ordner vorbereiten (liegt unter DATA)
    (base / "support").mkdir(parents=True, exist_ok=True)   # 👈 base verwenden
    (user_data_dir(uid) / "docs").mkdir(parents=True, exist_ok=True)

    # Sichtbares Home-Portal anlegen / aktualisieren
    try:
        ensure_user_home_portal(uid)
    except Exception:
        pass


def _write_json_atomic(path: Path, obj: dict) -> None:

    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", delete=False, dir=str(path.parent)
    ) as tmp:
        tmp.write(json.dumps(obj, ensure_ascii=False, indent=2))
        tmp.flush()
        os.fsync(tmp.fileno())
        tmp_name = tmp.name
    os.replace(tmp_name, path)
    if SYSTEM == "Windows":
        _set_hidden_win(path)
    else:
        _chmod_600(path)

def load_secrets() -> dict[str, str]:
    """
    Lädt die Secrets als Dict.
    Variante (B):
      - Existiert die Datei zwar, enthält aber **keine Benutzer-Einträge**
        (weder Multi-User `user.<uid>.*` noch Legacy `api_key_enc`/`kdf_salt`)
        und/oder ein leeres `user.active`, dann verhalten wir uns wie „leer“
        und geben {} zurück (→ Onboarding).
    """
    sec = read_secrets()
    if not sec:
        return {}  # Datei fehlt / leer / nur Kommentare

    # Multi-User: gibt es mind. einen user.<uid>.<field>?
    has_users = any(
        k.startswith("user.") and k.count(".") >= 2
        for k in sec.keys()
    )

    # Legacy-Single-User vorhanden?
    has_legacy = bool(sec.get("api_key_enc") and sec.get("kdf_salt"))

    # Effektiv „leer“, wenn keine User *und* keine Legacy-Creds
    if not has_users and not has_legacy:
        return {}
    # Sonderfall: Es gibt User-Einträge, aber kein aktiver User
    # (lassen wir zu; Onboarding ist nicht nötig, Auswahl passiert später)
    # → einfach sec zurückgeben.
    return sec

def get_active_uid() -> str | None:
    sec = read_secrets()
    uid = (sec.get("user.active") or "").strip()
    return uid or None

def list_users_decrypted(master_password: str) -> list[tuple[str, str]]:
    """
    Liefert [(uid, username)] – entschlüsselt alle Namen.
    - Tolerant gegenüber fehlendem Base64-Padding.
    - Überspringt Einträge bei falschem Master/InvalidToken.
    - Sortiert stabil nach Name (case-insensitive).
    """
    sec = read_secrets()
    out: list[tuple[str, str]] = []

    for uid in _users_in_file(sec):
        salt_b64u = sec.get(f"user.{uid}.kdf_salt")
        name_ct   = sec.get(f"user.{uid}.username_enc")
        if not (salt_b64u and name_ct):
            continue

        try:
            # tolerant decoden (fügt '='-Padding bei Bedarf hinzu)
            salt_bytes = _b64d_u_padded(salt_b64u)
            base_raw   = _derive_key_raw(master_password, salt_bytes)
            f_user     = _field_fernet(base_raw, uid, "username")

            name = f_user.decrypt(name_ct.encode("utf-8")).decode("utf-8")
            out.append((uid, name))
        except InvalidToken:
            # falscher Master für diesen Datensatz → still überspringen
            continue
        except Exception:
            # defekte/alte Einträge o.ä. → ebenfalls überspringen
            continue

    # Schöne, deterministische Reihenfolge
    out.sort(key=lambda t: (t[1] or "").casefold())
    return out

def remove_user_entry_by_uid(uid: str) -> None:
    """
    Entfernt alle user.<uid>.* Einträge aus der Secrets-Datei.
    Falls user.active == uid, wird active geleert oder auf einen verbleibenden User gesetzt.
    """
    txt = _read_text(SECRETS_FILE)
    if not txt:
        return

    lines = txt.splitlines()
    out: list[str] = []
    for line in lines:
        raw = line.strip()
        if not raw or raw.startswith("#") or raw.startswith(";"):
            out.append(line)
            continue
        if "=" not in raw:
            out.append(line)
            continue
        k, _ = raw.split("=", 1)
        k = k.strip()
        # user.<uid>.<field> → überspringen (löschen)
        if k.startswith(f"user.{uid}."):
            continue
        out.append(line)

    # user.active ggf. anpassen
    sec_after = {}
    for line in out:
        raw = line.strip()
        if not raw or raw.startswith("#") or raw.startswith(";") or "=" not in raw:
            continue
        k, v = raw.split("=", 1)
        sec_after[k.strip()] = v.strip()

    if sec_after.get("user.active") == uid:
        # nächste vorhandene UID wählen oder leeren
        remaining_uids = _users_in_file(sec_after)
        new_active = remaining_uids[0] if remaining_uids else ""
        # ersetze/füge user.active Zeile
        replaced = False
        for i, line in enumerate(out):
            if line.strip().startswith("user.active"):
                out[i] = f"user.active = {new_active}"
                replaced = True
                break
        if not replaced:
            out.append(f"user.active = {new_active}")

    new_txt = "\n".join(out).rstrip() + "\n"
    _write_text(SECRETS_FILE, new_txt)
    try:
        os.chmod(SECRETS_FILE, 0o600)
    except Exception:
        pass


def get_api_key_by_uid(uid: str, master_password: str) -> str:
    """
    Holt API-Key für gegebenen uid (ohne Klartextnamen).
    """
    sec = read_secrets()
    salt_b64u = sec.get(f"user.{uid}.kdf_salt")
    key_ct = sec.get(f"user.{uid}.api_key_enc")
    if not (salt_b64u and key_ct):
        raise KeyError("User/Key nicht gefunden.")
    base_raw = _derive_key_raw(master_password, _b64d_u(salt_b64u))
    f_key = _field_fernet(base_raw, uid, "api_key")
    return f_key.decrypt(key_ct.encode("utf-8")).decode("utf-8")


def get_api_key_by_username(username: str, master_password: str) -> str:
    """
    Lookup über Klartextnamen (ohne ihn im File zu speichern):
    - iteriert alle User, entschlüsselt 'username_enc', vergleicht normalisiert,
      gibt dann den API-Key zurück.
    """
    target = _norm_user(username)
    sec = read_secrets()
    for uid in _users_in_file(sec):
        salt_b64u = sec.get(f"user.{uid}.kdf_salt")
        name_ct = sec.get(f"user.{uid}.username_enc")
        key_ct = sec.get(f"user.{uid}.api_key_enc")
        if not (salt_b64u and name_ct and key_ct):
            continue
        base_raw = _derive_key_raw(master_password, _b64d_u(salt_b64u))
        f_user = _field_fernet(base_raw, uid, "username")
        try:
            name_plain = f_user.decrypt(name_ct.encode("utf-8")).decode("utf-8")
        except InvalidToken:
            continue
        if _norm_user(name_plain) == target:
            f_key = _field_fernet(base_raw, uid, "api_key")
            return f_key.decrypt(key_ct.encode("utf-8")).decode("utf-8")
    raise KeyError("User nicht gefunden oder Passwort falsch.")


def set_active_user_by_uid(uid: str) -> None:
    write_secret_kv("user.active", uid)
    # sicherstellen, dass die Verzeichnisstruktur vorhanden ist
    try:
        _touch_user_files(uid)
    except Exception:
        # still, nicht kritisch
        pass


def set_active_user_by_username(username: str, master_password: str) -> str:
    """
    Setzt den aktiven User via Namen (entschlüsselt intern, um die uid zu finden).
    Gibt die gesetzte uid zurück.
    """
    target = _norm_user(username)
    for uid, name_plain in list_users_decrypted(master_password):
        if _norm_user(name_plain) == target:
            write_secret_kv("user.active", uid)
            return uid
    raise KeyError("User nicht gefunden (Name).")


def get_active_api_key(master_password: str) -> str | None:
    """
    Holt den API-Key des aktiven Users (user.active). Fällt auf Single-User zurück.
    """
    sec = read_secrets()
    uid = sec.get("user.active")
    if uid:
        try:
            return get_api_key_by_uid(uid, master_password)
        except Exception:
            pass  # fällt durch zum Legacy-Fallback
    # Legacy-Fallback (Single-User)
    token, salt = sec.get("api_key_enc"), sec.get("kdf_salt")
    if token and salt:
        return decrypt_api_key(token, master_password, salt)
    return None

# ==========================================================
# Subkey für History-Crypto
# ==========================================================

_HISTORY_HKDF_INFO = b"chatti:history"

def _b64d_u_padded(s: str) -> bytes:
    s = (s or "").strip()
    # fehlendes '='-Padding ergänzen (Base64 muss Länge % 4 == 0 haben)
    s += "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s.encode("ascii"))

def derive_history_key(master: str, salt_bytes: bytes) -> bytes:
    """
    Leitet einen vom Master-Passwort abgeleiteten Fernet-Key (base64-encoded bytes)
    für die History-Verschlüsselung ab – getrennte KDF-Domäne via HKDF `info`.

    Hinweise:
      - `salt_bytes`: Du kannst hier denselben per-User-Salt wie fürs Login benutzen,
        da HKDF mit `info` ('chatti:history') eine saubere Kontexttrennung macht.
        Wenn du möchtest, kannst du später auch einen separaten salt für History einführen.
    """
    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt_bytes,
        info=_HISTORY_HKDF_INFO,
    )
    key32 = hkdf.derive(master.encode("utf-8"))
    # Fernet erwartet base64-url-encodete 32B:
    return base64.urlsafe_b64encode(key32)


# ================================================================================
# Simple Admin Border for potential destructive commands (user-add, user-remove)
# ================================================================================

ADMIN_PIN_FILE = Path.home() / ".config" / "chatti-cli" / "admin_pin.json"

def _ensure_parents_secure(p: Path) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(p.parent, 0o700)
    except Exception:
        pass

def _write_json_atomic_secure(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Atomic Write
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, dir=str(path.parent)) as tmp:
        json.dump(data, tmp, ensure_ascii=False)
        tmp.flush()
        os.fsync(tmp.fileno())
        tmp_name = tmp.name
    os.replace(tmp_name, path)
    # Rechte/Hidden
    try:
        if os.name != "nt":
            os.chmod(path, 0o600)
        else:
            try:
                FILE_ATTRIBUTE_HIDDEN = 0x2
                ctypes.windll.kernel32.SetFileAttributesW(str(path), FILE_ATTRIBUTE_HIDDEN)
            except Exception:
                pass
    except Exception:
        pass

def _read_json_or_empty(path: Path) -> dict:
    try:
        raw = path.read_text(encoding="utf-8")
        return json.loads(raw)
    except Exception:
        return {}

def count_users_in_secrets() -> int:
    """
    Zählt eindeutige UIDs in den Secrets (Keys: user.<UID>.*).
    """
    sec = load_secrets()
    uids: set[str] = set()
    for k in sec.keys():
        if k.startswith("user.") and k.count(".") >= 2:
            uids.add(k.split(".", 2)[1])
    return len(uids)

def has_any_user() -> bool:
    """True, falls mindestens ein Benutzer in den Secrets existiert."""
    return count_users_in_secrets() > 0

def has_admin_pin() -> bool:
    """True, wenn admin_pin.json existiert und plausibel (salt/hash b64, Parameter vorhanden)."""
    try:
        if not ADMIN_PIN_FILE.exists():
            return False
        data = _read_json_or_empty(ADMIN_PIN_FILE)
        # Pflichtfelder prüfen
        for k in ("salt", "hash", "n", "r", "p"):
            if k not in data:
                return False
        # b64 Plausibilität
        try:
            base64.b64decode((data["salt"] or "").encode("ascii"))
            base64.b64decode((data["hash"] or "").encode("ascii"))
        except Exception:
            return False
        # Parameter
        n = int(data["n"]); r = int(data["r"]); p = int(data["p"])
        if n <= 0 or r <= 0 or p <= 0:
            return False
        return True
    except Exception:
        return False

def change_admin_pin(current_pin: str, new_pin: str) -> None:
    """
    Ändert den Admin-PIN:
    - Wenn noch keiner existiert, wird einfach neu gesetzt.
    - Prüft Stärke des neuen PIN.
    - Validiert den aktuellen PIN (falls vorhanden).
    """
    ok, reason = validate_admin_secret(new_pin)
    if not ok:
        raise RuntimeError(f"Neues Admin-Passwort zu schwach: {reason}")

    # Wenn kein PIN existiert → setze neu
    if not has_admin_pin():
        set_admin_pin(new_pin)
        return

    # Sonst: aktuellen prüfen
    try:
        if not verify_admin_pin(current_pin or ""):
            raise RuntimeError("Aktueller Admin-PIN ist ungültig.")
    except Exception as e:
        # z.B. beschädigte Datei / JSON-Fehler
        raise RuntimeError(f"PIN-Validierung fehlgeschlagen: {type(e).__name__}: {e}")

    # Speichern
    set_admin_pin(new_pin)


def set_admin_pin(pin: str) -> None:
    ok, reason = validate_admin_secret(pin)
    if not ok:
        raise RuntimeError(f"Admin-Passwort zu schwach: {reason}")

    _ensure_parents_secure(ADMIN_PIN_FILE)
    try:
        salt = os.urandom(16)
        h = hashlib.scrypt(pin.encode("utf-8"), salt=salt, n=2**14, r=8, p=1, dklen=32)
        data = {
            "salt": base64.b64encode(salt).decode("ascii"),
            "hash": base64.b64encode(h).decode("ascii"),
            "n": 2**14, "r": 8, "p": 1, "dklen": 32,
        }
        _write_json_atomic_secure(ADMIN_PIN_FILE, data)
    except Exception as e:
        raise RuntimeError(f"Admin-PIN konnte nicht gespeichert werden: {type(e).__name__}: {e}")

def validate_admin_secret(pw: str) -> tuple[bool, str]:
    """
    Verwendet dieselbe Policy wie validate_master_password(), damit wir
    keine zweite, divergierende Passwortlogik pflegen.
    """
    return validate_master_password(pw)

def verify_admin_pin(pin: str) -> bool:
    try:
        data = _read_json_or_empty(ADMIN_PIN_FILE)
        if not data:
            return False
        salt = base64.b64decode(data["salt"])
        expect = base64.b64decode(data["hash"])
        n, r, p = int(data["n"]), int(data["r"]), int(data["p"])
        dklen = int(data.get("dklen", 32))
        h = hashlib.scrypt(pin.encode("utf-8"), salt=salt, n=n, r=r, p=p, dklen=dklen)
        return h == expect
    except Exception:
        return False


def ensure_admin_pin_initialized_interactive(strict: bool = False) -> bool:
    """
    Stellt sicher, dass ein Admin-PIN gesetzt ist.
    - Gibt True zurück, wenn ein PIN vorhanden/gesetzt wurde.
    - Gibt False zurück, wenn der Vorgang abgebrochen wurde (ohne Exception),
      außer strict=True: dann wird bei Abbruch RuntimeError geworfen.
    """
    if has_admin_pin():
        return True

    print("Kein Admin-PIN gesetzt. Bitte jetzt einen festlegen.")
    while True:
        try:
            p1 = getpass("Neuer Admin-PIN/Passwort: ")
        except (KeyboardInterrupt, EOFError):
            print("\nAdmin-PIN-Einrichtung abgebrochen.")
            if strict:
                raise RuntimeError("Admin-PIN-Einrichtung abgebrochen.")
            return False

        ok, reason = validate_admin_secret(p1)
        if not ok:
            print(f"✖  {reason}")
            continue

        try:
            p2 = getpass("Wiederholung: ")
        except (KeyboardInterrupt, EOFError):
            print("\nAdmin-PIN-Einrichtung abgebrochen.")
            if strict:
                raise RuntimeError("Admin-PIN-Einrichtung abgebrochen.")
            return False

        if p1 != p2:
            print("✖  Eingaben unterscheiden sich.")
            continue

        try:
            set_admin_pin(p1)
        except Exception as e:
            msg = f"Admin-PIN konnte nicht gespeichert werden: {type(e).__name__}: {e}"
            if strict:
                raise RuntimeError(msg)
            print(msg)
            return False

        print("✓ Admin-PIN gesetzt.")
        return True


def change_admin_pin_interactive(max_tries: int = 3) -> bool:
    """
    Interaktive Änderung des Admin-PIN/Passworts.
    Rückgabe:
      True  -> Änderung erfolgreich
      False -> abgebrochen oder nach max_tries gescheitert

    Ablauf:
      1) Falls noch kein PIN existiert, wird die einmalige Einrichtung gestartet.
      2) Aktuellen PIN erfragen.
      3) Neuen PIN (zweifach) erfragen, Policy prüfen.
      4) Änderung durchführen (change_admin_pin), Fehler sauber behandeln.
    """
    # 1) Existenz sicherstellen (freundlich interaktiv einrichten, wenn noch nicht gesetzt)
    if not has_admin_pin():
        print("Kein Admin-PIN gesetzt. Jetzt festlegen.")
        try:
            ok = ensure_admin_pin_initialized_interactive(strict=True)
        except (KeyboardInterrupt, EOFError):
            print("\nAbgebrochen.")
            return False
        return bool(ok)

    # 2) Mehrfach versuchen, bis Änderung klappt oder Versuche aufgebraucht
    tries = 0
    while tries < max_tries:
        tries += 1
        try:
            current = getpass("Aktueller Admin-PIN/Passwort: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nAbgebrochen.")
            return False

        if not current:
            print("✖ Eingabe leer — bitte erneut.")
            continue

        # 3) Neuen PIN doppelt erfragen + Policy prüfen
        try:
            p1 = getpass("Neuer Admin-PIN/Passwort: ").strip()
            ok, reason = validate_admin_secret(p1)
            if not ok:
                print(f"✖ {reason}")
                continue

            p2 = getpass("Wiederholung: ").strip()
            if p1 != p2:
                print("✖ Passwörter ungleich — bitte erneut.")
                continue
        except (KeyboardInterrupt, EOFError):
            print("\nAbgebrochen.")
            return False

        # 4) Änderung versuchen (prüft intern den aktuellen PIN)
        try:
            change_admin_pin(current_pin=current, new_pin=p1)
            # Erfolg (kein Print hier; die CLI darf "✓ Admin-PIN geändert." melden)
            return True
        except ValueError as e:
            # typischerweise bei falschem aktuellem PIN
            msg = str(e).lower()
            if "current" in msg or "falsch" in msg or "invalid" in msg:
                print("✖ Aktueller Admin-PIN falsch.")
                continue
            print(f"✖ Änderung fehlgeschlagen: {type(e).__name__}: {e}")
            return False
        except (KeyboardInterrupt, EOFError):
            print("\nAbgebrochen.")
            return False
        except Exception as e:
            print(f"✖ Unerwarteter Fehler: {type(e).__name__}: {e}")
            return False

    print("Abbruch: Zu viele Fehlversuche.")
    return False


def verify_admin_pin_interactive(max_tries: int = 3) -> bool:
    """
    Fragt den Admin-PIN ab und validiert ihn.
    - Bricht bei Ctrl+C / Ctrl+D ohne Traceback ab (False).
    - Leere Eingaben werden abgewiesen, ohne Versuchs-Counter zu verbrauchen.
    """
    tries = 0
    while tries < max_tries:
        try:
            pin = getpass("Admin-PIN: ")
        except (KeyboardInterrupt, EOFError):
            print("\nAbgebrochen.")
            return False

        if not pin:
            print("✖  Keine Eingabe.")
            continue  # zählt nicht als Versuch

        try:
            if verify_admin_pin(pin):
                return True
            print("✖  Falscher PIN.")
            tries += 1
        except Exception:
            # Unerwarteter Zustand der Datei o.ä.
            print("✖  PIN-Prüfung derzeit nicht möglich.")
            return False
    return False
