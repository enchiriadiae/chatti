from __future__ import annotations

from pathlib import Path


class PDFDepsMissing(RuntimeError):
    """Raised when PDF dependencies (pdf2image/Poppler) are unavailable."""

    pass


def _ensure_pdf_text_deps() -> None:
    try:
        import PyPDF2  # noqa: F401
    except Exception as e:
        raise RuntimeError(
            "PDF-Textunterstützung fehlt: 'PyPDF2' ist nicht installiert.\n"
            "Installiere in deiner aktiven venv:\n"
            "  python -m pip install PyPDF2"
        ) from e


def _ensure_pdf_deps() -> None:
    try:
        import pdf2image  # noqa: F401
    except Exception as e:
        raise PDFDepsMissing(explain_missing_poppler()) from e


def explain_missing_poppler() -> str:
    """
    Kurze, verständliche Erklärung für die TUI, wie man Poppler/pdf2image installiert.
    """
    return (
        "PDF-Bilder können nicht gerendert werden, weil die System-Tools fehlen.\n"
        "\n"
        "Benötigt:\n"
        "  • Python-Paket: pdf2image\n"
        "  • Systemtool: Poppler (liefert 'pdftoppm'/'pdfinfo')\n"
        "\n"
        "Installations-Hinweise:\n"
        "  macOS:\n"
        "    brew install poppler\n"
        "    pip install pdf2image\n"
        "\n"
        "  Ubuntu/Debian:\n"
        "    sudo apt install poppler-utils\n"
        "    pip install pdf2image\n"
        "\n"
        "  Windows:\n"
        "    1) Poppler herunterladen (z. B. 'poppler for windows')\n"
        "    2) ZIP entpacken, Pfad (…\\poppler-XX\\bin) zur PATH-Variablen hinzufügen\n"
        "    3) pip install pdf2image\n"
        "\n"
        "Hinweis: Ohne Poppler gibt es nur einen Textauszug aus dem PDF (falls möglich)."
    )


def pdf_extract_text(
    path: str | Path, max_pages: int | None = None, max_chars: int | None = None
) -> str:
    """
    Einfache Text-Extraktion via PyPDF2.

    Parameter:
      - max_pages:
          * None oder <= 0 → keine Seitenbegrenzung (alle Seiten)
          * > 0            → so viele Seiten maximal
      - max_chars: optionaler harter Cut auf die Gesamtzeichenzahl
    """
    _ensure_pdf_text_deps()
    from PyPDF2 import PdfReader

    p = Path(path).expanduser().resolve()
    if not p.exists():
        raise FileNotFoundError(f"PDF nicht gefunden: {p}")

    reader = PdfReader(str(p))
    n_pages = len(reader.pages)
    stop = n_pages if not max_pages or max_pages <= 0 else max(0, min(n_pages, max_pages))

    chunks: list[str] = []
    for i in range(stop):
        try:
            t = reader.pages[i].extract_text() or ""
        except Exception:
            t = ""
        if t:
            chunks.append(t)
        if max_chars is not None and sum(len(c) for c in chunks) >= max_chars:
            break

    text = "\n\n".join(chunks).strip()

    # weiches Normalisieren von Whitespace
    import re

    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)

    if max_chars is not None and len(text) > max_chars:
        text = text[:max_chars].rstrip() + " …"

    return text


def pdf_pages_to_dataurls(path: str | Path, max_pages: int | None = 2, dpi: int = 144) -> list[str]:
    """
    Rendert Seiten eines PDFs als PNG-`data:`-URLs.

    Verhalten (zusammen mit `chatti.conf`):
      - `pdf_max_pages > 0`  → Seitenlimit aus der Config
      - `pdf_max_pages <= 0` oder nicht gesetzt → alle Seiten (keine Begrenzung)
      - Sicherheitskappen:
          * DPI > 200  → wird auf 200 reduziert
          * Seiten > 10 → wird auf 10 reduziert (Kostenbremse)

    Hinweis: `max_pages`/`dpi` Parameter sind Defaults; Werte aus `chatti.conf`
    überschreiben sie.
    """
    # failsafe _notify (falls TUI keine einbindet)
    try:
        _notify  # type: ignore[name-defined]
    except NameError:

        def _notify(_title: str, _msg: str, color: str | None = None) -> None:
            pass

    from config_loader import load_config

    cfg = load_config("chatti.conf")

    # DPI aus Config, auf 200 kappen
    try:
        dpi_cfg = int(cfg.get("pdf_dpi", dpi))
    except Exception:
        dpi_cfg = 120
    if dpi_cfg > 200:
        _notify("PDF", f"DPI zu hoch ({dpi_cfg}), kappen auf 200.", color="yellow")
        dpi_cfg = 200
    dpi = dpi_cfg

    # Seitenlimit aus Config, 0/None ⇒ alle Seiten; sonst auf 10 kappen
    try:
        cfg_max = cfg.get("pdf_max_pages", max_pages if max_pages is not None else 2)
        cfg_max = int(cfg_max) if cfg_max is not None else None
    except Exception:
        cfg_max = 2

    if cfg_max is None or cfg_max <= 0:
        max_pages = None
    else:
        if cfg_max > 10:
            _notify("PDF", f"Zu viele Seiten ({cfg_max}), kappen auf 10.", color="yellow")
            cfg_max = 10
        if cfg_max < 1:
            cfg_max = 1
        max_pages = cfg_max

    # eigentliche Arbeit
    _ensure_pdf_deps()
    from pdf2image import convert_from_path
    from pdf2image.exceptions import (
        PDFInfoNotInstalledError,
        PDFPageCountError,
        PDFSyntaxError,
    )

    p = Path(path).expanduser().resolve()
    if not p.exists():
        raise FileNotFoundError(f"PDF not found: {p}")

    kwargs = {"dpi": dpi, "first_page": 1}
    if max_pages and max_pages > 0:
        kwargs["last_page"] = max_pages

    try:
        images = convert_from_path(str(p), **kwargs)
    except PDFInfoNotInstalledError as e:
        raise PDFDepsMissing(explain_missing_poppler()) from e
    except (PDFPageCountError, PDFSyntaxError) as e:
        raise ValueError(f"Failed to read PDF '{p.name}': {type(e).__name__}: {e}") from e
    except Exception as e:
        raise RuntimeError(f"Failed to rasterize PDF '{p.name}': {type(e).__name__}: {e}") from e

    out: list[str] = []
    import base64
    import io

    for img in images:
        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True, compress_level=9)
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        out.append(f"data:image/png;base64,{b64}")
    return out
