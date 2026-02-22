"""
_patch_html.py — Replace embedded MORPH_DATA + synchronous showDefinition
with a fetch-based JSON loader + async showDefinition with live Perseus fallback.

Run once:  python _patch_html.py
"""
import re, sys
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')
PROJECT = Path(__file__).parent

# ── New declarations to replace the giant embedded MORPH_DATA block ──────────
NEW_DECLARATIONS = r"""let MORPH_DATA = null;
        let _morphDataPromise = null;

        // ── Load the morphology cache from the external JSON file ────────────
        async function loadMorphData() {
            if (MORPH_DATA) return MORPH_DATA;
            if (!_morphDataPromise) {
                _morphDataPromise = fetch('morph_cache.json')
                    .then(r => { if (!r.ok) throw new Error(r.status); return r.json(); })
                    .then(d => { MORPH_DATA = d; return d; })
                    .catch(() => { MORPH_DATA = { greek: {}, latin: {} }; return MORPH_DATA; });
            }
            return _morphDataPromise;
        }

        // ── Live fallback: query Perseus via a CORS proxy ────────────────────
        // Perseus xmlmorph doesn't send CORS headers, so direct browser fetches
        // are blocked.  We route through allorigins.win as a transparent proxy.
        async function lookupPerseus(word, lang) {
            const persLang = lang === 'greek' ? 'greek' : 'la';
            const key = _normalizeMorphKey(word, lang);
            // Perseus needs Beta Code for Greek (key is already normalised).
            const target = 'https://www.perseus.tufts.edu/hopper/xmlmorph'
                + '?lang=' + persLang + '&lookup=' + encodeURIComponent(key);

            // Try direct first (works if Perseus ever adds CORS headers),
            // then fall back to the allorigins proxy.
            const urls = [
                target,
                'https://api.allorigins.win/raw?url=' + encodeURIComponent(target)
            ];
            for (const url of urls) {
                try {
                    const r = await fetch(url);
                    if (!r.ok) continue;
                    const xml = await r.text();
                    const result = _parsePerseusXml(xml);
                    if (result) return result;
                } catch (_) { /* try next */ }
            }
            return null;
        }

        // ── Parse Perseus xmlmorph XML response ──────────────────────────────
        function _parsePerseusXml(xml) {
            if (!xml || !xml.includes('<analysis>')) return null;
            const doc  = new DOMParser().parseFromString(xml, 'text/xml');
            const nodes = [...doc.querySelectorAll('analysis')];
            if (!nodes.length) return null;
            return nodes.map(node => {
                const get = tag => node.querySelector(tag)?.textContent?.trim() || null;
                const pos   = get('pos');
                const lemma = get('lemma');
                const details = {};
                for (const f of ['case','number','gender','tense','mood',
                                  'voice','person','dialect','feature']) {
                    const v = get(f); if (v) details[f] = v;
                }
                return { lemma, pos, display_str: _buildDisplayStr(pos, details), details };
            });
        }

        // ── Build a human-readable parse summary ─────────────────────────────
        function _buildDisplayStr(pos, det) {
            if (!pos) return '\u2014';
            const parts = [pos];
            if (det.tense)   parts.push(det.tense   + '.');
            if (det.mood)    parts.push(det.mood     + '.');
            if (det.voice)   parts.push(det.voice    + '.');
            if (det.person)  parts.push(det.person   + '.');
            if (det.number)  parts.push(det.number   + '.');
            if (det.case)    parts.push(det.case     + '.');
            if (det.gender)  parts.push(det.gender   + '.');
            if (det.dialect) parts.push('[' + det.dialect + ']');
            if (det.feature) parts.push('(' + det.feature + ')');
            return parts.join(' ');
        }"""

# ── New async showDefinition ─────────────────────────────────────────────────
NEW_SHOW_DEF = r"""async function showDefinition(word, lang) {
            document.querySelectorAll('.word').forEach(w => w.classList.remove('selected'));
            event.target.classList.add('selected');

            const popup   = document.getElementById('dict-popup');
            const content = document.getElementById('dict-content');

            // Show spinner immediately while we fetch
            content.innerHTML = `
                <div class="dict-word">${word}</div>
                <div class="dict-loading">
                    <div class="dict-spinner"></div>Looking up morphology\u2026
                </div>`;
            popup.classList.add('active');

            // 1. Check JSON cache
            const cache = await loadMorphData();
            const key   = _normalizeMorphKey(word, lang);
            let analyses = (cache[lang] || {})[key] || null;

            // 2. Live Perseus lookup for cache misses
            if (!analyses) {
                analyses = await lookupPerseus(word, lang);
                // Store in session cache so repeat clicks are instant
                if (analyses && cache[lang]) cache[lang][key] = analyses;
            }

            if (!analyses || !analyses.length) {
                content.innerHTML = `
                    <div class="dict-word">${word}</div>
                    <div class="dict-not-found">No morphological data found for this word.</div>`;
                return;
            }

            const count = analyses.length;
            const analysesHTML = analyses.map((a, i) => {
                const detailItems = Object.entries(a.details || {})
                    .map(([k, v]) => `<span class="dict-parse-item"><span class="dict-parse-label">${k}:</span> ${v}</span>`)
                    .join('');
                return `
                    <div class="dict-analysis-block">
                        ${count > 1 ? `<div class="dict-analysis-num">Analysis ${i+1} of ${count}</div>` : ''}
                        <div class="dict-section" style="margin-top:0">
                            <div class="dict-label">Lemma</div>
                            <div class="dict-content">${a.lemma || '\u2014'}</div>
                        </div>
                        <div class="dict-section">
                            <div class="dict-label">Part of Speech</div>
                            <div class="dict-content">${a.pos || '\u2014'}</div>
                        </div>
                        ${detailItems ? `<div class="dict-section">
                            <div class="dict-label">Grammatical Parse</div>
                            <div class="dict-parse">${detailItems}</div>
                        </div>` : ''}
                        <div class="dict-section">
                            <div class="dict-label">Parse Summary</div>
                            <div class="dict-content" style="font-style:italic">${a.display_str || '\u2014'}</div>
                        </div>
                    </div>`;
            }).join('');

            content.innerHTML = `<div class="dict-word">${word}</div>${analysesHTML}`;
        }"""


def patch(html_path: Path) -> None:
    text = html_path.read_text(encoding='utf-8')
    original_len = len(text)

    # ── 1. Replace embedded MORPH_DATA with slim declaration + new helpers ───
    n1 = [0]
    def _repl_decl(m):
        n1[0] += 1
        return NEW_DECLARATIONS
    text = re.sub(r'const MORPH_DATA = \{.*?\};', _repl_decl, text, count=1, flags=re.DOTALL)
    if n1[0] == 0:
        # Already patched (MORPH_DATA removed) — check whether we need to
        # insert the declarations before _GREEK_TO_BETA.
        if 'let MORPH_DATA = null' not in text:
            print(f'  WARNING: could not locate MORPH_DATA block in {html_path.name}')

    # ── 2. Replace showDefinition (sync → async) ─────────────────────────────
    # Find precise boundaries: from 'function showDefinition' up to (but not
    # including) the line that begins 'function closeDictionary'.
    start = text.find('function showDefinition(word, lang)')
    if start == -1:
        start = text.find('async function showDefinition(word, lang)')
    end_marker = text.find('function closeDictionary()', start if start != -1 else 0)

    if start != -1 and end_marker != -1:
        # Walk back to eat leading whitespace on the replacement line
        while start > 0 and text[start - 1] in (' ', '\t'):
            start -= 1
        text = text[:start] + '        ' + NEW_SHOW_DEF + '\n        ' + text[end_marker:]
    else:
        print(f'  WARNING: could not locate showDefinition in {html_path.name}')

    # ── 3. Kick off JSON preload at startup ───────────────────────────────────
    text = text.replace(
        'window.onload = init;',
        'window.onload = () => { init(); loadMorphData(); };'
    )

    html_path.write_text(text, encoding='utf-8')
    delta = len(text) - original_len
    print(f'  {html_path.name}: {delta:+,} bytes  ({len(text)//1024} KB total)')


if __name__ == '__main__':
    for name in ('classicus-ai-final.html', 'index.html'):
        p = PROJECT / name
        if p.exists():
            print(f'Patching {name}…')
            patch(p)
        else:
            print(f'Skipping {name} (not found)')
    print('Done.')
