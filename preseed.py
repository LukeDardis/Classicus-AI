"""
preseed.py — Pre-seed the morphology SQLite cache by extracting every word
from the corpus in classicus-ai-final.html and querying Perseus for each one.

Usage:
    python preseed.py [path/to/classicus-ai-final.html]

Resume-safe: words already in the DB are skipped (no API calls made).
Rate: ~1.5 s per new word to respect Perseus rate limits.
Covers: all texts in const texts{} AND Greek/Latin verses in BIBLE_TEXTS.
"""

import re
import sys
import time

sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')
from pathlib import Path

from morphology_engine import MorphologyEngine

_PUNCT = set('·,;:.!?—()[]«»""\'\'')

# Characters that look like punctuation / dashes used as separators in corpus
_STRIP_RE = re.compile(r'^[·,;:.!?—()\[\]«»""\'\']+|[·,;:.!?—()\[\]«»""\'\']+$')


_JUNK_RE = re.compile(r'[^\w\u0370-\u03FF\u1F00-\u1FFF]')  # must contain a real letter


def _tokenize(text: str, lang: str, freq: dict) -> None:
    """Tokenize a block of text and count word frequencies in-place."""
    for raw_token in re.split(r'[\s\n\r]+', text):
        token = _STRIP_RE.sub('', raw_token).lower()
        # Must be ≥2 chars, contain at least one letter (not pure punct/digits)
        if len(token) >= 2 and re.search(r'[a-zA-Z\u0370-\u03FF\u1F00-\u1FFF]', token):
            freq[token] = freq.get(token, 0) + 1


def extract_corpus_words(html_path: Path) -> dict[str, list[str]]:
    """
    Returns {'greek': [word, ...], 'latin': [word, ...]} sorted by frequency
    (most common first) so the preseed covers high-frequency vocabulary first.
    """
    source = html_path.read_text(encoding='utf-8')

    freq: dict[str, dict[str, int]] = {'greek': {}, 'latin': {}}

    # ── Regular texts (const texts = { greek: [...], latin: [...] }) ──────────
    match = re.search(
        r'const texts\s*=\s*\{(.+?)const BIBLE_BOOKS',
        source,
        re.DOTALL,
    )
    if not match:
        raise ValueError("Could not find 'const texts' block in HTML")

    texts_block = match.group(1)

    for lang in ('greek', 'latin'):
        lang_pattern = re.compile(
            rf'{lang}\s*:\s*\[(.+?)(?:(?:greek|latin)\s*:|\Z)',
            re.DOTALL,
        )
        lang_match = lang_pattern.search(texts_block)
        if not lang_match:
            print(f'  Warning: no {lang} section found in const texts')
            continue

        for content_match in re.finditer(r'content\s*:\s*`([^`]+)`', lang_match.group(1), re.DOTALL):
            _tokenize(content_match.group(1), lang, freq[lang])

    # ── Bible texts (BIBLE_TEXTS = { matthew: { 1: [{g:"...",l:"..."},...] }}  ──
    bible_match = re.search(r'const BIBLE_TEXTS\s*=\s*\{(.+?)\n        \};', source, re.DOTALL)
    if bible_match:
        bible_block = bible_match.group(1)
        for verse in re.findall(r'g\s*:\s*"([^"]+)"', bible_block):
            _tokenize(verse, 'greek', freq['greek'])
        for verse in re.findall(r'l\s*:\s*"([^"]+)"', bible_block):
            _tokenize(verse, 'latin', freq['latin'])
    else:
        print('  Warning: BIBLE_TEXTS block not found — Bible words not extracted')

    # Return deduplicated lists sorted by frequency descending
    return {
        lang: [w for w, _ in sorted(f.items(), key=lambda x: -x[1])]
        for lang, f in freq.items()
    }


def main() -> None:
    html_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path('classicus-ai-final.html')
    if not html_path.exists():
        sys.exit(f'Error: HTML file not found: {html_path}')

    print(f'Extracting corpus from {html_path}…')
    corpus = extract_corpus_words(html_path)
    for lang, words in corpus.items():
        print(f'  {lang}: {len(words)} unique tokens')

    engine = MorphologyEngine(db_path=Path(__file__).parent / 'morphology.db')
    print()

    for lang in ('greek', 'latin'):
        words = sorted(corpus[lang])
        total = len(words)
        cached_count = 0
        api_count = 0
        print(f'--- {lang.upper()}: {total} words ---')

        for i, word in enumerate(words, 1):
            normalized = engine._normalize_word(word, lang)
            if not normalized:
                continue

            if engine._cache_get(normalized, lang) is not None:
                cached_count += 1
                continue

            result = engine.lookup(word, lang)
            api_count += 1

            status = 'found' if result['found'] else 'miss'
            if api_count <= 10:
                # Log raw XML for the first 10 real API calls for verification
                raw = engine._conn.execute(
                    'SELECT raw_xml FROM morph_cache WHERE word=? AND lang=?',
                    (normalized, lang),
                ).fetchone()
                if raw and raw[0]:
                    print(f'  [{i}/{total}] {word!r} ({normalized}) → {status}')
                    print(f'  XML: {raw[0][:300]}')
                else:
                    print(f'  [{i}/{total}] {word!r} ({normalized}) → {status} (no xml)')
            elif api_count % 50 == 0 or i == total:
                print(f'  [{i}/{total}] {api_count} API calls, {cached_count} cached hits so far')

            time.sleep(1.5)

        print(f'Done {lang}: {api_count} new API calls, {cached_count} already cached.\n')

    # Final summary
    conn = engine._conn
    print('=== Database summary ===')
    for lang in ('greek', 'latin'):
        total_words = len(corpus[lang])
        row = conn.execute(
            'SELECT COUNT(*) as c FROM morph_cache WHERE lang=?', (lang,)
        ).fetchone()
        cached = row['c'] if row else 0
        row2 = conn.execute(
            'SELECT COUNT(*) as c FROM morph_cache WHERE lang=? AND found=1', (lang,)
        ).fetchone()
        found = row2['c'] if row2 else 0
        pct = 100 * found // total_words if total_words else 0
        print(f'  {lang}: {cached}/{total_words} cached, {found} with analyses ({pct}%)')


if __name__ == '__main__':
    main()
