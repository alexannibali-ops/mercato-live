#!/usr/bin/env python3
"""Controlli sulla catena editoriale. Lancia:  python tests/test_pipeline.py"""
import datetime as dt
import pathlib
import sys

import yaml

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))
from fetch import clean, fingerprint, keyword_score, rank, similar  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
cfg = yaml.safe_load((ROOT / "src" / "sources.yaml").read_text())
KW, ED = cfg["keywords"], cfg["editorial"]
now = dt.datetime.now(dt.timezone.utc)
ok = 0


def check(nome, condizione):
    global ok
    print(f"  {'✓' if condizione else '✗'} {nome}")
    ok += 0 if condizione else 1


def voce(titolo, link, fonte, minuti_fa):
    return {"title": titolo, "link": link, "summary": "", "source": fonte,
            "source_weight": 1.0, "scope": "generalista", "image": "", "id": link,
            "published": (now - dt.timedelta(minutes=minuti_fa)).isoformat()}


print("Pulizia del testo")
check("toglie i tag e le entità HTML", clean("<p>Ciao &amp;  mondo</p>") == "Ciao & mondo")
check("regge il campo vuoto", clean(None) == "")

print("\nSomiglianza fra titoli")
stessa = similar(fingerprint("Juventus, offerta da 34 milioni per Vunèr"),
                 fingerprint("La Juve rilancia: 34 milioni sul tavolo per Vunèr"))
diversa = similar(fingerprint("Juventus, summit con l'agente di Restelli"),
                  fingerprint("Juventus, plusvalenza con la cessione di Baldassin"))
check(f"la stessa notizia supera la soglia ({stessa:.2f} ≥ {ED['dedup_threshold']})",
      stessa >= ED["dedup_threshold"])
check(f"due notizie diverse restano sotto ({diversa:.2f} < {ED['dedup_threshold']})",
      diversa < ED["dedup_threshold"])

print("\nFiltro editoriale")
check("scarta le pagelle", keyword_score({"title": "Le pagelle di Inter-Milan", "summary": ""}, KW) is None)
check("scarta le probabili formazioni",
      keyword_score({"title": "Probabili formazioni del derby", "summary": ""}, KW) is None)
check("scarta il fuori tema", keyword_score({"title": "Il meteo del weekend", "summary": ""}, KW) is None)
check("tiene una trattativa", (keyword_score({"title": "Offerta ufficiale della Juve", "summary": ""}, KW) or 0) > 0)

print("\nCatena completa")
out = rank([
    voce("Inter, chiusura vicina per il centrale Dorigo: visite mediche giovedì", "1", "A", 10),
    voce("Visite mediche giovedì per Dorigo: l'Inter chiude, firma vicina", "2", "B", 25),
    voce("Dorigo-Inter, accordo trovato: visite mediche fissate", "5", "C", 30),
    voce("Inter, il nodo lista UEFA rallenta l'ultimo innesto: serve una cessione", "3", "C", 40),
    voce("Le pagelle di Inter-Milan", "4", "A", 5),
    voce("Juventus, offerta monstre per Rossi: trattativa avviata", "7", "A", 60 * 24 * 9),
], ED, KW)
check("fonde le tre versioni della stessa trattativa", len(out) == 2)
check("registra chi l'ha rilanciata", len(out[0]["also"]) == 2)
check("la notizia corroborata va in apertura", out[0]["id"] == "1")
check("scarta ciò che è fuori finestra temporale", all(o["id"] != "7" for o in out))

print(f"\n{'Tutto a posto.' if ok == 0 else str(ok) + ' controlli falliti.'}")
sys.exit(1 if ok else 0)
