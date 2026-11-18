"""One-off: create the TNX Creative Links workbook, one row per CR code + market seen in data/ads.json."""
import json, os, collections
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
d = json.load(open(os.path.join(ROOT, 'data', 'ads.json')))
rows = collections.OrderedDict()
for a in sorted(d['ads'], key=lambda a: a['cr'], reverse=True):
    mk = f"{a['mk']}-{a['lg']}" if a['lg'] else a['mk']
    if a['c']:
        k = (a['c'], mk, '')
    elif a['st'] == 'Active':
        k = ('', mk, a['id'])
    else:
        continue
    if k not in rows:
        rows[k] = dict(name=a['an'] or a['n'], batch=a['b'], created=a['cr'], platforms=set(), n=0)
    rows[k]['platforms'].add(a['p']); rows[k]['n'] += 1
wb = Workbook(); ws = wb.active; ws.title = 'Links'
hdr = ['CR Code', 'Market', 'Ad ID', 'Notion Link', 'Drive Folder Link', 'Angle', 'Batch', 'Latest Created', 'Platforms', 'No. of Ads']
F = 'Arial'
for j, h in enumerate(hdr, 1):
    c = ws.cell(row=1, column=j, value=h)
    c.font = Font(name=F, bold=True, color='FFFFFF' if j not in (4, 5) else '000000', size=10)
    c.fill = PatternFill('solid', fgColor='FFF2CC' if j in (4, 5) else '1F2A44')
for i, ((cr, mk, ad), r) in enumerate(rows.items(), 2):
    for j, v in enumerate([cr, mk, ad, '', '', r['name'], r['batch'], r['created'], ', '.join(sorted(r['platforms'])), r['n']], 1):
        c = ws.cell(row=i, column=j, value=v); c.font = Font(name=F, size=10)
for j, w in enumerate([12, 9, 20, 45, 45, 40, 28, 13, 11, 9], 1):
    ws.column_dimensions[chr(64 + j)].width = w
ws.freeze_panes = 'D2'
ws.auto_filter.ref = f'A1:J{len(rows) + 1}'
out = os.path.join(ROOT, 'sync', 'out', 'TNX_Creative_Links.xlsx'); wb.save(out)
print(len(rows), out)
