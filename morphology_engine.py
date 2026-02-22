"""
MorphologyEngine: SQLite-cached morphological analysis via the Perseus Morpheus API.

Perseus xmlmorph endpoint:
  GET https://www.perseus.tufts.edu/hopper/xmlmorph?lang=LANG&lookup=WORD
  lang: 'la' for Latin, 'greek' for Greek
  Greek input must be ASCII Beta Code (e.g. 'andra' for ανδρα).

XML response shape:
  <analyses>
    <analysis>
      <form lang="la">arma</form>
      <lemma>arma</lemma>
      <expandedForm>arma</expandedForm>
      <pos>noun</pos>
      <person>...</person>  <!-- optional -->
      <number>pl</number>
      <tense>...</tense>    <!-- optional -->
      <mood>...</mood>      <!-- optional -->
      <voice>...</voice>    <!-- optional -->
      <gender>neut</gender>
      <case>acc</case>
      <dialect></dialect>
      <feature></feature>
    </analysis>
  </analyses>
"""

import sqlite3
import unicodedata
import logging
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Greek Beta Code conversion
# Perseus Morpheus requires ASCII Beta Code for Greek input.
# Diacritics are stripped via NFD decomposition first, then each Greek
# Unicode letter is mapped to its Beta Code ASCII equivalent.
# ---------------------------------------------------------------------------

_GREEK_TO_BETA = {
    'α': 'a', 'β': 'b', 'γ': 'g', 'δ': 'd', 'ε': 'e',
    'ζ': 'z', 'η': 'h', 'θ': 'q', 'ι': 'i', 'κ': 'k',
    'λ': 'l', 'μ': 'm', 'ν': 'n', 'ξ': 'c', 'ο': 'o',
    'π': 'p', 'ρ': 'r', 'σ': 's', 'ς': 's', 'τ': 't',
    'υ': 'u', 'φ': 'f', 'χ': 'x', 'ψ': 'y', 'ω': 'w',
}

# Abbreviation maps for display string generation
_POS_ABBR = {
    'noun': 'noun', 'verb': 'verb', 'adj': 'adj.', 'adv': 'adv.',
    'prep': 'prep.', 'conj': 'conj.', 'part': 'part.', 'pron': 'pron.',
    'article': 'art.', 'exclam': 'exclam.', 'numeral': 'num.',
    'partic': 'part.',
}
_CASE_ABBR = {
    'nom': 'nom.', 'gen': 'gen.', 'dat': 'dat.', 'acc': 'acc.',
    'voc': 'voc.', 'abl': 'abl.', 'loc': 'loc.', 'ins': 'ins.',
}
_NUMBER_ABBR = {'sg': 'sg.', 'pl': 'pl.', 'dual': 'du.'}
_GENDER_ABBR = {'masc': 'masc.', 'fem': 'fem.', 'neut': 'neut.'}
_TENSE_ABBR = {
    'pres': 'pres.', 'imperf': 'imperf.', 'perf': 'perf.',
    'plup': 'plup.', 'fut': 'fut.', 'futperf': 'fut.perf.',
    'aor': 'aor.',
}
_MOOD_ABBR = {
    'ind': 'ind.', 'subj': 'subj.', 'opt': 'opt.',
    'imperat': 'imperat.', 'inf': 'inf.', 'part': 'part.',
    'gerundive': 'gerund.',
}
_VOICE_ABBR = {'act': 'act.', 'pass': 'pass.', 'mid': 'mid.', 'mp': 'mid./pass.'}
_PERSON_ABBR = {'1st': '1st', '2nd': '2nd', '3rd': '3rd'}

_STRIP_PUNCT = str.maketrans('', '', '·,;:.!?—()[]«»""\'\'')


class MorphologyEngine:
    PERSEUS_URL = 'https://www.perseus.tufts.edu/hopper/xmlmorph'

    def __init__(self, db_path: str | Path = 'morphology.db'):
        self.db_path = Path(db_path)
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_db()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def lookup(self, word: str, lang: str) -> dict:
        """Main entry point called by Flask. Returns a JSON-serialisable dict."""
        lang = self._normalize_lang(lang)
        normalized = self._normalize_word(word, lang)

        cached = self._cache_get(normalized, lang)
        if cached is not None:
            return cached

        raw_xml, found = self._fetch_perseus(normalized, lang)
        analyses = self._parse_xml(raw_xml) if found and raw_xml else []
        self._cache_set(normalized, lang, raw_xml, found, analyses)
        return self._format_result(word, lang, found, analyses)

    # ------------------------------------------------------------------
    # Normalisation
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_lang(lang: str) -> str:
        lang = lang.strip().lower()
        if lang in ('greek', 'grc', 'gr'):
            return 'greek'
        if lang in ('latin', 'la', 'lat'):
            return 'latin'
        raise ValueError(f"Unsupported language: {lang!r}. Use 'greek' or 'latin'.")

    @staticmethod
    def _normalize_word(word: str, lang: str) -> str:
        """Lowercase + strip surrounding punctuation. Greek is also converted to Beta Code."""
        word = word.strip().lower().translate(_STRIP_PUNCT)
        if lang == 'greek':
            # Strip diacritics via NFD decomposition
            nfd = unicodedata.normalize('NFD', word)
            stripped = ''.join(c for c in nfd if unicodedata.category(c) != 'Mn')
            # Convert Greek Unicode letters → ASCII Beta Code
            word = ''.join(_GREEK_TO_BETA.get(c, c) for c in stripped)
        return word

    # ------------------------------------------------------------------
    # Perseus HTTP
    # ------------------------------------------------------------------

    def _fetch_perseus(self, word: str, lang: str) -> tuple[str | None, bool]:
        perseus_lang = 'greek' if lang == 'greek' else 'la'
        try:
            resp = requests.get(
                self.PERSEUS_URL,
                params={'lang': perseus_lang, 'lookup': word},
                timeout=15,
                headers={'User-Agent': 'ClassicusAI/1.0'},
            )
            resp.raise_for_status()
            raw_xml = resp.text
            found = '<analysis>' in raw_xml
            return raw_xml, found
        except requests.RequestException as exc:
            logger.warning('Perseus request failed for %r (%s): %s', word, lang, exc)
            return None, False

    # ------------------------------------------------------------------
    # XML Parsing
    # ------------------------------------------------------------------

    def _parse_xml(self, raw_xml: str) -> list[dict]:
        analyses = []
        try:
            root = ET.fromstring(raw_xml)
        except ET.ParseError as exc:
            logger.warning('XML parse error: %s', exc)
            return analyses

        for analysis in root.findall('analysis'):
            def get(tag):
                el = analysis.find(tag)
                return el.text.strip() if el is not None and el.text else None

            row = {
                'lemma':      get('lemma'),
                'pos':        get('pos'),
                'person':     get('person'),
                'number':     get('number'),
                'tense':      get('tense'),
                'mood':       get('mood'),
                'voice':      get('voice'),
                'case_label': get('case'),
                'gender':     get('gender'),
                'dialect':    get('dialect'),
                'feature':    get('feature'),
            }
            row['display_str'] = self._build_display_str(row)
            analyses.append(row)
        return analyses

    @staticmethod
    def _build_display_str(row: dict) -> str:
        pos = row.get('pos') or ''
        parts = [_POS_ABBR.get(pos, pos)]

        tense  = _TENSE_ABBR.get(row.get('tense') or '', row.get('tense') or '')
        mood   = _MOOD_ABBR.get(row.get('mood') or '', row.get('mood') or '')
        voice  = _VOICE_ABBR.get(row.get('voice') or '', row.get('voice') or '')
        person = _PERSON_ABBR.get(row.get('person') or '', row.get('person') or '')
        number = _NUMBER_ABBR.get(row.get('number') or '', row.get('number') or '')
        case   = _CASE_ABBR.get(row.get('case_label') or '', row.get('case_label') or '')
        gender = _GENDER_ABBR.get(row.get('gender') or '', row.get('gender') or '')

        if pos == 'verb':
            parts += [x for x in [tense, mood, voice, person, number] if x]
        else:
            parts += [x for x in [case, number, gender] if x]

        dialect = row.get('dialect') or ''
        feature = row.get('feature') or ''
        if dialect:
            parts.append(f'[{dialect}]')
        if feature:
            parts.append(f'({feature})')

        return ' '.join(parts).strip()

    # ------------------------------------------------------------------
    # Cache
    # ------------------------------------------------------------------

    def _cache_get(self, word: str, lang: str) -> dict | None:
        row = self._conn.execute(
            'SELECT id, found FROM morph_cache WHERE word=? AND lang=?',
            (word, lang),
        ).fetchone()
        if row is None:
            return None  # cache miss

        analyses = []
        if row['found']:
            for a in self._conn.execute(
                'SELECT lemma, pos, person, number, tense, mood, voice, '
                'case_label, gender, dialect, feature, display_str '
                'FROM morph_analysis WHERE cache_id=?',
                (row['id'],),
            ):
                analyses.append({
                    'lemma':       a['lemma'],
                    'pos':         a['pos'],
                    'display_str': a['display_str'],
                    'details': {
                        'case':    a['case_label'],
                        'number':  a['number'],
                        'gender':  a['gender'],
                        'tense':   a['tense'],
                        'mood':    a['mood'],
                        'voice':   a['voice'],
                        'person':  a['person'],
                        'dialect': a['dialect'],
                        'feature': a['feature'],
                    },
                })
        return self._format_result(word, lang, bool(row['found']), analyses)

    def _cache_set(self, word: str, lang: str, raw_xml: str | None,
                   found: bool, analyses: list[dict]) -> None:
        now = datetime.now(timezone.utc).isoformat()
        cur = self._conn.execute(
            'INSERT OR IGNORE INTO morph_cache (word, lang, queried_at, found, raw_xml) '
            'VALUES (?, ?, ?, ?, ?)',
            (word, lang, now, int(found), raw_xml),
        )
        self._conn.commit()
        cache_id = cur.lastrowid

        # If INSERT was ignored (row already exists), don't re-insert analyses
        if cache_id == 0:
            return

        for a in analyses:
            self._conn.execute(
                'INSERT INTO morph_analysis '
                '(cache_id, lemma, pos, person, number, tense, mood, voice, '
                'case_label, gender, dialect, feature, display_str) '
                'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                (
                    cache_id,
                    a.get('lemma'), a.get('pos'), a.get('person'),
                    a.get('number'), a.get('tense'), a.get('mood'),
                    a.get('voice'), a.get('case_label'), a.get('gender'),
                    a.get('dialect'), a.get('feature'), a.get('display_str'),
                ),
            )
        self._conn.commit()

    # ------------------------------------------------------------------
    # Formatting
    # ------------------------------------------------------------------

    @staticmethod
    def _format_result(word: str, lang: str, found: bool, analyses: list[dict]) -> dict:
        out_analyses = []
        for a in analyses:
            # _parse_xml returns flat dicts; _cache_get returns nested 'details'
            if 'details' in a:
                details = {k: v for k, v in a['details'].items() if v}
            else:
                details = {k: v for k, v in {
                    'case':    a.get('case_label'),
                    'number':  a.get('number'),
                    'gender':  a.get('gender'),
                    'tense':   a.get('tense'),
                    'mood':    a.get('mood'),
                    'voice':   a.get('voice'),
                    'person':  a.get('person'),
                    'dialect': a.get('dialect'),
                    'feature': a.get('feature'),
                }.items() if v}
            out_analyses.append({
                'lemma':       a.get('lemma') or '—',
                'pos':         a.get('pos') or '—',
                'display_str': a.get('display_str') or '—',
                'details':     details,
            })
        return {
            'word':     word,
            'lang':     lang,
            'found':    found and bool(out_analyses),
            'analyses': out_analyses,
        }

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    def _init_db(self) -> None:
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS morph_cache (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                word       TEXT NOT NULL,
                lang       TEXT NOT NULL CHECK(lang IN ('greek', 'latin')),
                queried_at TEXT NOT NULL,
                found      INTEGER NOT NULL DEFAULT 1,
                raw_xml    TEXT,
                UNIQUE(word, lang)
            );

            CREATE TABLE IF NOT EXISTS morph_analysis (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                cache_id    INTEGER NOT NULL REFERENCES morph_cache(id) ON DELETE CASCADE,
                lemma       TEXT,
                pos         TEXT,
                person      TEXT,
                number      TEXT,
                tense       TEXT,
                mood        TEXT,
                voice       TEXT,
                case_label  TEXT,
                gender      TEXT,
                dialect     TEXT,
                feature     TEXT,
                display_str TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_cache_word_lang ON morph_cache(word, lang);
        """)
        self._conn.commit()
