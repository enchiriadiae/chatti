#!/usr/bin/env python3
from __future__ import annotations

import os
import pathlib
import socket
import sys
import urllib.request

# Projektwurzel in sys.path aufnehmen (so finden Imports vom Paket-Layout)
ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import core.security as sec  # ← EIN Import, überall unten nur "sec." benutzen
from config_loader import (
    as_bool,
    load_config_effective,
    normalize_color,
)
from core.api import (
    _preferred_model_from_conf_env,
    _should_run_selfcheck,
    cli_user_add,
    cli_user_list,
    cli_user_remove,
    cli_user_use,
)
from core.paths import (
    DOCS_DIR,
    ensure_global_docs_dir,
    ensure_global_prompts_seed,
    prune_orphan_secret_entries,
    prune_orphan_user_dirs,
)
from core.security import get_active_uid


# ---------------- Internet-Check ----------------
def check_internet(timeout: float = 2.0, retries: int = 2) -> tuple[bool, str]:
    """Is access to internet reachable?"""
    hosts = [("1.1.1.1", 443), ("8.8.8.8", 53)]
    last_err = "(no tcp)"
    for attempt in range(retries + 1):
        for host, port in hosts:
            try:
                with socket.create_connection((host, port), timeout=timeout):
                    return True, ""
            except Exception as e:
                last_err = f"{type(e).__name__}: {e}"
        if attempt < retries:
            import time
            time.sleep(0.5)

    # HTTP-Fallback zuletzt
    try:
        resp = urllib.request.urlopen("https://clients3.google.com/generate_204", timeout=timeout)
        if resp.status in (200, 204):
            return True, ""
        return False, f"unexpected http status: {resp.status}"
    except Exception as e:
        return False, f"{type(e).__name__}: {e} (last TCP error: {last_err})"

def show_welcome() -> None:
    from core.security import get_active_uid

    cfg = load_config_effective(uid=get_active_uid())
    if not as_bool(cfg, "show_welcome", True):
        return

    def c(name: str) -> str:
        return normalize_color(name)

    if as_bool(cfg, "show_ascii_art", True):
        ascii_path = ROOT / "scripts/chatti-ascii-art.txt"
        if ascii_path.exists():
            with open(ascii_path, encoding="utf-8") as f:
                print(f.read())

    print()
    print(
        f"🟢 {c('bold')}{c('green')}Chatti!{c('reset')} {c('green')}- Client-sided privacy out of the box! 🟢\n"
        f"Chatti! ist ein schlanker, sicherer, smarter, Text-basierter Client für OpenAI-Modelle.{c('reset')}"
    )
    print("---> Type ./chatti -h or ./chatti -man for help.\nMD-Files in ~/chatti/docs, or visit Chattis Website for manuals.\n")
    print(
        f"{c('bold')}{c('cyan')}==> HINWEIS: {c('reset')}{c('cyan')}"
        f"Diese Software funktioniert nur mit einem gültigen API-Schlüssel der Firma OpenAI!{c('reset')}"
    )
    print(f"{c('cyan')}Weitere Infos & Preise unter https://www.openai.com{c('reset')}\n")
    #print(f"{c('cyan')}https://www.openai.com{c('reset')}")
    #print(f"{c('cyan')}https://openai.com/de-DE/api/pricing/{c('reset')}")
    # print("(Abschaltbar in 'chatti.conf')\n")

# ---------------- Argumente ----------------
def _parse_args(argv: list[str]) -> dict:
    args = {
        "help": False,
        "doc": False,
        "doctor": False,
        "verify": False,
        "manual": False,
        "reset": None,             # "soft" | "hard" | None
        "collect_tickets": False,   # collect support-ticket
        "user_add": False,         # --user-add
        "user_list": False,        # --user-list
        "user_use": None,          # --user-use <name|uid> | --user-use=<...>
        "user_remove": None,       # --user-remove <name|uid> | --user-remove=<...>
        "user_remove_hard": False, # --hard (nur mit --user-remove)
        "user_remove_name": None,   # --user-remove-name "<Name>"
        "user_remove_all": False,   # --all (nur sinnvoll in Kombi mit --user-remove-name)
        "admin_set_pin": False,    # --admin-set-pin
        "admin_change_pin": False, # --admin-change-pin
        "_factory_reset": False     # --_factory-reset (not in public help or in public api)
    }

    i = 0
    while i < len(argv):
        a = argv[i]
        if a in ("-h", "--help"):
            args["help"] = True
        elif a in ("-man", "--manual"):
            args["manual"] = True
        elif a == "--doc":
            args["doc"] = True
        elif a == "--doctor":
            args["doctor"] = True
        elif a == "--verify":
            args["verify"] = True
        elif a.startswith("--reset-auth"):
            mode = "soft"
            if "=" in a:
                _, _, v = a.partition("=")
                v = v.strip().lower()
                if v in ("soft", "hard"):
                    mode = v
            args["reset"] = mode

        # --- Benutzerverwaltung ---
        elif a == "--user-add":
            args["user_add"] = True
        elif a == "--user-list":
            args["user_list"] = True
        elif a.startswith("--user-use="):
            _, _, v = a.partition("="); args["user_use"] = v.strip()
        elif a == "--user-use":
            if i + 1 < len(argv) and not argv[i + 1].startswith("--"):
                args["user_use"] = argv[i + 1].strip(); i += 1
        elif a.startswith("--user-remove="):
            _, _, v = a.partition("="); args["user_remove"] = v.strip()
        elif a == "--user-remove":
            if i + 1 < len(argv) and not argv[i + 1].startswith("--"):
                args["user_remove"] = argv[i + 1].strip(); i += 1
        elif a == "--hard":
            args["user_remove_hard"] = True

        elif a.startswith("--user-remove-name="):
            _,_,v = a.partition("="); args["user_remove_name"] = v.strip().strip('"').strip("'")
        elif a == "--user-remove-name":
            if i + 1 < len(argv) and not argv[i+1].startswith("--"):
                args["user_remove_name"] = argv[i+1].strip(); i += 1
        elif a == "--all":
            args["user_remove_all"] = True

        # Support-Tickets:
        elif a == "--collect-tickets":
            args["collect_tickets"] = True

        # --- Admin-PIN-Tools ---
        elif a == "--admin-set-pin":
            args["admin_set_pin"] = True
        elif a == "--admin-change-pin":
            args["admin_change_pin"] = True
        elif a == "--_factory-reset":
            args["_factory_reset"] = True
        i += 1

    return args

# --- Help/Manual ----------------
def _print_help() -> None:
    print("Chatti — CLI-Client\n")
    print("Verwendung:")
    print("  chatti <[--Optionen]>")
    print()
    print("Optionen:")
    print("  --admin-set-pin            Einmalig Admin-PIN setzen (Pflicht vor sensiblen Aktionen).")
    print("  --admin-change-pin         Admin-PIN ändern (erfordert aktuelle PIN-Eingabe).")
    print()
    print("  --verify                   Führe beim Start einen kurzen Smoke-Test (API-Key/Modell) aus.")
    print("  --reset-auth[=soft|hard]   Zurücksetzen gespeicherter Authentifizierungsdaten.")
    print("                              soft = löscht Schlüssel; Neu-Einrichtung beim nächsten Start")
    print("                              hard = zusätzlich lokale Caches löschen")
    print("  --doc, --doctor            Diagnose laufen lassen.")
    print("  --collect-tickets          Listet alle ticket.txt aus allen User-Verzeichnissen.")
    print("  -h, --help                 Diese Hilfe anzeigen")
    print("  -man, --manual             Ausführliche Anleitung (Manpage/Manual) anzeigen.")
    print("  --user-add                 Neuen Benutzer anlegen (Name, API-Key, Master).")
    print("  --user-list                Benutzerliste anzeigen (entschlüsselt; fragt Master).")
    print("  --user-use <Name|UID>      Aktiven Benutzer setzen (fragt Master).")
    print("  --user-remove-name '<Name|UID>' und --all (für Massenlöschung desselben Namens).")
    print("       --hard                Zusätzlich alle Benutzerdaten löschen (History, Attachments …).")
    print()


def _print_manual() -> int:
    """Zeigt die Manpage/README—Priorität: globale DOCS_DIR, dann Repo-Files."""
    candidates = [
        DOCS_DIR / "MANUAL.md",
        DOCS_DIR / "README.md",
        DOCS_DIR / "MANUAL.txt",
        DOCS_DIR / "README.txt",
        ROOT / "docs" / "MANUAL.md",
        ROOT / "docs" / "MANUAL.txt",
        ROOT / "README.md",
        ROOT / "README.txt",
    ]

    for path in candidates:
        try:
            if path.exists():
                text = path.read_text(encoding="utf-8")
                print(text)
                return 0
        except Exception:
            # Nächsten Kandidaten versuchen
            pass

    print("Keine Manpage/Anleitung gefunden. Lege MANUAL.md unter DOCS_DIR an oder siehe README.")
    try:
        print(f"Hinweis: DOCS_DIR = {DOCS_DIR}")
    except Exception:
        pass
    return 1


def _confirm(prompt: str, default: bool = False) -> bool:
    suf = " [Y/n] " if default else " [y/N] "
    try:
        ans = input(prompt + suf).strip().lower()
    except (KeyboardInterrupt, EOFError):
        print()
        return False
    if not ans:
        return default
    return ans in ("y", "yes", "j", "ja")

# --- Kurzer Hinweis bei fälligem API-Selfcheck (reine Terminal-Ausgabe) ---
def _maybe_print_selfcheck_notice() -> None:
    try:
        cfg = load_config_effective(uid=get_active_uid())
        model = _preferred_model_from_conf_env()
        if _should_run_selfcheck(cfg, model):
            print("⏳ Kurzer API-Gesundheitscheck läuft …", flush=True)
    except Exception:
        # Kein Blocker beim Start, falls Config/Imports mal klemmen
        pass

# ---------------- Main ----------------
def main() -> int:
    argv = sys.argv[1:]
    args = _parse_args(argv)

    # leises Aufräumen (keine Ausgabe, Fehler ignorieren)
    try:
        prune_orphan_user_dirs(verbose=False)
        prune_orphan_secret_entries(verbose=False)
    except Exception:
        pass

    # Collect tickets throughout all user-dirs
    if args.get("collect_tickets"):
        try:
            from core.api import collect_tickets
            rows = collect_tickets()
            if not rows:
                print("Keine Tickets gefunden.")
                return 0
            print("Tickets:")
            for uid, path, first in rows:
                preview = (first or "").strip()
                print(f"  {uid}: {path}")
                if preview:
                    print(f"     → {preview}")
            return 0
        except KeyboardInterrupt:
            print("\n[Abgebrochen]"); return 130
        except Exception as e:
            print(f"[Setup-Fehler] {e}"); return 1

    # --- First-run: decide Single vs Multi-user ---
    try:
        # Erstkonfiguration: keine User & kein Admin-PIN → einmalig fragen
        if sec.count_users_in_secrets() == 0 and not sec.has_admin_pin():

            def _ask_yn(prompt: str, default_no: bool = True) -> bool:
                suf = " [y/N] " if default_no else " [Y/n] "
                try:
                    ans = input(prompt + suf).strip().lower()
                except (KeyboardInterrupt, EOFError):
                    print("\nAbgebrochen.")
                    return False
                if not ans:
                    return not default_no
                return ans in ("y", "yes", "j", "ja")

            if _ask_yn("Möchtest du einen Multi-User-Modus einrichten (Admin-PIN setzen)?"):
                try:
                    sec.ensure_admin_pin_initialized_interactive(strict=True)
                    print("✓ Admin-PIN eingerichtet.")
                except KeyboardInterrupt:
                    print("\nAbgebrochen."); return 130
                except RuntimeError as e:
                    print(str(e)); return 1
            else:
                print("✓ Single-User-Modus verwendet (ohne Admin-PIN).")
                print("➡️ Hinweis: Wenn ein weiterer Benutzer eingerichtet wird, ist die Einrichtung einer Admin-PIN obligatorisch.")
    except Exception:
        # im Zweifel nicht blockieren
        pass

    # Hidden Easter Egg: complete reset, afterwards new init
    if args.get("_factory_reset"):
        try:
            from core.api import cli_factory_reset
            return cli_factory_reset()
        except KeyboardInterrupt:
            print("\n[Abgebrochen]")
            return 130
        except Exception as e:
            print(f"[Setup-Fehler] {e}")
            return 1

    # --- Nicht-admin: user-list / user-use früh behandeln ---
    if args.get("user_list") or args.get("user_use") is not None:
        try:
            if args.get("user_list"):
                cli_user_list()
                return 0
            if args.get("user_use") is not None:
                val = args["user_use"]
                if not val:
                    print("Fehler: --user-use benötigt einen Namen oder eine UID.")
                    return 2
                cli_user_use(val)
                return 0
        except KeyboardInterrupt:
            print("\n[Abgebrochen]")
            return 130
        except Exception as e:
            print(f"[Setup-Fehler] {e}")
            return 1

    # --- Admin-CLI: user-add / user-remove (PIN-Pflicht je nach Zustand) ---
    #if args.get("user_remove") is not None:
    if args.get("user_add") or args.get("user_remove") is not None:
        # Für --user-add: Admin-PIN erst ab dem ZWEITEN User erzwingen
        need_admin_for_add = args.get("user_add") and sec.has_any_user()
        # Für --user-remove: sobald jemand existiert, absichern
        need_admin_for_remove = args.get("user_remove") is not None and sec.has_any_user()

        if need_admin_for_add or need_admin_for_remove:
            try:
                sec.ensure_admin_pin_initialized_interactive(strict=True)
                if not sec.verify_admin_pin_interactive():
                    print("Abgebrochen.")
                    return 2
            except RuntimeError as e:
                print(str(e))
                return 1

        try:
            if args.get("user_add"):
                try:
                    cli_user_add(_preferred_model_from_conf_env())
                except KeyboardInterrupt:
                    print("\nAbgebrochen.")
                    return 130
                except Exception as e:
                    print(f"[Setup-Fehler] {e}")
                    return 1

            if args.get("user_remove") is not None:
                who = args["user_remove"]
                if not who:
                    print("Fehler: --user-remove benötigt einen Namen oder eine UID.")
                    return 2
                cli_user_remove(who, hard=bool(args.get("user_remove_hard")))
                return 0
        except KeyboardInterrupt:
            print("\n[Abgebrochen]")
            return 130
        except Exception as e:
            print(f"[Setup-Fehler] {e}")
            return 1

    # --- Admin-CLI: user-remove-name (PIN-Pflicht) ---
    if args.get("user_remove_name") is not None:
        # Admin-PIN nur verlangen, wenn wirklich User existieren
        if sec.count_users_in_secrets() > 0:
            sec.ensure_admin_pin_initialized_interactive(strict=True)
            if not sec.verify_admin_pin_interactive():
                print("Abgebrochen.")
                return 2
        name = args["user_remove_name"]
        hard = bool(args.get("user_remove_hard"))
        all_matches = bool(args.get("user_remove_all"))
        try:
            from core.api import cli_user_remove_by_name
            cli_user_remove_by_name(name, hard=hard, all_matches=all_matches)
            return 0
        except KeyboardInterrupt:
            print("\n[Abgebrochen]")
            return 130
        except Exception as e:
            print(f"[Setup-Fehler] {e}")
            return 1

    # --- Help/Manual/Doctor/Reset: ohne PIN-Zwang ---
    if args["help"]:
        _print_help()
        return 0

    if args["manual"]:
        return _print_manual()

    if args.get("doc") or args.get("doctor"):
        from tools.chatti_doctor import main as doctor_main
        return doctor_main()

    if args["reset"]:
        mode = args["reset"]
        print(f"Achtung: Authentifizierungsdaten werden zurückgesetzt ({mode}).")
        if not _confirm("Wirklich zurücksetzen?", default=False):
            print("Abgebrochen.")
            return 0
        try:
            sec.reset_secrets(mode)
            print("Authentifizierungsdaten zurückgesetzt.")
            print("Rufe 'chatti' erneut auf, um die Erstkonfiguration zu starten.")
            return 0
        except Exception as e:
            print(f"Fehler beim Zurücksetzen: {e}")
            return 1

    # Prompts + Docs seeden (best effort)
    try:
        ensure_global_prompts_seed()
        ensure_global_docs_dir()   # NEU
    except Exception as e:
        print(f"⚠️ Setup-Hinweis: {type(e).__name__}: {e}")


    except Exception as e:
        print(f"⚠️ Prompts-Seeding übersprungen: {type(e).__name__}: {e}")

    # --- Ab hier normaler Start: TUI ---
    if os.getenv("CHATTI_SKIP_NETCHECK") != "1":
        ok, err = check_internet()
        if not ok:
            print(
                f"🚫 {normalize_color('bold')}{normalize_color('bright_red')}Kein Internet:{normalize_color('reset')}",
                err,
            )
            print(
                f"⚠️{normalize_color('bold')}{normalize_color('yellow')} ---> Hinweis: Prüfe WLAN/LAN, VPN/Proxy oder Captive Portal (Login-Seite).{normalize_color('reset')}"
            )
            return 2

    show_welcome()

    try:
        from chatti_tui import ChattiTUI
    except KeyboardInterrupt:
        print("\nAbgebrochen.")
        return 130
    except Exception as e:
        print(f"[Setup-Fehler] {e}")
        return 1

    from core.api import get_client

    require_smoke = bool(args["verify"])
    _maybe_print_selfcheck_notice()

    try:
        get_client(require_smoke=require_smoke)
    except KeyboardInterrupt:
        print("\n[Abgebrochen]")
        return 130
    except Exception as e:
        print(f"[Setup-Fehler] {e}")
        return 1

    try:
        ChattiTUI().run()
        return 0
    except KeyboardInterrupt:
        print("\n[Abgebrochen]")
        return 130
    except Exception as e:
        print(f"Unerwarteter Fehler: {e}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
