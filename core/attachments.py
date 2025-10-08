# core/attachments.py
from __future__ import annotations

import base64
import hashlib
import json
import mimetypes
import os
import re
import shutil
import time
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from core.paths import (
    normalize_user_path,
    user_attachments_dir,
    user_attachments_files_dir,
    user_attachments_manifest,
)
from core.security import get_active_uid  # für _must_uid()

# -------------------------------------------------------------------
# Konstanten
# -------------------------------------------------------------------
_MAX_DATAURL_BYTES = 8 * 1024 * 1024  # 8 MiB

# Kritische Typen, bei denen die Endung oft „lügt“ → Endung darf nur mit passendem Header durch
_CRITICAL_EXT = {
    ".pdf":  "application/pdf",
    ".svg":  "image/svg+xml",
    ".zip":  "application/zip",
    ".tar":  "application/x-tar",
    ".gz":   "application/gzip",
    ".tgz":  "application/gzip",
    ".bz2":  "application/x-bzip2",
    ".xz":   "application/x-xz",
    ".7z":   "application/x-7z-compressed",
    ".docx": "application/zip",
    ".xlsx": "application/zip",
    ".pptx": "application/zip",
    ".doc":  "application/x-ole-storage",
    ".xls":  "application/x-ole-storage",
    ".ppt":  "application/x-ole-storage",
}

# -------------------------------------------------------------------
# Utilities
# -------------------------------------------------------------------

class AttachmentValidationError(ValueError):
    def __init__(self, path: Path, ext: str, expected: str, reason: str):
        super().__init__(reason)
        self.path = path
        self.ext = ext
        self.expected = expected
        self.reason = reason

def _now_ts() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")

def _safe_name(name: str) -> str:
    """Konservativ: Leerzeichen→_, nur [A-Za-z0-9._-], Mehrfach-„-“ eindampfen, Endungen behalten."""
    name = name.strip().replace(" ", "_")
    name = re.sub(r"[^A-Za-z0-9._-]+", "-", name)
    name = re.sub(r"-{2,}", "-", name).strip("-")
    return name or "file"

def _sha256_file(path: Path, chunk: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for blk in iter(lambda: f.read(chunk), b""):
            h.update(blk)
    return h.hexdigest()

def _must_uid(uid: str | None) -> str:
    u = uid or get_active_uid()
    if not u:
        raise RuntimeError("Kein aktiver Benutzer. Nutze '--user-use' oder '--user-add'.")
    return u

def _ensure_user_dirs(uid: str) -> None:
    user_attachments_dir(uid)
    user_attachments_files_dir(uid)

def _load_manifest(path: Path) -> dict:
    if not path.exists():
        return {"version": 1, "items": []}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"version": 1, "items": []}

def _save_manifest(path: Path, obj: dict) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)

def _normalize_item(it: dict, files_dir: Path) -> dict:
    out = dict(it)
    # Legacy-kompatible Keys:
    if "name" not in out:
        out["name"] = out.get("filename", "")
    # Absoluter Pfad berechnen:
    rel = out.get("relpath") or out.get("filename", "")
    fpath = files_dir / rel
    out["path"] = str(fpath)
    return out

def _magic_mime(path: Path) -> str:
    """Kleines Sniffing ohne externe Deps (Header + ein paar Offsets)."""
    try:
        with path.open("rb") as f:
            head = f.read(560)  # ZIP, OLE, ustar (Offset 257), SVG-Heuristik
    except Exception:
        head = b""

    # PDFs
    if head.startswith(b"%PDF"):
        return "application/pdf"

    # Bilder
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if head.startswith(b"GIF87a") or head.startswith(b"GIF89a"):
        return "image/gif"
    # SVG (heuristisch)
    low = head.lower()
    if low[:5].startswith(b"<?xml") or b"<svg" in low:
        return "image/svg+xml"

    # RTF
    if head.startswith(b"{\\rtf"):
        return "application/rtf"

    # OLE2/CFBF (altes MS Office)
    if head.startswith(b"\xD0\xCF\x11\xE0\xA1\xB1\x1A\xE1"):
        return "application/x-ole-storage"

    # ZIP (docx/xlsx/pptx, odt, epub, jar, …)
    if head.startswith((b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")):
        return "application/zip"

    # tar („ustar“ an Offset 257)
    if len(head) >= 265 and head[257:262] == b"ustar":
        return "application/x-tar"

    # gzip / bzip2 / xz / 7z
    if head.startswith(b"\x1F\x8B\x08"):
        return "application/gzip"
    if head.startswith(b"BZh"):
        return "application/x-bzip2"
    if head.startswith(b"\xFD\x37\x7A\x58\x5A\x00"):
        return "application/x-xz"
    if head.startswith(b"\x37\x7A\xBC\xAF\x27\x1C"):
        return "application/x-7z-compressed"

    # Fallback: Dateiendung
    mt, _ = mimetypes.guess_type(str(path))
    return mt or "application/octet-stream"


def _decide_mime_and_validate(path: Path) -> tuple[str, bool, str]:
    """
    -> (final_mime, is_valid, reason)
    - Kritische Endungen: passenden Magic-Header zwingend erforderlich.
    - Nicht-kritische: Magic bevorzugt; sonst Endung; sonst octet-stream.
    - OpenXML kriegen präzise Vendor-MIMEs, OLE-Altformate per Endung gemappt.
    """
    ext = path.suffix.lower()
    magic = _magic_mime(path)

    if ext in _CRITICAL_EXT:
        must = _CRITICAL_EXT[ext]
        if magic == must:
            # Verfeinerung: OpenXML
            if must == "application/zip":
                if ext == ".docx":
                    return "application/vnd.openxmlformats-officedocument.wordprocessingml.document", True, "zip+docx"
                if ext == ".xlsx":
                    return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", True, "zip+xlsx"
                if ext == ".pptx":
                    return "application/vnd.openxmlformats-officedocument.presentationml.presentation", True, "zip+pptx"
            # Verfeinerung: OLE-Altformate
            if must == "application/x-ole-storage":
                if ext == ".doc":
                    return "application/msword", True, "ole+doc"
                if ext == ".xls":
                    return "application/vnd.ms-excel", True, "ole+xls"
                if ext == ".ppt":
                    return "application/vnd.ms-powerpoint", True, "ole+ppt"
            return must, True, "magic-ok"
        # Header passt NICHT zur Endung → invalid
        return "application/octet-stream", False, f"extension {ext} requires magic {must}"

    # Nicht-kritisch: Magic gewinnt
    if magic and magic != "application/octet-stream":
        if magic == "application/x-ole-storage":
            # alte Office-Typen per Endung verfeinern (wenn möglich)
            if ext == ".doc":
                return "application/msword", True, "ole+doc"
            if ext == ".xls":
                return "application/vnd.ms-excel", True, "ole+xls"
            if ext == ".ppt":
                return "application/vnd.ms-powerpoint", True, "ole+ppt"
        return magic, True, "magic"

    # Fallback: Endung (oder ganz generisch)
    mt, _ = mimetypes.guess_type(str(path))
    return (mt or "application/octet-stream"), True, "ext-fallback"

# -------------------------------------------------------------------
# Public API (Multi-User, API-kompatibel)
# -------------------------------------------------------------------

def list_attachments(
    kind: str | None = None,
    _include_deleted: bool = False,   # legacy-kompatibles Flag, hat hier keine Wirkung
    uid: str | None = None,
) -> list[dict[str, Any]]:
    """
    Liefert Attachments des aktiven (oder gegebenen) Users, neueste zuerst.
    """
    u = _must_uid(uid)
    _ensure_user_dirs(u)

    manifest = _load_manifest(user_attachments_manifest(u))
    items = list(manifest.get("items", []))
    if kind:
        items = [m for m in items if str(m.get("mime", "")).startswith(kind)]
    items.sort(key=lambda x: x.get("added_ts", 0), reverse=True)
    items = [_normalize_item(m, files_dir=user_attachments_files_dir(u)) for m in items]
    return items

def add_attachment(
    src: str | Path,
    alias: str | None = None,
    tags: list[str] | None = None,
    note: str | None = None,
    uid: str | None = None,
) -> dict[str, Any]:
    """
    Datei in den User-Attachment-Store kopieren und im Manifest registrieren.
    """
    u = _must_uid(uid)
    _ensure_user_dirs(u)
    files_dir = user_attachments_files_dir(u)
    manifest_path = user_attachments_manifest(u)
    mf = _load_manifest(manifest_path)

    ###src_path = Path(src).expanduser().resolve()
    src_path = normalize_user_path(src)
    if not src_path.exists() or not src_path.is_file():
        raise FileNotFoundError(f"Attachment source not found: {src_path}")

    sha = _sha256_file(src_path)
    size = src_path.stat().st_size

    # ZENTRAL: MIME ermitteln + validieren (kritische Endungen erfordern passenden Header)
    final_mime, ok, reason = _decide_mime_and_validate(src_path)
    if not ok:
        expected = _CRITICAL_EXT.get(src_path.suffix.lower(), "application/octet-stream")
        raise AttachmentValidationError(src_path, src_path.suffix.lower(), expected, reason)
    real_mime = final_mime

    # Zielpfad (Bucket nach Hash)
    bucket = files_dir / sha[:2] / sha[2:4]
    bucket.mkdir(parents=True, exist_ok=True)
    dst_name = _safe_name(alias or src_path.name)
    dst_path = bucket / dst_name
    if dst_path.exists() and _sha256_file(dst_path) != sha:
        base, ext = os.path.splitext(dst_name)
        dst_path = bucket / f"{base}.{sha[:8]}{ext}"

    shutil.copy2(src_path, dst_path)

    item: dict[str, Any] = {
        "id": sha,
        "filename": dst_path.name,
        "name": dst_path.name,
        "mime": real_mime,           # ← jetzt korrekt gesetzt
        "size": size,
        "sha256": sha,
        "added_ts": int(time.time()),
        "relpath": str(dst_path.relative_to(files_dir)),
    }

    if alias:
        item["alias"] = alias
    if tags:
        item["tags"] = list(tags)
    if note:
        item["note"] = note

    # vorhandenen Eintrag (gleiche id) ersetzen, sonst anhängen
    items = mf.get("items", [])
    for i, it in enumerate(items):
        if it.get("id") == sha:
            items[i] = item
            break
    else:
        items.append(item)
    mf["items"] = items
    _save_manifest(manifest_path, mf)
    return item

def find_attachment(name_or_id: str, uid: str | None = None) -> dict[str, Any] | None:
    """
    Suche per id (sha256), filename, alias. Rückgabe inkl. absolutem Pfad.
    """
    u = _must_uid(uid)
    _ensure_user_dirs(u)
    files_dir = user_attachments_files_dir(u)
    manifest = _load_manifest(user_attachments_manifest(u))

    needle = (name_or_id or "").strip().lower()
    found: dict[str, Any] | None = None
    for it in manifest.get("items", []):
        if (
            it.get("id", "").lower() == needle
            or it.get("filename", "").lower() == needle
            or str(it.get("alias", "")).lower() == needle
        ):
            found = dict(it)
            break

    if not found:
        return None

    rel = found.get("relpath") or found.get("filename")
    fpath = files_dir / rel
    if not fpath.exists():
        # Fallback: sehr alte Strukturen durchsuchen
        for root, _, files in os.walk(files_dir):
            if found.get("filename") in files:
                fpath = Path(root) / found["filename"]
                break
        # Noch immer nichts? → sauber None zurück
        if not fpath.exists():
            return None

    found["path"] = str(fpath)
    found = _normalize_item(found, files_dir)
    return found

def read_bytes(name_or_id: str, max_bytes: int | None = None, uid: str | None = None) -> bytes:
    meta = find_attachment(name_or_id, uid=uid)
    if not meta:
        raise FileNotFoundError(f"Attachment not found: {name_or_id}")
    path = Path(meta["path"])
    if not path.exists():
        raise FileNotFoundError(f"Attachment file missing on disk: {path}")
    with path.open("rb") as f:
        return f.read() if max_bytes is None else f.read(max_bytes)

def purge_attachments(mode: str = "soft", uid: str | None = None) -> int:
    """
    Entfernt Attachments dieses Users.
      - "soft": Manifest leeren, Dateien behalten
      - "hard": Manifest leeren + Dateien löschen
    Rückgabe: Anzahl betroffener Einträge (best effort)
    """
    u = _must_uid(uid)
    _ensure_user_dirs(u)
    files_dir = user_attachments_files_dir(u)
    manifest_path = user_attachments_manifest(u)
    mf = _load_manifest(manifest_path)
    count = len(mf.get("items", []))

    if mode not in ("soft", "hard"):
        raise ValueError("mode must be 'soft' or 'hard'")

    if mode == "hard":
        # Dateien entfernen
        for root, dirs, files in os.walk(files_dir, topdown=False):
            for fn in files:
                try:
                    os.unlink(os.path.join(root, fn))
                except Exception:
                    pass
            for d in dirs:
                try:
                    os.rmdir(os.path.join(root, d))
                except Exception:
                    pass

    # Manifest leeren
    mf["items"] = []
    _save_manifest(manifest_path, mf)
    return count

def to_data_url(name_or_id: str, uid: str | None = None) -> str:
    """
    data:-URL für kleine Dateien (für Inline-Bilder). Größe begrenzt.
    """
    meta = find_attachment(name_or_id, uid=uid)
    if not meta:
        raise FileNotFoundError(f"Attachment not found: {name_or_id}")

    path = Path(meta["path"])
    mime = meta.get("mime") or _magic_mime(path) or "application/octet-stream"
    raw = read_bytes(name_or_id, max_bytes=_MAX_DATAURL_BYTES + 1, uid=uid)

    if len(raw) > _MAX_DATAURL_BYTES:
        raise ValueError(f"Attachment too large for data URL (> {_MAX_DATAURL_BYTES} bytes)")
    b64 = base64.b64encode(raw).decode("ascii")
    return f"data:{mime};base64,{b64}"

def pick_last_images(n: int = 4, uid: str | None = None) -> list[dict[str, Any]]:
    imgs = [m for m in list_attachments(uid=uid) if str(m.get("mime", "")).startswith("image/")]
    return imgs[:n]  # list_attachments liefert schon neueste zuerst

# -------------------------------------------------------------------
# OpenAI Responses parts (images)
# -------------------------------------------------------------------
def to_openai_image_parts(items: Iterable[str], uid: str | None = None) -> list[dict[str, Any]]:
    """
    IDs/Namen zu Responses-`input_image`-Parts konvertieren (inline data-URLs).
    Gut für Bilder < ~8 MiB.
    """
    parts: list[dict[str, Any]] = []
    for it in items:
        url = to_data_url(it, uid=uid)
        parts.append({"type": "input_image", "image_url": url})
    return parts
