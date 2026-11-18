"""Turn the TNX Creative Links sheet into sync/raw/links.json.

Input: the JSON result of Google Drive get_file_metadata (snippetVerbosity=MAX_ALLOWED)
for the Links sheet, saved to a file. Drive's text snapshot drops empty cells, so columns
can't be read by position; each value is recognised by what it looks like instead:
  CR code  CR12 / CR12_3      market  MY-EN, TH-TH ...     ad id  15+ digit number
  Notion   notion.so / notion.site / notion.com URL                     Drive  drive.google.com / docs.google.com URL
Usage: python3 sync/read_links.py <metadata.json>
"""
import json, re, sys, os
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
raw = open(sys.argv[1]).read()
try:
    d = json.loads(raw)
    if isinstance(d, list):
        d = json.loads(d[0]['text'])
    text = d.get('contentSnippet', '')
except ValueError:
    text = raw
rows = []
for line in text.splitlines():
    toks = [t.strip() for t in line.split(',')]
    if not toks or toks[0] in ('CR Code', '```', '') and not any('http' in t for t in toks):
        continue
    r = {'cr': '', 'market': '', 'ad_id': '', 'notion': '', 'drive': ''}
    for t in toks:
        if not r['cr'] and re.fullmatch(r'CR\d+(?:_\d+)?', t, re.I): r['cr'] = t.upper()
        elif not r['market'] and re.fullmatch(r'[A-Z]{2}(?:-[A-Z]{2})+|[A-Z]{2}', t): r['market'] = t
        elif not r['ad_id'] and re.fullmatch(r'\d{15,}', t): r['ad_id'] = t
        elif not r['notion'] and re.search(r'notion\.(so|site|com)/', t): r['notion'] = t
        elif not r['drive'] and re.search(r'(drive|docs)\.google\.com/', t): r['drive'] = t
    if r['notion'] or r['drive']:
        rows.append(r)
os.makedirs(os.path.join(ROOT, 'sync', 'raw'), exist_ok=True)
json.dump(rows, open(os.path.join(ROOT, 'sync', 'raw', 'links.json'), 'w'), indent=1)
print(f'{len(rows)} rows with links')
