"""
Flask server for Classicus AI.
  /           → serves classicus-ai-final.html
  /api/morph  → morphological analysis via Perseus + SQLite cache
"""

from pathlib import Path

from flask import Flask, jsonify, request, send_file

from morphology_engine import MorphologyEngine

app = Flask(__name__)
engine = MorphologyEngine(db_path=Path(__file__).parent / 'morphology.db')


@app.route('/')
def index():
    return send_file(Path(__file__).parent / 'classicus-ai-final.html')


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


if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5000, debug=True)
