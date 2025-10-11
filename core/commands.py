# core/commands.py
# Zentrale Kommando-Definition mit Gruppen + kurzen Erklärungen.
# Daraus leiten wir KNOWN_CMDS (Tuple) und CMD_DESC (Dict) ab.

from __future__ import annotations

# --- Single Source of Truth ---------------------------------------------------
COMMAND_GROUPS = [
    {
        "group": "Anhänge",
        "hint": "Dateien anhängen, auflisten, (de)aktivieren oder aufräumen.",
        "items": [
            {
                "main": ":attach-add",
                "aliases": ["/attach-add", ":upload", "/upload"],
                "desc": "Datei anhängen",
            },
            {
                "main": ":attach-list",
                "aliases": ["/attach-list", ":attachments", "/attachments"],
                "desc": "Anhänge anzeigen",
            },
            {
                "main": ":attach-clear",
                "aliases": ["/attach-clear", ":clearattach", "/clearattach"],
                "desc": "Anhänge aus Queue entfernen",
            },
            {
                "main": ":attach-purge",
                "aliases": [
                    "/attach-purge",
                    ":attachments-purge",
                    "/attachments-purge",
                ],
                "desc": "Anhänge endgültig löschen",
            },
            {
                "main": ":attach-use",
                "aliases": ["/attach-use"],
                "desc": "Anhang aktivieren",
            },
            {
                "main": ":attach-unuse",
                "aliases": ["/attach-unuse"],
                "desc": "Anhang deaktivieren",
            },
        ],
    },
    {
        "group": "History",
        "hint": "Gesprächsverlauf zurücksetzen oder exportieren.",
        "items": [
            {
                "main": ":history-import-view",
                "aliases": [
                    "/history-import-view",
                    ":history-import-viewonly",
                    "/history-import-viewonly",
                ],
                "desc": "Dump-Datei nur ansehen (keine Änderungen)",
            },
            {
                "main": ":history-import-add",
                "aliases": [
                    "/history-import-add",
                    ":history-import",
                    "/history-import",
                ],  # Legacy-Aliase
                "desc": "Dump-Datei an aktuelle History anhängen",
            },
            {
                "main": ":history-import-replace",
                "aliases": ["/history-import-replace"],
                "desc": "Aktuelle History durch Dump ersetzen",
            },
            # --- NEU: DUMPS ---
            {
                "main": ":history-dump-enc",
                "aliases": ["/history-dump-enc", ":history-dump", "/history-dump"],
                "desc": "History exportieren (verschlüsselt)",
            },
            {
                "main": ":history-dump-plain",
                "aliases": ["/history-dump-plain"],
                "desc": "History exportieren (Klartext)",
            },
            {
                "main": ":goto",
                "aliases": ["/goto"],
                "desc": "Geht zu einem gewählten Suchergebnis (Nur nach Suchabfrage mit ctrl+f)",
            },
        ],
    },
    {
        "group": "Diagnose",
        "hint": "Schnelle Statusprüfung & System-Prompt einsehen.",
        "items": [
            {"main": ":doctor", "aliases": ["/doctor"], "desc": "Status-Diagnose"},
            {
                "main": ":show-prompt",
                "aliases": ["/show-prompt"],
                "desc": "System-Prompt anzeigen",
            },
            {
                "main": ":whoami",
                "aliases": ["/whoami"],
                "desc": "Zeigt aktiven Benutzer, UID und relevante Pfade.",
            },
        ],
    },
    {
        "group": "Verbrauch",
        "hint": "Token-Nutzung anzeigen (lokal / remote).",
        "items": [
            {
                "main": ":usage",
                "aliases": ["/usage", ":u"],
                "desc": "Token-Verbrauch anzeigen",
            },
            {
                "main": ":usage-reset",
                "aliases": ["/usage-reset"],
                "desc": "Session-Zähler zurücksetzen",
            },
        ],
    },
    {
        "group": "Modelle",
        "hint": "Modellauswahl & Anzeige",
        "items": [
            {
                "main": ":change-openai-model",
                "aliases": ["/change-openai-model"],
                "desc": "OpenAI-Modell auswählen & speichern",
            },
        ],
    },
    {
        "group": "Beenden",
        "hint": "TUI schließen.",
        "items": [
            {
                "main": ":exit",
                "aliases": ["/exit", ":quit", "/quit", ":q", "/q"],
                "desc": "Beenden",
            },
            {
                "main": ":remove-my-account",
                "aliases": ["/remove-my-account"],
                "desc": "Löscht dein Konto (mit Bestätigung)",
            },
        ],
    },
]


# --- Abgeleitete Strukturen ---------------------------------------------------
def _all_aliases() -> list[str]:
    out: list[str] = []
    for grp in COMMAND_GROUPS:
        for it in grp["items"]:
            out.append(it["main"])
            out.extend(it.get("aliases", []))
    return out


def _desc_map() -> dict[str, str]:
    d: dict[str, str] = {}
    for grp in COMMAND_GROUPS:
        for it in grp["items"]:
            desc = it["desc"]
            d[it["main"]] = desc
            for al in it.get("aliases", []):
                d[al] = desc
    return d


# public:
KNOWN_CMDS = tuple(_all_aliases())
CMD_DESC = _desc_map()


# Optional: hübsche Vorschlagsliste mit Gruppen-Headern (für Autocomplete/Help)
def suggestions_for_prefix(prefix: str, *, with_aliases: bool = False) -> list[str]:
    """
    Gibt formatierte Vorschlagszeilen zurück, gruppiert nach COMMAND_GROUPS.
    - prefix: Filterpräfix (":a", "/att", …). Leerer/unklarer String ⇒ beide Familien.
    - with_aliases: Wenn True, zeige auch Aliase, sonst nur das Hauptkommando.
    """
    pfx = (prefix or "").strip()

    # Welche Präfixfamilien dürfen matchen?
    if not pfx:
        families = (":", "/")  # zeige alles
    elif pfx[0] in (":", "/"):
        families = (pfx[0],)
    else:
        families = (":", "/")  # falls jemand z. B. "att" übergibt

    out: list[str] = []
    for grp in COMMAND_GROUPS:
        lines: list[str] = []
        for it in grp["items"]:
            cmds = [it["main"], *it.get("aliases", [])] if with_aliases else [it["main"]]
            for c in cmds:
                if c and c[0] in families:
                    if not pfx or c.startswith(pfx):
                        lines.append(f"  {c:<22} — {it['desc']}")
        if lines:
            out.append(f"[{grp['group']}] {grp['hint']}")
            out.extend(lines)
            out.append("")  # Leerzeile zwischen Gruppen

    if out and out[-1] == "":
        out.pop()
    return out
