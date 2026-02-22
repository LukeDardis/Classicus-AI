# Classicus AI

A classical text reader for Greek and Latin with live morphological analysis powered by the [Perseus Digital Library](https://www.perseus.tufts.edu/) Morpheus engine.

Every word in the corpus is clickable. Click any word to instantly see its lemma, part of speech, and full grammatical parse (case, number, gender, tense, mood, voice, etc.) — sourced from Perseus and cached locally in SQLite so repeated lookups are instant.

---

## Features

- **Full corpus coverage** — every word is clickable, not just a hardcoded subset
- **Real morphological data** — parsed by the Perseus Morpheus engine (lemma, POS, case, tense, mood, voice, and more)
- **Local SQLite cache** — results stored permanently; no repeated network calls
- **Graceful fallbacks** — spinner while loading, friendly message if Perseus has no data
- **Multiple analyses** — ambiguous words show all possible parses

---

## Texts Included

**Greek**
- Homer's *Odyssey* — Book 1
- Homer's *Iliad* — Book 1
- Plato's *Apology*
- Various other selections

**Latin**
- Vergil's *Aeneid* — Book 1
- Caesar's *Gallic War* — Book 1
- Cicero's *Catilinarian Orations*
- Various other selections

---

## Project Structure

```
classicus/
├── classicus-ai-final.html   # Single-file app (served by Flask)
├── morphology_engine.py      # SQLite cache + Perseus API client
├── server.py                 # Flask server
├── preseed.py                # One-time corpus pre-seeding script
├── requirements.txt
└── morphology.db             # Pre-seeded SQLite cache (910 corpus words)
```

---

## Setup & Usage

**1. Install dependencies**
```bash
pip install -r requirements.txt
```

**2. Start the server**
```bash
python server.py
```
Then open **http://127.0.0.1:5000/** in your browser.

**3. (Optional) Pre-seed the cache**

Pre-fetches morphological data for every word in the corpus so all clicks are instant from the start. Takes ~20 minutes on a cold run; fully resume-safe if interrupted.
```bash
python preseed.py
```
The pre-seeded `morphology.db` is included in the repo, so this step is only needed if you want to extend coverage beyond the included corpus.

---

## How It Works

```
Browser click → fetch('/api/morph?word=arma&lang=latin')
                      ↓
              Flask /api/morph
                      ↓
          MorphologyEngine.lookup()
            ↙               ↘
    SQLite cache hit     Cache miss → Perseus API
    (instant)            → parse XML → store in DB
                                ↓
                      JSON response to browser
```

- **Greek input** is converted from Unicode (with diacritics) to ASCII Beta Code before querying Perseus, which is what the Morpheus engine requires (e.g. `ἄνδρα` → `andra`)
- **`found=0` rows** are cached for known misses so Perseus is never queried twice for the same unknown word
- **Same-origin** serving (Flask at `127.0.0.1:5000`) means no CORS configuration needed

---

## API

```
GET /api/morph?word=WORD&lang=LANG
```

- `lang`: `latin` or `greek`
- Returns JSON:

```json
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

---

## Requirements

- Python 3.10+
- Flask 3.0+
- requests 2.31+
- Internet connection for first-time word lookups (or run `preseed.py` once)
