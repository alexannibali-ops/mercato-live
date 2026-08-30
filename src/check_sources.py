#!/usr/bin/env python3
"""check_sources.py — dice quali feed di sources.yaml rispondono davvero.

Da lanciare ogni tanto: i percorsi RSS cambiano senza preavviso e una fonte
morta è una colonna vuota in prima pagina.
"""
import pathlib
import sys

import feedparser
import requests
import yaml

from fetch import USER_AGENT, TIMEOUT  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
cfg = yaml.safe_load((ROOT / "src" / "sources.yaml").read_text())

righe, problemi = [], 0
for s in cfg["sources"]:
    try:
        r = requests.get(s["url"], headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT)
        n = len(feedparser.parse(r.content).entries) if r.ok else 0
        esito = f"HTTP {r.status_code}, {n} voci"
        if not r.ok or n == 0:
            esito += "   ← DA CONTROLLARE"
            problemi += 1
    except Exception as exc:
        esito = f"{exc.__class__.__name__}   ← DA CONTROLLARE"
        problemi += 1
    righe.append(f"  {s['name']:<20} {esito}")

print("\n".join(righe))
print(f"\n{len(cfg['sources']) - problemi}/{len(cfg['sources'])} fonti in salute.")
sys.exit(1 if problemi else 0)
