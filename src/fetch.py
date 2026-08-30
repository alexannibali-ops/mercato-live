#!/usr/bin/env python3
"""
fetch.py — raccoglie le notizie di calciomercato dai feed RSS/Atom.

Produce  build/news.json  : elenco normalizzato, deduplicato e ordinato.
Mantiene build/httpcache.json : ETag / Last-Modified per fare richieste
condizionali (304 = zero banda, e le fonti ringraziano).

NOTA-COPYRIGHT: qui si conservano SOLO titolo, un sommario troncato e il
link alla fonte. Non si scarica ne' si archivia il testo integrale degli
articoli. Il giornale cita e rimanda, non ristampa.
"""
from __future__ import annotations

import concurrent.futures as cf
import datetime as dt
import hashlib
import html
import json
import pathlib
import re
import sys
import unicodedata
from difflib import SequenceMatcher

import feedparser
import requests
import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
CACHE_FILE = BUILD / "httpcache.json"

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0 Safari/537.36 GiornaleCalciomercato/1.0 (+RSS reader)"
)
TIMEOUT = 15
ROME = dt.timezone(dt.timedelta(hours=2))  # sostituito da zoneinfo piu' sotto
try:
    from zoneinfo import ZoneInfo
    ROME = ZoneInfo("Europe/Rome")
except Exception:  # pragma: no cover
    pass


# --------------------------------------------------------------------------- #
# utilita' di testo
# --------------------------------------------------------------------------- #
TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")


def clean(text: str | None) -> str:
    if not text:
        return ""
    text = html.unescape(TAG_RE.sub(" ", text))
    return WS_RE.sub(" ", text).strip()


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


_STOP = {
    "il", "lo", "la", "i", "gli", "le", "un", "uno", "una", "di", "a", "da",
    "in", "con", "su", "per", "tra", "fra", "e", "ed", "che", "del", "della",
    "dei", "delle", "al", "alla", "ai", "dal", "dalla", "nel", "nella", "si",
    "il", "non", "ma", "the", "of", "to", "and",
}


def fingerprint(title: str) -> str:
    """Chiave di confronto: minuscole, senza accenti, senza stopword."""
    base = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode()
    words = re.findall(r"[a-z0-9]+", base.lower())
    return " ".join(w for w in words if w not in _STOP and len(w) > 2)


# Parole troppo frequenti nel lessico di mercato per distinguere due notizie:
# "Inter" e "rinnovo" compaiono ovunque, "Kasprzyk" e "34" no.
_COMUNI = set("""
inter milan juventus juve napoli roma lazio atalanta fiorentina bologna torino
udinese genoa como cagliari lecce parma verona sassuolo pisa cremonese monza
mercato calciomercato offerta trattativa rinnovo contratto ingaggio prestito
riscatto club squadra giocatore calciatore ufficiale accordo affare colpo addio
cessione acquisto milioni anni nuovo nuova serie
""".split())


def similar(a: str, b: str) -> float:
    """Quanto due titoli raccontano la stessa cosa (0-1).

    Non basta la sovrapposizione di parole: due notizie diverse sulla stessa
    squadra condividono già il nome del club. Pesa quindi soprattutto i token
    *distintivi* — cognomi, cifre, nomi propri — che sono quelli che davvero
    identificano una trattativa. Calibrata su titoli reali: notizie diverse
    stanno sotto 0.20, riformulazioni della stessa notizia sopra 0.54.
    """
    if not a or not b:
        return 0.0
    sa, sb = set(a.split()), set(b.split())
    if not sa or not sb:
        return 0.0
    comuni = sa & sb
    jaccard = len(comuni) / len(sa | sb)
    overlap = len(comuni) / min(len(sa), len(sb))
    rari_a, rari_b = sa - _COMUNI, sb - _COMUNI
    rari = (
        len(comuni - _COMUNI) / min(len(rari_a), len(rari_b))
        if rari_a and rari_b else 0.0
    )
    seq = SequenceMatcher(None, a, b).ratio()
    return 0.30 * jaccard + 0.25 * overlap + 0.35 * rari + 0.10 * seq


# --------------------------------------------------------------------------- #
# rete
# --------------------------------------------------------------------------- #
def load_cache() -> dict:
    if CACHE_FILE.exists():
        try:
            return json.loads(CACHE_FILE.read_text())
        except json.JSONDecodeError:
            pass
    return {}


def fetch_one(source: dict, cache: dict) -> tuple[dict, list[dict], str]:
    """Scarica un feed. Non solleva mai: un feed rotto non ferma l'edizione."""
    url = source["url"]
    headers = {"User-Agent": USER_AGENT, "Accept": "application/rss+xml, application/xml, text/xml, */*"}
    entry = cache.get(url, {})
    if entry.get("etag"):
        headers["If-None-Match"] = entry["etag"]
    if entry.get("modified"):
        headers["If-Modified-Since"] = entry["modified"]

    try:
        r = requests.get(url, headers=headers, timeout=TIMEOUT)
    except requests.RequestException as exc:
        return source, [], f"errore rete: {exc.__class__.__name__}"

    if r.status_code == 304:
        return source, [], "304 non modificato"
    if r.status_code != 200:
        return source, [], f"HTTP {r.status_code}"

    new_cache = {}
    if r.headers.get("ETag"):
        new_cache["etag"] = r.headers["ETag"]
    if r.headers.get("Last-Modified"):
        new_cache["modified"] = r.headers["Last-Modified"]
    cache[url] = new_cache

    parsed = feedparser.parse(r.content)
    items = [normalize(e, source) for e in parsed.entries]
    items = [i for i in items if i]
    return source, items, f"ok ({len(items)} voci)"


def normalize(e, source: dict) -> dict | None:
    title = clean(getattr(e, "title", ""))
    link = getattr(e, "link", "") or ""
    if not title or not link:
        return None

    summary = clean(getattr(e, "summary", "") or getattr(e, "description", ""))
    # se il sommario ripete il titolo non serve a niente
    if summary.lower().startswith(title.lower()[:40]):
        summary = summary[len(title):].strip(" -–—:")

    published = None
    for attr in ("published_parsed", "updated_parsed"):
        tm = getattr(e, attr, None)
        if tm:
            published = dt.datetime(*tm[:6], tzinfo=dt.timezone.utc)
            break
    if published is None:
        published = dt.datetime.now(dt.timezone.utc)

    image = ""
    for mc in (getattr(e, "media_content", None) or []):
        if mc.get("url"):
            image = mc["url"]
            break
    if not image:
        for enc in (getattr(e, "enclosures", None) or []):
            if str(enc.get("type", "")).startswith("image"):
                image = enc.get("href", "")
                break

    return {
        "title": title,
        "link": link,
        "summary": summary,
        "source": source["name"],
        "source_weight": float(source.get("weight", 1.0)),
        "scope": source.get("scope", "generalista"),
        "published": published.isoformat(),
        "image": image,
        "id": hashlib.sha1(link.encode()).hexdigest()[:12],
    }


# --------------------------------------------------------------------------- #
# selezione editoriale
# --------------------------------------------------------------------------- #
def keyword_score(item: dict, kw: dict) -> float | None:
    """None = fuori tema, si scarta."""
    blob = f"{item['title']} {item['summary']}".lower()
    for bad in kw.get("esclusione", []):
        if bad in blob:
            return None
    score = 0.0
    title_l = item["title"].lower()
    for word in kw.get("forte", []):
        if word in title_l:
            score += 2.0
        elif word in blob:
            score += 0.8
    for word in kw.get("medio", []):
        if word in title_l:
            score += 1.0
        elif word in blob:
            score += 0.4
    return score if score > 0 else None


def rank(items: list[dict], ed: dict, kw: dict) -> list[dict]:
    now = dt.datetime.now(dt.timezone.utc)
    max_age = dt.timedelta(hours=ed["max_age_hours"])

    kept: list[dict] = []
    for it in items:
        published = dt.datetime.fromisoformat(it["published"])
        age = now - published
        if age > max_age or age < dt.timedelta(hours=-6):
            continue
        ks = keyword_score(it, kw)
        if ks is None:
            continue
        # decadimento: una notizia vale meta' dopo 8 ore
        freshness = 0.5 ** (age.total_seconds() / (8 * 3600))
        it["_kw"] = ks
        it["_fresh"] = freshness
        it["_fp"] = fingerprint(it["title"])
        it["age_minutes"] = int(age.total_seconds() // 60)
        kept.append(it)

    # --- deduplica: notizie molto simili diventano una sola, piu' pesante ---
    kept.sort(key=lambda x: x["published"], reverse=True)
    clusters: list[dict] = []
    for it in kept:
        for c in clusters:
            if similar(it["_fp"], c["_fp"]) >= ed["dedup_threshold"]:
                c["also"].append({"source": it["source"], "link": it["link"]})
                c["_corroboration"] += 0.6
                if not c.get("image") and it.get("image"):
                    c["image"] = it["image"]
                break
        else:
            it["also"] = []
            it["_corroboration"] = 0.0
            clusters.append(it)

    for c in clusters:
        c["score"] = round(
            c["_kw"] * 1.0
            + c["_fresh"] * 4.0
            + c["source_weight"] * 1.5
            + c["_corroboration"],
            3,
        )
        # sommario troncato con garbo
        s = c["summary"]
        limit = ed["summary_chars"]
        if len(s) > limit:
            cut = s[:limit].rsplit(" ", 1)[0]
            s = cut.rstrip(" ,;:.") + "…"
        c["summary"] = s

    clusters.sort(key=lambda x: x["score"], reverse=True)
    for c in clusters:
        for k in ("_kw", "_fresh", "_fp", "_corroboration"):
            c.pop(k, None)
    return clusters[: ed["max_articles"]]


# --------------------------------------------------------------------------- #
def main() -> int:
    cfg = yaml.safe_load((ROOT / "src" / "sources.yaml").read_text())
    sources, ed, kw = cfg["sources"], cfg["editorial"], cfg["keywords"]

    BUILD.mkdir(exist_ok=True)
    cache = load_cache()

    # se un feed risponde 304, riusiamo le sue voci dall'edizione precedente
    previous: list[dict] = []
    prev_file = BUILD / "news.json"
    if prev_file.exists():
        try:
            previous = json.loads(prev_file.read_text()).get("raw", [])
        except Exception:
            previous = []

    collected: list[dict] = []
    report: list[str] = []
    with cf.ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(fetch_one, s, cache) for s in sources]
        for fut in cf.as_completed(futures):
            src, items, status = fut.result()
            if status.startswith("304"):
                items = [p for p in previous if p["source"] == src["name"]]
                status += f" (riuso {len(items)} voci)"
            report.append(f"  {src['name']:<20} {status}")
            collected.extend(items)

    print("Fonti:")
    print("\n".join(sorted(report)))

    if not collected:
        print("\n! Nessuna voce raccolta: mantengo l'edizione precedente.", file=sys.stderr)
        return 1

    # deduplica per link identico prima di tutto
    seen, unique = set(), []
    for it in collected:
        if it["link"] in seen:
            continue
        seen.add(it["link"])
        unique.append(it)

    articles = rank(unique, ed, kw)
    out = {
        "generated_at": dt.datetime.now(ROME).isoformat(),
        "articles": articles,
        "raw": unique,       # serve per il riuso in caso di 304
        "stats": {
            "fonti": len(sources),
            "voci_lette": len(unique),
            "in_edizione": len(articles),
        },
    }
    (BUILD / "news.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    CACHE_FILE.write_text(json.dumps(cache, indent=1))
    print(f"\n{len(unique)} voci lette → {len(articles)} in edizione.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
