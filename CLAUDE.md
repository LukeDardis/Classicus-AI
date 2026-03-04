# CLAUDE.md — Classicus AI / Academia Classica

## Project Overview

**Classicus AI** (branded as "Academia Classica") is a classical-language text reader for Greek and Latin. Every word in the corpus is clickable and returns full morphological analysis (lemma, POS, case, tense, mood, voice, etc.) sourced from the Perseus Digital Library Morpheus engine, cached locally to avoid repeated network calls.

The app runs in two distinct modes:

| Mode | Entry point | When to use |
|------|-------------|-------------|
| **Flask server** | `server.py` | Local development; live Perseus fallback via Python backend |
| **Static PWA** | `index.html` | GitHub Pages / CDN hosting; morphology baked into the HTML via `MORPH_DATA` |

---

## Repository Structure

```
Classicus-AI/
├── server.py               # Flask server (dev mode)
├── morphology_engine.py    # Core: SQLite cache + Perseus API client
├── preseed.py              # One-time corpus pre-seeder (reads HTML, queries Perseus)
├── export_cache.py         # Export morphology.db → morph_cache.json
├── _embed_morph.py         # Re-embed MORPH_DATA JSON into HTML files
├── _patch_html.py          # One-time patch: converts sync to async showDefinition
├── classicus-ai-final.html # Canonical source HTML (edit this, then copy to index.html)
├── index.html              # Deployed static PWA entry point
├── morph_cache.json        # Exported morphology cache (loaded by index.html at runtime)
├── manifest.json           # PWA manifest (name: "Academia Classica")
├── sw.js                   # Service worker (cache-first static, network-first API)
├── icons/                  # PWA icons (192, 256, 512 px)
├── requirements.txt        # Python deps: flask>=3.0.0, requests>=2.31.0
└── .gitignore              # Excludes morphology.db, __pycache__, .env
```

> **Note:** `morphology.db` (SQLite) is git-ignored. It must be generated locally by running `preseed.py` or will be created empty on first server start.

---

## Architecture & Data Flow

### Flask server mode (development)

```
Browser click
  → fetch('/api/morph?word=arma&lang=latin')
  → Flask /api/morph  (server.py)
  → MorphologyEngine.lookup()  (morphology_engine.py)
      ├── SQLite cache hit  → instant JSON response
      └── cache miss
            → Perseus xmlmorph API (HTTPS GET)
            → parse XML → store in morphology.db
            → JSON response
```

### Static PWA mode (GitHub Pages)

```
Browser click
  → showDefinition() in index.html
  → loadMorphData()  (fetches morph_cache.json once, cached in memory)
      ├── key found in MORPH_DATA  → instant display
      └── cache miss
            → lookupPerseus() via allorigins.win CORS proxy
            → parse XML in browser
            → store in session cache
```

### Morphology data pipeline

Run these steps in order when corpus or DB changes:

```
1. python preseed.py           # fills morphology.db from Perseus (slow, ~1.5s/word)
2. python export_cache.py      # writes morph_cache.json  (for static PWA)
3. python _embed_morph.py      # re-embeds MORPH_DATA into classicus-ai-final.html + index.html
```

---

## Key Components

### `morphology_engine.py` — `MorphologyEngine` class

- **`lookup(word, lang)`** — public entry point; returns a JSON-serialisable dict
- **`_normalize_lang(lang)`** — accepts `greek/grc/gr` → `'greek'`; `latin/la/lat` → `'latin'`
- **`_normalize_word(word, lang)`** — lowercase, strip punctuation; Greek additionally NFD-stripped and converted to Beta Code
- **`_fetch_perseus(word, lang)`** — HTTP GET to `https://www.perseus.tufts.edu/hopper/xmlmorph`
- **`_parse_xml(raw_xml)`** — ElementTree parse of Perseus XML response
- **`_build_display_str(row)`** — builds human-readable summary like `"noun acc. pl. neut."`
- **`_cache_get / _cache_set`** — SQLite read/write; `found=0` rows are cached (known misses)

#### SQLite schema

```sql
morph_cache (id, word TEXT, lang TEXT, queried_at TEXT, found INT, raw_xml TEXT)
  UNIQUE(word, lang)

morph_analysis (id, cache_id → morph_cache.id, lemma, pos, person, number,
                tense, mood, voice, case_label, gender, dialect, feature, display_str)
```

#### Greek Beta Code conversion

Perseus Morpheus requires ASCII Beta Code for Greek. The engine:
1. NFD-decomposes the Unicode string to strip diacritics
2. Maps each Greek letter via `_GREEK_TO_BETA` dict (e.g. `α→a`, `θ→q`, `ω→w`, `ξ→c`)

### `server.py` — Flask endpoints

| Route | Description |
|-------|-------------|
| `GET /` | Serves `index.html` |
| `GET /api/morph?word=&lang=` | Morphological analysis; delegates to `MorphologyEngine.lookup()` |
| `GET /api/greek-mass?date=YYYYMMDD` | Proxy to universalis.com; returns Greek NT Mass readings as JSON |

### `preseed.py`

Extracts every word from `const texts` and `BIBLE_TEXTS` blocks in the HTML, sorted by frequency (most common first), then queries Perseus for each. Rate-limited to 1.5 s per new API call. Fully resume-safe (already-cached words are skipped).

Usage: `python preseed.py [path/to/classicus-ai-final.html]`

### `_patch_html.py`

One-time migration script. Replaces the synchronous `showDefinition()` with an async version that fetches `morph_cache.json` lazily and falls back to live Perseus via the `allorigins.win` CORS proxy. Only run once per HTML file; already-patched files are detected.

---

## API Response Format

```json
GET /api/morph?word=arma&lang=latin

{
  "word": "arma",
  "lang": "latin",
  "found": true,
  "analyses": [
    {
      "lemma": "arma",
      "pos": "noun",
      "display_str": "noun acc. pl. neut.",
      "details": { "case": "acc", "number": "pl", "gender": "neut" }
    }
  ]
}
```

`found: false` is returned (not an error) when Perseus has no data for the word.

---

## PWA Details

- **Manifest:** `manifest.json` — app name "Academia Classica", theme `#c9a84c` (gold), background `#09080a` (near-black)
- **Service Worker:** `sw.js` (`CACHE_NAME = 'academia-classica-v3'`)
  - Cache-first for static assets (`index.html`, `manifest.json`)
  - Network-first for API paths and external hosts (Perseus, Universalis, allorigins)
  - **Bump the cache version** (`academia-classica-vN`) whenever static assets change so clients pick up updates

---

## Development Workflows

### Run locally (Flask mode)

```bash
pip install -r requirements.txt
python server.py          # http://127.0.0.1:5000/
```

### Pre-seed the morphology cache

```bash
python preseed.py         # ~20 min cold run; safe to interrupt and resume
```

### Update the static PWA after DB changes

```bash
python export_cache.py    # regenerate morph_cache.json
python _embed_morph.py    # re-embed into classicus-ai-final.html + index.html
```

### Adding new texts to the corpus

1. Edit `classicus-ai-final.html` — add entries to the `const texts` JS block (greek or latin array)
2. Copy relevant changes to `index.html` if they diverge
3. Run the pipeline above to pre-seed and embed new vocabulary

---

## Conventions & Gotchas

- **`classicus-ai-final.html` is the canonical source.** Keep it in sync with `index.html`. When editing JS or CSS, edit `classicus-ai-final.html` first, then propagate.
- **`morph_cache.json` is committed.** It is the pre-built morphology data for the static PWA. Regenerate and commit it whenever `morphology.db` is updated.
- **`morphology.db` is NOT committed** (`.gitignore`). The SQLite file is local only.
- **Greek words are stored in Beta Code** in the DB and in `morph_cache.json`. The normalization happens in `MorphologyEngine._normalize_word()` (Python) and `_normalizeMorphKey()` (JavaScript).
- **`found=0` rows are cached** in SQLite so Perseus is never queried twice for known unknowns.
- **Perseus rate limit:** space API calls at least 1.5 s apart in `preseed.py`.
- **CORS:** Perseus does not send CORS headers. The static PWA routes live lookups through `allorigins.win`. The Flask server bypasses CORS entirely (same-origin).
- **Python 3.10+** required (uses `str | Path` union type hints).
- **Service worker cache version:** bump `CACHE_NAME` in `sw.js` on every static asset deployment.

---

## External Dependencies

| Service | Purpose | Notes |
|---------|---------|-------|
| Perseus Digital Library (`perseus.tufts.edu/hopper/xmlmorph`) | Morphological analysis | Requires Beta Code for Greek; no API key |
| universalis.com | Daily Greek NT Mass readings | Scraped HTML; not an official API |
| allorigins.win | CORS proxy for browser → Perseus | Used only in static PWA mode |
