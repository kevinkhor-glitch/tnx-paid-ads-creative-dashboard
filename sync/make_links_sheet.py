"""Create the TNX Creative Links workbook: one row per Meta CR code + market, one row per TikTok ad.

Prefills Notion/Drive links from sync/raw/links.json when present, and adds a Check column where
the Notion page's batch number differs from the ad's batch (worth a look, often a translated batch).
"""
import json, os, re, collections
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
d = json.load(open(os.path.join(ROOT, 'data', 'ads.json')))
lk = json.load(open(os.path.join(ROOT, 'sync', 'raw', 'links.json'))) if os.path.exists(os.path.join(ROOT, 'sync', 'raw', 'links.json')) else []
by_ad = {r['ad_id']: r for r in lk if r['ad_id']}
by_crm = {(r['cr'], r['market']): r for r in lk if not r['ad_id']}
mkt = lambda a: f"{a['mk']}-{a['lg']}" if a['lg'] else a['mk']
rows = collections.OrderedDict()
for a in sorted(d['ads'], key=lambda a: a['cr'], reverse=True):
    if a['p'] == 'tt':
        k = (a['c'], mkt(a), a['id'])
    elif a['c']:
        k = (a['c'], mkt(a), '')
    elif a['st'] == 'Active':
        k = ('', mkt(a), a['id'])
    else:
        continue
    r = rows.setdefault(k, dict(angle=a['an'] or a['n'], batch=a['b'], created=a['cr'], platforms=set(), n=0))
    r['platforms'].add(a['p']); r['n'] += 1
def check(notion, batch):
    nb = re.search(r'Batch-?(\d+)', notion or '', re.I); ab = re.search(r'batch-?(\d+)', batch or '', re.I)
    return f'Notion page is {nb.group(0)}, ad is {batch}' if nb and ab and nb.group(1) != ab.group(1) else ''
wb = Workbook(); ws = wb.active; ws.title = 'Links'
hdr = ['CR Code', 'Market', 'Ad ID', 'Notion Link', 'Drive Folder Link', 'Angle', 'Batch', 'Latest Created', 'Platforms', 'No. of Ads', 'Check']
F = 'Arial'
for j, h in enumerate(hdr, 1):
    c = ws.cell(row=1, column=j, value=h)
    c.font = Font(name=F, bold=True, color='000000' if j in (4, 5) else 'FFFFFF', size=10)
    c.fill = PatternFill('solid', fgColor='FFF2CC' if j in (4, 5) else '1F2A44')
filled = 0
for i, ((cr, mk, ad), r) in enumerate(rows.items(), 2):
    L = by_ad.get(ad) or (by_crm.get((cr, mk)) if not ad else None) or {}
    filled += bool(L)
    vals = [cr, mk, ad, L.get('notion', ''), L.get('drive', ''), r['angle'], r['batch'], r['created'],
            ', '.join(sorted(r['platforms'])), r['n'], check(L.get('notion'), r['batch'])]
    for j, v in enumerate(vals, 1):
        ws.cell(row=i, column=j, value=v).font = Font(name=F, size=10)
for j, w in enumerate([12, 9, 20, 45, 45, 40, 28, 13, 11, 9, 40], 1):
    ws.column_dimensions[chr(64 + j)].width = w
ws.freeze_panes = 'D2'; ws.auto_filter.ref = f'A1:K{len(rows) + 1}'
out = os.path.join(ROOT, 'sync', 'out', 'TNX_Creative_Links.xlsx'); wb.save(out)
print(len(rows), 'rows,', filled, 'prefilled ->', out)
