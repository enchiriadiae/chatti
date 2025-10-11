# tools/chatti_doctor.py
#
# "Chatti Doctor"
# A diagnostic helper script to check if the local setup for Chatti works.
# It prints step-by-step information about configuration files, encryption,
# environment variables, and the connection to the OpenAI API.
#
# The Doctor does **not** modify anything — it only inspects and reports.
# Think of it like a medical check-up for your Chatti installation.
#
# Using:
# Linux/MacOS
# ./chatti --<doc><doctor>
# CHATTI_MASTER='myPassword' ./chatti --doc
#
# Windows, Powershell:
# $env:CHATTI_MASTER="mypassword"; .\chatti --doc
#
# Windows, CMD:
# set CHATTI_MASTER=mypassword && chatti --doc


import os
import sys
import time
import traceback
from collections.abc import Iterable

# Import only the public API functions from the core modules.
from core.api import (
    get_client,
    get_default_model,
    smoke_test,
)
from core.paths import PUBLIC_CONF, SECRETS_FILE
from core.security import (
    get_api_key_by_uid,
    read_secrets,
)

# Strict chat-text model filter: allow common chat families, exclude audio/image/realtime/embeddings/etc.
_CHAT_ALLOW_PREFIX = (
    "gpt-4",
    "gpt-4o",
    "gpt-4.1",
    "gpt-3.5",
    "o3",
    "o4",
)
_CHAT_EXCLUDE_SUBSTR = (
    "audio",
    "image",
    "vision",
    "whisper",
    "realtime",
    "embed",
    "embedding",
    "tts",
    "speech",
    "translate",
    "jsonl",
)


def _is_likely_text_chat_model(mid: str) -> bool:
    s = mid.lower()
    if not any(s.startswith(p) for p in _CHAT_ALLOW_PREFIX):
        return False
    if any(x in s for x in _CHAT_EXCLUDE_SUBSTR):
        return False
    # ditch known non-chat singletons
    if s in {"gpt-image-1"}:
        return False
    return True


def _env_set_hint(var: str, value_placeholder: str = "dein-passwort") -> list[str]:
    """
    Return platform-specific examples for setting an environment variable.

    Example (Linux/macOS):
        CHATTI_MASTER="mypassword" ./chatti --doc

    Example (Windows PowerShell):
        $env:CHATTI_MASTER="mypassword"; .\\chatti --doc

    Example (Windows CMD):
        set CHATTI_MASTER=mypassword && chatti --doc
    """
    if os.name == "nt":
        return [
            f'PowerShell:  $env:{var}="{value_placeholder}"; .\\chatti --doc',
            f"CMD:         set {var}={value_placeholder} && chatti --doc",
        ]
    else:
        return [f'{var}="{value_placeholder}" ./chatti --doc']


def _explain_exc_for_user(e: Exception) -> str:
    """Roh-Fehler → freundliche Diagnose (de) ohne Stacktrace."""
    s = str(e).strip()
    sl = s.lower()

    # häufige OpenAI-/HTTP-Themen
    if "insufficient_quota" in sl or "quota" in sl:
        return "Kein Guthaben / Kontingent erschöpft (bitte Billing prüfen)."
    if "payment" in sl and ("method" in sl or "add" in sl):
        return "Zahlungsmethode fehlt – bitte im OpenAI-Konto hinterlegen."
    if "rate limit" in sl or "429" in sl:
        return "Rate-Limit erreicht – kurz warten und nochmal probieren."
    if "401" in sl or "unauthorized" in sl or "invalid api key" in sl:
        return "API-Key ungültig oder nicht berechtigt."
    if "403" in sl or "permission" in sl or "access terminated" in sl:
        return "Kein Zugriff auf dieses Modell (Berechtigungen fehlen)."
    if "404" in sl or "not found" in sl:
        return "Modell nicht gefunden (id existiert nicht mehr)."
    if "timeout" in sl:
        return "Zeitüberschreitung – Netzwerk langsam oder Service hakt."
    if "ssl" in sl or "tls" in sl:
        return "TLS/SSL-Problem – ggf. Netzwerk/Proxy prüfen."
    if "dns" in sl:
        return "DNS-Problem – Internetverbindung / Resolver prüfen."

    # Fallback – letzte, neutrale Variante
    return f"Fehler beim Test: {s or type(e).__name__}"


# --- replace your diagnose_models(...) with this version ---
def diagnose_models(client, *, probe: bool = False, timeout: float = 2.0, max_models: int = 20):
    """
    Return [(model_id, status, hint)] for likely text-chat models only.
    status: "OK", "Kein Zugriff", "Nicht erreichbar"
    """
    from core.api import list_models_raw

    rows = []
    try:
        all_ids: Iterable[str] = sorted(set(list_models_raw(client)))
    except Exception as e:
        return [("—", "Nicht erreichbar", _explain_exc_for_user(e))]

    ids = [m for m in all_ids if _is_likely_text_chat_model(m)]
    if not ids:
        return []

    ids = ids[:max_models]

    # 👇 neu: Client-Variante mit Timeout verwenden
    try:
        c = client.with_options(timeout=timeout)
    except Exception:
        c = client  # Fallback: wenn SDK alt ist

    for mid in ids:
        try:
            c.models.retrieve(mid)
        except Exception as e:
            rows.append((mid, "Nicht erreichbar", _explain_exc_for_user(e)))
            continue

        if not probe:
            rows.append((mid, "OK", ""))
        else:
            try:
                c.responses.create(
                    model=mid,
                    input="ping",
                    max_output_tokens=16,
                    timeout=timeout,
                )
                rows.append((mid, "OK", ""))
            except Exception as e:
                rows.append((mid, "Kein Zugriff", _explain_exc_for_user(e)))

        time.sleep(0.02)

    return rows


def main() -> int:
    """
    Run the diagnostic checks.
    Steps:
    1. Show config file locations
    2. Check if secrets exist (encrypted API key + salt)
    3. Check if the crypto library is installed
    4. Try to decrypt the key (if password provided)
    5. Optionally build a client and run a smoke test
    6. Optionally list available models
    """
    print("🔎 Chatti Doctor – Diagnose")
    print(f"• PUBLIC_CONF : {PUBLIC_CONF}")
    print(f"• SECRETS_FILE: {SECRETS_FILE}")

    # --- Step 1: Secrets file (nur Version 2, pro User) ---
    sec = read_secrets()
    active_uid = (sec.get("user.active") or "").strip()

    if not active_uid:
        print("⚠️  Kein aktiver Benutzer gesetzt (user.active fehlt).")
        print("    Bitte mit ./chatti einen Benutzer einrichten.")
        return 1

    token = (sec.get(f"user.{active_uid}.api_key_enc") or "").strip()
    salt = (sec.get(f"user.{active_uid}.kdf_salt") or "").strip()

    if token and salt:
        print(f"✅ Secrets für User [{active_uid}] gefunden (api_key_enc + kdf_salt).")
    else:
        print(f"⚠️  Secrets unvollständig für User [{active_uid}].")
        print("    Bitte Benutzer neu einrichten: ./chatti --user-add")
        return 1

    # --- Step 2: Crypto library ---
    try:
        import cryptography  # noqa: F401

        print("✅ cryptography installed")
    except Exception:
        print("❌ cryptography missing (pip install cryptography)")
        return 1

    # --- Step 3: Try to decrypt with CHATTI_MASTER if set ---
    master = os.getenv("CHATTI_MASTER")
    if master:
        try:
            _ = get_api_key_by_uid(active_uid, master)
            print("✅ Master password from environment accepted. Key decrypted successfully.")
        except Exception as e:
            print(f"⚠️  Decryption with CHATTI_MASTER failed: {type(e).__name__}: {e}")
            tb = traceback.format_exc(limit=1)
            print("    Details:", tb.strip())
            print("    Hint: check password or run interactively: ./chatti")
            return 1
    else:
        print("ℹ️  Encrypted key found, but no master password in environment.")
        print("    Run normally:   ./chatti   (you will be prompted)")
        for line in _env_set_hint("CHATTI_MASTER"):
            print("    Alternative:    " + line)

    # --- Step 4: Build client and run smoke test if possible ---
    try:
        client = get_client(non_interactive=True, require_smoke=False)
    except Exception as e:
        print(f"ℹ️  Client setup skipped: {e}")
        return 0  # still a valid diagnosis

    model = get_default_model()
    print(f"➡️  Default model from config: {model}")

    # 4a) schneller Mini-Call (zeigt unmittelbare Nutzbarkeit)
    try:
        smoke_test(client, model)
        print("✅ Smoke test passed: API key and model working.")
    except Exception as e:
        print(f"⚠️  Smoke test failed: {e}")

    # 4b) Modell-Diagnose: Reachability + optional Mini-Probe (kurze Pings)
    yes_probe = ("--probe" in sys.argv) or (os.getenv("CHATTI_DOCTOR_PROBE") == "1")
    no_probe = ("--no-probe" in sys.argv) or (os.getenv("CHATTI_DOCTOR_NO_PROBE") == "1")
    use_probe = False if no_probe else bool(yes_probe)  # Default: False (keine Token-Probe)

    if use_probe:
        print(
            "⏳ Prüfe Modelle mit Mini-Token-Probe (max_output_tokens=16)… das kann einige Sekunden dauern.",
            flush=True,
        )
    else:
        print("⚡ Prüfe Modelle ohne Token-Verbrauch (nur Reachability).", flush=True)

    try:
        max_models = int(os.getenv("CHATTI_DOCTOR_MAX", "20"))
        rows = diagnose_models(client, probe=use_probe, timeout=2.0, max_models=max_models)
        print(
            "\nModelldiagnose — {}".format(
                "mit Mini-Token-Probe" if use_probe else "ohne Token-Probe"
            )
        )

        if not rows:
            print("  Keine Modelle gelistet – API erreichbar, aber keine IDs gefunden.")
        else:
            # Default-Modell mit ⭐ markieren und Ausgabe sortieren:
            status_rank = {"OK": 0, "Kein Zugriff": 1, "Nicht erreichbar": 2}

            def star(mid: str) -> str:
                return "⭐" if mid == model else " "

            rows_sorted = sorted(
                rows,
                key=lambda r: (
                    0 if r[0] == model else 1,  # Default-Modell zuerst
                    status_rank.get(r[1], 99),  # Statusreihenfolge
                    r[0],  # dann alphabetisch
                ),
            )

            any_ok = False
            for mid, status, hint in rows_sorted:
                if status == "OK":
                    any_ok = True
                    print(f"  ✅ {star(mid)} {mid}")
                elif status == "Kein Zugriff":
                    print(f"  ⚠️  {star(mid)} {mid} – {hint or 'Kein Zugriff'}")
                else:
                    print(f"  ❌ {star(mid)} {mid} – {hint or 'Nicht erreichbar'}")

            if not any_ok:
                print("\nKeine Modelle sind aktuell nutzbar.")
                print("→ Prüfe Billing/Zugriffsrechte und versuche es erneut.")
            else:
                print("\nHinweis: Modelle mit ⚠️/❌ sind aktuell nicht benutzbar.")
                print("Du kannst im Client ein funktionierendes Modell auswählen.")
    except Exception as e:
        print(f"⚠️  Could not list models: {e}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
