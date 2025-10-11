# core/history.py
from __future__ import annotations

import base64
import json
import os
import re
import time
from datetime import datetime
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

from .paths import _init_history_file_if_missing, user_data_dir, user_history_file
from .security import _b64d_u_padded, derive_history_key, get_active_uid, load_secrets


# -------------------------------------------------------------------
# Pfad & Schlüssel
# -------------------------------------------------------------------
def _history_path(uid: str | None = None) -> Path:
    uid_eff = uid or get_active_uid()
    if not uid_eff:
        # Kein aktiver User → leere, user-lokale Datei (oder: raise)
        return user_history_file("default")
    p = user_history_file(uid_eff)
    user_data_dir(uid_eff)  # parent sicherstellen
    return p


def _history_key_for_uid(uid: str, master: str) -> Fernet:
    sec = load_secrets()
    b64 = (sec.get(f"user.{uid}.kdf_salt") or "").strip()
    if not b64:
        raise RuntimeError("KDF-Salt fehlt im Secrets für diesen Benutzer.")
    # WICHTIG: urlsafe + Padding-fix
    salt = _b64d_u_padded(b64)
    fkey = derive_history_key(master, salt)  # liefert Fernet-Key (base64)
    return Fernet(fkey)


def _now_iso() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


# -------------------------------------------------------------------
# Public API
# -------------------------------------------------------------------
def load_history(
    last_n: int | None = None,
    *,
    uid: str | None = None,
    master: str | None = None,
) -> list[dict]:
    uid_eff = uid or get_active_uid()
    if not uid_eff:
        return []
    path = _history_path(uid_eff)
    if not path.exists():
        return []

    master_eff = master or os.environ.get("CHATTI_MASTER")
    if not master_eff:
        return []

    f = _history_key_for_uid(uid_eff, master_eff)
    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    if last_n:
        lines = lines[-last_n:]

    out: list[dict] = []
    for line in lines:
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        try:
            payload = f.decrypt(s.encode("ascii"), ttl=None)
            rec = json.loads(payload.decode("utf-8"))
            if isinstance(rec, dict) and "role" in rec and "content" in rec:
                out.append(rec)
        except (InvalidToken, ValueError):
            # Tolerant: kaputte/alte Zeilen überspringen
            continue
    return out


def load_history_tail(
    last_n: int = 200,
    *,
    uid: str | None = None,
    master: str | None = None,
    newest_first: bool = False,
    chunk_size: int = 64 * 1024,
) -> list[dict]:
    """
    Wie load_history(), aber effizient: liest nur die letzten `last_n` Zeilen
    (per tail) und entschlüsselt nur diese.

    - newest_first=False  → Rückgabe in chronologischer Reihenfolge (alt → neu)
      newest_first=True   → neueste zuerst
    """
    uid = uid or get_active_uid()
    if not uid or last_n <= 0:
        return []
    path = _history_path(uid)
    if not path.exists():
        return []

    master = master or os.environ.get("CHATTI_MASTER")
    if not master:
        return []

    fernet = _history_key_for_uid(uid, master)

    # --- tail letzte N Zeilen, ohne ganze Datei zu laden ---
    want = last_n
    lines: list[bytes] = []
    remainder = b""

    with open(path, "rb") as fh:
        fh.seek(0, os.SEEK_END)
        pos = fh.tell()

        while pos > 0 and len(lines) < want + 1:  # +1: falls letzte Zeile leer
            read_size = min(chunk_size, pos)
            pos -= read_size
            fh.seek(pos, os.SEEK_SET)
            chunk = fh.read(read_size)
            remainder = chunk + remainder
            parts = remainder.split(b"\n")
            # die letzte Komponente ist evtl. unvollständig → für nächste Runde aufheben
            remainder = parts[0]
            # alle *vollständigen* Zeilen (ab Index 1) einsammeln
            lines[0:0] = parts[1:]  # vorne einfügen, damit Reihenfolge stimmt

        # am Anfang der Datei bleibt evtl. eine Restzeile übrig
        if remainder:
            lines[0:0] = [remainder]

    # Nur die letzten N Textzeilen (Base64-Tokens) nehmen
    tail_lines = [ln.strip() for ln in lines if ln.strip()][-last_n:]

    out: list[dict] = []
    for s in tail_lines:
        try:
            payload = fernet.decrypt(s, ttl=None)
            rec = json.loads(payload.decode("utf-8"))
            if isinstance(rec, dict) and "role" in rec and "content" in rec:
                out.append(rec)
        except Exception:
            # kaputte/alte Zeilen tolerant überspringen
            continue

    if newest_first:
        out.reverse()  # wir hatten chronologisch → umdrehen
    return out


def history_import(
    src: Path,
    *,
    uid: str | None = None,
    export_passphrase: str | None = None,  # Passphrase des *Exports* (nur für enc-Dumps)
    replace: bool = False,
) -> int:
    """
    Importiert eine History-Dump-Datei (verschlüsselt oder plain).
    - src: Pfad zur Dump-Datei
    - uid: Ziel-User (default: aktiver User)
    - export_passphrase: Passphrase des *Exports* (nur für enc-Dumps nötig)
    - replace=True → existierende History-Datei überschreiben
    Rückgabe: Anzahl importierter Einträge.
    """
    u = uid or get_active_uid()
    if not u:
        raise RuntimeError("Kein aktiver Benutzer (history_import).")
    if not src.exists():
        raise FileNotFoundError(f"Dump-Datei nicht gefunden: {src}")

    # ---- Dateiinhalt lesen (robust) ----
    # Wir arbeiten intern mit 'text' (UTF-8, BOM entfernt).
    try:
        text = src.read_text(encoding="utf-8", errors="ignore")
    except Exception as e:
        raise RuntimeError(f"Lesefehler bei Dump-Datei: {type(e).__name__}: {e}")
    text = (text or "").lstrip("\ufeff").strip()

    records: list[dict] = []

    # ---- enc/plain autodetect ----
    is_enc = False
    doc = None
    try:
        doc = json.loads(text)
        is_enc = isinstance(doc, dict) and doc.get("fmt") == "chatti-hist-v1"
    except json.JSONDecodeError:
        is_enc = False

    if is_enc:
        # --- verschlüsselter Export ---
        if not export_passphrase:
            raise ValueError("Passphrase für verschlüsselten Import erforderlich.")
        try:
            salt = base64.b64decode(doc["salt_b64"])
            params = doc.get("scrypt", {"n": 16384, "r": 8, "p": 1, "dklen": 32})
            raw_key = _scrypt_derive_key(export_passphrase, salt, **params)
            fkey = base64.urlsafe_b64encode(raw_key)
            f = Fernet(fkey)
            payload = f.decrypt(base64.b64decode(doc["ciphertext_b64"]))
            plaintext = payload.decode("utf-8", errors="ignore")
            for line in plaintext.splitlines():
                try:
                    rec = json.loads(line)
                    if isinstance(rec, dict) and "role" in rec and "content" in rec:
                        records.append(rec)
                except Exception:
                    continue
        except Exception as e:
            raise ValueError(f"Entschlüsselung/Parsing fehlgeschlagen: {type(e).__name__}: {e}")
    else:
        # --- Plain JSONL ---
        for line in text.splitlines():
            try:
                rec = json.loads(line)
                if isinstance(rec, dict) and "role" in rec and "content" in rec:
                    records.append(rec)
            except Exception:
                continue

    # ---- Einfügen ----
    if replace:
        reset_user_history(u)

    # WICHTIG: Hier NICHT export_passphrase benutzen – speichern geht wie immer über User-Master.
    for rec in records:
        save_turn(rec["role"], rec["content"], uid=u, master=None)

    return len(records)


def save_turn(
    role: str,
    content: str,
    *,
    uid: str | None = None,
    master: str | None = None,
) -> None:
    uid_eff = uid or get_active_uid()
    if not uid_eff:
        raise RuntimeError("Kein aktiver Benutzer (History).")
    master_eff = master or os.environ.get("CHATTI_MASTER")
    if not master_eff:
        raise RuntimeError("Master-Passwort nicht verfügbar (ENV CHATTI_MASTER).")

    f = _history_key_for_uid(uid_eff, master_eff)
    rec = {"ts": _now_iso(), "role": role, "content": content}
    token = f.encrypt(json.dumps(rec, ensure_ascii=False).encode("utf-8"))
    with _history_path(uid_eff).open("a", encoding="utf-8") as out:
        out.write(token.decode("ascii") + "\n")


def reset_user_history(uid: str | None = None) -> None:
    """
    Hartes Reset: Datei entfernen und mit Header neu anlegen (0600).
    """
    u = uid or get_active_uid()
    if not u:
        raise RuntimeError("Kein aktiver Benutzer (reset_user_history).")
    p = _history_path(u)
    try:
        if p.exists():
            p.unlink()
    except Exception:
        pass
    _init_history_file_if_missing(p)


def _scrypt_derive_key(
    passphrase: str,
    salt: bytes,
    *,
    n: int = 2**14,
    r: int = 8,
    p: int = 1,
    dklen: int = 32,
) -> bytes:
    """Scrypt → Key (für Fernet Base64-Kodierung)."""
    kdf = Scrypt(salt=salt, length=dklen, n=n, r=r, p=p)
    return kdf.derive(passphrase.encode("utf-8"))


def history_dump(
    dst: Path,
    *,
    mode: str = "enc",  # "enc" | "plain"
    passphrase: str | None = None,  # nur für enc
    uid: str | None = None,
    confirm_plain: bool = False,  # explizites Opt-in für Klartext
) -> int:
    """
    Exportiert die aktuelle History in eine Datei.

    - mode="enc": Verschlüsselter Export (NEUE Passphrase nötig).
    - mode="plain": Klartext-JSONL. Aus Sicherheitsgründen nur, wenn confirm_plain=True.

    Rückgabe: Anzahl exportierter Zeilen.
    """
    mode_norm = (mode or "").strip().lower()

    if mode_norm == "plain":
        if not confirm_plain:
            raise ValueError("Klartext-Export erfordert confirm_plain=True.")
        return dump_history_plain(dst, uid=uid)

    if mode_norm == "enc":
        if not passphrase:
            raise ValueError("Passphrase für verschlüsselten Export (mode='enc') erforderlich.")
        return dump_history_encrypted(dst, passphrase=passphrase, uid=uid)

    raise ValueError(f"Unbekannter mode: {mode!r} (erwartet 'enc' oder 'plain')")


def dump_history_plain(dst: Path, uid: str | None = None) -> int:
    """
    Entschlüsselte History als JSONL im Klartext schreiben.
    Rückgabe: Anzahl exportierter Zeilen.
    """
    u = uid or get_active_uid()
    if not u:
        raise RuntimeError("Kein aktiver Benutzer (dump_history_plain).")
    records = load_history(uid=u)  # → bereits entschlüsselte dicts
    dst.parent.mkdir(parents=True, exist_ok=True)
    with dst.open("w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    try:
        os.chmod(dst, 0o600)
    except Exception:
        pass
    return len(records)


def dump_history_encrypted(dst: Path, passphrase: str, uid: str | None = None) -> int:
    """
    Entschlüsselte History als *verschlüsselten* JSON-Blob speichern.
    Format:
      {
        "fmt":"chatti-hist-v1",
        "ts": 1699999999,
        "salt_b64": "...",
        "scrypt": {"n":16384,"r":8,"p":1,"dklen":32},
        "ciphertext_b64": "..."
      }
    Rückgabe: Anzahl exportierter Zeilen (vor Verschlüsselung).
    """
    u = uid or get_active_uid()
    if not u:
        raise RuntimeError("Kein aktiver Benutzer (dump_history_encrypted).")

    records = load_history(uid=u)
    payload = "\n".join(json.dumps(rec, ensure_ascii=False) for rec in records).encode("utf-8")

    salt = os.urandom(16)
    raw_key = _scrypt_derive_key(passphrase, salt)
    fkey = base64.urlsafe_b64encode(raw_key)
    f = Fernet(fkey)
    ct = f.encrypt(payload)

    doc = {
        "fmt": "chatti-hist-v1",
        "ts": int(time.time()),
        "salt_b64": base64.b64encode(salt).decode("ascii"),
        "scrypt": {"n": 16384, "r": 8, "p": 1, "dklen": 32},
        "ciphertext_b64": base64.b64encode(ct).decode("ascii"),
    }
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    try:
        os.chmod(dst, 0o600)
    except Exception:
        pass
    return len(records)


# -------------------------------------------------------------------
# Suche (verschlüsselte JSONL Zeile-für-Zeile entschlüsseln)
# -------------------------------------------------------------------
def _match(line_text: str, needle: str, mode: str, case_sensitive: bool) -> bool:
    t = line_text if case_sensitive else line_text.lower()
    q = needle if case_sensitive else needle.lower()

    if mode == "regex":
        flags = 0 if case_sensitive else re.IGNORECASE
        try:
            return re.search(needle, line_text, flags) is not None
        except re.error:
            return False

    terms = [x for x in q.split() if x]
    if not terms:
        return False
    if mode == "or":
        return any(term in t for term in terms)
    # default: "and"
    return all(term in t for term in terms)


# def _make_snippet(text: str, query: str, *, case_sensitive: bool, width: int = 160) -> str:
# # alles zu einer Zeile zusammenziehen (Leerzeilen komprimieren)
# flat = re.sub(r"\s+", " ", text).strip()
# if not flat:
#     return ""
#
# # Position des ersten Treffers suchen
# flags = 0 if case_sensitive else re.IGNORECASE
# m = re.search(re.escape(query), flat, flags)
# if not m:
#     # Fallback: Anfang zeigen
#     return (flat[:width] + "…") if len(flat) > width else flat
#
# start = max(0, m.start() - width // 4)   # etwas Kontext davor
# end   = min(len(flat), m.end() + width // 2)  # mehr Kontext danach
# cut = flat[start:end]
# # Ellipsen sauber setzen
# if start > 0:
#     cut = "… " + cut
# if end < len(flat):
#     cut = cut + " …"
# return cut


def _make_snippet(text: str, query: str, *, case_sensitive: bool, width: int = 160) -> str:
    # alles zu einer Zeile zusammenziehen (Leerzeilen komprimieren)
    flat = re.sub(r"\s+", " ", text).strip()
    if not flat:
        return ""

    # 1) Erst versuchen, query als Regex zu verwenden (für mode="regex")
    flags = 0 if case_sensitive else re.IGNORECASE
    m = None
    try:
        rx = re.compile(query, flags)
        m = rx.search(flat)
    except re.error:
        pass

    # 2) Falls Regex nicht passt/kompiliert: Literal-Suche
    if not m:
        m = re.search(re.escape(query), flat, flags)

    # 3) Nichts gefunden → Anfang zeigen
    if not m:
        return (flat[:width] + "…") if len(flat) > width else flat

    start = max(0, m.start() - width // 4)  # etwas Kontext davor
    end = min(len(flat), m.end() + width // 2)  # mehr Kontext danach
    cut = flat[start:end]
    if start > 0:
        cut = "… " + cut
    if end < len(flat):
        cut = cut + " …"
    return cut


def search_history(
    query: str,
    mode: str = "and",  # "and" | "or" | "regex"
    case_sensitive: bool = False,
    limit: int = 50,
    uid: str | None = None,
    master: str | None = None,
    with_context: bool = True,  # ← optional: vorher/nachher mitgeben
) -> list[dict]:
    """
    Durchsucht die (verschlüsselte) User-History zeilenweise.
    Rückgabe: Liste von Treffern mit {idx, ts, role, snippet, ...} und optional Kontext.
    """
    uid = uid or get_active_uid()
    if not uid:
        return []
    path = _history_path(uid)
    if not path.exists():
        return []

    master = master or os.environ.get("CHATTI_MASTER")
    if not master:
        return []

    fernet = _history_key_for_uid(uid, master)

    # Query vorbereiten
    q = (query or "").strip()
    if not q:
        return []
    regex = None
    if mode == "regex":
        try:
            flags = 0 if case_sensitive else re.IGNORECASE
            regex = re.compile(q, flags)
        except re.error:
            return []

    # Alle Zeilen entschlüsseln (tolerant)
    plain: list[dict] = []
    raw_lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    for line in raw_lines:
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        try:
            payload = fernet.decrypt(s.encode("ascii"))
            rec = json.loads(payload.decode("utf-8"))
            if isinstance(rec, dict) and "role" in rec and "content" in rec:
                # ts nachrüsten falls gewünscht
                if "ts" not in rec:
                    rec["ts"] = _now_iso()
                plain.append(rec)
        except Exception:
            # kaputte/alte Zeilen überspringen
            continue

    # Match-Logik
    res: list[dict] = []
    for idx, rec in enumerate(plain):
        text = str(rec.get("content") or "")
        if not text:
            continue
        if mode == "regex":
            ok = bool(regex.search(text)) if regex else False
        else:
            ok = _match(text, q, mode, case_sensitive)
        if not ok:
            continue

        # first = text.splitlines()[0]
        # snippet = (first[:160] + "…") if len(first) > 160 else first
        snippet = _make_snippet(text, q, case_sensitive=case_sensitive, width=160)

        item = {
            "idx": idx,  # Position in History (0=bestehender Anfang)
            "ts": rec.get("ts"),
            "role": rec.get("role"),
            "snippet": snippet,
        }

        if with_context:
            # Vorher/Nachher (best effort)
            if idx > 0:
                prev = plain[idx - 1]
                item["prev"] = {
                    "role": prev.get("role"),
                    "line": (prev.get("content") or "").splitlines()[0][:160],
                }
            if idx + 1 < len(plain):
                nxt = plain[idx + 1]
                item["next"] = {
                    "role": nxt.get("role"),
                    "line": (nxt.get("content") or "").splitlines()[0][:160],
                }

        res.append(item)
        if len(res) >= max(1, limit):
            break

    return res


# -------------------------------------------------------------------
# Eingabe-Hilfen (TUI)
# -------------------------------------------------------------------
def load_user_inputs(uid: str | None = None, last_n: int = 200) -> list[str]:
    """Letzte N Nutzereingaben (role=='user'), neueste zuerst, als Liste."""
    hist = load_history(last_n=max(last_n * 5, 1000), uid=uid)
    users = [
        h.get("content", "")
        for h in hist
        if h.get("role") == "user" and (h.get("content") or "").strip()
    ]
    return users[-last_n:][::-1]


def load_user_commands(uid: str | None = None, last_n: int = 200) -> list[str]:
    """Nur Kommandos (User-Eingaben beginnend mit ':' oder '/'), neueste zuerst, als Liste."""
    hist = load_history(last_n=max(last_n * 5, 1000), uid=uid)
    cmds: list[str] = []
    for h in hist:
        if h.get("role") != "user":
            continue
        text = (h.get("content") or "").lstrip()
        if text.startswith(("/", ":")):
            cmds.append(text)
    return cmds[-last_n:][::-1]
