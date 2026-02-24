"""
Flask server for Classicus AI.
  /                → serves index.html
  /api/morph       → morphological analysis via Perseus + SQLite cache
  /api/greek-mass  → proxy: fetches Universalis Greek NT readings by date
"""

import html as html_mod
import re
import urllib.request
from pathlib import Path

from flask import Flask, jsonify, request, send_file

from morphology_engine import MorphologyEngine

app = Flask(__name__)
engine = MorphologyEngine(db_path=Path(__file__).parent / 'morphology.db')


@app.route('/')
def index():
    return send_file(Path(__file__).parent / 'index.html')


@app.route('/api/morph')
def api_morph():
    word = request.args.get('word', '').strip()
    lang = request.args.get('lang', '').strip()
    if not word:
        return jsonify({'error': "Missing 'word' parameter"}), 400
    if not lang:
        return jsonify({'error': "Missing 'lang' parameter"}), 400
    try:
        return jsonify(engine.lookup(word, lang))
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400


@app.route('/api/greek-mass')
def api_greek_mass():
    date_str = request.args.get('date', '').strip()
    if not date_str or not date_str.isdigit() or len(date_str) != 8:
        return jsonify({'error': 'Invalid date parameter'}), 400

    url = f'https://universalis.com/G/{date_str}/mass.htm'
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=10) as r:
            page_html = r.read().decode('utf-8')
    except Exception as exc:
        return jsonify({'error': str(exc)}), 502

    _type_map = {
        'first reading': 'Mass_R1',
        'second reading': 'Mass_R2',
        'gospel': 'Mass_G',
    }

    readings = {}
    for m in re.finditer(r'class="parallelR">(.*?)</td>', page_html, re.DOTALL):
        section = m.group(1)
        heading_m = re.search(
            r'<th[^>]*>(.*?)</th>.*?<th[^>]*>(.*?)</th>', section, re.DOTALL
        )
        if not heading_m:
            continue
        reading_type_raw = html_mod.unescape(
            re.sub(r'<[^>]+>', '', heading_m.group(1))
        ).strip()
        citation = html_mod.unescape(
            re.sub(r'<[^>]+>', '', heading_m.group(2))
        ).strip()
        reading_key = _type_map.get(reading_type_raw.lower())
        if not reading_key:
            continue

        # Strip heading table, then split on versenumber spans to extract verses
        body = re.sub(r'<table.*?</table>', '', section, flags=re.DOTALL)
        parts = re.split(
            r'<span[^>]*class="versenumber"[^>]*>(\d+)</span>', body
        )
        verses = []
        i = 1
        while i < len(parts) - 1:
            verse_num = int(parts[i])
            verse_text = html_mod.unescape(re.sub(r'<[^>]+>', ' ', parts[i + 1]))
            verse_text = re.sub(r'\s+', ' ', verse_text).strip()
            if verse_text:
                verses.append({'v': verse_num, 't': verse_text})
            i += 2

        if verses:
            readings[reading_key] = {'citation': citation, 'verses': verses}

    return jsonify(readings)


if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5000, debug=True)
