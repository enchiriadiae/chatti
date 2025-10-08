# core/usage.py
from __future__ import annotations

import calendar
import datetime as dt
import json
import os
import sys
import time
from collections import defaultdict
from pathlib import Path

from core.paths import user_data_dir
from core.security import get_active_uid

_USAGE_FN = "usage.jsonl"
_PRUNE_MARK = ".usage_prune_ts"
_PRUNE_INTERVAL_SEC = 6 * 3600  # höchstens alle 6h kürzen

API_BASE = os.getenv("OPENAI_BASE_URL", "https://api.openai.com")
API_KEY  = os.getenv("OPENAI_API_KEY")  # Pflicht
PROJECT  = os.getenv("OPENAI_PROJECT")  # optional, aber empfohlen bei orgs mit Projekten

def _now_ts() -> int:
    return int(time.time())

def _usage_path(uid: str | None = None) -> Path:
    u = uid or get_active_uid()
    if not u:
        raise RuntimeError("Kein aktiver Benutzer für Usage-Log.")
    d = user_data_dir(u)
    d.mkdir(parents=True, exist_ok=True)
    return d / _USAGE_FN

def append_usage(usage: dict, uid: str | None = None) -> None:
    path = _usage_path(uid)
    was_new = not path.exists()
    rec = {
        "ts": _now_ts(),
        "model": usage.get("model", ""),
        "input_tokens": int(usage.get("input_tokens", 0) or 0),
        "output_tokens": int(usage.get("output_tokens", 0) or 0),
        "total_tokens": int(usage.get("total_tokens", 0) or 0),
    }
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    if was_new:
        try:
            os.chmod(path, 0o600)
        except Exception:
            pass
    try:
        prune_usage_log()  # nutzt Config + Throttle intern
    except Exception:
        pass

def prune_usage_log(keep_days: int | None = None, *, throttle: bool = True) -> int:
    """
    Schneidet usage.jsonl auf die letzten `keep_days` zu.
    - Wenn keep_days=None: Wert aus Config (usage_keep_days, Default 120)
    - throttle=True: höchstens alle _PRUNE_INTERVAL_SEC Sekunden (per Markerdatei)
    Gibt die Anzahl der behaltenen Zeilen zurück (nur grob informativ).
    """
    try:
        uid = get_active_uid()
        if not uid:
            return 0
        # keep_days aus Config (falls nicht explizit übergeben)
        if keep_days is None:
            try:
                from config_loader import load_config_effective
                cfg = load_config_effective(uid=uid)
                keep_days = int(cfg.get("usage_keep_days", 120) or 120)
            except Exception:
                keep_days = 120

        p = user_data_dir(uid) / _USAGE_FN
        if not p.exists():
            return 0

        # Deckel via Markerdatei
        if throttle:
            d = p.parent
            mark = d / _PRUNE_MARK
            now = int(time.time())
            try:
                last = int(mark.read_text(encoding="utf-8").strip())
            except Exception:
                last = 0
            if now - last < _PRUNE_INTERVAL_SEC:
                return 0  # zu früh, überspringen

        # Safety: mindestens 1 Tag behalten
        keep_days = max(1, int(keep_days))
        cutoff = int(time.time()) - keep_days * 24 * 3600
        tmp = p.with_suffix(".jsonl.tmp")

        kept = 0
        total = 0
        with p.open("r", encoding="utf-8") as fin, tmp.open("w", encoding="utf-8") as fout:
            for line in fin:
                total += 1
                try:
                    rec = json.loads(line)
                    ts = int(rec.get("ts", 0))
                except Exception:
                    # defekte Zeilen verwerfen
                    continue
                if ts >= cutoff:
                    fout.write(line)
                    kept += 1

        # atomar ersetzen
        tmp.replace(p)

        # Marker aktualisieren NUR wenn gekürzt wurde
        if throttle and kept < total:
            try:
                mark.write_text(str(int(time.time())), encoding="utf-8")
                os.chmod(mark, 0o600)
            except Exception:
                pass

        return kept
    except Exception:
        # defensiv: niemals crasht die App nur wegen Pruning
        return 0

def sum_month(uid: str | None = None, *, month_start_day: int = 1) -> tuple[int, int, int]:
    """
    Summiert input/output/total für den laufenden Abrechnungsmonat (einfacher Cut: ab month_start_day).
    Robust auch für 29/30/31 in kürzeren Monaten.
    """
    path = _usage_path(uid)
    if not path.exists():
        return (0, 0, 0)

    today = dt.date.today()

    # Falls wir vor dem Abrechnungs-Stichtag sind → Vormonat als Startmonat
    if today.day < month_start_day:
        # in den Vormonat springen
        year = today.year if today.month > 1 else today.year - 1
        month = today.month - 1 if today.month > 1 else 12
    else:
        year = today.year
        month = today.month

    # Stichtag an Monatstage anpassen (31 in Feb → 29/28 etc.)
    last_day = calendar.monthrange(year, month)[1]
    start_day = min(max(1, month_start_day), last_day)

    start_dt = dt.datetime(year, month, start_day, 0, 0, 0)
    start_ts = int(start_dt.timestamp())

    s_in = s_out = s_tot = 0
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            if int(rec.get("ts", 0) or 0) >= start_ts:
                s_in  += int(rec.get("input_tokens", 0) or 0)
                s_out += int(rec.get("output_tokens", 0) or 0)
                s_tot += int(rec.get("total_tokens", 0) or 0)
    return (s_in, s_out, s_tot)

def _ymd(d: dt.date) -> str:
    return d.strftime("%Y-%m-%d")

def fetch_usage_month_to_date(project: str | None = PROJECT) -> dict:
    """
    Ruft Monatsverbrauch (seit 1. bis heute) von OpenAI ab.
    """
    # Lazy import: nur wenn Funktion genutzt wird, brauchen wir requests
    try:
        import requests  # noqa: F401
    except Exception as ie:
        raise RuntimeError("Das Paket 'requests' ist nicht installiert (pip install requests).") from ie

    # 👉 ENV zur Laufzeit lesen (statt nur Modulkonstanten)
    api_key  = os.getenv("OPENAI_API_KEY") or API_KEY
    api_base = (os.getenv("OPENAI_BASE_URL") or API_BASE or "https://api.openai.com").rstrip("/")
    proj     = project if project is not None else os.getenv("OPENAI_PROJECT") or PROJECT

    if not api_key:
        raise RuntimeError("OPENAI_API_KEY fehlt in der Umgebung.")

    url = f"{api_base}/v1/usage"

    today = dt.date.today()
    start = today.replace(day=1)
    end   = today

    params = {"start_date": _ymd(start), "end_date": _ymd(end)}
    if proj:
        params["project_id"] = proj

    headers = {"Authorization": f"Bearer {api_key}"}

    try:
        resp = requests.get(url, headers=headers, params=params, timeout=45)    #timeout in sec.
    except Exception as e:
        raise RuntimeError(f"Usage-API nicht erreichbar: {type(e).__name__}: {e}") from e

    if resp.status_code != 200:
        text = resp.text
        if isinstance(text, str) and len(text) > 500:
            text = text[:500] + "…"
        raise RuntimeError(f"Usage-API HTTP {resp.status_code}: {text}")

    data = resp.json()

    total_in  = 0
    total_out = 0
    total_tok = 0
    total_usd = 0.0
    by_model  = defaultdict(lambda: {"input_tokens":0, "output_tokens":0, "total_tokens":0, "cost_usd":0.0})

    # möglichst generisch Liste der Items finden
    items: list = []
    if isinstance(data, dict):
        if isinstance(data.get("data"), list):
            items = data["data"]
        elif isinstance(data.get("daily_costs"), list):
            items = data["daily_costs"]
        else:
            for v in data.values():
                if isinstance(v, list):
                    items.extend(v)

    def _num(x, default=0.0):
        try:
            return float(x)
        except Exception:
            return float(default)

    for it in items:
        model = it.get("model") or it.get("name") or it.get("line_item") or "unknown"
        inp = int(it.get("input_tokens", 0) or it.get("prompt_tokens", 0) or 0)
        out = int(it.get("output_tokens", 0) or it.get("completion_tokens", 0) or 0)
        tot = int(it.get("total_tokens", 0) or (inp + out))

        cost = 0.0
        if "cost" in it and isinstance(it["cost"], dict):
            cost = _num(it["cost"].get("total_cost_usd", it["cost"].get("usd")))
        else:
            cost = _num(it.get("total_cost_usd", it.get("cost_usd", it.get("cost"))))

        total_in  += inp
        total_out += out
        total_tok += tot
        total_usd += cost

        bm = by_model[model]
        bm["input_tokens"]  += inp
        bm["output_tokens"] += out
        bm["total_tokens"]  += tot
        bm["cost_usd"]      += cost

    return {
        "start_date": _ymd(start),
        "end_date":   _ymd(end),
        "total": {
            "input_tokens":  total_in,
            "output_tokens": total_out,
            "total_tokens":  total_tok,
            "cost_usd":      round(total_usd, 6),
        },
        "by_model": dict(by_model),
        "raw": data,
    }

if __name__ == "__main__":
    try:
        rep = fetch_usage_month_to_date()
        print(f"Monatsverbrauch {rep['start_date']} … {rep['end_date']}")
        t = rep["total"]
        print(f"  Tokens: in={t['input_tokens']:,} out={t['output_tokens']:,} tot={t['total_tokens']:,}")
        print(f"  Kosten (USD): {t['cost_usd']:.6f}")
        print("\n  pro Modell:")
        for m, v in sorted(rep["by_model"].items(), key=lambda kv: -kv[1]["total_tokens"]):
            print(f"   - {m}: tokens={v['total_tokens']:,} (in {v['input_tokens']:,} / out {v['output_tokens']:,}), usd={v['cost_usd']:.6f}")
    except Exception as e:
        print(f"Fehler: {e}", file=sys.stderr)
        sys.exit(1)
