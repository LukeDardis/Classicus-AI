"""
export_cache.py — Export morphology.db → morph_cache.json

Produces:
  {
    "greek": { "betacode_word": [{lemma, pos, display_str, details}, ...], ... },
    "latin": { "lowercase_word": [{...}, ...], ... }
  }

Only rows with found=1 are exported.  Miss rows (found=0) are omitted
because the JS will try Perseus live for any cache miss.
"""
import sqlite3, json, sys
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')

PROJECT = Path(__file__).parent
DB      = PROJECT / 'morphology.db'
OUT     = PROJECT / 'morph_cache.json'

def build():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row

    data = {'greek': {}, 'latin': {}}

    cache_rows = conn.execute(
        "SELECT id, word, lang FROM morph_cache WHERE found=1"
    ).fetchall()

    for crow in cache_rows:
        analyses = conn.execute(
            """SELECT lemma, pos, display_str,
                      case_label, number, gender,
                      tense, mood, voice, person, dialect, feature
               FROM morph_analysis WHERE cache_id=?""",
            (crow['id'],)
        ).fetchall()

        if not analyses:
            continue

        entries = []
        for a in analyses:
            details = {}
            for field in ('case_label','number','gender','tense','mood',
                          'voice','person','dialect','feature'):
                val = a[field]
                key = 'case' if field == 'case_label' else field
                if val:
                    details[key] = val
            entries.append({
                'lemma':       a['lemma'],
                'pos':         a['pos'],
                'display_str': a['display_str'],
                'details':     details,
            })

        data[crow['lang']][crow['word']] = entries

    conn.close()
    return data

if __name__ == '__main__':
    print('Exporting morphology cache…')
    data = build()
    greek_n = len(data['greek'])
    latin_n = len(data['latin'])
    print(f'  Greek: {greek_n} words,  Latin: {latin_n} words')

    json_str = json.dumps(data, ensure_ascii=False, separators=(',', ':'))
    size_kb  = len(json_str.encode('utf-8')) / 1024
    print(f'  Size:  {size_kb:.1f} KB')

    OUT.write_text(json_str, encoding='utf-8')
    print(f'  Written → {OUT}')
