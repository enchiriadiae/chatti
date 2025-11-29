# -----------------------------------------------------------------------------
# core/api.py
#
# High-level interface to the OpenAI API used by the Chatti client.
#
# Responsibilities:
# - Handle API key resolution: environment variables, secrets file, or
#   interactive onboarding (with encryption).
# - Manage the default model preference (read/write to public config).
# - Provide helper functions for listing models and detecting chat-capable ones.
# - Build message context from conversation history for API requests.
# - Wrap the OpenAI client in a robust way:
#     * Smoke-test API keys when onboarding
#     * Support both streaming and non-streaming chat responses
#     * Gracefully handle connection errors and retry/fallback
#
# In short: this module centralizes all logic around talking to the OpenAI API,
# keeping key handling, model selection, and response flow safe and consistent.
# -----------------------------------------------------------------------------

from __future__ import annotations

import os
import shutil
import time
from getpass import getpass
from importlib.metadata import version as pkg_version
from pathlib import Path
from collections.abc import Callable

from config_loader import (
    as_bool,
    ensure_user_conf_skeleton,
    load_config_effective,
    normalize_color,
    write_conf_kv_scoped,
)
from openai import APIConnectionError, APIError, AuthenticationError, OpenAI

from core.attachments import (
    find_attachment,
    to_data_url,
)
from core.paths import (
    HOME,
    CONF_DIR,
    DATA_DIR,
    PUBLIC_CONF,
    SECRETS_FILE,
    USERS_CONF_DIR,
    USERS_DATA_DIR,
    ensure_global_prompts_seed,
    ensure_user_prompts_initialized,
    prune_orphan_user_dirs,
    user_prompts_dir,
)
from core.pdf_utils import (
    PDFDepsMissing,
    pdf_extract_text,
    pdf_pages_to_dataurls,
)
from core.security import (
    ADMIN_PIN_FILE,
    add_user,
    count_users_in_secrets,
    decrypt_api_key,
    ensure_admin_pin_initialized_interactive,
    get_active_uid,
    get_api_key_by_uid,
    has_admin_pin,
    list_users_decrypted,
    load_secrets,
    remove_user_entry_by_uid,
    set_active_user_by_uid,
    set_active_user_by_username,
    validate_master_password,
    verify_admin_pin_interactive,
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

BRIGHT_RED = normalize_color("bright_red")
GREEN = normalize_color("green")
CYAN = normalize_color("cyan")
BOLD = normalize_color("bold")
RESET = normalize_color("reset")

_UI_NOTIFY: Callable[[str, str, str | None], None] | None = None


def register_ui_notifier(fn: Callable[[str, str, str | None], None]) -> None:
    """TUI can register a callback: (title, body, color?) -> None"""
    global _UI_NOTIFY
    _UI_NOTIFY = fn


def _notify(title: str, body: str, color: str | None = None) -> None:
    try:
        if _UI_NOTIFY:
            _UI_NOTIFY(title, body, color)
    except Exception:
        pass


# -------------------------------------------------------------------------
# API-Health-Check: are OpenAI's API and those of this file still compatible?
# -------------------------------------------------------------------------

# prozessweite, simple Reentrancy-Sperre:
_SELFCHK_IN_PROGRESS = False


def _now_ts() -> int:
    return int(time.time())


def smoke_test(client: OpenAI, model: str = "gpt-4o", timeout: float | None = None) -> None:
    """Kurzer Key/Modell-Sanity-Check. Hebt RuntimeError mit klarer User-Message aus."""
    # 1) Modelle listen → Auth/Quota/Reachability
    try:
        _ = client.models.list()
    except AuthenticationError as e:
        raise RuntimeError("API-Key ungültig oder nicht autorisiert (401/403).") from e
    except APIConnectionError as e:
        raise RuntimeError(f"Netzwerk-/Verbindungsproblem: {e}") from e
    except APIError as e:
        raise RuntimeError(f"Modellliste fehlgeschlagen: {e}") from e

    # 2) Minimaler Responses-Call → Modellzugriff
    try:
        client.responses.create(
            model=model,
            input="ping",
            stream=False,
            max_output_tokens=16,  # wichtig: Mindestwert für „strenge“ Modelle
            timeout=timeout,
        )
    except AuthenticationError as e:
        raise RuntimeError("API-Key ok, aber Modell-Call abgelehnt (401/403).") from e
    except APIError as e:
        raise RuntimeError(f"Testcall auf {model} fehlgeschlagen: {e}") from e


def _conf_get_int(cfg: dict, key: str, default: int) -> int:
    try:
        return int(cfg.get(key, default))
    except Exception:
        return default


def _should_run_selfcheck(cfg: dict, model: str) -> bool:
    if not as_bool(cfg, "api_selfcheck", True):
        return False
    interval_h = _conf_get_int(cfg, "api_selfcheck_interval_hours", 24)
    last_ts = int(cfg.get("api_selfcheck_last_ts", 0) or 0)
    last_model = cfg.get("api_selfcheck_last_model") or ""
    last_ver = cfg.get("api_selfcheck_last_openai") or ""
    try:
        cur_ver = pkg_version("openai")
    except Exception:
        cur_ver = ""

    if model != last_model:
        return True
    if cur_ver and cur_ver != last_ver:
        return True
    if interval_h <= 0:
        return True
    return (_now_ts() - last_ts) >= interval_h * 3600


def _mark_selfcheck_ok(model: str) -> None:
    try:
        cur_ver = pkg_version("openai")
    except Exception:
        cur_ver = ""
    uid = get_active_uid() or None
    write_conf_kv_scoped("api_selfcheck_last_ts", str(_now_ts()), uid=uid)
    write_conf_kv_scoped("api_selfcheck_last_model", model, uid=uid)
    if cur_ver:
        write_conf_kv_scoped("api_selfcheck_last_openai", cur_ver, uid=uid)


def run_api_selfcheck_if_needed(client, model: str) -> None:
    """
    Wrapper: führt api_selfcheck() nur bei Bedarf aus und pflegt die Marker.
    Gibt selbst *nichts* aus; Logging macht api_selfcheck() abhängig von quiet_on_success.
    """
    global _SELFCHK_IN_PROGRESS
    if _SELFCHK_IN_PROGRESS:
        return  # reentrancy-guard

    cfg = load_config_effective(uid=get_active_uid())
    if not _should_run_selfcheck(cfg, model):
        return

    _SELFCHK_IN_PROGRESS = True
    try:
        # Lese Flags zentral aus der Conf (Fallbacks wie gehabt)
        verbose = as_bool(cfg, "api_selfcheck_verbose", True)
        check_stream = as_bool(cfg, "api_selfcheck_stream", True)

        # Nichts doppelt ansagen: *kein* zusätzliches print hier.
        rep = api_selfcheck(client, model, check_stream=check_stream, quiet_on_success=not verbose)
        if rep.get("ok"):
            _mark_selfcheck_ok(model)
    finally:
        _SELFCHK_IN_PROGRESS = False


def api_selfcheck(
    client: OpenAI,
    model: str,
    check_stream: bool = True,
    quiet_on_success: bool = False,
) -> dict:
    """Führt einen kurzen Gesundheitscheck aus.
    Rückgabe:
      {
        "ok": bool,
        "nonstream_ok": bool,
        "streaming": "ok" | "unavailable" | "failed" | "skipped",
        "messages": [str, ...]
      }
    """
    if not quiet_on_success:
        _notify(
            "API-Selfcheck",
            f"Prüfe Verbindung zum Modell „{model}“… das kann einen Moment dauern.",
            color=normalize_color("yellow"),
        )
    report = {"ok": True, "nonstream_ok": False, "streaming": "skipped", "messages": []}

    # --- Non-streaming Check ---
    try:
        probe = [{"role": "user", "content": "ping"}]
        resp = client.responses.create(
            model=model,
            input=probe,
            stream=False,
            max_output_tokens=16,  # robust gegen Modelle mit Mindestanforderung
        )

        text = getattr(resp, "output_text", "") or ""
        if not text and getattr(resp, "output", None):
            for item in resp.output:
                for part in getattr(item, "content", []) or []:
                    if getattr(part, "type", "") == "output_text":
                        text += getattr(part, "text", "")

        if text.strip():
            report["nonstream_ok"] = True
            if not quiet_on_success:
                _notify(
                    "Verbindungstest",
                    "Antwort erhalten – alles gut.",
                    color=normalize_color("green"),
                )
        else:
            report["ok"] = False
            msg = (
                "Unerwartete Antwortstruktur – möglicherweise wurde die Schnittstelle geändert. "
                "Bitte aktualisiere den Client."
            )
            report["messages"].append(msg)
            _notify("Verbindungstest", msg, color=normalize_color("red"))

    except Exception as e:
        report["ok"] = False
        msg = f"Anfrage fehlgeschlagen: {type(e).__name__}: {e}"
        report["messages"].append(msg)
        _notify("Verbindungstest", msg, color=normalize_color("red"))

    # --- Optional: Streaming Check (tolerant) ---
    if check_stream and report["nonstream_ok"]:
        try:
            stream = client.responses.create(
                model=model,
                input=[{"role": "user", "content": "stream ping"}],
                stream=True,
            )
            saw_text = False
            for ev in stream:
                # wir akzeptieren JEGLICHE textliche Teilantwort als „ok“
                if getattr(ev, "delta", "") or getattr(ev, "text", ""):
                    saw_text = True
                    break
            if saw_text:
                report["streaming"] = "ok"
                if not quiet_on_success:
                    _notify(
                        "Streamingtest",
                        "Live-Antworten verfügbar.",
                        color=normalize_color("green"),
                    )
            else:
                report["streaming"] = "failed"
                _notify(
                    "Streamingtest",
                    "Live-Antworten konnten nicht bestätigt werden. "
                    "Eventuell ist diese Funktion im Konto noch nicht freigeschaltet.",
                    color=normalize_color("yellow"),
                )
        except Exception as e:
            emsg = str(e).lower()
            if (
                ("must be verified" in emsg)
                or ("param: 'stream'" in emsg)
                or ("unsupported_value" in emsg)
            ):
                report["streaming"] = "unavailable"
                _notify(
                    "Streamingtest",
                    "Live-Antworten sind derzeit nicht verfügbar. Normale Antworten funktionieren.",
                    color=normalize_color("yellow"),
                )
            else:
                report["streaming"] = "failed"
                _notify(
                    "Streamingtest",
                    f"Live-Antworten konnten nicht getestet werden ({type(e).__name__}). "
                    "Normale Antworten funktionieren.",
                    color=normalize_color("yellow"),
                )
    # ok-Flag finalisieren
    if not report["nonstream_ok"]:
        report["ok"] = False
    return report


def _write_conf_kv(key: str, value: str) -> None:
    """
    Insert or replace a single 'key = value' line in PUBLIC_CONF.

    Notes:
    - Intentionally avoids regex replacement to prevent backreference issues.
    - Preserves existing comments and unrelated lines.
    - Creates PUBLIC_CONF if missing and ensures its parent directory exists.
    """
    PUBLIC_CONF.parent.mkdir(parents=True, exist_ok=True)
    if not PUBLIC_CONF.exists():
        PUBLIC_CONF.write_text("# chatti.conf\n", encoding="utf-8")

    lines = PUBLIC_CONF.read_text(encoding="utf-8").splitlines(keepends=False)
    key_norm = key.strip()
    new_line = f"{key_norm} = {value}"

    found = False
    for i, line in enumerate(lines):
        raw = line.strip()
        if not raw or raw.startswith("#") or raw.startswith(";"):
            continue
        # Only consider the part before an inline comment when parsing k=v
        before = raw.split("#", 1)[0].split(";", 1)[0].strip()
        if "=" in before:
            k, _ = before.split("=", 1)
            if k.strip() == key_norm:
                lines[i] = new_line
                found = True
                break

    if not found:
        if lines and lines[-1] != "":
            lines.append("")  # visual separation before appending
        lines.append(new_line)

    PUBLIC_CONF.write_text("\n".join(lines) + "\n", encoding="utf-8")


# =====================================================
# API-Key Handling
# =====================================================


def _get_api_key_from_env() -> str | None:
    """
    Return API key from environment if present.
    Supports both OPENAI_API_KEY and OPENAI_KEY for convenience.
    """
    return os.getenv("OPENAI_API_KEY") or os.getenv("OPENAI_KEY")


def _has_multiuser(sec: dict) -> bool:
    """Erkennt Multi-User-Layout in den Secrets."""
    try:
        return any(k.startswith("user.") for k in (sec or {}).keys())
    except Exception:
        return False


def _preferred_model_from_conf_env() -> str:
    """
    Determine the preferred default model with this priority:
      1) default_model from PUBLIC_CONF (project-local config)
      2) OPENAI_MODEL from environment
      3) literal fallback 'gpt-4o'
    """
    uid = get_active_uid()
    cfg = load_config_effective(uid=uid)
    val = cfg.get("default_model") or os.getenv("OPENAI_MODEL") or "gpt-4o"
    return val.strip()


def _prompt_api_key() -> tuple[str, str]:
    """
    Interactively ask the user for:
      - OpenAI API key
      - Master password (twice, to confirm)
    Returns (api_key, master).
    Raises RuntimeError on empty key or mismatched passwords.
    """
    api_key = getpass("OpenAI API-Key: ").strip()
    if not api_key:
        raise RuntimeError("Abbruch: kein API-Key eingegeben.")
    while True:
        pw1 = getpass("Master-Passwort (min. 12 chars, Passphrase empfohlen): ")
        ok, reason = validate_master_password(pw1)
        if not ok:
            print(f"✖  {reason}")
            continue
        pw2 = getpass("Master-Passwort (Wiederholung): ")
        if pw1 != pw2:
            print("✖  Passwörter ungleich – bitte erneut eingeben.")
            continue
        return api_key, pw1


# =====================================================
# User-Handling and CLI with Admin-Gate
# =====================================================


def _prompt_master_retry(
    prompt1: str = "Master-Passwort (min. 12 Zeichen, Passphrase empfohlen): ",
    prompt2: str = "Master-Passwort (Wiederholung): ",
) -> str:
    """
    Fragt ein Master-Passwort ab, prüft Policy via validate_master_password()
    und verlangt eine bestätigte Wiederholung. Wiederholt bei Fehlern.
    """
    while True:
        pw1 = getpass(prompt1)
        ok, reason = validate_master_password(pw1)
        if not ok:
            print(f"✖  {reason}")
            continue
        pw2 = getpass(prompt2)
        if pw1 != pw2:
            print("✖  Passwörter ungleich – bitte erneut.")
            continue
        return pw1


def _interactive_user_onboarding(preferred_model: str) -> tuple[str, str, str]:
    """
    Fragt Username, API-Key, Master ab, smoketestet und legt User an. Returns (uid, api_key, master).
    """
    print("Erstkonfiguration – Benutzer, API-Key und Master-Passwort einrichten.")
    username = input("Benutzername: ").strip()
    if not username:
        raise RuntimeError("Abbruch: Kein Benutzername eingegeben.")
    api_key = getpass("OpenAI API-Key: ").strip()
    if not api_key:
        raise RuntimeError("Abbruch: kein API-Key eingegeben.")
    master = _prompt_master_retry(
        "Master-Passwort (min. 12 Zeichen, Passphrase empfohlen): ",
        "Master-Passwort (Wiederholung): ",
    )

    # Smoke-Test mit temporärem Client
    tmp = OpenAI(api_key=api_key)
    print("→ Prüfe API-Key und Modellzugriff …")
    smoke_test(tmp, preferred_model)
    print("✓ Key gültig. Minimaler Testcall erfolgreich.")

    # persistiert als Multi-User-Record (UID, verschl. Name & Key)
    uid = add_user(username, master, api_key)
    set_active_user_by_uid(uid)

    # Prompts bereitstellen
    ensure_global_prompts_seed()  # global (~/.config/chatti-cli/docs/prompts)
    ensure_user_prompts_initialized(uid)  # ein paar Beispiele für den User

    cfg_path = ensure_user_conf_skeleton(uid)
    print(f"• User-Konfig angelegt: {cfg_path}")
    print(f"✓ Benutzer angelegt (uid={uid}).")
    return uid, api_key, master


def _interactive_user_login(sec: dict, _preferred_model: str) -> tuple[str, str]:
    """
    Fragt Master ab, versucht erst den aktiven User; wenn keiner/fehlgeschlagen:
    zeigt entschlüsselte Liste zur Auswahl. Liefert (api_key, master).
    """
    master = getpass("Master-Passwort (entschlüsselt Benutzer & API-Key. Abbrechen: ctrl+c): ")
    # Aktiver User zuerst
    active = sec.get("user.active")
    if active:
        try:
            api_key = get_api_key_by_uid(active, master)
            set_active_user_by_uid(active)  # sicherheitshalber erneut setzen
            print("✅  Login (aktiver Benutzer) ok.")
            return api_key, master
        except Exception:
            print("⚠️  Aktiver Benutzer konnte nicht entschlüsselt werden.")

    # Auswahl anzeigen
    users = list_users_decrypted(master)
    if not users:
        raise RuntimeError("Kein entschlüsselbarer Benutzer gefunden (Passwort korrekt?).")

    print("\nVerfügbare Benutzer:")
    for i, (uid, name) in enumerate(users, 1):
        print(f"  {i:2d}) {name}   [{uid}]")
    sel = input("Benutzer wählen (Zahl), oder 'n' für neuen Benutzer: ").strip().lower()

    if sel == "n":
        # neuer Benutzer im laufenden Flow
        username = input("Neuer Anzeigename: ").strip()
        if not username:
            raise RuntimeError("Abbruch: Kein Benutzername eingegeben.")
        api_key = getpass("OpenAI API-Key: ").strip()
        if not api_key:
            raise RuntimeError("Abbruch: kein API-Key eingegeben.")
        uid = add_user(username, master, api_key)
        set_active_user_by_uid(uid)
        print(f"✓ Benutzer angelegt & aktiviert (uid={uid}).")
        return api_key, master

    if sel.isdigit():
        idx = int(sel)
        if 1 <= idx <= len(users):
            uid = users[idx - 1][0]
            api_key = get_api_key_by_uid(uid, master)
            set_active_user_by_uid(uid)
            print("✅  Login ok.")
            return api_key, master

    raise RuntimeError("Ungültige Auswahl.")


def _init_user_prompts(uid: str) -> None:
    """
    Kopiert Beispiel-Prompts aus dem Repo in den per-User-Prompts-Ordner,
    ohne bestehende Dateien zu überschreiben.
    """
    try:
        # Repo-Pfad: <repo>/docs/prompts
        repo_prompts = Path(__file__).resolve().parents[1] / "docs" / "prompts"
        dest = user_prompts_dir(uid)  # sorgt bereits für mkdir(parents=True, exist_ok=True)

        if repo_prompts.exists():
            # nur *.prompt.txt (oder was immer du willst) kopieren, ohne bestehende zu überschreiben
            for p in repo_prompts.iterdir():
                if p.is_file() and p.suffix in {".txt"} and not p.name.startswith("."):
                    target = dest / p.name
                    if not target.exists():
                        target.write_text(p.read_text(encoding="utf-8"), encoding="utf-8")

        # Optional: kleines README stub (nur wenn noch nicht vorhanden)
        readme = dest / "README.txt"
        if not readme.exists():
            readme.write_text(
                "Lege hier eigene Prompt-Dateien ab. Beispiele wurden aus docs/prompts kopiert.\n",
                encoding="utf-8",
            )

    except Exception as e:
        # genau die Meldung, die du gesehen hast – jetzt aber nur, wenn wirklich was anderes schiefgeht
        print(f"⚠️  Konnte Prompts nicht initialisieren: {type(e).__name__}: {e}")


def cli_user_add(preferred_model: str | None = None) -> None:
    """
    Interaktiver Wizard; legt einen neuen Benutzer an, setzt ihn aktiv
    und erzeugt eine kommentierte User-Konfig (Skeleton), mit der
    zentrale Defaults überschrieben werden können.
    """
    # Admin-PIN needed
    # _require_admin_gate()

    preferred_model = preferred_model or _preferred_model_from_conf_env()

    # Onboarding (fragt Anzeigename, API-Key, Master; smoketestet)
    uid, api_key, master = _interactive_user_onboarding(preferred_model)

    # User sofort aktiv schalten (Safety: sollte _interactive_user_onboarding bereits tun,
    # aber doppelt ist hier idempotent und harmless)
    set_active_user_by_uid(uid)

    # User-Skeleton anlegen (nur falls noch nicht vorhanden)
    cfg_path = ensure_user_conf_skeleton(uid)
    print(f"• User-Konfig angelegt: {cfg_path}")

    # Für diese Session verfügbar machen
    os.environ["CHATTI_MASTER"] = master
    os.environ["OPENAI_API_KEY"] = api_key

    # Prompts initialisieren
    try:
        _init_user_prompts(uid)
        print("✓ Beispiel-Prompts wurden angelegt.")
    except Exception as e:
        print(f"⚠️  Konnte Prompts nicht initialisieren: {e}")

    print(f"✓ Benutzer angelegt & aktiviert (uid={uid}).")


def cli_user_use(name_or_uid: str) -> None:
    """
    Setzt aktiven Benutzer per Name oder UID (fragt Master).
    """
    sec = load_secrets()
    if not sec:
        raise RuntimeError("Keine Secrets vorhanden. Lege zuerst einen Benutzer an (--user-add).")

    master = getpass("Master-Passwort: ")
    # Versuch per UID
    if name_or_uid == (sec.get("user.active") or ""):
        # schon aktiv
        print("• Benutzer ist bereits aktiv.")
        return
    try:
        # Falls es eine UID ist: prüfen, ob Datensatz existiert
        if sec.get(f"user.{name_or_uid}.kdf_salt"):
            # Testweise API-Key entschlüsseln (Validierung)
            _ = get_api_key_by_uid(name_or_uid, master)
            set_active_user_by_uid(name_or_uid)
            print(f"✓ Aktiver Benutzer gesetzt: {name_or_uid}")
            return
    except Exception:
        pass
    # sonst per Name
    uid = set_active_user_by_username(name_or_uid, master)
    print(f"✓ Aktiver Benutzer gesetzt: {uid}")


def cli_user_list() -> None:
    """
    Zeigt entschlüsselte Benutzerliste (fragt Master).
    """
    sec = load_secrets()
    if not any(k.startswith("user.") for k in sec.keys()):
        print("Keine Benutzer in den Secrets gefunden.")
        return
    master = getpass("Master-Passwort (zum Entschlüsseln der Namen): ")
    users = list_users_decrypted(master)
    if not users:
        print("Keine entschlüsselbaren Benutzer (Passwort korrekt?).")
        return
    active = sec.get("user.active") or ""
    print("\nBenutzer:")
    for uid, name in users:
        mark = " *" if uid == active else ""
        print(f"  {name}  [{uid}]{mark}")


def _norm(s: str) -> str:
    return (s or "").strip().casefold()


def _looks_like_existing_uid(s: str) -> bool:
    """Prüft, ob s eine gespeicherte UID ist (nur Secrets lesen, keine Master-Eingabe nötig)."""
    if not s or " " in s:
        return False
    sec = load_secrets()
    return bool(sec.get(f"user.{s}.kdf_salt"))


def _resolve_uid(name_or_uid: str, master_password: str | None = None) -> str:
    """
    Name→UID oder UID→UID.
    - Wenn es bereits eine gültige UID ist: return ohne Master.
    - Sonst (Name): Master ist nötig, um Namen zu entschlüsseln.
    - Bei Mehrdeutigkeit: interaktive Auswahl.
    """
    needle = (name_or_uid or "").strip()
    if not needle:
        raise RuntimeError(f"Benutzer nicht gefunden: {name_or_uid!r}")

    # Direkt-UID?
    if _looks_like_existing_uid(needle):
        return needle

    # Sonst Name → Master nötig
    if not master_password:
        master_password = getpass("Master-Passwort (zur Namensauflösung): ")

    users = list_users_decrypted(master_password)  # [(uid, name)]
    matches = [(uid, nm) for (uid, nm) in users if (nm or "").strip() == needle]
    if not matches:
        raise RuntimeError(f"Benutzer nicht gefunden: {name_or_uid!r}")

    if len(matches) == 1:
        return matches[0][0]

    # Mehrdeutig → Auswahl
    print("Name mehrfach vorhanden. Bitte wählen:")
    for i, (uid, nm) in enumerate(matches, 1):
        print(f"  {i:2d}) {nm}  [{uid}]")
    sel = input("Nummer wählen (oder Enter zum Abbrechen): ").strip()
    if not sel.isdigit():
        raise RuntimeError("Abgebrochen.")
    idx = int(sel)
    if 1 <= idx <= len(matches):
        return matches[idx - 1][0]
    raise RuntimeError("Ungültige Auswahl.")


def _delete_all_user_portals(name: str = "chatti") -> None:
    try:
        sec = load_secrets()
        uids = {k.split(".")[1] for k in sec.keys() if k.startswith("user.") and k.count(".") >= 2}
        for uid in uids:
            _delete_user_portal(uid, name=name)
    except Exception:
        pass


def _delete_user_portal(uid: str, name: str = "chatti") -> None:
    portal = HOME / f"{name}_{uid[:8]}"
    try:
        if portal.is_symlink() or portal.exists():
            portal.unlink(missing_ok=True)
    except Exception:
        pass


def _delete_user_files(uid: str) -> None:
    """Löscht per-User-Daten & per-User-Konfiguration (keine Secrets)."""
    try:
        shutil.rmtree(USERS_DATA_DIR / uid, ignore_errors=True)
    except Exception:
        pass
    try:
        shutil.rmtree(USERS_CONF_DIR / uid, ignore_errors=True)
    except Exception:
        pass
    _delete_user_portal(uid)


def cli_user_remove(name_or_uid: str, hard: bool = False) -> None:
    """
    Entfernt einen Benutzer.
      - soft (default): löscht nur Secrets/Registry-Eintrag
      - hard: zusätzlich alle per-User-Dateien/Ordner
    Admin-PIN wird NICHT hier geprüft (macht chatti_go.py).
    Master wird NUR abgefragt, wenn eine Namensauflösung nötig ist.
    """
    # Nur falls Name → dann Master; bei UID keine Abfrage:
    master: str | None = None
    uid = _resolve_uid(name_or_uid, master_password=master)

    # Falls aktiv → bestätigen
    if get_active_uid() == uid:
        ans = (
            input("Achtung: Dieser Benutzer ist aktuell aktiv. Trotzdem entfernen? [y/N] ")
            .strip()
            .lower()
        )
        if ans not in ("y", "yes", "j", "ja"):
            print("Abgebrochen.")
            return

    # Bei --hard extra bestätigen
    if hard:
        ans = input(
            "WIRKLICH ALLE BENUTZER-DATEN LÖSCHEN (History, Attachments, Inputs, Cmds)? [LÖSCHEN/NEIN] "
        ).strip()
        if ans.lower() not in ("löschen", "loeschen", "delete", "yes", "ja"):
            print("Abgebrochen.")
            return

    # Secrets/Registry-Eintrag löschen
    remove_user_entry_by_uid(uid)
    if hard:
        _delete_user_files(uid)
        prune_orphan_user_dirs()
        print(f"✓ Benutzer entfernt (hart): {uid} – Daten & per-User-Konfiguration gelöscht.")
    else:
        print(f"✓ Benutzer entfernt (soft): {uid} – Secrets-Eintrag gelöscht, Dateien behalten.")


def cli_user_remove_by_name(name: str, *, hard: bool = False, all_matches: bool = False) -> None:
    """
    Entfernt Benutzer nach ANZEIGENAME.
    - all_matches=False → bei Mehrdeutigkeiten Auswahl anzeigen
    - all_matches=True  → alle Treffer entfernen (eine Bestätigung, keine Einzelabfragen)
    """
    if not name.strip():
        raise ValueError("Name darf nicht leer sein.")

    # Für Namensauflösung Master EINMAL abfragen (wie bisher)
    master = getpass("Master-Passwort (zur Namensauflösung): ")
    pairs = list_users_decrypted(master)  # [(uid, username)]
    matches = [(uid, nm) for (uid, nm) in pairs if nm == name]

    if not matches:
        raise RuntimeError(f"Benutzer nicht gefunden: '{name}'")

    # Mehrdeutig?
    if len(matches) > 1 and not all_matches:
        print("Name mehrfach vorhanden. Bitte wählen:")
        for i, (uid, nm) in enumerate(matches, 1):
            print(f"  {i}) {nm}  [{uid}]")
        try:
            sel = input("Nummer wählen (oder Enter zum Abbrechen): ").strip()
        except KeyboardInterrupt:
            print("\nAbgebrochen.")
            return
        if not sel:
            print("Abgebrochen.")
            return
        try:
            idx = int(sel)
            if idx < 1 or idx > len(matches):
                print("Ungültige Auswahl.")
                return
        except Exception:
            print("Ungültige Eingabe.")
            return
        matches = [matches[idx - 1]]  # genau einer

    # Bei all_matches → EINMAL deutlich bestätigen
    if len(matches) > 1 and all_matches:
        print(f"Achtung: {len(matches)} Benutzer mit dem Namen „{name}“ werden entfernt.")
        if hard:
            ans = (
                input("WIRKLICH ALLE BENUTZER-DATEN (inkl. Files) löschen? [LÖSCHEN/NEIN] ")
                .strip()
                .lower()
            )
            if ans not in ("löschen", "loeschen", "delete", "yes", "ja"):
                print("Abgebrochen.")
                return
        else:
            ans = input("Wirklich alle passenden Benutzer entfernen (soft)? [y/N] ").strip().lower()
            if ans not in ("y", "yes", "j", "ja"):
                print("Abgebrochen.")
                return

    # Entfernen (wie cli_user_remove, aber ohne per-UID Bestätigungen)
    active = get_active_uid()
    removed = 0

    for uid, _nm in matches:
        # Falls aktiv → kurze Warnung (keine zweite Abfrage)
        if active == uid:
            print(f"⚠️  Entferne aktiven Benutzer [{uid}] …")

        remove_user_entry_by_uid(uid)
        if hard:
            _delete_user_files(uid)
        removed += 1

    try:
        prune_orphan_user_dirs()
    except Exception:
        pass

    mode = "hart" if hard else "soft"
    print(f"✓ {removed} Benutzer entfernt ({mode}).")


def get_client(
    non_interactive: bool = False,
    require_smoke: bool = False,  # default: faster startup; smoke-test only on onboarding
) -> OpenAI:
    """
    Construct and return an authenticated OpenAI client.

    Resolution order:
      1) Environment variable (OPENAI_API_KEY/OPENAI_KEY)
         - If `require_smoke` is True, do a quick smoke test.
      2) Secrets file (api_key_enc, kdf_salt)
         - Decrypt using CHATTI_MASTER, or prompt once if interactive.
         - On decryption typo: allow a single retry (interactive only).
         - If `require_smoke` is True, do a quick smoke test.
         - Cache master/key in-process to avoid repeated prompts in the same run.
      3) Interactive onboarding (no secrets yet)
         - Prompt for API key + master (double entry).
         - Always smoke-test once to confirm the key works.
         - Optionally let the user choose and persist a default model.
         - Encrypt and store the API key in the secrets file.
         - Cache master/key for the current run.

    Raises:
      RuntimeError in non-interactive environments when input would be required.
    """
    preferred_model = _preferred_model_from_conf_env()

    # ---------- 1) ENV key ----------
    env_key = _get_api_key_from_env()
    if env_key:
        client = OpenAI(api_key=env_key)
        if require_smoke:
            smoke_test(client, preferred_model)
        # # API-Check via Wrapper (führt den Selfcheck nur bei Bedarf aus)
        run_api_selfcheck_if_needed(client, preferred_model)
        return client

    # ---------- 2) Secrets (encrypted) ----------
    sec = load_secrets()

    # 2a) NEU: Multi-User vorhanden?
    if _has_multiuser(sec):
        if non_interactive:
            raise RuntimeError(
                "Mehrbenutzer-Secrets gefunden, aber kein Master-Passwort verfügbar (non-interactive).\n"
                "Bitte einmal interaktiv starten, um den Master einzugeben."
            )
        api_key, master = _interactive_user_login(sec, preferred_model)
        # Cache im Prozess
        os.environ["CHATTI_MASTER"] = master
        os.environ["OPENAI_API_KEY"] = api_key
        client = OpenAI(api_key=api_key)
        if require_smoke:
            smoke_test(client, preferred_model)
        run_api_selfcheck_if_needed(client, preferred_model)
        return client

    # 2b) Legacy Single-User vorhanden?
    token = (sec.get("api_key_enc") or "").strip()
    salt = (sec.get("kdf_salt") or "").strip()
    if token and salt:
        if non_interactive:
            raise RuntimeError(
                "Verschlüsselter API-Key gefunden (Single-User), aber kein Master verfügbar (non-interactive).\n"
                "Bitte einmal interaktiv starten oder --reset-auth nutzen."
            )
        master = getpass("Master-Passwort (entschlüsselt API-Key): ")
        try:
            real_key = decrypt_api_key(token, master, salt)
        except Exception:
            print(f"⚠️  {BRIGHT_RED}Entschlüsselung fehlgeschlagen! (Passwort/Salt prüfen).{RESET}")
            print(f"{BOLD}{CYAN} --> Hinweis:{RESET}")
            print(f"{CYAN}Mit --reset-auth kannst du die Anmeldung zurücksetzen.{RESET}")
            master = getpass("Master-Passwort (nochmal): ")
            real_key = decrypt_api_key(token, master, salt)

        # Optional: Migration in Multi-User
        try:
            mig = (
                input("Auf Mehrbenutzer umstellen (Benutzername vergeben)? [J/n]: ").strip().lower()
            )
        except Exception:
            mig = "n"
        if mig in ("", "j", "y", "ja", "yes"):
            name = input("Anzeigename für diesen Schlüssel: ").strip() or "default"
            uid = add_user(name, master, real_key)
            set_active_user_by_uid(uid)
            print(f"✓ Multi-User aktiviert (uid={uid}).")
        else:
            # Kein Multi-User → weiter wie gehabt (nur für diese Session)
            pass

        os.environ["CHATTI_MASTER"] = master
        os.environ["OPENAI_API_KEY"] = real_key
        client = OpenAI(api_key=real_key)
        if require_smoke:
            smoke_test(client, preferred_model)
        print(f"✅  {GREEN}Entschlüsselung erfolgreich!{RESET}")
        run_api_selfcheck_if_needed(client, preferred_model)
        return client

    # ---------- 3) Onboarding (no secrets at all) ----------
    if non_interactive:
        raise RuntimeError(
            "Kein API-Key eingerichtet (non-interactive).\nBitte das Script interaktiv ausführen."
        )

    # Multi-User-Ersteinrichtung (Username + Master + API-Key)
    uid, api_key, master = _interactive_user_onboarding(preferred_model)

    # Für diese Session verfügbar machen
    os.environ["CHATTI_MASTER"] = master
    os.environ["OPENAI_API_KEY"] = api_key

    # Temporären Client bauen
    temp_client = OpenAI(api_key=api_key)

    # Optional: komfortable Modellwahl (persistiert zentral)
    try:
        all_models = [m.id for m in temp_client.models.list().data]
        chat_models = [m for m in sorted(all_models) if is_chat_model(m)]
        if chat_models:
            print(f"\nVerfügbare Chat-Modelle ({len(chat_models)}):")
            for i, m in enumerate(chat_models[:25], 1):
                print(f"  {i:2d}) {m}")
            print(f"\n→ Aktuelles Default-Modell: {preferred_model}")
            print("  0 ) (so lassen)")
            sel = input("Standard-Modell wählen (Zahl = Modell, Enter = so lassen): ").strip()
            if sel.isdigit():
                idx = int(sel)
                if 1 <= idx <= len(chat_models[:25]):
                    chosen = chat_models[idx - 1]
                    _write_conf_kv("default_model", chosen)  # persist in PUBLIC_CONF
                    os.environ["OPENAI_MODEL"] = chosen
                    print(f"✓ default_model = {chosen} gespeichert.")
    except Exception:
        # Komfortfunktion; Fehler hier nicht fatal
        pass

    # API-Selfcheck nur bei Bedarf
    run_api_selfcheck_if_needed(temp_client, preferred_model)

    # Bereiten, liefern
    return temp_client


def get_default_model() -> str:
    """
    Return the effective default model for the current process.
    (Primarily reads OPENAI_MODEL; PUBLIC_CONF is handled elsewhere.)
    """
    return os.getenv("OPENAI_MODEL", "gpt-4o")


def set_default_model(name: str) -> None:
    """
    Set the default model for the current process (environment-scoped).
    """
    # Schutz: Keine „NoSelection“-Objekte / Leere
    if not isinstance(name, str) or not name.strip():
        raise ValueError("Kein Modell ausgewählt.")
    os.environ["OPENAI_MODEL"] = name.strip()


# --- Model discovery (single source of truth) ---
def list_models_raw(client) -> list[str]:
    """Ungefilterte IDs direkt aus der API (robust, kein Token-Verbrauch)."""
    try:
        resp = client.models.list()
        items = getattr(resp, "data", None) or []
        out = []
        for it in items:
            mid = getattr(it, "id", None) or (it.get("id") if isinstance(it, dict) else None)
            if isinstance(mid, str):
                out.append(mid)
        return out
    except Exception:
        return []

def get_reachable_chat_models(client, *, probe: bool = False, timeout: float = 2.0) -> list[str]:
    """
    Liefert Chat-geeignete Modelle, die *jetzt* erreichbar sind.
    - immer: client.models.retrieve(mid) (kein Tokenverbrauch)
    - optional probe=True: Mini-Chat-Request als End-to-End-Check (kostet 1-2 Token)
    """

    try:
        all_ids = list_models_raw(client)
        candidates = [m for m in all_ids if is_chat_model(m)]
        ok: list[str] = []

        for mid in sorted(set(candidates)):
            # Reachability ohne Token:
            try:
                client.models.retrieve(mid)  # 404/403 → not ok
            except Exception:
                continue

            if probe:
                try:
                    client.responses.create(
                        model=mid,
                        input="ping",
                        max_output_tokens=16,  # Mindestwert, der bei „strengen“ Modellen akzeptiert wird
                        timeout=timeout,
                        stream=False,
                    )
                except Exception:
                    continue

            ok.append(mid)

        return ok
    except Exception:
        return []


# New version of is_chat_model(): No further Hard-Pinning of LLM-Models.
def is_chat_model(name: str) -> bool:
    """
    Heuristik: erkenne allgemeine Text-Chat-Modelle, ohne konkrete Versionsnamen
    hart zu verdrahten.

    Idee:
    - „Offensichtliche Nicht-Chat-Modelle“ (Embeddings, Moderation, Audio, TTS …)
      explizit ausschließen.
    - Alles, was wie ein allgemeines GPT-/o*-Chatmodell aussieht, zulassen.
    """
    if not name:
        return False

    nid = name.lower().strip()

    # 1) offensichtliche Nicht-Chat-Familien hart ausschließen
    block_substrings = (
        "embedding",
        "embeddings",
        "moderation",
        "omni-moderation",
        "whisper",
        "audio",
        "tts",
        "image",
        "vision",
        "batch",
    )
    if any(bad in nid for bad in block_substrings):
        return False

    # 2) typische Chat-Familien
    #    - alles, was mit "gpt-" beginnt → GPT-3.5/4/5/…
    #    - neue o*-Familien (o1, o3, …), falls du die später nutzen willst
    if nid.startswith("gpt-") or nid.startswith("o1") or nid.startswith("o3"):
        return True

    # 3) Fallback: Modelle, die explizit "chat" im Namen tragen
    if "chat" in nid:
        return True

    return False

def build_context(history: list[dict], system: str | None = None) -> list[dict]:
    """
    Transform a simple history structure into the format expected
    by the OpenAI Responses API.

    Input:
      history = [
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi there!"},
        ...
      ]
      system = optional system prompt (string)

    Process:
      - Start with an empty message list.
      - If `system` is given, insert it as the very first message
        with role 'system'.
      - Then loop over all history turns:
        * Each turn must have a 'role' and 'content'.
        * Skip empty contents (saves bandwidth / avoids null input).
        * Roles are normalized:
            - explicit "user" → role "user"
            - everything else → role "assistant"
          (This way, if the dict was malformed, it won't silently pass as user input.)

    Output:
      msgs = [
        {"role": "system", "content": "..."} (optional),
        {"role": "user", "content": "..."},
        {"role": "assistant", "content": "..."},
        ...
      ]
      which is exactly what client.responses.create() expects.
    """
    msgs: list[dict] = []
    if system:
        msgs.append({"role": "system", "content": system})
    for turn in history:
        role = turn.get("role", "")
        content = turn.get("content", "")
        if not content:
            continue
        msgs.append({"role": "user" if role == "user" else "assistant", "content": content})
    return msgs


def chat_once(
    client: OpenAI,
    model: str,
    history: list[dict],
    system: str = "Du bist hilfsbereit und knapp.",
    stream_preferred: bool = True,
    on_delta: Callable[[str], None] | None = None,
    attach_ids: list[str] | None = None,
) -> tuple[str, bool, dict]:
    """
    Perform a single chat completion (one 'turn') using the OpenAI Responses API.
    Returns:
        (full_text: str, used_streaming: bool, usage: dict)
    """

    # --- config for PDF handling ---
    # cfg = load_config("chatti.conf")
    cfg = load_config_effective(uid=get_active_uid())

    try:
        cfg_pdf_max_pages = int(cfg.get("pdf_max_pages", 2))
    except Exception:
        cfg_pdf_max_pages = 2
    pdf_text_only = as_bool(cfg, "pdf_text_only", False)

    # normalize attachments
    attach_ids = attach_ids or []

    # Build base messages from history (+ system)
    msgs = build_context(history, system=system)

    # If attachments are present, convert the *last user* message into parts
    if attach_ids:
        # last_user_idx suchen
        last_user_idx = None
        for i in range(len(msgs) - 1, -1, -1):
            if msgs[i].get("role") == "user":
                last_user_idx = i
                break

        if last_user_idx is None:
            msgs.append({"role": "user", "content": ""})
            last_user_idx = len(msgs) - 1

        user_text = msgs[last_user_idx].get("content", "")
        parts = [{"type": "input_text", "text": user_text}]

        for att_id in attach_ids:
            meta = find_attachment(att_id)
            if not meta:
                continue

            mime = str(meta.get("mime") or "")
            try:
                if mime.startswith("image/"):
                    # Bild → data:-URL als string
                    url = to_data_url(att_id)
                    parts.append({"type": "input_image", "image_url": url})

                elif mime == "application/pdf":
                    # 1) Textauszug (funktioniert ohne Poppler)
                    try:
                        max_pages_for_text = (
                            None if cfg_pdf_max_pages == 0 else max(1, cfg_pdf_max_pages)
                        )
                        txt = pdf_extract_text(
                            meta["path"], max_pages=max_pages_for_text, max_chars=4000
                        )
                        if txt.strip():
                            parts.append(
                                {
                                    "type": "input_text",
                                    "text": f"(PDF-Textauszug)\n\n{txt}",
                                }
                            )
                        else:
                            parts.append(
                                {
                                    "type": "input_text",
                                    "text": "(PDF enthält keinen extrahierbaren Text.)",
                                }
                            )
                    except Exception as e2:
                        parts.append(
                            {
                                "type": "input_text",
                                "text": f"(PDF-Textauszug fehlgeschlagen: {type(e2).__name__}: {e2})",
                            }
                        )

                    # 2) Optional: Seiten als Bilder (nur wenn nicht text_only)
                    if not pdf_text_only:
                        try:
                            # 0 (=unbegrenzt) -> sichere Kappe für Bilder
                            pages_for_images = (
                                10 if cfg_pdf_max_pages == 0 else max(1, cfg_pdf_max_pages)
                            )
                            urls = pdf_pages_to_dataurls(
                                meta["path"], max_pages=pages_for_images, dpi=120
                            )
                            for page_idx, url in enumerate(urls, start=1):
                                parts.append(
                                    {
                                        "type": "input_text",
                                        "text": f"[PDF page {page_idx}]",
                                    }
                                )
                                parts.append({"type": "input_image", "image_url": url})
                        except PDFDepsMissing:
                            # Freundliche TUI-Info, nicht ans Modell
                            from core.pdf_utils import explain_missing_poppler

                            _notify(
                                "PDF",
                                explain_missing_poppler(),
                                color=normalize_color("yellow"),
                            )
                        except Exception as e:
                            _notify(
                                "PDF",
                                f"PDF-Rendering fehlgeschlagen: {type(e).__name__}: {e}",
                                color=normalize_color("yellow"),
                            )
                else:
                    # Sonstiger MIME-Typ
                    parts.append({"type": "input_text", "text": f"(Anhang ignoriert: {mime})"})

            except Exception:
                # worst-case: ignorieren
                pass

        msgs[last_user_idx]["content"] = parts

    # Try streaming first
    if stream_preferred:
        try:
            stream = client.responses.create(model=model, input=msgs, stream=True)
            chunks: list[str] = []

            # Platzhalter; wird am Ende aus dem Stream gefüllt, wenn verfügbar
            usage = {
                "input_tokens": 0,
                "output_tokens": 0,
                "total_tokens": 0,
                "model": model,
            }

            for ev in stream:
                ev_type = getattr(ev, "type", "") or ""
                # Text-Deltas einsammeln (verschiedene Eventnamen abdecken)
                if "output_text.delta" in ev_type:
                    d = getattr(ev, "delta", "") or ""
                elif "delta" in ev_type:
                    d = getattr(ev, "delta", "") or getattr(ev, "text", "") or ""
                else:
                    d = ""
                if d:
                    chunks.append(d)
                    if on_delta:
                        try:
                            on_delta(d)
                        except Exception:
                            pass

                # Usage aus finalen Events/Objekten ziehen (robust auf verschiedene SDK-Shapes)
                # 1) Manche SDKs hängen usage direkt ans Event
                u = getattr(ev, "usage", None)
                # 2) Manche liefern ein 'response' Objekt mit 'usage'
                if not u:
                    resp_obj = getattr(ev, "response", None)
                    if resp_obj is not None:
                        u = getattr(resp_obj, "usage", None)

                if u:
                    try:
                        # u kann Obj oder dict sein
                        usage = {
                            "input_tokens": int(
                                getattr(u, "input_tokens", 0)
                                or (u.get("input_tokens", 0) if isinstance(u, dict) else 0)
                            ),
                            "output_tokens": int(
                                getattr(u, "output_tokens", 0)
                                or (u.get("output_tokens", 0) if isinstance(u, dict) else 0)
                            ),
                            "total_tokens": int(
                                getattr(u, "total_tokens", 0)
                                or (u.get("total_tokens", 0) if isinstance(u, dict) else 0)
                            ),
                            "model": model,
                        }
                    except Exception:
                        # notfalls alte Werte behalten
                        pass

            return "".join(chunks), True, usage

        except (APIConnectionError, APIError) as e:
            msg = str(e).lower()
            code = getattr(e, "status_code", None)
            if (
                "must be verified to stream" in msg
                or "unsupported_value" in msg
                or "param: 'stream'" in msg
                or code in (429, 500, 502, 503, 504)
            ):
                pass  # Fallback auf Non-Streaming unten
            else:
                raise

    # Non-streaming fallback
    resp = client.responses.create(model=model, input=msgs, stream=False)

    text = getattr(resp, "output_text", "") or ""
    if not text and getattr(resp, "output", None):
        for item in resp.output:
            for part in getattr(item, "content", []) or []:
                if getattr(part, "type", "") == "output_text":
                    text += getattr(part, "text", "")

    # ➜ Usage sicher einsammeln (vor dem return!)
    try:
        u = getattr(resp, "usage", None) or {}
        usage = {
            "input_tokens": int(
                getattr(u, "input_tokens", 0)
                or (u.get("input_tokens", 0) if isinstance(u, dict) else 0)
            ),
            "output_tokens": int(
                getattr(u, "output_tokens", 0)
                or (u.get("output_tokens", 0) if isinstance(u, dict) else 0)
            ),
            "total_tokens": int(
                getattr(u, "total_tokens", 0)
                or (u.get("total_tokens", 0) if isinstance(u, dict) else 0)
            ),
            "model": model,
        }
    except Exception:
        usage = {
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "model": model,
        }

    return text, False, usage


###############################################################
#
# Factory-Reset
#
###############################################################


def _print_warn(msg: str) -> None:
    print(msg)


def _reset_enabled() -> bool:
    v = (os.getenv("CHATTI_ALLOW_FACTORY_RESET") or "").strip().lower()
    return v in {"1", "true", "yes", "on"}


def _confirm_typed(prompt: str, expect: str) -> bool:
    """
    Fragt den Benutzer im Terminal nach einer Bestätigung.
    Der Text muss exakt so eingegeben werden wie `expected`.
    Gibt True zurück, wenn es passt, sonst False.
    """
    try:
        val = input(f"{prompt} (tippe exakt: {expect}): ").strip()
        return val == expect
    except (KeyboardInterrupt, EOFError):
        print()
        return False


def _dryrun_tree(path: Path) -> None:
    """Listet alle Dateien und Ordner unterhalb von path (rekursiv)."""
    if not path.exists():
        print(f"(fehlt) {path}")
        return
    if path.is_file():
        print(f"FILE: {path}")
        return
    # sonst ein Ordner
    print(f"DIR : {path}")
    for root, dirs, files in os.walk(path):
        for d in dirs:
            print(f"DIR : {Path(root) / d}")
        for f in files:
            print(f"FILE: {Path(root) / f}")


def _safe_rm(p: Path) -> None:
    try:
        if p.is_dir():
            shutil.rmtree(p, ignore_errors=True)
        elif p.exists():
            p.unlink(missing_ok=True)
    except Exception:
        # bewusst still – wir zeigen das Gesamtergebnis unten an
        pass


# def cli_factory_reset(*, name: str = "Chatti") -> int:
def cli_factory_reset() -> int:
    """
    Nicht öffentlicher Werksreset …
    Aufruf:
      CHATTI_RESET_DRYRUN=1 ./chatti --_factory-reset               ===> Probelauf
      CHATTI_ALLOW_FACTORY_RESET=1 ./chatti --_factory-reset        ===> Reset auf Anfang
    """
    if os.getenv("CHATTI_RESET_DRYRUN") == "1":
        print("### TROCKENLAUF – es wird nichts gelöscht ###")
        for d in (USERS_CONF_DIR, USERS_DATA_DIR):
            _dryrun_tree(d)
        for f in (SECRETS_FILE, ADMIN_PIN_FILE):
            print(f"FILE: {f} (würde gelöscht)")
        # Flag im aktuellen Prozess wieder entfernen
        try:
            os.unsetenv("CHATTI_RESET_DRYRUN")
        except Exception:
            pass
        os.environ.pop("CHATTI_RESET_DRYRUN", None)
        return 0

    orig_flag = os.getenv("CHATTI_ALLOW_FACTORY_RESET")  # merken, ob es in der Shell gesetzt war
    try:
        if not _reset_enabled():
            print("Werkreset ist deaktiviert. Setze CHATTI_ALLOW_FACTORY_RESET=1, um fortzufahren.")
            return 2

        # Prüfen, ob irgendetwas „schützenswertes“ existiert
        has_users = count_users_in_secrets() > 0
        has_pin = has_admin_pin()

        if has_users or has_pin:
            try:
                ensure_admin_pin_initialized_interactive(strict=True)
                if not verify_admin_pin_interactive(max_tries=3):
                    print("Abgebrochen.")
                    return 130
            except RuntimeError as e:
                print(str(e))
                return 1

        _print_warn(
            "⚠️  WERKSRESET: Dies löscht ALLE Benutzer, Histories, Attachments, Secrets und die Admin-PIN lokal."
        )
        _print_warn("⚠️  Dies kann NICHT rückgängig gemacht werden.")

        # Nur für Transparenz: vorhandene UIDs anzeigen (best effort)
        try:
            from core.security import load_secrets

            sec = load_secrets()
            uids = sorted(
                {k.split(".")[1] for k in sec.keys() if k.startswith("user.") and k.count(".") >= 2}
            )
            print(f"→ Aktive UIDs in chatti-secrets: {', '.join(uids) if uids else '(keine)'}")
        except Exception:
            print("→ Konnte UIDs nicht ermitteln (Secrets evtl. leer/beschädigt).")

        print(f"→ Zu löschende Verzeichnisse: {USERS_CONF_DIR}, {USERS_DATA_DIR}")
        print(f"→ Zu löschende Dateien: {SECRETS_FILE}, {ADMIN_PIN_FILE}")

        if not _confirm_typed("Letzte Warnung – wirklich alles löschen?", "WERKRESET"):
            print("Abgebrochen.")
            return 0
        if not _confirm_typed("Zur Bestätigung erneut tippen", "LÖSCHEN"):
            print("Abgebrochen.")
            return 0

        # Löschen
        for d in (USERS_CONF_DIR, USERS_DATA_DIR):
            _safe_rm(d)
        for f in (SECRETS_FILE, ADMIN_PIN_FILE):
            _safe_rm(f)

        # Alle User-Portale löschen
        _delete_all_user_portals()

        # Root-Verzeichnisse neu anlegen (ohne Inhalte)
        try:
            CONF_DIR.mkdir(parents=True, exist_ok=True)
            DATA_DIR.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            print(f"Fehler beim Neuaufsetzen: {type(e).__name__}: {e}")
            return 1

        print("✓ Werkszustand hergestellt. Starte Chatti neu, um die Ersteinrichtung zu beginnen.")
        return 0

    except KeyboardInterrupt:
        print("\nAbgebrochen.")
        return 130

    finally:
        # Im aktuellen Prozess entfernen (wirkt für Subprozesse dieses Laufs)
        try:
            os.unsetenv("CHATTI_ALLOW_FACTORY_RESET")
        except Exception:
            pass
        os.environ.pop("CHATTI_ALLOW_FACTORY_RESET", None)

        # Nur wenn es ursprünglich in der Shell gesetzt war: Hinweis ausgeben
        if orig_flag:
            print(
                "Hinweis: Entferne die Variable in DEINER Shell, falls sie exportiert wurde:\n"
                "  • bash/zsh:      unset CHATTI_ALLOW_FACTORY_RESET\n"
                "  • fish:          set -e CHATTI_ALLOW_FACTORY_RESET\n"
                "  • PowerShell:    Remove-Item Env:CHATTI_ALLOW_FACTORY_RESET\n"
                "  • Windows CMD:   set CHATTI_ALLOW_FACTORY_RESET=\n"
            )
