# -----------------------------------------------------------------------------
# chatti_tui.py
#
# Text-based user interface (TUI) for the Chatti client.
#
# What this module does:
# - boots the terminal UI
# - wires user input/output to the OpenAI client
# - streams model responses with safe, wrapped output
# - provides a small command: /doctor (runs the diagnostics tool)
#
#
# Design notes:
# - Defensive style: we treat I/O, env, and network as fallible; errors are
#   handled locally with readable messages instead of raw tracebacks.
# - All console printing funnels through a single wrapped logger:
#   `_log_block_wrapped(title, body, color=None)` → consistent formatting.
# -----------------------------------------------------------------------------

import asyncio
import atexit
import base64
import contextlib
import datetime
import io
import json
import os
import shlex
import shutil
import sys
import textwrap
from pathlib import Path

import core.commands as commands
import core.security as sec

# from core.security import (
# get_active_uid,
# get_active_user_display,
# get_api_key_by_uid,
# is_admin,
# mask_secrets,
# remove_user_entry_by_uid,
# )
from config_loader import (
    as_bool,
    load_config_effective,
    normalize_color,
    write_conf_kv_scoped,
)
from core.api import (
    _delete_user_files,
    chat_once,
    cli_user_remove,
    get_client,
    get_default_model,
    get_reachable_chat_models,
    prune_orphan_user_dirs,
    register_ui_notifier,
    set_default_model,
)
from core.attachments import (
    AttachmentValidationError,  # ← neu
    add_attachment,
    find_attachment,
    list_attachments,
    purge_attachments,
)
from core.history import (
    _scrypt_derive_key,
    history_dump,
    history_import,
    load_history,
    load_history_tail,
    load_user_inputs,
    reset_user_history,
    save_turn,
    search_history,
)
from core.paths import (
    PUBLIC_CONF,
    normalize_user_path,
    user_attachments_files_dir,
    user_conf_file,
    user_history_file,
)
from core.usage import append_usage, fetch_usage_month_to_date, sum_month
from cryptography.fernet import Fernet
from textual import events, on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Footer, Header, Input, Log, Select, Static
from tools.chatti_doctor import diagnose_models
from tools.chatti_doctor import main as doctor_main

# Optional TextArea (if available in your Textual version)
try:
    from textual.widgets import TextArea

    HAS_TEXTAREA = True
except Exception:
    HAS_TEXTAREA = False
from core import __version__
from core.tickets import collect_tickets


class ChattiTUI(App):
    """Main TUI application."""

    CSS = """
    Screen { layout: vertical; }
    #topbar { height: 3; }
    #content { layout: vertical; }
    #controls { height: 8; }

    #input {
      height: 8;
      border: round $accent;
    }

    #input.chat {
      border: round $accent;     /* normal chat */
    }

    #input.search {
      border: round $success;    /* search mode (green) */
    }
    """

    # ANSI-Colors from config_loader.normalize_color()
    _RED = normalize_color("red")
    _GREEN = normalize_color("green")
    _CYAN = normalize_color("cyan")
    _YELLOW = normalize_color("yellow")
    _BOLD = normalize_color("bold")
    _RESET = normalize_color("reset")

    # careful: Don't bind against textuals. Use their key-bindings instead! Saves lots of work!
    # BINDINGS = [
    #     Binding("alt+up", "history_prev", show=False, priority=True),
    #     Binding("alt+down", "history_next", show=False, priority=True),
    #     Binding("ctrl+q", "exit", show=False, priority=True),
    #     Binding("shift+ctrl+b", "boss_toggle", show=False, priority=True),
    # ]

    BINDINGS = [
        Binding("alt+up", "history_prev", show=False, priority=True),
        Binding("alt+down", "history_next", show=False, priority=True),
        Binding("ctrl+q", "exit", show=False, priority=True),
        Binding("ctrl+b", "boss_toggle_b", show=False, priority=True),  # the one to rely on
        Binding("ctrl+g", "boss_toggle_g", show=False, priority=True),  # extra fallback
    ]

    def __init__(self, client=None):
        super().__init__()
        self.client = client or get_client()
        self.model = get_default_model()
        self.title = f"Chatti — {self.model}"
        # self.history = load_history()
        self.history = load_history_tail(last_n=200)

        self.chat_view: Log | None = None
        self.input: Input | None = None

        # streaming state
        self._cur_line = ""
        self._block_open = False

        # boss-mode (a quick and weak protection against curious noses...)
        self._boss_mode = False
        self._squelch_output = False
        self._boss_key: str | None = None
        self._boss_buffer = ""

        # Quick-Pick State (für Zahlenauswahl ohne zusätzliche Widgets)
        self._pending_choice = None  # für den Quick-Pick "Model wählen"
        self._pick_buf = ""  # Ziffern-Puffer für die Auswahl

        # pretty output (ANSI colors); can be disabled in config
        self.pretty = True

        # frame colors for input box (CSS names, fix default)
        self.chat_border_css = "green"
        self.search_border_css = "orange"
        self._startup_warnings: list[str] = []

        self._last_usage: dict[str, int | str] | None = None
        self.cost_session: float = 0.0

        # für numerische Auswahl per Senden-Button
        self._pending_choice: dict | None = None

        # -----------------------------
        # Konfiguration laden (zentral + per User)
        # -----------------------------
        uid = sec.get_active_uid()
        cfg = load_config_effective(uid=uid)
        self.boss_strict = False  # wird in on_mount() korrekt geladen & geloggt

        DEFAULT_SYSTEM_PROMPT = "Du bist hilfsbereit und knapp."
        prompt = (cfg.get("system_prompt") or "").strip()

        # Basis-Verzeichnis der *wirksamen* Konfig (User-Conf hat Vorrang)
        if uid and user_conf_file(uid).exists():
            conf_dir = user_conf_file(uid).parent
        else:
            conf_dir = PUBLIC_CONF.parent

        prompt_file = (cfg.get("system_prompt_file") or "").strip()
        if not prompt and prompt_file:
            pf = Path(prompt_file)
            if not pf.is_absolute():
                pf = conf_dir / pf
            try:
                prompt = pf.read_text(encoding="utf-8").strip()
            except FileNotFoundError:
                self._startup_warnings.append(
                    f"Konnte system_prompt_file '{str(pf)}' nicht finden – nutze Default."
                )
                prompt = ""
            except Exception as e:
                self._startup_warnings.append(
                    f"Konnte system_prompt_file '{str(pf)}' nicht lesen ({type(e).__name__}: {e}) – nutze Default."
                )
                prompt = ""  # fällt unten auf DEFAULT zurück

        if not prompt:
            style = (cfg.get("system_prompt_style") or "").strip().lower()
            PRESET_STYLES = {
                "knapp": "Du bist hilfsbereit und äußerst knapp. Antworte in maximal 3 Sätzen.",
                "freundlich": "Du bist hilfsbereit, freundlich und prägnant.",
                "technisch": "Du antwortest sachlich, präzise und mit Fokus auf technische Details.",
                "coach": "Du fragst kurz nach Ziel und Kontext, gibst dann strukturierte, motivierende Hinweise.",
                "humor": "Hilfsbereit, knapp, mit einem leichten Schmunzeln – niemals verletzend.",
            }
            prompt = PRESET_STYLES.get(style, "")

        self.system_prompt = prompt or DEFAULT_SYSTEM_PROMPT

        def cfg_color(key: str, default_name: str) -> str:
            val = cfg.get(key)
            return normalize_color(val if isinstance(val, str) and val.strip() else default_name)

        # ANSI-Farben (immer normalisieren)
        self.user_colour = cfg_color("u_colour", "cyan")
        self.chat_colour = cfg_color("c_colour", "green")
        self.ansi_reset = cfg_color("ansi_reset", "reset")
        self.ansi_bold = cfg_color("ansi_bold", "bold")

        self.user_label = (cfg.get("user_label") or "User").strip()
        self.assistant_label = (cfg.get("assistant_label") or "Chatti").strip()
        self.pretty = as_bool(cfg, "pretty_output", True)

        # Suchfarbe (ANSI), ebenfalls normalisieren
        self.search_colour = cfg_color("s_colour", "yellow")

        self._awaiting_confirm = None  # z.B. {"token": "LÖSCHEN", "on_success": callable}

        self.mode = "chat"  # "chat" | "search"
        self._last_list_cache: list[dict] = []  # cache für @N
        self.attach_queue: list[str] = []  # IDs für nächste Nachricht

        cfg_model = cfg.get("default_model")
        if cfg_model:
            set_default_model(cfg_model)
            self.model = cfg_model

        self._history_chat: list[str] = []
        self._history_search: list[str] = []
        self._hist_pos: int | None = None
        self._hist_draft: str = ""

        # Suchen in der Historie (ctrl+f)
        self._last_search_hits: list[dict] = []
        self._last_search_query: str = ""

        # Debug Only: write keys-event in widget if = true
        self.debug_keys = False

        # History-Größe aus cfg (mit failsafe)
        try:
            self._history_max = int(cfg.get("history_max", 200))
        except Exception:
            self._history_max = 200

        # Eingabe-Historie aus der persistierten History.jsonl vorfüllen
        try:
            # optional per Conf begrenzen
            cfg_inputs_max = int(cfg.get("input_history_max", 200))
        except Exception:
            cfg_inputs_max = 200

        preload_inputs = as_bool(cfg, "preload_input_history", True)
        if preload_inputs:
            # jüngste zuerst geliefert → wir wollen chronologisch „alt → neu“ in der Liste
            recent_user_inputs = list(reversed(load_user_inputs(last_n=cfg_inputs_max)))
            # Sanity: keine leeren / direkten Duplikate hinzufügen
            for s in recent_user_inputs:
                if not s:
                    continue
                if self._history_chat and self._history_chat[-1] == s:
                    continue
                self._history_chat.append(s)

    # ---------------------------------------------------------------------
    # Small helpers
    # ---------------------------------------------------------------------

    # Debug-Only: print out key-events from textual_events

    #     def action_autocomplete_cmd(self) -> None:
    #         if self.focused is self.input:
    #             txt = self._get_user_text()
    #             if txt and (txt.startswith(":") or txt.startswith("/")) and " " not in txt:
    #                 self._autocomplete_command()

    def _run_async(self, coro, *, exclusive: bool = False):
        self.run_worker(coro, thread=False, exclusive=exclusive)

    def _show_welcome(self) -> None:
        tips = [
            "Enter: senden · Shift+Enter: neue Zeile",
            "Alt+↑/↓: Eingabe-Historie",
            "Ctrl+F: Suchmodus · Esc: zurück",
            "Alt/Strg+→: Autocomplete für :/Kommandos",
            ":doctor – Diagnose, :show-prompt – aktiver System-Prompt",
        ]
        body = "\n".join(tips)
        self._log_block_wrapped("Willkommen bei Chatti 🟢", body, self._GREEN)

    def _show_startup_warnings(self) -> None:
        if self._startup_warnings:
            msg = "\n".join("⚠️ " + w for w in self._startup_warnings)
            self._log_block_wrapped("Hinweis", msg, self._YELLOW)
            self._startup_warnings.clear()

    def _title_line(self) -> str:
        base = f"Model: {self.model}"

        # aktueller Turn (falls vorhanden)
        if self._last_usage:
            tot = int(self._last_usage.get("total_tokens", 0) or 0)
            base += f" | Tokens: {tot}"

        # Monatsstand
        try:
            uid = sec.get_active_uid()
            sin, sout, stot = sum_month(uid=uid)
            base += f" | Monat: {stot}"
        except Exception:
            pass

        return base

    def _refresh_title_bar(self) -> None:
        # Header (falls vorhanden)
        try:
            self.query_one(Header)
        except Exception:
            pass

        # Grundzeile
        parts = [f"Model: {self.model}"]

        # Tokens (falls vorhanden)
        u = self._last_usage or {}
        if u:
            inp = int(u.get("input_tokens", 0) or 0)
            out = int(u.get("output_tokens", 0) or 0)
            tot = int(u.get("total_tokens", 0) or 0)
            parts.append(f"tokens in:{inp} out:{out} tot:{tot}")

            # Monatsstand anhängen
            try:
                uid = sec.get_active_uid()
                sin, sout, stot = sum_month(uid=uid)
                parts.append(f"Monat: {stot} tok")
            except Exception:
                pass
        else:
            parts.append("tokens in:– out:– tot:–")

        # Fenster-/Tabtitel ebenfalls aktualisieren
        try:
            self.title = f"Chatti — {self._title_line()}"
        except Exception:
            pass

    def _insert_into_input(self, s: str) -> None:
        w = self.input
        if not w or not s:
            return
        try:
            if HAS_TEXTAREA and isinstance(w, TextArea):
                # am Caret einfügen (Textual >= 0.56 hat insert())
                if hasattr(w, "insert"):
                    w.insert(s)
                else:
                    w.text = (w.text or "") + s
                if hasattr(w, "action_cursor_document_end"):
                    w.action_cursor_document_end()
            else:
                val = w.value or ""
                pos = int(getattr(w, "cursor_position", len(val)) or 0)
                new = val[:pos] + s + val[pos:]
                w.value = new
                try:
                    w.cursor_position = pos + len(s)
                except Exception:
                    pass
            self.set_focus(w)
        except Exception:
            pass

    def _parse_drop_text(self, raw: str) -> list[str]:
        """Zerlegt einen Drop-/Paste-Text in normalisierte Dateipfade (ohne Upload)."""
        if not raw:
            return []
        out: list[str] = []
        for line in raw.replace("\r", "").splitlines():
            line = line.strip()
            if not line:
                continue
            # Direkte Pfade oder file://-URLs
            if line.startswith(("file://", "/", "~")):
                out.append(str(normalize_user_path(line)))
                continue
            # Auch „komisch“ aussehende Strings könnten Pfade sein → versuchen
            try:
                out.append(str(normalize_user_path(line)))
            except Exception:
                # kein Pfad → Rohtext zurückgeben (der Aufrufer entscheidet)
                out.append(line)
        return out

    async def on_paste(self, event: events.Paste) -> None:
        paths = self._parse_drop_text(event.text or "")
        if not paths:
            return

        # Einfügen: wenn mehrere → nacheinander mit Space trennen
        # oder (besser) gleich mehrere Tokens ins Input übernehmen
        text = " ".join(shlex.quote(p) for p in paths)
        self.set_focus(self.input)
        self._insert_into_input(text + " ")

    def _debug_key_event(self, ev) -> None:
        try:
            info = [
                f"key={getattr(ev, 'key', None)!r}",
                f"character={getattr(ev, 'character', None)!r}",
                f"shift={getattr(ev, 'shift', None)}",
                f"ctrl={getattr(ev, 'ctrl', None)}",
                f"alt={getattr(ev, 'alt', None)}",
                f"meta={getattr(ev, 'meta', None)}",  # macOS ⌘
                f"is_printable={getattr(ev, 'is_printable', None)}",
                f"repeat={getattr(ev, 'repeat', None)}",  # gehaltene Taste?
                f"handled={getattr(ev, 'handled', None)}",
            ]
            self._log_block_wrapped("KeyEvent", "\n".join(info), color=self.search_colour)
        except Exception as e:
            self._log_block_wrapped("KeyEvent", f"debug failed: {type(e).__name__}: {e}")

    def action_cursor_end(self) -> None:
        # Name without first "_", because of Textuals Method-Name
        w = self.input
        if not w:
            return
        try:
            # TextArea: eingebaute "ans Dokumentende"
            if HAS_TEXTAREA and isinstance(w, TextArea):
                if hasattr(w, "action_cursor_document_end"):
                    w.action_cursor_document_end()
                elif hasattr(w, "action_end"):
                    w.action_end()
                if hasattr(w, "scroll_visible"):
                    w.scroll_visible()
            else:
                # Input: erst Action, sonst Fallback auf Position setzen
                if hasattr(w, "action_end"):
                    w.action_end()
                else:
                    w.cursor_position = len(getattr(w, "value", "") or "")
            self.set_focus(w)
        except Exception:
            pass

    # Umschalten zwischen Chat-/Search-History-Liste
    def _active_history(self) -> list[str]:
        return self._history_search if self.mode == "search" else self._history_chat

    def _c(self, s: str, color: str, bold: bool = False) -> str:
        if not self.pretty:
            return s
        return f"{self.ansi_bold if bold else ''}{color}{s}{self.ansi_reset}"

    def _ui(self, fn, *args):
        try:
            self.call_from_thread(fn, *args)
        except RuntimeError:
            fn(*args)

    def _autocomplete_command(self) -> None:
        """Autocomplete für :/Kommandos mit Kurzbeschreibung & gruppierten Vorschlägen."""
        w = self.input
        if not w:
            return

        # 1) aktuellen Text + Caret-Position holen
        if HAS_TEXTAREA and isinstance(w, TextArea):
            full = w.text or ""
            caret_at_end = True  # bei TextArea completen wir nur am Zeilenende
            prefix = full.strip()
            after_caret = ""
        else:
            full = w.value or ""
            pos = int(getattr(w, "cursor_position", len(full)) or 0)
            prefix = full[:pos].rstrip()
            after_caret = full[pos:].lstrip()
            caret_at_end = after_caret == ""

        # Nur wenn am „Wortende“ und es wie ein Kommando aussieht
        if not caret_at_end:
            return
        if not prefix or " " in prefix:
            return
        if not (prefix.startswith(":") or prefix.startswith("/")):
            return

        # 2) Kandidaten einsammeln (gleiches Präfix-Zeichen)
        prefix_char = prefix[0]
        cmds = [c for c in commands.KNOWN_CMDS if isinstance(c, str) and c.startswith(prefix_char)]
        if not cmds:
            return

        cands = sorted(c for c in cmds if c.startswith(prefix))
        if not cands:
            return

        def insert(s: str) -> None:
            self._insert_into_input(s)

        # a) exakt getroffen → nur Space + Mini-Hilfe
        if prefix in cands:
            if not prefix.endswith(" "):
                insert(" ")
            desc = commands.CMD_DESC.get(prefix)
            if desc:
                self._log_block_wrapped("Befehl", f"{prefix} — {desc}", color=self._CYAN)
            return

        # b) nur Kandidaten nehmen, die mit '-' weitergehen (spezifischere Liste)
        dash_cands = [c for c in cands if c.startswith(prefix + "-")]
        if dash_cands:
            cands = dash_cands

        # c) exakt ein Kandidat → Rest + Space + Mini-Hilfe
        if len(cands) == 1:
            chosen = cands[0]
            rest = chosen[len(prefix) :] + " "
            insert(rest)
            desc = commands.CMD_DESC.get(chosen)
            if desc:
                self._log_block_wrapped("Befehl", f"{chosen} — {desc}", color=self._CYAN)
            return

        # d) mehrere Kandidaten → Longest Common Prefix (nur vom Rest)
        suffixes = [c[len(prefix) :] for c in cands]

        def lcp(strings: list[str]) -> str:
            if not strings:
                return ""
            s1, s2 = min(strings), max(strings)
            i = 0
            for a, b in zip(s1, s2):
                if a != b:
                    break
                i += 1
            return s1[:i]

        common = lcp(suffixes)
        # Bis zum letzten '-' einkürzen, damit z. B. ':attach-' entsteht
        if "-" in common:
            common = common[: common.rfind("-") + 1]

        if common:
            # Was bleibt nach Einfügen noch mehrdeutig?
            still = [c for c in cands if c.startswith(prefix + common)]
            # gemeinsamen Teil einfügen (ggf. trailing '-')
            if common.endswith("-"):
                insert(common)
            else:
                needs_dash = any(c.startswith(prefix + common + "-") for c in cands)
                insert(common + ("-" if needs_dash else ""))
            # Gruppierte Vorschläge (nur wenn es noch mehrere sind)
            if len(still) > 1:
                lines = commands.suggestions_for_prefix(prefix, with_aliases=True)
                text = "\n".join(lines) if lines else "\n".join("  " + s for s in cands)
                self._log_block_wrapped("Autocomplete", text, color=self._CYAN)
        else:
            # kein gemeinsamer Zusatz → gruppierte Vorschläge zeigen
            lines = commands.suggestions_for_prefix(prefix, with_aliases=True)
            text = "\n".join(lines) if lines else "\n".join("  " + s for s in cands)
            self._log_block_wrapped("Autocomplete", text, color=self._CYAN)

    def _as_str(self, x) -> str:
        return x if isinstance(x, str) else str(x)

    def _log_write(self, text) -> None:
        # ⚠️ defensive: chat_view kann theoretisch None sein, wenn sehr früh aufgerufen
        if getattr(self, "_squelch_output", False):
            return
        if not self.chat_view:
            return
        self.chat_view.write(self._as_str(text))

    def _log_write_line(self, text="") -> None:
        if getattr(self, "_squelch_output", False):
            return
        s = self._as_str(text)
        if not self.chat_view:
            return
        if hasattr(self.chat_view, "write_line"):
            self.chat_view.write_line(s)  # type: ignore[attr-defined]
        else:
            self.chat_view.write(s)
            self.chat_view.write("\n")

    # In class ChattiTUI:
    async def _confirm_typed(self, title: str, prompt: str, expect: str) -> bool:
        """
        Zeigt ein Eingabe-Modal und gibt True zurück, wenn der/die User:in
        exakt `expect` eingibt. Bricht bei ESC/Cancel mit False ab.
        """
        try:
            msg = f"{prompt}\n[Tippe exakt: {expect}]"
            val = await self._ask_secret(title, msg)  # nutzt dein SecretPrompt
            return (val or "") == expect
        except Exception:
            return False

    def _blank(self, n: int = 1, spacer: str | None = None) -> None:
        if spacer is None:
            spacer = ""
        for _ in range(max(1, n)):
            self._ui(self._log_write_line, spacer)

    def _line_width(self) -> int:
        try:
            w = int(
                self.chat_view.size.width
            )  # ⚠️ self.chat_view könnte None sein – aber alle Aufrufe passieren nach compose()
        except Exception:
            w = shutil.get_terminal_size().columns
        return max(20, w - 12)

    def _write_wrapped(
        self, text, new_line: bool = True, color: str | None = None, bold: bool = False
    ) -> None:
        if getattr(self, "_squelch_output", False):
            return

        text = self._as_str(text)
        width = self._line_width()

        def paint(s: str) -> str:
            if not color or not self.pretty:
                return s
            return f"{self.ansi_bold if bold else ''}{color}{s}{self.ansi_reset}"

        if new_line:
            for line in text.splitlines() or [""]:
                chunks = textwrap.wrap(
                    line,
                    width=width,
                    break_long_words=False,
                    break_on_hyphens=False,
                    replace_whitespace=False,
                ) or [""]
                for chunk in chunks:
                    self._log_write_line(paint(chunk))
        else:
            self._cur_line += text
            parts = self._cur_line.split("\n")

            for part in parts[:-1]:
                chunks = textwrap.wrap(
                    part,
                    width=width,
                    break_long_words=False,
                    break_on_hyphens=False,
                    replace_whitespace=False,
                ) or [""]
                for chunk in chunks:
                    self._log_write_line(paint(chunk))

            last = parts[-1]
            wrapped = textwrap.wrap(
                last,
                width=width,
                break_long_words=False,
                break_on_hyphens=False,
                replace_whitespace=False,
            )

            if wrapped:
                for chunk in wrapped[:-1]:
                    self._log_write_line(paint(chunk))
                self._cur_line = wrapped[-1]
            else:
                self._cur_line = ""

    def _log_block_wrapped(self, title: str, body: str, color: str | None = None) -> None:
        if getattr(self, "_squelch_output", False):
            return

        if not self.chat_view:
            return
        width = self._line_width()
        sep = "─" * max(10, min(80, width))

        self._log_write_line(f"[reverse] {title} [/reverse]")

        if body:
            for line in body.splitlines() or [""]:
                self._write_wrapped(line, new_line=True, color=color, bold=False)
        else:
            self._log_write_line("(empty)")

        self._log_write_line(sep)
        self._log_write_line("")

    def _history_prev(self) -> None:
        cur_list = self._active_history()
        if not cur_list:
            return

        cur = self._get_user_text()

        if self._hist_pos is None:
            # Draft merken und Einstiegsindex wählen
            self._hist_draft = cur
            start = len(cur_list) - 1
            # Wenn aktueller Text == jüngster History-Eintrag → gleich eine Stufe weiter zurück
            if start >= 0 and cur_list[start] == cur:
                start -= 1
            if start < 0:
                # es gibt nichts älteres → zeig einfach den (einzigen) Eintrag
                start = 0
            self._hist_pos = start
        else:
            if self._hist_pos > 0:
                self._hist_pos -= 1

        self._set_input_text(cur_list[self._hist_pos])

    # ---------------------------------------------------------------------
    # Starting client...
    # ---------------------------------------------------------------------

    def _render_history_on_start(self) -> None:
        """Zeigt vorhandene History-Einträge beim Start im Log an (read-only)."""

        def _finally_show_warnings():
            try:
                self._show_startup_warnings()
            except Exception:
                pass

        # 1) Frisch von Platte laden (defensiv)
        try:
            self.history = load_history_tail(last_n=200) or []
        except Exception as e:
            self._log_block_wrapped(
                "History", f"Load fehlgeschlagen: {type(e).__name__}: {e}", self._YELLOW
            )
            _finally_show_warnings()
            return

        # 2) Falls die Log-View noch nicht gemountet ist, einfach später nochmal versuchen
        if not self.chat_view:
            try:
                # Versuch im nächsten Frame erneut
                self.call_after_refresh(self._render_history_on_start)
            except Exception:
                pass
            _finally_show_warnings()
            return

        # 3) Header nur anzeigen, wenn es Einträge gibt
        if self.history:
            head = [f"{len(self.history)} Einträge geladen."]
            try:
                uid = sec.get_active_uid()
                if uid:
                    hp = user_history_file(uid)
                    if hp.exists():
                        head.append(f"Datei: {hp}")
            except Exception:
                pass
            self._log_block_wrapped("Vorherige Sitzung", " / ".join(head))
        else:
            self._log_block_wrapped("Vorherige Sitzung", "Keine Einträge gefunden.")

        # 4) Einträge rendern …
        try:
            for turn in self.history:
                role = (turn.get("role") or "").lower()
                content = turn.get("content") or ""
                if not content:
                    continue
                if role == "user":
                    self._write_user_message(content)
                else:
                    self._log_write_line(
                        self._c(f"{self.assistant_label}:", self.chat_colour, bold=True)
                    )
                    self._blank()
                    self._write_wrapped(
                        sec.mask_secrets(content),
                        new_line=True,
                        color=self.chat_colour,
                        bold=False,
                    )
                    self._blank()
                    self._blank()
        except Exception as e:
            self._log_block_wrapped(
                "History",
                f"Konnte History nicht rendern: {type(e).__name__}: {e}",
                self._YELLOW,
            )

        # --- Admin: Ticket-Meldung ---
        try:
            uid = sec.get_active_uid()
            if uid and sec.is_admin(uid):
                tickets = sorted(collect_tickets(), key=lambda t: (t[0], str(t[1])))
                if tickets:
                    lines = [f"{t_uid}: {path.name} → {first}" for t_uid, path, first in tickets]
                    self._log_block_wrapped(
                        "Support-Anfragen",
                        "Gefundene Tickets:\n" + "\n".join(lines),
                        color=self._CYAN,
                    )
                else:
                    self._log_block_wrapped(
                        "Support-Anfragen",
                        "Keine offenen Tickets gefunden.",
                        color=self._CYAN,
                    )
        except Exception as e:
            self._log_block_wrapped(
                "Support-Anfragen",
                f"Fehler: {type(e).__name__}: {e}",
                color=self._YELLOW,
            )

        _finally_show_warnings()

    def _history_next(self) -> None:
        cur_list = self._active_history()
        if not cur_list:
            return

        if self._hist_pos is None:
            # Nicht in der History → nichts zu „vorwärtsen“
            return

        if self._hist_pos < len(cur_list) - 1:
            self._hist_pos += 1
            self._set_input_text(cur_list[self._hist_pos])
        else:
            # Ende erreicht → zurück in den Draft
            self._hist_pos = None
            self._set_input_text(self._hist_draft)

    def _set_input_text(self, s: str) -> None:
        w = self.input
        if HAS_TEXTAREA and isinstance(w, TextArea):
            w.text = s
        else:
            w.value = s
        try:
            self.set_focus(self.input)
            self.call_after_refresh(self.action_cursor_end)
        except Exception:
            pass

    def action_exit(self) -> None:
        # optional: little farewell in the log
        try:
            self._log_block_wrapped("Bye", "Chatti wird beendet …")
        except Exception:
            pass
        self.exit()  # Textual: closes the app and cancels workers

    # ---------------------------------------------------------------------
    # UI tree
    # ---------------------------------------------------------------------
    def compose(self) -> ComposeResult:
        yield Header()

        with Horizontal(id="topbar"):
            # Zuerst nur das aktuell gesetzte Modell anzeigen …
            options = [(self.model, self.model)]
            yield Select(options=options, value=self.model, prompt="Modell", id="model_select")
            yield Button("Clear Chat", id="btn_clear")
            yield Static(f"Chatti! {__version__} Model: {self.model}", id="status_model")

        with Vertical(id="content"):
            self.chat_view = Log()
            yield self.chat_view

            with Horizontal(id="controls"):
                if HAS_TEXTAREA:
                    self.input = TextArea(
                        placeholder="Frag mich [TAB-ENTER zum Senden oder : TAB-ENTER für Command-Liste...]", id="input"
                    )
                else:
                    self.input = Input(placeholder="Frag mich...", id="input")

                self.input.add_class("chat")
                self.input.styles.border = ("round", self.chat_border_css)
                yield self.input
                yield Button("Senden", id="btn_send")

        yield Footer()

    async def on_mount(self) -> None:
        # notifier + focus + title
        register_ui_notifier(lambda t, b, c=None: self._ui(self._log_block_wrapped, t, b, c))
        try:
            self.call_after_refresh(lambda: self.set_focus(self.query_one("#input")))
        except Exception:
            pass
        try:
            self._refresh_title_bar()
        except Exception:
            pass

        try:
            uid = sec.get_active_uid()
            cfg = load_config_effective(uid=uid)

            self.boss_passcode = (cfg.get("boss_passcode") or "").strip()
            self.boss_strict = bool(self.boss_passcode)  # nur wenn gesetzt → strict
            self._boss_buffer = ""
        except Exception:
            self.boss_passcode = ""
            self.boss_strict = False

        # History erst nach Refresh rendern (wie gehabt)
        self.call_after_refresh(self._render_history_on_start)

        # Modelle asynchron nachladen und Select auffüllen
        # self._run_async(self._run_doctor_worker(), exclusive=False)

    # ---------------------------------------------------------------------
    # Events
    # ---------------------------------------------------------------------

    @on(Select.Changed, "#model_select")
    def on_model_changed(self, ev: Select.Changed) -> None:
        try:
            value = ev.value  # kann Select.BLANK sein
            if not isinstance(value, str) or not value.strip():
                # Noch keine gültige Auswahl → einfach ignorieren
                return
            set_default_model(value)
            # Optional: in User-conf persistieren
            uid = sec.get_active_uid()
            write_conf_kv_scoped("default_model", value, uid=uid)

            # UI updaten
            self.model = value
            try:
                sel = self.query_one("#model_select", Select)
                sel.value = value
            except Exception:
                pass
            self._refresh_title_bar()
            self._log_block_wrapped("Model", f"✓ Modell gesetzt: {value}", color=self._GREEN)

        except Exception as e:
            self._log_block_wrapped(
                "Model",
                f"✖ Konnte Modell nicht setzen: {type(e).__name__}: {e}",
                color=self._YELLOW,
            )

    @on(Button.Pressed, "#btn_clear")
    def clear_pressed(self) -> None:
        self._reset_history_state()

    @on(Button.Pressed, "#btn_send")
    def send_pressed(self) -> None:
        self._handle_text(self._consume_input())

    async def on_input_submitted(self, message: Input.Submitted) -> None:
        self._clear_input()
        self._refocus_input()
        self._handle_text((message.value or "").strip())

    def action_history_prev(self) -> None:
        if self.focused is self.input:
            self._history_prev()

    def action_history_next(self) -> None:
        if self.focused is self.input:
            self._history_next()

    async def action_boss_toggle_b(self) -> None:
        self._last_boss_trigger = "ctrl+b"
        await self.action_boss_toggle()

    async def action_boss_toggle_g(self) -> None:
        self._last_boss_trigger = "ctrl+g"
        await self.action_boss_toggle()

    async def action_boss_toggle(self) -> None:
        trig = getattr(self, "_last_boss_trigger", None)

        # Einschalten
        if not self._boss_mode:
            self._boss_buffer = ""  # Buffer leeren
            self._boss_key = trig if self.boss_strict else None
            self._toggle_boss_mode()
            return
        # Ausschalten:
        # Wenn Passcode definiert → KEIN Toggle über Tastenkombi, nur via Keystrokes
        if self.boss_passcode:
            # Optional: kurzes Feedback
            self._log_block_wrapped(
                "Boss-Mode", "Passcode tippen zum Entsperren.", color=self._YELLOW
            )
            return

        # Kein Passcode → normales Toggle
        if self.boss_strict and self._boss_key and trig != self._boss_key:
            return
        self._toggle_boss_mode()
        self._boss_key = None

    # History nur, wenn Eingabe fokussiert
    async def on_key(self, event) -> None:
        # Debug (temporär):
        if getattr(self, "debug_keys", False):
            self._debug_key_event(event)

        # --- Quick-Pick für _pending_choice: "Model wählen" ---
        if self._pending_choice and self._pending_choice.get("title") == "Model wählen":
            k = getattr(event, "key", "") or ""
            ch = getattr(event, "character", "") or ""
            ctrl = bool(getattr(event, "ctrl", False))
            alt = bool(getattr(event, "alt", False))
            meta = bool(getattr(event, "meta", False))

            options = self._pending_choice.get("options") or []
            on_select = self._pending_choice.get("on_select")
            maxn = len(options)

            def _apply_and_cleanup(idx1: int) -> None:
                try:
                    if callable(on_select):
                        on_select(idx1 - 1)  # 0-basiert
                except Exception as e:
                    self._log_block_wrapped(
                        "Model",
                        f"Fehler beim Setzen: {type(e).__name__}: {e}",
                        color=self._YELLOW,
                    )
                finally:
                    self._pick_buf = ""
                    self._pending_choice = None

            # ESC → Abbrechen
            if k == "escape":
                self._pick_buf = ""
                self._pending_choice = None
                self._log_block_wrapped("Model", "Abgebrochen.", color=self._YELLOW)
                event.prevent_default()
                event.stop()
                return

            # Hilfsfunktion: Ziffern auch vom Numpad erkennen
            def _extract_digit(key: str, char: str) -> str | None:
                if len(char) == 1 and char.isdigit():
                    return char
                if len(key) == 1 and key.isdigit():
                    return key
                for prefix in ("numpad_", "numpad", "kp"):
                    if key.startswith(prefix):
                        tail = key[len(prefix) :]
                        if tail and tail[0].isdigit():
                            return tail[0]
                return None

            # Ziffer → Buffer erweitern
            d = _extract_digit(k, ch)
            if d is not None and not (ctrl or alt or meta):
                # max. 2 Stellen (1..99)
                self._pick_buf = (self._pick_buf + d)[:2]

                # Sofort anwenden, sobald die Auswahl *entscheidbar* ist:
                # - <10 Optionen: 1 Ziffer genügt
                # - ≥10 Optionen: 2 Ziffern
                buf = self._pick_buf
                if buf.isdigit():
                    idx = int(buf)
                    decisive = (maxn < 10 and len(buf) == 1) or (len(buf) == 2)
                    if decisive and 1 <= idx <= maxn:
                        _apply_and_cleanup(idx)
                        event.prevent_default()
                        event.stop()
                        return

                event.prevent_default()
                event.stop()
                return

            # Backspace → letzte Ziffer löschen
            if k == "backspace":
                self._pick_buf = self._pick_buf[:-1]
                event.prevent_default()
                event.stop()
                return

            # Enter/Return/Space/Tab → Auswahl (falls möglich) anwenden
            if k in ("enter", "return", "space") or ch in ("\r", "\n", " "):
                buf = self._pick_buf
                if not buf or not buf.isdigit():
                    self._log_block_wrapped(
                        "Model", "Bitte zuerst Nummer tippen.", color=self._YELLOW
                    )
                    event.prevent_default()
                    event.stop()
                    return
                idx = int(buf)
                if not (1 <= idx <= maxn):
                    self._log_block_wrapped(
                        "Model", f"Ungültige Nummer (1..{maxn}).", color=self._YELLOW
                    )
                    event.prevent_default()
                    event.stop()
                    return
                _apply_and_cleanup(idx)
                event.prevent_default()
                event.stop()
                return

            # TAB / Shift+TAB → durchlassen (kein prevent_default), damit Fokus wechselt
            if k in ("tab", "shift+tab"):
                # nichts tun: Fokuswechsel soll stattfinden
                return

        # --- Ende Quick-Pick "Model wählen" ---

        # --- Boss-Mode Keystroke-Exit ---
        if self._boss_mode and self.boss_passcode:
            ch = getattr(event, "character", "") or ""
            ctrl = bool(getattr(event, "ctrl", False))
            alt = bool(getattr(event, "alt", False))
            meta = bool(getattr(event, "meta", False))

            # nur „einfache“ druckbare Zeichen berücksichtigen
            if ch and len(ch) == 1 and not (ctrl or alt or meta):
                self._boss_buffer = (self._boss_buffer + ch)[-len(self.boss_passcode) :]
                if self._boss_buffer == self.boss_passcode:
                    # richtiger Code getippt → Boss-Mode beenden
                    try:
                        self.pop_screen()
                    except Exception:
                        pass
                    self._boss_mode = False
                    self._squelch_output = False
                    self._boss_buffer = ""
                    try:
                        self._repaint_history_tail(n=50)
                    except Exception:
                        pass
                    self._ui(self._refresh_title_bar)
                    event.prevent_default()
                    event.stop()
                    return

            # optional: mit ESC den Buffer leeren
            if getattr(event, "key", "") == "escape":
                self._boss_buffer = ""
                event.prevent_default()
                event.stop()
                return
        # --- Ende Boss-Mode Keystroke-Exit ---

        # --- robuste Erkennung für Ctrl+F ---
        k = getattr(event, "key", "")
        ch = getattr(event, "character", "")
        ctl = bool(getattr(event, "ctrl", False))

        if k == "ctrl+f" or ch == "\x06" or (k == "right" and ctl) or (ctl and k == "f"):
            event.prevent_default()
            event.stop()
            self._enter_search_mode()
            return

        if self.mode == "search" and self.focused is self.input:
            if event.key == "enter":
                event.prevent_default()
                event.stop()
                q = (self._get_user_text() or "").strip()
                if not q:
                    self._clear_input()
                    self.set_focus(self.input)
                    return

                # --- NEU: Kommandos im Suchmodus zuerst abfangen ---
                low = q.lower()
                # Kurzform :N
                if q.startswith(":") and q[1:].isdigit():
                    self._cmd_goto(q[1:])
                    self._clear_input()
                    self.set_focus(self.input)
                    return
                # Vollform :goto N / /goto N
                if low.startswith(":goto") or low.startswith("/goto"):
                    parts = q.split(maxsplit=1)
                    arg = parts[1].strip() if len(parts) > 1 else ""
                    self._cmd_goto(arg)
                    self._clear_input()
                    self.set_focus(self.input)
                    return
                # Allgemeine Kommandos (beginnend mit ':' oder '/'): an _handle_text delegieren
                if q.startswith(":") or q.startswith("/"):
                    # optional: History als Command speichern
                    try:
                        self._history_push(q, kind="cmd")
                    except Exception:
                        pass
                    self._handle_text(q)
                    self._clear_input()
                    self.set_focus(self.input)
                    return
                # --- Ende NEU ---

                # Normale Suche
                try:
                    self._history_push(q, kind="search")
                except Exception:
                    pass
                self._do_search(q)
                self._clear_input()
                self.set_focus(self.input)
                self._hist_pos = None
                self._hist_draft = ""
                return

            # if event.key == "enter":
            #     event.prevent_default(); event.stop()
            #     q = self._get_user_text().strip()
            #     if q:
            #         self._history_push(q, kind="search")
            #     self._do_search(q)
            #     self.set_focus(self.input)
            #     self._clear_input()
            #     self._hist_pos = None
            #     self._hist_draft = ""
            #     self.set_focus(self.input)
            #     return
            if event.key == "escape":
                event.prevent_default()
                event.stop()
                self._exit_search_mode()
                return

        if self.focused is self.input:
            key = getattr(event, "key", "")
            mods = set(getattr(event, "modifiers", ()))
            is_shift = "shift" in mods

            #             key = getattr(event, "key", "")
            #             is_shift = bool(getattr(event, "shift", False))

            if HAS_TEXTAREA and isinstance(self.input, TextArea):
                # TextArea:
                #   Enter          → senden
                #   Shift+Enter    → neue Zeile
                if key == "enter" and not is_shift:
                    event.prevent_default()
                    event.stop()
                    self._handle_text(self._consume_input())
                    return
                if key == "enter" and is_shift:
                    event.prevent_default()
                    event.stop()
                    # TextArea hat meist insert(); fallback auf text-Append
                    if hasattr(self.input, "insert"):
                        self.input.insert("\n")
                    else:
                        self.input.text = (self.input.text or "") + "\n"
                    return
            else:
                # Einfaches Input:
                #   Enter          → senden
                #   Shift+Enter    → neue Zeile einfügen
                if key == "enter" and is_shift:
                    event.prevent_default()
                    event.stop()
                    self.input.value = (self.input.value or "") + "\n"
                    return
                if key == "enter":
                    event.prevent_default()
                    event.stop()
                    self._handle_text(self._consume_input())
                    return

        # --- Command Autocomplete: Alt+Right oder Ctrl+Right ---
        if self.focused is self.input and event.key in ("alt+right", "ctrl+right"):
            # Nur wenn Feld wie ein (Teil-)Kommando aussieht (z.B. ":att")
            txt = self._get_user_text()
            if txt and (txt.startswith(":") or txt.startswith("/")):
                # Nur „ein Wort“: keine Leerzeichen => klassischer Kommandoanfang
                if " " not in txt and txt.strip():
                    event.prevent_default()
                    event.stop()
                    self._autocomplete_command()  # existierende Funktion nutzen
                    return
        # --- Ende Autocomplete ---

        # History (nur wenn Eingabe fokussiert)
        if self.focused is self.input:
            if event.key == "up":
                event.prevent_default()
                event.stop()
                self._history_prev()
                return
            if event.key == "down":
                event.prevent_default()
                event.stop()
                self._history_next()
                return

    # ---------------------------------------------------------------------
    # Handle Attachments
    # ---------------------------------------------------------------------
    def _plural_word(
        self, n: int, singular: str, plural: str | None = None, zero: str | None = None
    ) -> str:
        """
        Gibt für n das passende Wort zurück.
        - singular: "Datei"
        - plural:   "Dateien" (optional)
        - zero:     Spezialform für 0 (optional), z.B. "keine Dateien"
        """
        if n == 0 and zero is not None:
            return zero
        if n == 1:
            return singular
        if plural is not None:
            return plural
        if singular.endswith("e"):
            return singular + "n"  # Karte -> Karten
        if singular.endswith("s"):
            return singular  # Logs -> Logs
        return singular + "en"  # Datei -> Dateien (Fallback)

    def _fmt_count(self, n, singular, plural=None, zero=None):
        if n == 0 and zero is not None:
            return zero
        num = str(n)
        return f"{num} {self._plural_word(n, singular, plural, zero)}"

    def _cmd_attach_add(self, args: str) -> None:
        # 0) robust tokenisieren (respektiert Quotes)
        try:
            tokens = shlex.split((args or "").strip())
        except ValueError as e:
            self._log_block_wrapped("Attach/Add", f"Argumente unklar (Quotes?): {e}")
            return

        if not tokens:
            self._log_block_wrapped(
                "Attach/Add",
                "Bitte Pfad/Pfade angeben: :attach-add <pfad> [weitere …] "
                "[--tag t] [--note txt] [--alias name]",
            )
            return

        # 1) Alle Pfad-Token bis zum ersten --flag einsammeln
        path_tokens: list[str] = []
        i = 0
        for i, tok in enumerate(tokens):
            if tok.startswith("--"):
                break
            path_tokens.append(tok)
        else:
            i += 1  # falls keine Flags vorhanden

        # → jedes Token ist EIN Pfad (Leerzeichen wären gequotet)
        paths = [str(normalize_user_path(p)) for p in path_tokens if p.strip()]
        if not paths:
            self._log_block_wrapped("Attach/Add", "Pfad fehlt.")
            return

        # 2) optionale Flags parsen
        tags: list[str] = []
        note: str | None = None
        alias: str | None = None
        while i < len(tokens):
            tok = tokens[i]
            if tok == "--tag" and i + 1 < len(tokens):
                tags.append(tokens[i + 1])
                i += 2
                continue
            if tok == "--note" and i + 1 < len(tokens):
                note = tokens[i + 1]
                i += 2
                continue
            if tok == "--alias" and i + 1 < len(tokens):
                alias = tokens[i + 1]
                i += 2
                continue
            i += 1  # unbekanntes Flag ignorieren

        # 3) alle hinzufügen (pro Pfad ein Eintrag)
        added_lines: list[str] = []
        multi = len(paths) > 1
        added_count = 0
        error_count = 0

        for idx, src_path in enumerate(paths, start=1):
            alias_eff = f"{alias}-{idx}" if (alias and multi) else alias
            try:
                meta = add_attachment(src_path, alias=alias_eff, tags=tags or None, note=note)
                self.attach_queue.append(meta["id"])
                added_count += 1
                line = [
                    f"✅ {meta.get('name', '?')}  (id: {meta.get('id', '?')})",
                    f"   MIME: {meta.get('mime', '?')}  Größe: {meta.get('size', 0)} B  "
                    f"SHA-256: {str(meta.get('sha256', ''))[:16]}…",
                ]
                if meta.get("tags"):
                    line.append("   Tags: " + ", ".join(meta["tags"]))
                if meta.get("note"):
                    line.append("   Notiz: " + meta["note"])
                added_lines.append("\n".join(line))

            except AttachmentValidationError as e:
                error_count += 1
                pretty = os.path.basename(str(e.path))
                added_lines.append(
                    f"❌ {pretty}: Datei wirkt nicht wie ein echtes {e.ext.upper()}.\n"
                    "   Bitte als echtes Format exportieren (korrekter Datei-Header erforderlich)."
                )

            except Exception as e:
                error_count += 1
                added_lines.append(f"❌ {src_path} → Fehler: {type(e).__name__}: {e}")

        # Footer/Title dynamisch formulieren
        einheiten = self._plural_word(added_count, "Datei", "Dateien")
        footer = (
            "\n→ Nichts angeheftet."
            if added_count == 0
            else f"\n→ Für die nächste Nachricht {added_count} {einheiten} angeheftet. "
            f"(Gesamt in Queue: {len(self.attach_queue)})"
        )

        if error_count == 0 and added_count > 0:
            title = "Attach/Add"
        elif added_count > 0 and error_count > 0:
            title = "Attach/Add (teilweise Fehler)"
        else:
            title = "Attach/Add (Fehler)"

        self._log_block_wrapped(title, "\n\n".join(added_lines) + footer)

    def _cmd_attach_list(self, args: str) -> None:
        q = (args or "").strip().lower()
        kind = None
        if q in ("images", "image", "img"):
            kind = "image/"
        elif q in ("text", "txt"):
            kind = "text/"
        elif q in ("audio",):
            kind = "audio/"
        elif q in ("video",):
            kind = "video/"

        try:
            items = list_attachments(kind)
            items = [m for m in items if not m.get("deleted") and m.get("name")]

            if not items:
                self._log_block_wrapped("Attachments", "Keine Anhänge vorhanden.")
                return

            lines = [f"{len(items)} Anhang/Anhänge:"]
            for idx, m in enumerate(items, start=1):
                mid = m.get("id", "?")
                mime = m.get("mime", "?")
                name = m.get("name", "?")
                size = m.get("size", 0)
                mark = " (angeheftet)" if mid in self.attach_queue else ""
                lines.append(f"[{idx:>2}] {mid}  {mime:<12}  {name}  {size} B{mark}")

            self._log_block_wrapped("Attachments", "\n".join(lines))
            # Merkhilfe für @N
            self._last_list_cache = items  # << cache für @N (siehe unten)
        except Exception as e:
            self._log_block_wrapped("Attachments", f"Fehler: {type(e).__name__}: {e}")

    def _cmd_attach_clear(self) -> None:
        n = len(self.attach_queue)
        self.attach_queue.clear()
        self._log_block_wrapped(
            "Attach/Clear",
            f"{n} Anhang/Anhänge aus der Queue entfernt (Dateien nicht gelöscht).",
        )

    def _cmd_attach_purge(self, args: str, force: bool) -> None:
        """Purge der Attachments. Nur bei force=True (via '!') ausführen."""
        mode = "hard" if "hard" in (args or "").lower() else "soft"

        if not force:
            self._log_block_wrapped(
                "Attachments",
                "Zur Sicherheit ohne Bestätigung deaktiviert.\n"
                "Nutze:\n"
                "  :attach-purge!        (soft: Dateien + Manifest leeren)\n"
                "  :attach-purge hard!   (hard: Ordner komplett neu anlegen)",
            )
            return

        try:
            affected = purge_attachments(mode=mode)
            self.attach_queue.clear()
            human = "HARD (Ordner neu)" if mode == "hard" else "soft"
            self._log_block_wrapped(
                "Attachments", f"Bereinigt [{human}]. {affected} Datei(en) entfernt."
            )
        except Exception as e:
            self._log_block_wrapped("Attachments", f"Fehler bei purge: {type(e).__name__}: {e}")

    def _cmd_attach_use(self, args: str) -> None:
        parts = [p for p in (args or "").split() if p.strip()]
        if not parts:
            self._log_block_wrapped(
                "Attach/Use", "Nutze: :attach-use <id|name|last|@N> [weitere …]"
            )
            return
        metas = self._resolve_attachment_selectors(parts)
        if not metas:
            return
        added = 0
        for m in metas:
            aid = m["id"]
            if aid not in self.attach_queue:
                self.attach_queue.append(aid)
                added += 1
        self._log_block_wrapped(
            "Attach/Use",
            f"{added} Anhang/Anhänge angeheftet. (Gesamt: {len(self.attach_queue)})",
        )

    def _cmd_attach_unuse(self, args: str) -> None:
        parts = [p for p in (args or "").split() if p.strip()]
        if not parts:
            self._log_block_wrapped(
                "Attach/Unuse", "Nutze: :attach-unuse <id|name|last|@N> [weitere …]"
            )
            return
        metas = self._resolve_attachment_selectors(parts)
        if not metas:
            return
        ids = {m["id"] for m in metas}
        before = len(self.attach_queue)
        self.attach_queue = [x for x in self.attach_queue if x not in ids]
        removed = before - len(self.attach_queue)
        self._log_block_wrapped(
            "Attach/Unuse",
            f"{removed} entfernt. (Verbleibend: {len(self.attach_queue)})",
        )

    def _cmd_goto(self, args: str) -> None:
        """Springt im Suchmodus zu einem der letzten Suchtreffer: :goto N oder :N"""
        # Vorbedingung: Treffer vorhanden?
        hits = getattr(self, "_last_search_hits", None) or []
        if not hits:
            self._log_block_wrapped(
                "🔎 Suche",
                "Kein Suchergebnis im Speicher. Erst suchen, dann :goto N.",
                self._YELLOW,
            )
            return

        n_str = (args or "").strip()
        if not n_str.isdigit():
            self._log_block_wrapped("🔎 Suche", "Nutze: :goto N  (oder kurz :N)", self._YELLOW)
            return

        n = int(n_str)
        if not (1 <= n <= len(hits)):
            self._log_block_wrapped("🔎 Suche", f"Ungültige Nummer (1..{len(hits)}).", self._YELLOW)
            return

        hit = hits[n - 1]
        idx = hit.get("idx", -1)
        if idx < 0:
            self._log_block_wrapped(
                "🔎 Suche",
                "Interner Treffer ohne Index – kann nicht springen.",
                self._YELLOW,
            )
            return

        # komplette History laden & Item + Kontext rendern
        try:
            uid = sec.get_active_uid()
            hist = load_history(uid=uid)
        except Exception as e:
            self._log_block_wrapped(
                "🔎 Suche", f"History-Ladefehler: {type(e).__name__}: {e}", self._YELLOW
            )
            return

        if not (0 <= idx < len(hist)):
            self._log_block_wrapped(
                "🔎 Suche", "Trefferindex außerhalb des Bereichs.", self._YELLOW
            )
            return

        cur = hist[idx]
        prev = hist[idx - 1] if idx > 0 else None
        nxt = hist[idx + 1] if idx + 1 < len(hist) else None

        # Zeitformat hübsch
        def _fmt_ts(ts: str) -> str:
            try:
                if ts and ts.endswith("Z"):
                    dt = datetime.datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone()
                else:
                    dt = datetime.datetime.fromisoformat(ts).astimezone()
                return dt.strftime("%Y-%m-%d %H:%M:%S")
            except Exception:
                return ts or ""

        blocks = []
        if prev:
            blocks.append(
                f"[dim]{_fmt_ts(prev.get('ts', ''))}  {prev.get('role', '')}>[/dim]\n{prev.get('content', '')}"
            )
        blocks.append(
            f"[b]{_fmt_ts(cur.get('ts', ''))}  {cur.get('role', '')}>[/b]\n{cur.get('content', '')}"
        )
        if nxt:
            blocks.append(
                f"[dim]{_fmt_ts(nxt.get('ts', ''))}  {nxt.get('role', '')}>[/dim]\n{nxt.get('content', '')}"
            )

        # head = f"🔎 Treffer {n}/{len(hits)} – „{getattr(self, '_last_search_query', '')}“"
        # self._log_block_wrapped(head, "\n\n".join(blocks), self.search_colour)

        head = f"🔎 Treffer {n}/{len(hits)} – „{getattr(self, '_last_search_query', '')}“"

        # --- optische Hervorhebung robust ---
        try:
            width = max(40, min(100, getattr(self, "_line_width", lambda: 80)()))
        except Exception:
            width = 80

        sep = "═" * width
        # Farben bewusst über _log_block_wrapped, nicht _log_write_line
        self._log_block_wrapped("", sep, self.search_colour)
        self._log_block_wrapped(head, "\n\n".join(blocks), self.search_colour)
        self._log_block_wrapped("", sep, self.search_colour)
        self._log_write_line("")

        # Auto-Scroll ans Ende
        try:
            if getattr(self, "chat_view", None):
                if hasattr(self.chat_view, "scroll_end"):
                    self.chat_view.scroll_end(animate=False)  # Textual Log
                elif hasattr(self.chat_view, "scroll_to_end"):
                    self.chat_view.scroll_to_end()  # Fallback ältere Varianten
        except Exception:
            pass

        # Fokus zurück ins Eingabefeld (Komfort)
        try:
            self.set_focus(self.input)
        except Exception:
            pass

    def _cmd_usage(self, args: str) -> None:
        """
        :usage               → zeigt lokale Monats-Summe (Tokens) des aktiven Users
        :usage remote        → fragt zusätzlich die OpenAI Usage-API ab (Monatsstand)
        :usage remote models → wie oben + Aufschlüsselung pro Modell
        """
        want_remote = False
        want_models = False

        q = (args or "").strip().lower()
        if q:
            parts = q.split()
            want_remote = "remote" in parts
            want_models = "models" in parts

        # 1) Lokale Summen (monatlich, ab Tag 1)
        try:
            s_in, s_out, s_tot = sum_month()
            lines = [
                "Lokale Nutzungs-Summe (dieser Monat):",
                f"  tokens in: {s_in:,}",
                f"  tokens out: {s_out:,}",
                f"  tokens total: {s_tot:,}",
            ]
        except Exception as e:
            lines = [f"Lokale Nutzungs-Summe konnte nicht gelesen werden: {type(e).__name__}: {e}"]

        # 2) Optional: Remote (OpenAI Usage-API)
        if want_remote:
            lines.append("")  # Leerzeile
            try:
                rep = fetch_usage_month_to_date()
                t = rep["total"]
                lines.extend(
                    [
                        f"Remote (OpenAI) {rep['start_date']} … {rep['end_date']}:",
                        f"  tokens in: {t['input_tokens']:,}",
                        f"  tokens out: {t['output_tokens']:,}",
                        f"  tokens total: {t['total_tokens']:,}",
                        # falls du Kosten vermeiden willst, lass die nächste Zeile einfach weg
                        f"  (Kosten USD, nur Info): {t['cost_usd']:.6f}",
                    ]
                )
                if want_models and rep.get("by_model"):
                    lines.append("")
                    lines.append("  pro Modell:")
                    bym = rep["by_model"]
                    # sortiert nach total_tokens absteigend
                    for m, v in sorted(
                        bym.items(), key=lambda kv: -int(kv[1].get("total_tokens", 0))
                    ):
                        lines.append(
                            f"   - {m}: tokens={int(v.get('total_tokens', 0)):,} "
                            f"(in {int(v.get('input_tokens', 0)):,} / out {int(v.get('output_tokens', 0)):,})"
                        )
            except Exception as e:
                lines.append(f"Remote (OpenAI) nicht verfügbar: {type(e).__name__}: {e}")

        self._log_block_wrapped("Usage", "\n".join(lines))

    def _cmd_usage_reset(self, _args: str) -> None:
        """Setzt nur die *Session*-Zähler zurück (Monat/History bleiben unverändert)."""
        try:
            # Session-Kosten/Zähler zurücksetzen (defensiv initialisieren)
            if not hasattr(self, "cost_session") or self.cost_session is None:
                self.cost_session = 0.0
            else:
                self.cost_session = 0.0

            # Letzte Turn-Usage optional leeren, damit die Kopfzeile „– – –“ zeigt,
            # bis die nächste Antwort kommt (rein kosmetisch).
            self._last_usage = {}

            # UI informieren
            self._log_block_wrapped(
                "Usage",
                "Session-Zähler zurückgesetzt. Monatsstand bleibt unverändert.",
                color=getattr(self, "_CYAN", None),
            )

            # Titel/Status sofort aktualisieren
            self._ui(self._refresh_title_bar)

        except Exception as e:
            self._log_block_wrapped(
                "Usage",
                f"Fehler beim Zurücksetzen: {type(e).__name__}: {e}",
                color=getattr(self, "_YELLOW", None),
            )

    def _cmd_whoami(self, _args: str) -> None:
        """Zeigt Informationen über den aktuell aktiven Benutzer und seine Pfade an."""
        try:
            uid = sec.get_active_uid()
            if not uid:
                self._log_block_wrapped("whoami", "Kein aktiver Benutzer gesetzt.")
                return

            # Anzeigename ggf. mit Master freischalten
            master = os.environ.get("CHATTI_MASTER")
            _uid, name = sec.get_active_user_display(master=master)

            # Benutzerpfade
            hist = user_history_file(uid)
            atts = user_attachments_files_dir(uid)
            ucfg = user_conf_file(uid)

            # Token-Nutzung aus letzter Session
            u = self._last_usage or {}
            inp = int(u.get("input_tokens", 0) or 0)
            out = int(u.get("output_tokens", 0) or 0)
            tot = int(u.get("total_tokens", 0) or 0)

            lines = [
                f"Aktiver Benutzer: {name or '(Name verborgen – Master nötig)'}  [{uid}]",
                f"Model: {self.model}   tokens in:{inp} out:{out} tot:{tot}",
                "",
                f"History:     {hist}",
                f"Attachments: {atts}",
                f"User-Config: {ucfg}",
            ]
            self._log_block_wrapped("whoami", "\n".join(lines), color=self._CYAN)

        except Exception as e:
            self._log_block_wrapped(
                "whoami",
                f"Fehler: {type(e).__name__}: {e}",
                color=self._YELLOW,
            )

    async def _remove_my_account_async(self) -> None:
        """Löscht den aktiven Benutzer *hart* (non-interactive): Secrets + Dateien.
        Fragt nur das Master-Passwort ab, KEIN 'LÖSCHEN'-Text nötig.
        """
        uid = sec.get_active_uid()
        if not uid:
            self._log_block_wrapped("Konto löschen", "Kein aktiver Benutzer.", color=self._YELLOW)
            return

        # 1) Master-Passwort abfragen & prüfen
        master = await self._ask_secret(
            "Konto löschen", "Master-Passwort zur Bestätigung eingeben:"
        )
        if not master:
            self._log_block_wrapped("Konto löschen", "Abgebrochen.", color=self._YELLOW)
            return

        try:
            # Validiert das Master-Passwort (wirft Exception bei Fehler)
            _ = sec.get_api_key_by_uid(uid, master)
        except Exception:
            self._log_block_wrapped(
                "Konto löschen", "✖ Master-Passwort falsch.", color=self._YELLOW
            )
            return

        # 2) Harte Löschung ohne weitere Prompts – im Thread, damit UI responsiv bleibt
        try:
            await asyncio.to_thread(sec.remove_user_entry_by_uid, uid)
            await asyncio.to_thread(_delete_user_files, uid)
            await asyncio.to_thread(prune_orphan_user_dirs)

            self._log_block_wrapped(
                "Konto löschen",
                f"✓ Benutzer entfernt: {uid}\n• Secrets gelöscht\n• Benutzerdateien entfernt\n• Verwaiste Ordner bereinigt",
                color=self._GREEN,
            )
        except Exception as e:
            self._log_block_wrapped(
                "Konto löschen",
                f"Fehler beim Entfernen: {type(e).__name__}: {e}",
                color=self._YELLOW,
            )
            return

        # 3) Sauber beenden: erst Shell-Abschied *registrieren*, dann Worker canceln, dann exit
        try:
            # 3a) Abschied *nach* UI-Teardown in die Shell schreiben
            def _farewell():
                msg = "Chatti: Tschüss! 👋\n"
                stream = getattr(sys, "__stdout__", None)
                try:
                    if stream:
                        stream.write(msg)
                        stream.flush()
                    else:
                        os.write(1, msg.encode("utf-8", "ignore"))
                except Exception:
                    pass

            self._squelch_output = True
            atexit.register(_farewell)

            # 3b) Laufende Worker abbrechen (robust für verschiedene Textual-Versionen)
            try:
                if hasattr(self, "workers"):
                    try:
                        self.workers.cancel_all()  # Textual >= 0.58
                    except Exception:
                        for w in list(getattr(self.workers, "workers", []) or []):
                            try:
                                w.cancel()
                            except Exception:
                                pass
            except Exception:
                pass

        finally:
            # 3c) App schließen (beendet verbleibende Worker ohnehin)
            self.exit()

    async def _ask_secret(self, title: str, prompt: str) -> str | None:
        dlg = SecretPrompt(title, prompt or "")
        self.push_screen(dlg)  # <— kein wait_for_dismiss, daher kein Worker nötig
        try:
            return await dlg.dismissed  # <— Future des Screens abwarten
        finally:
            self._ui(self._refocus_input)

    async def _ask_text_inline(self, title: str, prompt: str, placeholder: str = "") -> str | None:
        """Fragt Text im normalen Eingabefeld ab (ohne Overlay)."""
        # Info in den Log
        self._log_block_wrapped(title, prompt, color=self._CYAN)
        # Eingabefeld passend herrichten
        old_mode = self.mode
        self.mode = "chat"
        self._swap_input(to_textarea=False, preset="")
        try:
            self.input.placeholder = placeholder or "Eingabe …"
        except Exception:
            pass

        loop = asyncio.get_running_loop()
        fut: asyncio.Future[str | None] = loop.create_future()

        def handler(ev):
            try:
                val = (ev.value or "").strip()
            except Exception:
                val = ""
            if not fut.done():
                fut.set_result(val or None)
            # Feld leeren & Fokus zurück
            self._clear_input()
            self._refocus_input()

        # einmaligen Listener registrieren
        async def wait_submit():
            try:
                self.input._on_input_submitted = handler  # monkey-patch minimal
                return await fut
            finally:
                try:
                    self.input._on_input_submitted = None
                except Exception:
                    pass

        # Hook via on_input_submitted der App abfangen
        orig_on_submit = getattr(self, "on_input_submitted", None)

        async def on_submit_wrapper(message):
            # zuerst unser Future bedienen
            handler(message)
            # optional: ursprüngliches Verhalten weiterreichen (nicht nötig hier)
            return

        self.on_input_submitted = on_submit_wrapper  # type: ignore

        try:
            ans = await fut
            return ans
        finally:
            # Zustand zurücksetzen
            self.on_input_submitted = orig_on_submit  # type: ignore
            self.mode = old_mode
            self._swap_input(to_textarea=(old_mode != "search"), preset="")
            self._refocus_input()

    def _cmd_history_dump(self, args: str, mode: str = "enc") -> None:
        """
        :history-dump-enc  → fragt Dump-Passwort (zweimal), prüft Policy & Gleichheit
        :history-dump-plain→ verlangt Master-Bestätigung (aktiver User)
        """
        ##self.run_worker(self._cmd_history_dump_async(args, mode), exclusive=False)
        self._run_async(self._cmd_history_dump_async(args, mode), exclusive=False)

    async def _cmd_history_dump_async(self, args: str, mode: str = "enc") -> None:
        uid = sec.get_active_uid()
        if not uid:
            self._log_block_wrapped("History", "Kein aktiver Benutzer.", color=self._YELLOW)
            return

        out_path = None
        arg = (args or "").strip()
        if arg.startswith("--out "):
            out_path = arg[6:].strip().strip('"').strip("'")

        dump_kwargs = {"mode": mode, "uid": uid}

        # Zielpfad setzen
        if out_path:
            dst = Path(out_path).expanduser().resolve()
        else:
            # Default: Home-Verzeichnis + sprechender Dateiname
            home = Path.home()
            suffix = "enc" if mode == "enc" else "plain"

            # Zeitstempel im Format yyyy-mm-dd_nn-ss
            ts = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M")
            dst = home / f"chatti_history_dump_{uid}_{ts}.{suffix}.jsonl"
        dump_kwargs["dst"] = dst

        if mode == "enc":
            # Einmalige Master-Bestätigung; wird zugleich als Dump-Schlüssel verwendet
            master = await self._ask_secret(
                "History-Export (verschlüsselt)",
                "Zur Bestätigung Master-Passwort eingeben (wird als Dump-Schlüssel genutzt):",
            )
            if master is None or master == "":
                self._log_block_wrapped("History", "Abgebrochen.", color=self._YELLOW)
                return
            try:
                _ = sec.get_api_key_by_uid(uid, master)
            except Exception:
                self._log_block_wrapped(
                    "History",
                    "✖ Master-Passwort falsch – Export abgebrochen.",
                    color=self._YELLOW,
                )
                return
            dump_kwargs["passphrase"] = master

        elif mode == "plain":
            master = await self._ask_secret(
                "History-Export (Klartext)",
                "Zur Bestätigung Master-Passwort eingeben (Export erfolgt unverschlüsselt!):",
            )
            if master is None or master == "":
                self._log_block_wrapped("History", "Abgebrochen.", color=self._YELLOW)
                return
            try:
                _ = sec.get_api_key_by_uid(uid, master)
            except Exception:
                self._log_block_wrapped(
                    "History",
                    "✖ Master-Passwort falsch – Klartext-Export abgebrochen.",
                    color=self._YELLOW,
                )
                return
            # auch im Plain-Modus die Passphrase mitgeben (für Konsistenz)
            dump_kwargs["passphrase"] = master

        else:
            self._log_block_wrapped("History", f"Unbekannter Modus: {mode}", color=self._YELLOW)
            return

        try:
            res = await asyncio.to_thread(history_dump, **dump_kwargs)
            dst = dump_kwargs.get("dst")

            msg = f"✓ Export erstellt: {dst}"
            if isinstance(res, int):
                msg += f"  ({res} Einträge)"

            self._log_block_wrapped("History", msg, color=self._GREEN)

        except Exception as e:
            self._log_block_wrapped(
                "History",
                f"Fehler beim Export: {type(e).__name__}: {e}",
                color=self._YELLOW,
            )

    async def _cmd_history_import_view(self, args: str) -> None:
        """
        Zeigt eine Vorschau eines History-Dumps (enc oder plain), ohne zu importieren.
        Nutzung:
          :history-import-view /pfad/zur/datei [--full] [--lines=N]
        """
        try:
            # --- Args robust parsen ---
            try:
                toks = shlex.split((args or "").strip())
            except ValueError as e:
                self._log_block_wrapped(
                    "history-import-view",
                    f"Argumente unklar (Quotes?): {e}",
                    color=self._YELLOW,
                )
                return

            if not toks:
                self._log_block_wrapped(
                    "history-import-view",
                    "Bitte Datei angeben: :history-import-view /pfad/zum/dump [--full] [--lines=N]",
                    color=self._YELLOW,
                )
                return

            # Flags lesen
            want_full = any(t.lower() == "--full" for t in toks[1:])
            max_lines = None
            for t in toks[1:]:
                t = t.strip().lower()
                if t.startswith("--lines="):
                    try:
                        max_lines = max(1, int(t.split("=", 1)[1]))
                    except Exception:
                        pass

            # Pfad ist erstes Token
            src = Path(toks[0]).expanduser().resolve()
            if not src.exists() or not src.is_file():
                self._log_block_wrapped(
                    "history-import-view",
                    f"Datei nicht gefunden: {src}",
                    color=self._YELLOW,
                )
                return

            # Datei lesen
            try:
                head = src.read_text(encoding="utf-8", errors="ignore").lstrip("\ufeff").strip()
            except Exception as e:
                self._log_block_wrapped(
                    "history-import-view", f"Fehler beim Lesen: {e}", color=self._YELLOW
                )
                return

            # Auto-Detect enc/plain
            is_enc = False
            doc = None
            try:
                doc = json.loads(head)
                is_enc = isinstance(doc, dict) and doc.get("fmt") == "chatti-hist-v1"
            except Exception:
                is_enc = False

            records: list[dict] = []

            if is_enc:
                # Einmal Passphrase erfragen
                pw = await self._ask_secret(
                    "History-Preview (verschlüsselt)",
                    "Export-Passphrase eingeben (beim Erstellen der *.enc-Datei vergeben):",
                )
                if pw is None or pw == "":
                    self._log_block_wrapped(
                        "history-import-view", "Abgebrochen.", color=self._YELLOW
                    )
                    return

                try:
                    # Entschlüsseln, aber NICHT importieren
                    salt = base64.b64decode(doc["salt_b64"])
                    params = doc.get("scrypt", {"n": 16384, "r": 8, "p": 1, "dklen": 32})
                    raw = _scrypt_derive_key(pw, salt, **params)
                    fkey = base64.urlsafe_b64encode(raw)
                    f = Fernet(fkey)
                    payload = f.decrypt(base64.b64decode(doc["ciphertext_b64"])).decode("utf-8")
                    for line in payload.splitlines():
                        try:
                            rec = json.loads(line)
                            if isinstance(rec, dict) and "role" in rec and "content" in rec:
                                records.append(rec)
                        except Exception:
                            continue
                except Exception:
                    self._log_block_wrapped(
                        "history-import-view",
                        "✖ Falsche Passphrase oder beschädigte Datei.",
                        color=self._YELLOW,
                    )
                    return
            else:
                # Plain JSONL
                for line in head.splitlines():
                    try:
                        rec = json.loads(line)
                        if isinstance(rec, dict) and "role" in rec and "content" in rec:
                            records.append(rec)
                    except Exception:
                        continue

            # Kurzer Kopfblock (Datei, Anzahl, erste 5 Zeilen)
            self._show_preview_block(src, records)

            # Optional: detailierte Vorschau
            if want_full or (max_lines is not None):
                lines = self._render_history_preview(records, None if want_full else max_lines)
                self._log_block_wrapped(
                    "history-import-view (Vorschau)",
                    "\n".join(lines) if lines else "(leer)",
                    color=self._CYAN,
                )

        except Exception as e:
            self._log_block_wrapped(
                "history-import-view",
                f"Unerwarteter Fehler: {type(e).__name__}: {e}",
                color=self._YELLOW,
            )

    def _reset_history_state(self) -> None:
        """Leert persistente History + UI + Session-State konsistent."""
        reset_user_history()
        self.history = []
        if self.chat_view:
            self.chat_view.clear()
        self._log_block_wrapped("History", "Zurückgesetzt.")
        self._block_open = False
        self.cost_session = 0.0
        self._last_usage = None
        self._refresh_title_bar()

    def _cmd_history_reset(self, _args: str) -> None:
        """Command-Variante von 'Clear Chat'."""
        try:
            self._reset_history_state()
        except Exception as e:
            self._log_block_wrapped(
                "History",
                f"Fehler beim Zurücksetzen: {type(e).__name__}: {e}",
                self._YELLOW,
            )

    def _repaint_history_tail(self, n: int = 50, show_header: bool = True) -> None:
        """Malt die letzten n Einträge aus self.history in den Log."""
        try:
            if not getattr(self, "chat_view", None):
                return
            self.chat_view.clear()

            # optional: Header wieder anzeigen
            if show_header:
                try:
                    uid = sec.get_active_uid()
                    head = [f"{len(self.history)} Einträge geladen."]
                    if uid:
                        hp = user_history_file(uid)
                        if hp.exists():
                            head.append(f"Datei: {hp}")
                    self._log_block_wrapped("Vorherige Sitzung", " / ".join(head))
                except Exception:
                    # Header ist nur Kosmetik – Fehler hier ignorieren
                    pass

            # nur die letzten n Einträge zeigen
            tail = self.history[-n:] if self.history else []
            for rec in tail:
                txt = sec.mask_secrets(rec.get("content", "") or "")
                role = rec.get("role", "assistant")
                color = self.user_colour if role == "user" else self.chat_colour
                # True = Zeilenabschluss, kein Streaming
                self._ui(self._write_wrapped, txt, True, color, False)
            # kosmetik + fokus zurück
            self._blank(1, spacer="\u00a0")
            self._ui(self._refocus_input)
        except Exception:
            pass

    def _render_history_preview(self, records: list[dict], max_lines: int | None = 80) -> list[str]:
        """Baut eine Textliste aus Records. max_lines=None => alles."""
        lines: list[str] = []
        for r in records:
            pref = "U>" if (r.get("role") == "user") else "A>"
            content = r.get("content") or ""
            # Leere Zeilen beibehalten
            chunk = content.splitlines() or [""]
            for ln in chunk:
                lines.append(f"{pref} {ln}")

        if max_lines is not None and len(lines) > max_lines:
            head = lines[:max_lines]
            rest = len(lines) - max_lines
            head.append(f"... und {rest} weitere Zeilen (nutze --full oder --lines=N).")
            return head
        return lines

    def _show_preview_block(self, src: Path, recs: list[dict]) -> None:
        n = len(recs)
        head = []
        for i, r in enumerate(recs[:5], 1):
            txt = (r.get("content") or "").splitlines()[0]
            if len(txt) > 160:
                txt = txt[:160] + "…"
            head.append(f"  {i:2d}) [{r.get('role')}] {txt}")
        more = "" if n <= 5 else f"\n  … und {n - 5} weitere"
        self._log_block_wrapped(
            "history-import-view",
            f"Datei: {src}\nEinträge: {n}\n" + "\n".join(head) + more,
            color=self._CYAN,
        )

    async def _cmd_history_import(self, args: str, *, replace: bool) -> None:
        """
        Importiert eine History-Dump-Datei in den aktiven User:
          - replace=False → anhängen
          - replace=True  → bestehende History ersetzen
        Erkennt enc/plain automatisch; bei enc fragt nach Export-Passphrase (SecretPrompt).
        """
        try:
            uid = sec.get_active_uid()
            if not uid:
                self._log_block_wrapped(
                    "history-import",
                    "Kein aktiver Benutzer gesetzt.",
                    color=self._YELLOW,
                )
                return

            # --- Pfad robust parsen (Quote-sicher) ---
            try:
                toks = shlex.split((args or "").strip())
            except ValueError as e:
                self._log_block_wrapped(
                    "history-import",
                    f"Argumente unklar (Quotes?): {e}",
                    color=self._YELLOW,
                )
                return

            if not toks:
                self._log_block_wrapped(
                    "history-import",
                    "Bitte Datei angeben: :history-import-add /pfad/zum/dump  (oder :history-import-replace …)",
                    color=self._YELLOW,
                )
                return

            path_str = toks[0]
            src = Path(path_str).expanduser().resolve()
            if not src.exists() or not src.is_file():
                self._log_block_wrapped(
                    "history-import", f"Datei nicht gefunden: {src}", color=self._YELLOW
                )
                return

            # --- enc/plain Auto-Detect ---
            try:
                head = src.read_text(encoding="utf-8", errors="ignore").lstrip("\ufeff").strip()
            except Exception as e:
                self._log_block_wrapped(
                    "history-import", f"Fehler beim Lesen: {e}", color=self._YELLOW
                )
                return

            is_enc = False
            doc = None
            try:
                doc = json.loads(head)
                is_enc = isinstance(doc, dict) and doc.get("fmt") == "chatti-hist-v1"
            except Exception:
                is_enc = False

            # --- ggf. Export-Passphrase erfragen + Preflight prüfen ---
            export_pw: str | None = None
            if is_enc:
                export_pw = await self._ask_secret(
                    "History-Import (verschlüsselt)",
                    "Export-Passphrase eingeben (beim Erstellen der *.enc-Datei vergeben):",
                )
                if export_pw is None or export_pw == "":
                    self._log_block_wrapped("history-import", "Abgebrochen.", color=self._YELLOW)
                    return

                # Preflight-Decrypt → sofortige, klare Fehlermeldung bei falscher Passphrase
                try:
                    salt = base64.b64decode(doc["salt_b64"])
                    params = doc.get("scrypt", {"n": 16384, "r": 8, "p": 1, "dklen": 32})
                    raw = _scrypt_derive_key(export_pw, salt, **params)
                    fkey = base64.urlsafe_b64encode(raw)
                    f = Fernet(fkey)
                    _ = f.decrypt(base64.b64decode(doc["ciphertext_b64"]))  # reine Probe
                except Exception:
                    self._log_block_wrapped(
                        "history-import",
                        "✖ Falsche Passphrase oder beschädigte Datei.",
                        color=self._YELLOW,
                    )
                    return
            # --- Import im Thread ausführen ---
            try:
                n = await asyncio.to_thread(
                    history_import,
                    src,
                    uid=uid,
                    export_passphrase=export_pw,
                    replace=replace,
                )
                mode = "ersetzt" if replace else "angehängt"
                msg = f"✓ {n} Einträge {mode}."
                if n == 0:
                    msg += " (Keine gültigen Records gefunden.)"
                self._log_block_wrapped("history-import", msg, color=self._GREEN)

                # UI auffrischen
                try:
                    self.history = load_history_tail(last_n=200, newest_first=False, uid=uid)
                    self._repaint_history_tail(n=50)
                except Exception:
                    pass
                self._ui(self._refresh_title_bar)

            except Exception as e:
                self._log_block_wrapped(
                    "history-import",
                    f"Fehler: {type(e).__name__}: {e}",
                    color=self._YELLOW,
                )

        except Exception as e:
            self._log_block_wrapped(
                "history-import",
                f"Unerwarteter Fehler: {type(e).__name__}: {e}",
                color=self._YELLOW,
            )

    async def _cmd_remove_my_account(self, _args: str) -> None:
        """
        Löscht den AKTIVEN Benutzer vollständig (hard).
        Schritte:
          1) Tipp-Bestätigung („LÖSCHEN“)
          2) Master-Passwort (per SecretPrompt) verifizieren
          3) cli_user_remove(uid, hard=True) im Thread ausführen
        """
        try:
            uid = sec.get_active_uid()
            if not uid:
                self._log_block_wrapped(
                    "Konto löschen", "Kein aktiver Benutzer.", color=self._YELLOW
                )
                return

            # 2) Master-Passwort erfragen und verifizieren (API-Key als Check)
            pw = await self._ask_secret(
                "Konto löschen", "Master-Passwort eingeben (zur Bestätigung):"
            )
            if not pw:
                self._log_block_wrapped("Konto löschen", "Abgebrochen.", color=self._YELLOW)
                return
            try:
                _ = sec.get_api_key_by_uid(uid, pw)  # nur Verifikation
            except Exception:
                self._log_block_wrapped(
                    "Konto löschen", "✖ Master-Passwort falsch.", color=self._YELLOW
                )
                return

            # 3) Hartes Entfernen im Thread
            try:
                await asyncio.to_thread(cli_user_remove, uid, True)
                self._log_block_wrapped(
                    "Konto löschen", "✓ Konto entfernt. Tschüss! 👋", color=self._GREEN
                )
                self.exit()
            except Exception as e:
                self._log_block_wrapped(
                    "Konto löschen",
                    f"Fehler: {type(e).__name__}: {e}",
                    color=self._YELLOW,
                )

        except Exception as e:
            self._log_block_wrapped(
                "Konto löschen",
                f"Unerwarteter Fehler: {type(e).__name__}: {e}",
                color=self._YELLOW,
            )

    def _resolve_attachment_selectors(self, selectors: list[str]) -> list[dict]:
        """Nimmt IDs/Namen/Shortcuts ('last', '@N') und gibt Attachment-Metadaten zurück."""
        out: list[dict] = []
        for sel in selectors:
            s = (sel or "").strip()
            if not s:
                continue
            # @N: Index aus letzter Liste
            if s.startswith("@"):
                try:
                    n = int(s[1:])
                    items = getattr(self, "_last_list_cache", None) or list_attachments()
                    items = [m for m in items if not m.get("deleted") and m.get("name")]
                    if 1 <= n <= len(items):
                        out.append(items[n - 1])
                    else:
                        self._log_block_wrapped("Attach", f"@{n}: Index außerhalb der Liste.")
                except Exception:
                    self._log_block_wrapped("Attach", f"Ungültiger Index-Selektor: {s}")
                continue
            # last: letzter Eintrag im Manifest (der nicht gelöscht ist)
            if s.lower() == "last":
                items = [m for m in list_attachments() if not m.get("deleted") and m.get("name")]
                if items:
                    out.append(items[-1])
                else:
                    self._log_block_wrapped("Attach", "Kein 'last': Liste ist leer.")
                continue
            # id|name normal
            meta = find_attachment(s)
            if meta and not meta.get("deleted"):
                out.append(meta)
            else:
                self._log_block_wrapped("Attach", f"Nicht gefunden: {s}")
        return out

    # ---------------------------------------------------------------------
    # Input helpers / command handling
    # ---------------------------------------------------------------------
    def _consume_input(self) -> str:
        txt = (self._get_user_text() or "").strip()
        self._clear_input()
        self._refocus_input()
        return txt

    # History-Push -> fills up chat-/search-lists
    def _history_push(self, s: str, kind: str | None = None) -> None:
        s = (s or "").rstrip()
        if not s:
            return

        # Art bestimmen: explizit via kind, sonst Modus/Prefix
        if kind is None:
            if s.startswith(("/", ":")):
                kind = "cmd"
            else:
                kind = "search" if self.mode == "search" else "chat"

        target = (
            self._history_search
            if kind == "search"
            else self._history_chat  # chat & cmd landen hier
        )

        if target and target[-1] == s:
            return
        target.append(s)
        if len(target) > self._history_max:
            del target[: -self._history_max]

        # beim neuen Push wird der Cursor-Status zurückgesetzt
        self._hist_pos = None
        self._hist_draft = ""

    def _get_user_text(self) -> str:
        if HAS_TEXTAREA and isinstance(self.input, TextArea):
            return (self.input.text or "").rstrip()
        return (self.input.value or "").rstrip()

    def _clear_input(self) -> None:
        if HAS_TEXTAREA and isinstance(self.input, TextArea):
            self.input.text = ""
        else:
            self.input.value = ""

    def _refocus_input(self) -> None:
        if self.input:
            self.set_focus(self.input)

    def _handle_text(self, text: str) -> None:
        text = (text or "").strip()
        if not text:
            return

        # --- Auswahl-Fallback (wenn Liste "Model wählen" offen ist) ---
        # Greift, wenn Enter/Senden aus dem Eingabefeld kommt (Textual frisst Enter teils vorm on_key)
        if self._pending_choice and self._pending_choice.get("title") == "Model wählen":
            if text.lower() in (":cancel", "/cancel", "cancel"):
                self._pending_choice = None
                self._pick_buf = ""
                self._log_block_wrapped("Model", "Abgebrochen.", color=self._YELLOW)
                return

            if text.isdigit():
                idx = int(text)
                options = self._pending_choice.get("options") or []
                on_select = self._pending_choice.get("on_select")
                if 1 <= idx <= len(options):
                    try:
                        if callable(on_select):
                            on_select(idx - 1)  # 0-basiert
                    except Exception as e:
                        self._log_block_wrapped(
                            "Model",
                            f"Fehler beim Setzen: {type(e).__name__}: {e}",
                            color=self._YELLOW,
                        )
                    finally:
                        self._pending_choice = None
                        self._pick_buf = ""
                    return
                else:
                    self._log_block_wrapped(
                        "Model",
                        f"Ungültige Nummer (1..{len(options)}).",
                        color=self._YELLOW,
                    )
                    return

            # Nicht-Ziffern bei offener Auswahl nicht ans Modell schicken:
            self._log_block_wrapped(
                "Model",
                "Bitte gib eine gültige Zahl ein (oder :cancel).",
                color=self._YELLOW,
            )
            return
        # --- Ende Auswahl-Fallback ---

        # jeden „echten“ Input merken (Kommandos inklusive)
        self._history_push(text)

        # Kommandos nur behandeln, wenn sie auch wirklich als solche gemeint sind
        if text.startswith(("/", ":")):
            raw_cmd, *rest = text.split(maxsplit=1)
            args = (rest[0] if rest else "").strip()
            token = raw_cmd.rstrip("!").lower()

            # Teil-Kommando ohne Leerzeichen → Autocomplete / Vorschläge statt Chat
            if " " not in raw_cmd:
                # Alle Kommandos mit gleichem Präfix-Zeichen (':' oder '/')
                same_prefix_cmds = [
                    c
                    for c in commands.KNOWN_CMDS
                    if isinstance(c, str) and c.startswith(raw_cmd[0])
                ]
                # EXAKT? Dann NICHT hier abbiegen → später normal dispatchen
                if raw_cmd in same_prefix_cmds:
                    pass
                else:
                    # Präfix-Kandidaten
                    cands = sorted(c for c in same_prefix_cmds if c.startswith(raw_cmd))
                    if cands:
                        # 1) Caret-Autocomplete ausführen
                        self._autocomplete_command()
                        # 2) Feedback ins Log geben
                        if len(cands) > 0:
                            self._log_block_wrapped(
                                "Autocomplete",
                                "Mögliche Fortsetzungen:\n" + "\n".join("  " + s for s in cands),
                                color=self._CYAN,
                            )
                        return
            # --- Ende Teil-Kommando ---
            # Unbekanntes "Kommando" → als normalen Chattext behandeln (damit z. B. ":-)" nicht meckert)
            if token not in commands.KNOWN_CMDS:
                # Im Suchmodus zuerst :goto / :N zulassen, sonst normale Suche
                if self.mode == "search":
                    low = text.lower()

                    # Kurzform ":N" (z.B. ":2") → direkt goto
                    if text.startswith(":") and text[1:].isdigit():
                        self._cmd_goto(text[1:])
                        return

                    # Vollform ":goto N" / "/goto N"
                    if low.startswith(":goto") or low.startswith("/goto"):
                        # Argument extrahieren: alles nach dem ersten Space
                        parts = text.split(maxsplit=1)
                        arg = parts[1].strip() if len(parts) > 1 else ""
                        self._cmd_goto(arg)
                        return

                    # Kein goto → als Suchtext behandeln
                    self._run_search(text)
                    return

            # Ab hier: ECHTE Kommandos dispatchen
            force = raw_cmd.endswith("!") or args.endswith("!")
            cmd = token  # bereits lowercase und ohne '!'

            if cmd in (":attach-add", "/attach-add", ":upload", "/upload"):
                self._cmd_attach_add(args)
                return
            if cmd in (":attach-list", "/attach-list", ":attachments", "/attachments"):
                self._cmd_attach_list(args)
                return
            if cmd in (
                ":attach-clear",
                "/attach-clear",
                ":clearattach",
                "/clearattach",
            ):
                self._cmd_attach_clear()
                return
            if cmd in (
                "/attach-purge",
                ":attach-purge",
                "/attachments-purge",
                ":attachments-purge",
            ):
                self._cmd_attach_purge(args, force=force)
                return
            if cmd in (":attach-use", "/attach-use"):
                self._cmd_attach_use(args)
                return
            if cmd in (":attach-unuse", "/attach-unuse"):
                self._cmd_attach_unuse(args)
                return
            if cmd in ("/doctor", ":doctor"):
                self._run_doctor()
                return
            if cmd in (":exit", "/exit", ":quit", "/quit", ":q", "/q"):
                self._history_chat.clear()
                self._history_search.clear()
                self.action_exit()
                return
            if cmd in (":show-prompt", "/show-prompt"):
                self._log_block_wrapped("System-Prompt", self.system_prompt, color=self._CYAN)
                return
            if cmd in (":usage", "/usage", ":u"):
                self._cmd_usage(args)
                return
            if token in (":usage-reset", "/usage-reset"):
                self._cmd_usage_reset(args)
                return
            if token in (":whoami", "/whoami"):
                self._cmd_whoami(args)
                return
            if token in (":boss", "/boss"):
                # Für strict-Mode merken, dass der Toggle per Command erfolgte
                self._last_boss_trigger = ":boss"
                self.action_boss_toggle()
                return
            if token in (
                ":change-openai-model",
                "/change-openai-model",
                ":model",
                "/model",
            ):
                self._cmd_change_openai_model(args)
                return  # <-- wichtig!
            if token in (":history-reset", "/history-reset"):
                self._cmd_history_reset(args)
                return
            # --- History-Export (plain / enc) ---
            if token in (":history-dump-plain", "/history-dump-plain"):
                self._cmd_history_dump(args, mode="plain")
                return
            if token in (
                ":history-dump-enc",
                "/history-dump-enc",
                ":history-dump",
                "/history-dump",
            ):
                self._cmd_history_dump(args, mode="enc")
                return
            # History: Import (nur ansehen)
            if token in (
                ":history-import-view",
                "/history-import-view",
                ":history-import-viewonly",
                "/history-import-viewonly",
            ):
                # self.run_worker(self._cmd_history_import_view(args), exclusive=False)
                self._run_async(self._cmd_history_import_view(args), exclusive=False)
                return
            # History: Import (ADD)
            if token in (":history-import-add", "/history-import-add"):
                # self.run_worker(self._cmd_history_import(args, replace=False), exclusive=False)
                self._run_async(self._cmd_history_import(args, replace=False), exclusive=False)
                return
            # History: Import (REPLACE)
            if token in (":history-import-replace", "/history-import-replace"):
                # self.run_worker(self._cmd_history_import(args, replace=True), exclusive=False)
                self._run_async(self._cmd_history_import(args, replace=True), exclusive=False)
                return
            # :goto N (im Search-Mode)
            if token in (":goto", "/goto"):
                self._cmd_goto(args)
                return
            # Kurzform :N  (z. B. ":2")
            if token.startswith(":") and token[1:].isdigit():
                self._cmd_goto(token[1:])
                return
            # --- Self delete (bewusst keine Admin-PIN – User löscht sich selbst) ---
            if cmd in (":remove-my-account", "/remove-my-account"):
                self._run_async(self._remove_my_account_async(), exclusive=False)
                return
            # (Theoretisch nicht erreichbar, weil Unbekanntes oben schon als Text durchgeht.)
            return

        # Kein Kommando: Im Suchmodus → Suchlauf; sonst normal chatten.
        if self.mode == "search":
            self._do_search(text)
            return

        self._submit(text)

    def _run_search(self, raw: str) -> None:
        # Defaults
        mode = "and"

        # Config → Limit & Case
        try:
            cfg = load_config_effective(uid=sec.get_active_uid())
        except Exception:
            cfg = {}
        try:
            limit = int(cfg.get("search_limit", 20))
        except Exception:
            limit = 20
        case = (
            bool(as_bool(cfg, "search_case_sensitive", False)) if "as_bool" in globals() else False
        )

        # Präfixe
        text = raw
        for prefix, m in (
            ("rx:", "regex"),
            ("regex:", "regex"),
            ("or:", "or"),
            ("and:", "and"),
        ):
            if raw.lower().startswith(prefix):
                mode = m
                text = raw[len(prefix) :].strip()
                break

        if not text:
            self._log_block_wrapped(
                "🔎 Suche", "leer – bitte Begriffe eingeben", self.search_colour
            )
            return

        # Suche
        try:
            hits = search_history(
                text, mode=mode, case_sensitive=case, limit=limit, with_context=True
            )
            self._last_search_query = text
            self._last_search_hits = hits
        except Exception as e:
            self._log_block_wrapped("🔎 Suche (Fehler)", str(e), self.search_colour)
            return

        n = len(hits or [])
        header = f"🔎 Suche [{mode}{', ci' if not case else ''}] – „{text}“  ({n} Treffer, Limit {limit})"

        if not hits:
            self._log_block_wrapped(header, "Keine Treffer.", self.search_colour)
            return

        # merken für :goto
        self._last_search_query = text
        self._last_search_hits = hits

        # kleine TS-Formatierung → lesbar lokal
        def _fmt(ts: str) -> str:
            try:
                if ts and ts.endswith("Z"):
                    dt = datetime.datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone()
                else:
                    dt = datetime.datetime.fromisoformat(ts).astimezone()
                return dt.strftime("%Y-%m-%d %H:%M")
            except Exception:
                return ts or ""

        # durchnummerieren + TS ausgeben
        lines = []
        for i, rec in enumerate(hits, 1):
            ts = _fmt(rec.get("ts", ""))
            role = rec.get("role", "")
            snip = rec.get("snippet", "")
            lines.append(f"{i:>2}. {ts}  {role}> {snip}")
        # Ausgabe für User...
        lines.append("\nTipp ':N' (z. B. :2) oder ':goto N', um zu diesem Treffer zu springen.")
        self._log_block_wrapped(header, "\n\n".join(lines), self.search_colour)

    def _enter_search_mode(self) -> None:
        self.mode = "search"
        self._swap_input(to_textarea=False, preset="? ")
        self.input.styles.border = ("round", self.search_border_css)
        self._hist_pos = None  # ← neu
        self._hist_draft = ""  # ← neu
        self._log_block_wrapped("🔎 Suchmodus", "Enter = suchen, Esc = zurück", self.search_colour)

    def _exit_search_mode(self) -> None:
        self.mode = "chat"
        self._swap_input(to_textarea=True, preset="")
        self.input.styles.border = ("round", self.chat_border_css)
        self._hist_pos = None  # ← neu
        self._hist_draft = ""  # ← neu
        self._log_block_wrapped("Modus", "Zurück im Chatmodus", self.chat_colour)

    def _do_search(self, raw: str) -> None:
        text = raw.strip()
        if text.startswith("? ") or text.startswith("/ "):
            text = text[2:].strip()
        if not text:
            self._log_block_wrapped("🔎 Suche", "(leer)", self.search_colour)
            return
        self._run_search(text)

    def _swap_input(self, to_textarea: bool, preset: str = "") -> None:
        old = self.input

        if to_textarea:
            if HAS_TEXTAREA:
                new = TextArea(placeholder="Frag mich…", id="input")
                new.text = preset
            else:
                new = Input(placeholder="Frag mich…", id="input")
                new.value = preset
            new.remove_class("search")
            new.add_class("chat")
        else:
            new = Input(placeholder="Suche…", id="input")
            new.value = preset
            new.remove_class("chat")
            new.add_class("search")

        container = old.parent if old is not None else None
        if container is None:
            try:
                container = self.query_one("#controls")
            except Exception:
                container = self

        if old is not None:
            try:
                container.mount(new, before=old)
            except Exception:
                container.mount(new)
            old.remove()
        else:
            container.mount(new)

        self.input = new
        new.styles.border = (
            "round",
            self.search_border_css if self.mode == "search" else self.chat_border_css,
        )
        if self.mode == "search":
            new.styles.background = "rgb(30,30,30)"
        else:
            # nichts setzen = Theme/Default behalten;
            # new.styles.background = "transparent"
            pass
        self.set_focus(self.input)

    def _run_doctor(self) -> None:
        # 1) Sofort User informieren (wird direkt gerendert)
        self._log_block_wrapped(
            "Chatti Doctor",
            "⏳ Diagnose läuft, das dauert ein paar Sekunden …",
            color=self._CYAN,
        )
        # 2) Diagnose asynchron starten (UI bleibt responsiv)
        # self.run_worker(self._run_doctor_worker(), exclusive=False)
        self.run_worker(self._run_doctor_worker(), thread=False, exclusive=False)

    async def _run_doctor_worker(self) -> None:
        buf_out, buf_err = io.StringIO(), io.StringIO()

        try:
            # doctor_main() blockiert → in Thread ausführen
            def _call_doctor():
                with (
                    contextlib.redirect_stdout(buf_out),
                    contextlib.redirect_stderr(buf_err),
                ):
                    return doctor_main()

            exit_code = await asyncio.to_thread(_call_doctor)

        except Exception as e:
            self._log_block_wrapped("Doctor-Fehler", f"{type(e).__name__}: {e}")
            return

        parts = []
        out = buf_out.getvalue().strip()
        err = buf_err.getvalue().strip()
        if out:
            parts.append(out)
        if err:
            parts.append("[stderr]\n" + err)
        parts.append(f"Exit-Code: {exit_code}")

        self._log_block_wrapped("Chatti Doctor", "\n".join(parts))

    # ---------------------------------------------------------------------
    # Chat → API worker
    # ---------------------------------------------------------------------
    def _submit(self, text: str) -> None:
        if not text:
            return

        cmd = text.lstrip()
        if cmd.startswith("? ") or cmd.startswith("/ "):
            self._run_search(cmd[2:].strip())
            return

        if self._block_open:
            self._blank(1, spacer="")
            self._block_open = False

        self._write_user_message(text)

        self._log_write_line(self._c(f"{self.assistant_label}:", self.chat_colour, bold=True))
        self._blank()

        self._cur_line = ""
        self._block_open = True

        save_turn("user", text)
        self.history.append({"role": "user", "content": text})

        attach_ids = list(self.attach_queue)
        self.attach_queue.clear()

        ##self.run_worker(self._do_chat(attach_ids), exclusive=True)
        self._run_async(self._do_chat(attach_ids), exclusive=True)

    async def _do_chat(self, attach_ids: list[str] | None = None):
        assert self.chat_view is not None

        def on_delta(chunk: str):
            safe = sec.mask_secrets(chunk)
            self._ui(self._write_wrapped, safe, False, self.chat_colour, False)

        uid = sec.get_active_uid()  # einmal ermitteln

        try:
            # --- API-Call (in Thread) ---
            full, used_stream, usage = await asyncio.to_thread(
                chat_once,
                self.client,
                self.model,
                self.history,
                self.system_prompt,  # Behaviour of model
                True,  # stream_preferred
                on_delta,
                attach_ids or [],
            )

            # --- Ausgabe rendern ---
            if used_stream:
                if self._cur_line:
                    self._ui(
                        self._write_wrapped,
                        self._cur_line,
                        True,
                        self.chat_colour,
                        False,
                    )
                    self._cur_line = ""
                else:
                    self._ui(self._log_write_line, "")
            else:
                if full.strip():
                    self._ui(
                        self._write_wrapped,
                        sec.mask_secrets(full),
                        True,
                        self.chat_colour,
                        False,
                    )
                else:
                    self._ui(self._log_write_line, "(leer)")

            if full.strip():
                safe_full = sec.mask_secrets(full)
                save_turn("assistant", safe_full)
                self.history.append({"role": "assistant", "content": full})

            # --- State/UI housekeeping ---
            self._block_open = False
            self._blank(1, spacer="\u00a0")
            self._ui(self._refocus_input)

            # --- Usage übernehmen & persistieren ---
            self._last_usage = usage or {}
            try:
                append_usage(self._last_usage, uid=uid)  # pro aktivem User in usage.jsonl
            except Exception as e:
                self._log_write_line(f"[debug] append_usage failed: {e}")

            # --- Budget-Warnung (optional) ---
            try:
                cfg = load_config_effective(uid=uid)
                budget = int(cfg.get("token_budget_per_month", 0) or 0)
                warnpct = float(cfg.get("token_budget_warn_pct", 0.8) or 0.8)
                reset_day = int(cfg.get("token_budget_reset_day", 1) or 1)
                if budget > 0:
                    _, _, stot = sum_month(uid=uid, month_start_day=reset_day)
                    frac = stot / float(budget)
                    if frac >= warnpct:
                        pct = int(round(frac * 100))
                        self._log_block_wrapped(
                            "Budget",
                            f"Monatliche Token-Nutzung: {stot} / {budget} ({pct}%).",
                            color=self._YELLOW,
                        )
            except Exception:
                pass

        except Exception as e:
            # Harte Fehler freundlich melden, ohne die UI zu killen
            self._log_block_wrapped("Fehler", f"{type(e).__name__}: {e}", self._YELLOW)

        finally:
            # Header/Status immer aktualisieren
            self._ui(self._refresh_title_bar)

    # ---------------------------------------------------------------------
    # Rendering helpers
    # ---------------------------------------------------------------------
    def _write_user_message(self, user_text: str) -> None:
        safe_text = sec.mask_secrets(user_text or "")  # ✅ Secrets-Redaktion

        # (docstring-String stand hier vor dem Code; für Klarheit verschoben)
        # Render a full user block: header + wrapped lines + spacing.
        lines = safe_text.splitlines()

        self._log_write_line(self._c(f"{self.user_label}:", self.user_colour, bold=True))
        self._blank()

        for line in lines or [""]:
            self._write_wrapped(f"> {line}", new_line=True, color=self.user_colour, bold=False)

        self._blank()
        self._blank()

    def _toggle_boss_mode(self) -> None:
        if not self._boss_mode:
            self._boss_mode = True
            self._squelch_output = True
            if self.boss_strict and self._boss_key:
                hint = f"Drücke {self._boss_key.upper()} oder dein PW, um zurückzukehren."
            else:
                hint = "Drücke Ctrl+B (oder Ctrl+G) um zurückzukehren."
            self.push_screen(BossCover(hint))
        else:
            # Screen schließen & Rendering wieder aktivieren
            try:
                self.pop_screen()
            except Exception:
                pass
            self._boss_mode = False
            self._squelch_output = False
            # Optional: unteren Verlauf neu malen (z. B. letzte 50 Zeilen)
            try:
                self._repaint_history_tail(n=50)
            except Exception:
                pass
            # Statusbar/Titel auffrischen
            self._ui(self._refresh_title_bar)

    # ---------------------------------------------------------------------
    # User may select the preferred OpenAI-Modell
    # ---------------------------------------------------------------------

    def _pretty_model_label(self, mid: str) -> str:
        # Optional: compact labels for display
        return mid

    async def _ask_text(self, title: str, prompt: str, placeholder: str = "") -> str | None:
        return await self._ask_text_inline(title, prompt, placeholder)

    def _log_models_list(self, models: list[str], current: str | None) -> None:
        lines = ["Verfügbare Modelle:"]
        for i, m in enumerate(models, 1):
            mark = " (aktuell)" if current and m == current else ""
            lines.append(f"  {i:>2}) {self._pretty_model_label(m)}{mark}")
        self._log_block_wrapped("Model-Auswahl", "\n".join(lines), color=self._CYAN)

    def _sort_models_for_humans(self, mids: list[str], current: str | None) -> list[str]:
        # Light-weight: prefer current first, then “newer” families if present
        prio = [
            "gpt-4.1",
            "gpt-4.1-mini",
            "gpt-4o",
            "gpt-4o-mini",
            "gpt-4",
            "gpt-3.5",
        ]

        def score(m: str) -> tuple[int, str]:
            base = next((i for i, p in enumerate(prio) if m.startswith(p)), 999)
            cur = -1 if current and m == current else 0
            return (cur, base, m)

        return sorted(set(mids), key=score)

    async def _fetch_model_ids(self) -> list[str]:
        return await asyncio.to_thread(lambda: get_reachable_chat_models(self.client, probe=False))

    def _set_model_options(self, options: list[tuple[str, str]]) -> None:
        try:
            sel = self.query_one("#model_select", Select)
        except Exception:
            return
        if hasattr(sel, "set_options"):
            sel.set_options(options)  # Textual ≥ 0.58
        else:
            sel.options = options  # Fallback

    async def _update_model_select(self) -> None:
        ids = await self._fetch_model_ids()
        opts = [(m, m) for m in sorted(set([self.model, *ids]))]
        self._set_model_options(opts)

    # def _write_user_model_conf(self, uid: str, model_id: str) -> None:
    #     conf = user_conf_file(uid)
    #     #_write_kv_in_file(conf, "model", model_id)
    #     write_conf_kv_scoped(key, "model", uid=sec.get_active_uid())

    def _write_user_model_conf(self, uid: str, model_id: str) -> None:
        """Schreibt das aktuelle Modell in die user-spezifische Konfiguration."""
        try:
            from config_loader import write_conf_kv_scoped

            write_conf_kv_scoped("default_model", model_id, uid=uid)
            self._log_block_wrapped("Model", f"✓ Modell gespeichert: {model_id}", color=self._GREEN)
        except Exception as e:
            self._log_block_wrapped(
                "Model",
                f"Fehler beim Schreiben der Konfiguration: {type(e).__name__}: {e}",
                color=self._YELLOW,
            )

    def _refresh_model_in_ui(self, model_id: str) -> None:
        try:
            # Update in-memory model immediately for the session
            self.model = model_id
        except Exception:
            pass
        # Update title bar/status
        self._ui(self._refresh_title_bar)

    def _log_success_change(self, model_id: str) -> None:
        self._log_block_wrapped(
            "Model",
            f"✓ Modell gesetzt auf: {model_id}\n"
            "Hinweis: Wird sofort im Titel angezeigt; dauerhaft in deiner lokalen chatti.conf gespeichert.",
            color=self._GREEN,
        )

    def _parse_choice(self, s: str, models: list[str]) -> str | None:
        s = (s or "").strip()
        if not s:
            return None
        # number?
        if s.isdigit():
            i = int(s)
            if 1 <= i <= len(models):
                return models[i - 1]
        # direct id?
        if s in models:
            return s
        return None

    def _cmd_change_openai_model(self, _args: str) -> None:
        try:
            # Sofortige Info an den User
            self._log_block_wrapped(
                "Modelle",
                "⏳ Suche nutzbare Modelle, das dauert ein paar Sekunden …",
                color=self._CYAN,
            )

            async def _do():
                # 1) Client holen
                try:
                    client = self.client or get_client(non_interactive=True, require_smoke=False)
                except Exception as e:
                    self._log_block_wrapped(
                        "Model",
                        f"Client-Fehler: {type(e).__name__}: {e}",
                        color=self._YELLOW,
                    )
                    return

                # 2) Doctor-Liste ziehen (nur Reachability, keine Tokens) und auf OK filtern
                try:
                    rows = await asyncio.to_thread(
                        diagnose_models,
                        client,
                        probe=False,
                        timeout=2.0,
                        max_models=200,
                    )
                except Exception as e:
                    self._log_block_wrapped(
                        "Model",
                        f"Diagnose fehlgeschlagen: {type(e).__name__}: {e}",
                        color=self._YELLOW,
                    )
                    return

                ok_ids = [mid for (mid, status, _hint) in rows if status == "OK"]
                if not ok_ids:
                    self._log_block_wrapped(
                        "Model", "Keine nutzbaren Modelle gefunden.", color=self._YELLOW
                    )
                    return

                # 3) Sortieren & auf 15 kürzen
                models_all = self._sort_models_for_humans(ok_ids, self.model)
                models_all = models_all[:15]

                # 4) Liste GENAU so loggen, wie sie verwendet wird (wichtig für die Auswahl)
                lines = [f"{i + 1:>3}) {m}" for i, m in enumerate(models_all)]
                self._log_block_wrapped(
                    "Model wählen",
                    "Gib die Nummer ein und klicke auf Senden (oder :cancel):\n\n"
                    + "\n".join(lines),
                    color=self._CYAN,
                )

                # 5) Callback VOR _pending_choice definieren!
                def _apply_selection(index_zero_based: int) -> None:
                    uid = sec.get_active_uid()
                    if not uid:
                        self._log_block_wrapped(
                            "Model",
                            "Kein aktiver Benutzer gesetzt.",
                            color=self._YELLOW,
                        )
                        return
                    if not (0 <= index_zero_based < len(models_all)):
                        self._log_block_wrapped(
                            "Model",
                            "Auswahl außerhalb des Bereichs.",
                            color=self._YELLOW,
                        )
                        return

                    model_id = models_all[index_zero_based]

                    # Persistieren in *User*-Konfig (UID-scoped)
                    try:
                        write_conf_kv_scoped("default_model", model_id, uid=uid)
                    except Exception as e:
                        self._log_block_wrapped(
                            "Model",
                            f"Konfig-Schreiben fehlgeschlagen: {type(e).__name__}: {e}",
                            color=self._YELLOW,
                        )
                        return
                    # Debug: wohin geschrieben?
                    try:
                        cfg_path = user_conf_file(uid)
                        self._log_block_wrapped(
                            "Model", f"(geschrieben in: {cfg_path})", color=self._CYAN
                        )
                    except Exception:
                        pass

                    # Sofort in der Session verwenden + UI aktualisieren
                    try:
                        self.model = model_id
                    except Exception:
                        pass
                    try:
                        sel = self.query_one("#model_select")
                        if hasattr(sel, "value"):
                            sel.value = model_id
                    except Exception:
                        pass

                    self._log_block_wrapped(
                        "Model",
                        f"✓ Modell gesetzt: [b]{model_id}[/b]\n"
                        "(Hinweis: in deiner lokalen chatti.conf gespeichert; wirkt sicher nach Neustart)",
                        color=self._GREEN,
                    )
                    self._ui(self._refresh_title_bar)

                # 6) One-shot-Auswahl aktivieren (keinen Modus wechseln!)
                self._pick_buf = ""  # Buffer reset – wichtig!
                self._pending_choice = {
                    "title": "Model wählen",
                    "options": models_all,  # <- identische Liste wie geloggt
                    "on_select": _apply_selection,
                }

            # Async-Worker starten
            self.run_worker(_do(), thread=False)

        except Exception as e:
            self._log_block_wrapped("Model", f"Fehler: {type(e).__name__}: {e}", color=self._YELLOW)


###################################################
#
# Klasse für die Passwortabfrage
#
###################################################


class SecretPrompt(ModalScreen[str | None]):
    BINDINGS = [
        Binding("enter", "ok", show=False),
        Binding("escape", "cancel", show=False),
        Binding("ctrl+c", "cancel", show=False),
    ]

    def __init__(self, title: str, prompt: str):
        super().__init__()
        self._title = title
        self._prompt = prompt
        # eigenes Future für await self._ask_secret(...)
        self._dismissed_future: asyncio.Future[str | None] | None = None

    @property
    def dismissed(self) -> "asyncio.Future[str | None]":
        if self._dismissed_future is None:
            loop = asyncio.get_running_loop()
            self._dismissed_future = loop.create_future()
        return self._dismissed_future

    def dismiss(self, result: str | None = None) -> None:
        fut = self._dismissed_future
        if fut is not None and not fut.done():
            fut.set_result(result)
        return super().dismiss(result)

    def compose(self) -> ComposeResult:
        with Vertical(id="secret_modal"):
            yield Static(f"[b]{self._title}[/b]")
            yield Static(self._prompt)
            self._in = Input(password=True, placeholder="Passphrase …", id="secret_input")
            yield self._in
            with Horizontal():
                yield Button("OK", id="ok")
                yield Button("Abbrechen", id="cancel")

    async def on_mount(self) -> None:
        self.call_after_refresh(lambda: self.set_focus(self._in))

    def on_button_pressed(self, ev: Button.Pressed) -> None:
        self.dismiss(self._in.value or "" if ev.button.id == "ok" else None)

    def action_ok(self) -> None:
        self.dismiss(self._in.value or "")

    def action_cancel(self) -> None:
        self.dismiss(None)

    def on_input_submitted(self, ev: Input.Submitted) -> None:
        self.dismiss(ev.value or "")


###################################################
#
# Klasse für den Privacy-Mode
#
###################################################


class BossCover(ModalScreen):
    def __init__(self, hint: str = ""):
        super().__init__()
        self._hint = hint or "Drücke Ctrl+B (Ctrl+G) oder dein PW, um zurückzukehren."

    def compose(self) -> ComposeResult:
        # Ein einfacher, sichtbarer Overlay-Hinweis
        with Vertical(id="boss_cover"):
            yield Static(
                f"[b] 😴 Stiller-Mode aktiv[/b]\n\nBildschirm ausgeblendet.\n\n{self._hint}",
                id="boss_text",
            )

    # Keine Keys abfangen – die App-Actions sollen die Tastenkürzel verarbeiten
    def on_key(self, event) -> None:
        pass


if __name__ == "__main__":
    env_model = os.getenv("OPENAI_MODEL")
    if env_model:
        set_default_model(env_model)
    ChattiTUI().run()
