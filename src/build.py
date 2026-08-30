#!/usr/bin/env python3
"""
build.py — impagina build/news.json in docs/index.html.

Il "menabò": le notizie ordinate per punteggio vengono distribuite negli
spazi della pagina come farebbe un capo servizio.

    apertura   1   il pezzo forte, taglio alto, sommario lungo
    spalla     1   colonna di destra, seconda notizia per peso
    civette    3   fascia sotto la testata, solo titolo
    centrali   6   corpo pagina su tre colonne
    box_squadre    raggruppate per club (fonti di scope non generalista)
    brevi      resto, in colonnino "Ultimissime"
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import pathlib
import re
import shutil
import sys

import yaml
from jinja2 import Environment, FileSystemLoader, select_autoescape

ROOT = pathlib.Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
DOCS = ROOT / "docs"
TPL = ROOT / "src" / "templates"

MESI = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio",
        "agosto", "settembre", "ottobre", "novembre", "dicembre"]
GIORNI = ["lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica"]

# Il numero dell'edizione: giorni trascorsi dal "primo numero".
PRIMO_NUMERO = dt.date(2026, 1, 1)


def data_estesa(d: dt.datetime) -> str:
    return f"{GIORNI[d.weekday()]} {d.day} {MESI[d.month - 1]} {d.year}"


def occhiello(article: dict) -> str:
    """Sovratitolo: la squadra o il tema dominante, in maiuscoletto."""
    club = [
        "Juventus", "Inter", "Milan", "Napoli", "Roma", "Lazio", "Atalanta",
        "Fiorentina", "Bologna", "Torino", "Udinese", "Genoa", "Como",
        "Cagliari", "Lecce", "Parma", "Verona", "Sassuolo", "Pisa", "Cremonese",
        "Real Madrid", "Barcellona", "Bayern", "Chelsea", "Arsenal", "Liverpool",
        "Manchester United", "Manchester City", "Tottenham", "PSG", "Al-Hilal",
    ]
    blob = f"{article['title']} {article['summary']}"
    found = [c for c in club if re.search(rf"\b{re.escape(c)}\b", blob, re.I)]
    if found:
        return " · ".join(found[:2])
    if article.get("scope", "generalista") != "generalista":
        return article["scope"]
    return "Mercato"


def eta(minuti: int) -> str:
    if minuti < 1:
        return "adesso"
    if minuti < 60:
        return f"{minuti} min fa"
    ore = minuti // 60
    if ore < 24:
        return f"{ore} h fa"
    return f"{ore // 24} g fa"


def menabo(articles: list[dict], impaginazione: dict | None = None) -> dict:
    """Distribuisce le notizie nei quattro spazi della pagina.

        colonne 1-2   gli articoli, incolonnati come in un quotidiano
        colonne 3-4   il pezzo fotografico: foto e titolo a cavallo delle due
                      colonne, il testo ripartito sotto; poi le altre notizie
        fascia alta   tre civette sotto la testata
        fascia bassa  quel che resta, in "In breve"
    """
    imp = impaginazione or {}
    n_articoli = int(imp.get("articoli", 11))
    n_sotto = int(imp.get("sotto_foto", 9))
    a = list(articles)
    layout: dict = {
        # il pezzo forte va a destra, sotto la foto
        "fotografico": a.pop(0) if a else None,
        "civette": [a.pop(0) for _ in range(min(3, len(a)))],
    }

    # Le due metà devono chiudersi più o meno alla stessa altezza: a sinistra
    # stanno gli articoli distesi, a destra la foto si mangia parecchio spazio.
    # Il rapporto 11 a 9 è quello misurato che lascia meno scarto (~56 px);
    # si regola da sources.yaml → impaginazione.
    layout["articoli"] = [a.pop(0) for _ in range(min(n_articoli, len(a)))]

    # Box di club, ma solo dove c'è davvero qualcosa da raggruppare: un box
    # con una notizia sola è un filetto sprecato.
    per_squadra: dict[str, list[dict]] = {}
    for art in a:
        scope = art.get("scope", "generalista")
        if scope != "generalista":
            per_squadra.setdefault(scope, []).append(art)
    box = {
        s: n[:3]
        for s, n in sorted(per_squadra.items(), key=lambda kv: -len(kv[1]))
        if len(n) >= 2
    }
    box = dict(sorted(list(box.items())[:2]))
    in_box = {n["id"] for gruppo in box.values() for n in gruppo}

    resto = [art for art in a if art["id"] not in in_box]
    layout["box_squadre"] = box
    sotto, brevi = resto[:n_sotto], resto[n_sotto:]
    # Una fascia "In breve" con due righe in croce è peggio che non averla:
    # sotto le quattro voci si riversa tutto nella colonna delle ultimissime.
    if len(brevi) < 4:
        sotto, brevi = sotto + brevi, []
    layout["sotto_foto"] = sotto
    layout["brevi"] = brevi
    return layout


def main() -> int:
    ap = argparse.ArgumentParser(description="Impagina l'edizione.")
    ap.add_argument("--demo", action="store_true",
                    help="usa tests/fixtures/demo.json e stampa il bollo 'edizione di prova'")
    args = ap.parse_args()

    cfg = yaml.safe_load((ROOT / "src" / "sources.yaml").read_text())
    src_json = (ROOT / "tests" / "fixtures" / "demo.json") if args.demo else (BUILD / "news.json")
    if not src_json.exists():
        print(
            f"Non trovo {src_json.relative_to(ROOT)}.\n"
            "Vuol dire che fetch.py non ha prodotto niente: nessuna fonte ha\n"
            "risposto. Prova 'make check-sources' per vedere quali feed sono\n"
            "caduti, oppure 'make demo' per impaginare intanto dati di prova.",
            file=sys.stderr,
        )
        return 1
    data = json.loads(src_json.read_text())
    generated = dt.datetime.fromisoformat(data["generated_at"])
    articles = data["articles"]

    for art in articles:
        art["occhiello"] = occhiello(art)
        art["eta"] = eta(art.get("age_minutes", 0))

    env = Environment(
        loader=FileSystemLoader(TPL),
        autoescape=select_autoescape(["html"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    tpl = env.get_template("giornale.html.j2")
    html = tpl.render(
        layout=menabo(articles, cfg.get("impaginazione")),
        data_estesa=data_estesa(generated),
        ora=generated.strftime("%H:%M"),
        numero=(generated.date() - PRIMO_NUMERO).days,
        anno=generated.year,
        stats=data["stats"],
        fonti=sorted({a["source"] for a in articles}),
        demo=args.demo,
    )

    DOCS.mkdir(exist_ok=True)
    shutil.copy(TPL / "style.css", DOCS / "style.css")
    shutil.copy(TPL / "foto-mancante.svg", DOCS / "foto-mancante.svg")
    (DOCS / ".nojekyll").touch()

    out = DOCS / "index.html"
    # impronta del contenuto senza l'orario: evita 48 commit al giorno a vuoto
    body_hash = hashlib.sha1(
        "".join(sorted(a["id"] for a in articles)).encode()
    ).hexdigest()
    old_hash = ""
    stamp = DOCS / ".content-hash"
    if stamp.exists():
        old_hash = stamp.read_text().strip()

    out.write_text(html, encoding="utf-8")
    stamp.write_text(body_hash)
    (DOCS / "edizione.json").write_text(
        json.dumps(
            {"generated_at": data["generated_at"], "articles": articles},
            ensure_ascii=False, indent=1,
        )
    )

    changed = body_hash != old_hash
    print(f"docs/index.html scritto — {len(articles)} notizie — "
          f"{'contenuto cambiato' if changed else 'stesse notizie di prima'}")
    # esce 0 sempre: al workflow interessa il file .content-hash nel diff
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
