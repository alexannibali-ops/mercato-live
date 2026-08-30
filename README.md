# Il Mercato — un quotidiano di calciomercato che si compone da solo

Pagina web impaginata come un giornale di carta, con le notizie di mercato
raccolte dai feed delle testate specializzate e rifatta **ogni 30 minuti**.
Nessun server, nessuna carta di credito: gira interamente dentro GitHub.

```
GitHub Actions (cron */30)  →  fetch.py  →  build.py  →  docs/index.html
      il "cron gratis"          i feed      il menabò      GitHub Pages
```

---

## 1. Perché questo ambiente e non un altro

Il problema non è generare l'HTML: è **avere qualcosa che si svegli ogni 30
minuti gratis, per sempre**. Ecco il confronto, aggiornato ad agosto 2026.

| Ambiente | Cron ogni 30 min | Hosting | Costo | Il vero limite |
|---|---|---|---|---|
| **GitHub Actions + Pages** ← scelto | sì, `*/30 * * * *` | Pages incluso | **0 €** | i job schedulati **si disattivano dopo 60 giorni** senza attività nel repo; il cron può ritardare di 5-20 min |
| Cloudflare Workers + Cron Triggers | sì, granularità 1 minuto | Workers/Pages | 0 € nel piano free | max 3 cron trigger per Worker, niente retry né storico esecuzioni nel piano free; per servire HTML statico serve KV o R2 |
| Vercel / Netlify scheduled functions | dipende dal piano | ottimo | 0 € limitato | le cadenze fitte sono tipicamente riservate ai piani a pagamento: da verificare prima di legarsi |
| VPS con `cron` classico | sì, senza vincoli | tuo | 3-5 €/mese | non è gratis e devi mantenerlo tu |
| n8n / Make / Zapier | sì | no | free tier stretto | finisci le esecuzioni in pochi giorni con 48 run al giorno |

**Verdetto.** Per un aggiornamento ogni 30 minuti, in italiano, gratuito e
duraturo, GitHub Actions + GitHub Pages è la scelta giusta: 48 esecuzioni al
giorno da ~40 secondi l'una restano dentro il free tier dei repository
pubblici, e Pages serve l'HTML senza che tu debba gestire niente.

I due difetti vanno conosciuti, non subiti — e questo progetto li tratta già:

- **Disattivazione a 60 giorni.** Vale per i repo pubblici senza attività.
  Qui ogni edizione con notizie nuove produce un commit, quindi il repo è
  attivo per costruzione; in più `manutenzione.yml` mette un timbro il primo
  di ogni mese, così il cron resta sveglio anche in un agosto senza mercato.
- **Cron impuntuale.** GitHub accoda i job schedulati e nelle ore di punta
  ritarda; ogni tanto salta un giro. Per un giornale di trattative è
  irrilevante: la pagina dichiara sempre l'ora dell'edizione che stai leggendo.

Se un giorno ti servisse la puntualità al minuto, la migrazione naturale è
Cloudflare Workers: stesso `fetch.py` riscritto in un Worker, output in KV.
Non ne hai bisogno adesso.

---

## 2. Come si mette in piedi (10 minuti)

```bash
# 1. crea un repository PUBBLICO su GitHub (i repo privati consumano minuti)
git init && git add . && git commit -m "Primo numero"
git branch -M main
git remote add origin https://github.com/<tuo-utente>/<repo>.git
git push -u origin main
```

2. **Settings → Pages** → *Source*: `Deploy from a branch` → branch `main`,
   cartella `/docs` → *Save*.
3. **Settings → Actions → General** → *Workflow permissions*:
   `Read and write permissions` → *Save*. Senza questo il bot non può committare.
4. **Actions → Edizione → Run workflow**: fa uscire subito il primo numero.

Dopo un paio di minuti il giornale è su
`https://<tuo-utente>.github.io/<repo>/`.

### In locale

```bash
make install
make demo     # impagina dati finti, senza toccare la rete: serve a provare il layout
make edizione # scarica i feed veri e compone l'edizione
make serve    # anteprima su http://localhost:8000
make test     # controlla filtro, deduplica e punteggio
```

---

## 3. Com'è fatto

```
src/sources.yaml     le fonti, i pesi e le regole editoriali — è qui che si mette mano
src/fetch.py         scarica i feed, filtra, deduplica, assegna un punteggio
src/build.py         il menabò: distribuisce le notizie negli spazi della pagina
src/templates/       il template Jinja e il foglio di stile tipografico
src/check_sources.py verifica che i feed rispondano ancora
docs/                l'edizione pubblicata (questa cartella la serve Pages)
build/               cache HTTP e news.json, non si guardano a mano
```

**`fetch.py`** fa quattro cose non ovvie:

- *richieste condizionali*: conserva `ETag` e `Last-Modified` di ogni feed, e
  quando la fonte risponde `304 Not Modified` riusa le voci dell'edizione
  precedente. Meno banda per te e meno traffico inutile per le testate.
- *filtro lessicale*: una notizia entra solo se il titolo o il sommario
  contengono termini di mercato (`sources.yaml → keywords`). Pagelle, moviola
  e probabili formazioni restano fuori.
- *deduplica*: la stessa trattativa rilanciata da cinque siti diventa **una**
  notizia sola, e le altre testate la corroborano — cioè le fanno **salire**
  in pagina. È l'euristica che avrebbe un caposervizio: se lo scrivono tutti,
  è la notizia di apertura.
- *punteggio*: freschezza (una notizia vale metà dopo 8 ore) + peso della
  fonte + forza delle parole chiave + corroborazione.

**`build.py`** non ordina soltanto: assegna gli spazi. La prima pagina è su
**quattro colonne**:

```
┌─────────────────────────────────────────────────────────────┐
│                        IL MERCATO                           │
├──────────────┬──────────────┬───────────────────────────────┤
│  civetta 1   │  civetta 2   │  civetta 3                    │
├──────────────┼──────────────┼───────────────────────────────┤
│              │              │ ┌───────────────────────────┐ │
│              │              │ │        FOTOGRAFIA         │ │
│  articolo    │  articolo    │ └───────────────────────────┘ │
│  articolo    │  articolo    │  TITOLO A CAVALLO DELLE DUE   │
│  articolo    │  articolo    │  COLONNE                      │
│  articolo    │  articolo    ├───────────────┬───────────────┤
│  articolo    │  articolo    │ testo         │ testo         │
│              │              ├───────────────┴───────────────┤
│              │              │ ultimissime  │  ultimissime   │
└──────────────┴──────────────┴──────────────┴────────────────┘
        colonne 1-2                   colonne 3-4
```

Le colonne 1-2 ospitano gli articoli incolonnati; le 3-4 il **pezzo
fotografico**: foto e titolo occupano tutta la larghezza delle due colonne,
il testo scorre sotto ripartito fra le due. Sotto, le ultimissime e i box di
club, sempre su due colonne.

Il rapporto fra le notizie a sinistra e quelle a destra
(`impaginazione.articoli` e `impaginazione.sotto_foto` in `sources.yaml`) serve
a far **chiudere le due metà alla stessa altezza**: 11 e 9 sono i valori
misurati, lasciano uno scarto di una quarantina di pixel. Se la colonna di
sinistra ti resta corta, alza `articoli`.

Due accorgimenti da giornale: i box di club compaiono solo quando hanno almeno
due notizie (un box con una riga sola è un filetto sprecato), e la fascia
"In breve" in fondo appare solo sopra le quattro voci — altrimenti quel che
avanza si riversa nelle ultimissime.

---

## 4. La stampa

Il layout ha due destinazioni. A schermo è una pagina responsive; in stampa
diventa un **A3 verticale** — il formato che regge quattro colonne di testo
leggibile. Il bottone in basso a destra chiama `window.print()`, e in stampa
sparisce da solo, insieme al richiamo "l'articolo completo su…" che su carta
non si può cliccare.

Su telefono le quattro colonne diventano una sola e il pezzo fotografico sale
in cima, dove ha senso che stia.

Per passare all'A4, in fondo a `src/templates/style.css`:

```css
@page{ size: A4 portrait; margin: 10mm; }
@media print{ .colonne-basso{ column-count:3; } .articoli{ column-count:1; } }
```

Le regole che contano davvero sono già lì: `break-inside: avoid` sui pezzi
perché un articolo non si spezzi a metà colonna, e `orphans/widows: 3` per
non lasciare righe sole in fondo.

Se vuoi anche un **PDF automatico** a ogni edizione, si aggiunge in una decina
di righe: `pip install playwright`, `playwright install chromium`, e nel
workflow un passo che apre `docs/index.html` e chiama `page.pdf(format="A3")`.
Chiedimelo e te lo scrivo.

---

## 5. Mettere mano al giornale

- **Cambiare fonti** → `src/sources.yaml`. Poi `make check-sources`: dice
  subito quali feed rispondono e quali sono morti. I percorsi RSS cambiano
  senza preavviso, vale la pena rilanciarlo ogni tanto.
  Le fonti già verificate al momento della scrittura: Calciomercato.it,
  MilanNews, FcInterNews, Football Italia. Le altre sono plausibili ma
  **vanno verificate da te**: alcune testate rispondono `403` a chi non
  sembra un browser, e alcune (Gazzetta, Corriere dello Sport, Tuttosport)
  pubblicano feed vuoti o li hanno dismessi.
- **Cambiare testata** → `<h1 class="gerente">` nel template, e `--rosso`,
  `--carta`, i font in `style.css`.
- **Cambiare il colore della carta** → la variabile `--carta` in cima a
  `style.css` (ora è il rosa da rotativa dei quotidiani sportivi, `#f7d5cd`),
  e `--carta-scura` per il piano attorno al foglio. Se la cambi, ricontrolla
  il contrasto: `--inchiostro` sta a 13.2:1, `--rosso` a 5.9:1, entrambi
  sopra la soglia AA. In stampa il fondo esce davvero grazie a
  `print-color-adjust: exact` — senza quella riga il foglio uscirebbe bianco.
- **La fotografia** → viene presa dal feed (`media:content` o `enclosure`)
  e finisce in cima alle colonne 3-4. Quando il feed non ne fornisce una,
  al suo posto va `foto-mancante.svg`, un segnaposto grafico che dichiara di
  esserlo: meglio un vuoto onesto di un'immagine presa da chissà dove.
- **Più o meno notizie** → `editorial.max_articles`.
- **Finestra temporale** → `editorial.max_age_hours` (36 ore di default:
  d'estate alzala, a mercato chiuso pure).
- **Cadenza diversa** → il `cron` in `.github/workflows/edizione.yml`.
  Sotto i 5 minuti GitHub non scende, e comunque i feed non si aggiornano
  così spesso.

---

## 6. Due note serie prima di pubblicare

**Diritto d'autore.** Il progetto conserva e mostra soltanto **titolo, un
sommario troncato a ~220 caratteri e il link all'originale**, con la testata
sempre in chiaro sotto ogni pezzo. Questo è il perimetro dell'aggregazione
per citazione, ed è il motivo per cui `summary_chars` è basso: non alzarlo
per riempire la pagina, e soprattutto non aggiungere lo scraping del testo
integrale degli articoli. Se un editore ti chiede di uscire dall'aggregatore,
togli la sua riga da `sources.yaml` e sei a posto.

**RSS, non scraping.** Leggere un feed è un invito che il sito ti ha fatto.
Raschiare l'HTML delle pagine è un'altra cosa: più fragile, spesso vietata
dai termini di servizio, e ti fa bloccare l'IP. Se una fonte che ti serve non
ha RSS, prima cerca `/feed`, `/rss`, `/feed.xml` o il tag
`<link rel="alternate" type="application/rss+xml">` nel sorgente della home.

---

## 7. Quando qualcosa non va

| Sintomo | Causa quasi certa |
|---|---|
| Il workflow fallisce sul `git push` | mancano i permessi di scrittura: punto 3 del setup |
| Pagina vuota o pochissime notizie | feed caduti → `make check-sources`; oppure `max_age_hours` troppo stretto |
| Una fonte dà sempre `HTTP 403` | filtra sullo User-Agent; prova a modificarlo in `fetch.py` |
| Il cron non parte più | 60 giorni di inattività: **Actions → Edizione → Enable workflow** |
| La storia di git è enorme | normale con 48 commit/giorno; `git gc` oppure una `git checkout --orphan` una volta l'anno |
| In stampa i pezzi si spezzano | qualche browser ignora `break-inside`; stampa da Chrome |

---

*Generato come progetto di partenza. Il codice è tuo: cambialo senza riguardi.*
