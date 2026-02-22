"""Re-embed MORPH_DATA from morphology.db into classicus-ai-final.html and index.html."""
import sqlite3, json, re, sys
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')

PROJECT = Path(__file__).parent
DB = PROJECT / 'morphology.db'
HTML_FILES = [PROJECT / 'classicus-ai-final.html', PROJECT / 'index.html']

def build_morph_data():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    data = {'greek': {}, 'latin': {}}

    cache_rows = conn.execute(
        "SELECT id, word, lang FROM morph_cache WHERE found=1"
    ).fetchall()

    for crow in cache_rows:
        analyses = conn.execute(
            """SELECT lemma, pos, display_str, case_label, number, gender,
                      tense, mood, voice, person, dialect, feature
               FROM morph_analysis WHERE cache_id=?""",
            (crow['id'],)
        ).fetchall()

        if not analyses:
            continue

        entries = []
        for a in analyses:
            details = {}
            for field in ('case_label','number','gender','tense','mood','voice','person','dialect','feature'):
                val = a[field]
                key = 'case' if field == 'case_label' else field
                if val:
                    details[key] = val
            entries.append({
                'lemma': a['lemma'],
                'pos': a['pos'],
                'display_str': a['display_str'],
                'details': details
            })

        data[crow['lang']][crow['word']] = entries

    conn.close()
    return data

def embed(html_path, morph_json):
    text = html_path.read_text(encoding='utf-8')
    new_decl = f'const MORPH_DATA = {morph_json};'
    # Replace from 'const MORPH_DATA = ' up to the closing ';'
    new_text = re.sub(
        r'const MORPH_DATA = \{.*?\};',
        new_decl,
        text,
        count=1,
        flags=re.DOTALL
    )
    if new_text == text:
        print(f"  WARNING: MORPH_DATA pattern not found in {html_path.name}")
        return False
    html_path.write_text(new_text, encoding='utf-8')
    return True

if __name__ == '__main__':
    print("Building MORPH_DATA from SQLite cache...")
    data = build_morph_data()
    greek_count = len(data['greek'])
    latin_count = len(data['latin'])
    print(f"  Greek: {greek_count} words, Latin: {latin_count} words")

    morph_json = json.dumps(data, ensure_ascii=False, separators=(',', ':'))
    size_kb = len(morph_json.encode('utf-8')) / 1024
    print(f"  JSON size: {size_kb:.1f} KB")

    for html_file in HTML_FILES:
        if html_file.exists():
            ok = embed(html_file, morph_json)
            if ok:
                print(f"  Embedded into {html_file.name}")
        else:
            print(f"  Skipping {html_file.name} (not found)")

    print("Done.")
