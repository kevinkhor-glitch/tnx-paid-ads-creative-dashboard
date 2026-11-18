"""One-off: carry Notion and Drive links from the TNX Master Creative Sheet breakdown tabs into the Links sheet.

Input: sync/raw/master_links_raw.json (rows 'ad_name', 'region', 'notion link', 'folder link' per tab,
read from the sheet's HTML view so link addresses are kept). Output: sync/raw/links.json and a report.
"""
import json, re, os, collections
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
o = json.load(open(os.path.join(ROOT, 'sync', 'raw', 'master_links_raw.json')))
ads = json.load(open(os.path.join(ROOT, 'data', 'ads.json')))['ads']
tt_ads = collections.defaultdict(list)   # (cr, market) -> TikTok ad ids
for a in ads:
    if a['p'] == 'tt' and a['c']:
        tt_ads[(a['c'].upper(), f"{a['mk']}-{a['lg']}" if a['lg'] else a['mk'])].append(a['id'])
markets_by_cr = collections.defaultdict(set)
for a in ads:
    if a['c']:
        markets_by_cr[a['c'].upper()].add(f"{a['mk']}-{a['lg']}" if a['lg'] else a['mk'])

def url(c):
    return c[1] if isinstance(c, list) else ''

def market(region, tab):
    r = (region or '').lower().replace(' ', '')
    if tab == 'TH' or r.startswith('th'):
        return 'TH-TH'
    m = re.match(r'my/(en|cn|bm)', r)
    return f'MY-{m.group(1).upper()}' if m else ''   # bare "my": resolved below

found = {}          # (cr, market) -> {notion, drive, src}
tt_rows = {}        # TikTok ad id -> row
conflicts, unmatched = [], []
for tab in ('MY', 'TH', 'TT'):
    t = o[tab]
    n = len(t['ad_name'])
    for i in range(n):
        name = t['ad_name'][i] if isinstance(t['ad_name'][i], str) else t['ad_name'][i][0]
        nl = url(t['notion link'][i]) if i < len(t['notion link']) else ''
        dl = url(t['folder link'][i]) if i < len(t['folder link']) else ''
        if not (nl or dl):
            continue
        m = re.match(r'(CR\d+(?:_\d+)?)', (name or '').strip(), re.I)
        if not m:
            unmatched.append((tab, i, name, 'no CR code')); continue
        cr = m.group(1).upper()
        reg = t['region'][i] if isinstance(t['region'][i], str) else t['region'][i][0]
        mk = market(reg, tab)
        if not mk:
            cands = [x for x in markets_by_cr.get(cr, ()) if re.fullmatch(r'MY-[A-Z]{2}', x)]
            mk = cands[0] if len(cands) == 1 else ''
        if not mk or mk not in markets_by_cr.get(cr, ()):
            # Master sheet region can be off (e.g. a CN ad labelled my/en): fall back to the only market this CR runs in
            country = 'TH' if (tab == 'TH' or (reg or '').lower().startswith('th')) else 'MY'
            only = {x for x in markets_by_cr.get(cr, set()) if x.startswith(country + '-')}
            if len(only) == 1:
                mk = next(iter(only))
            else:
                why = 'CR code not found in Meta/TikTok' if not only else f'region {reg} unclear, {cr} runs in {sorted(only)}'
                unmatched.append((tab, i, name, why)); continue
        if tab == 'TT':
            # TikTok reuses CR codes for different creatives than Meta, so TikTok links go on the TikTok ads by Ad ID
            ids = tt_ads.get((cr, mk), [])
            if not ids:
                unmatched.append((tab, i, name, f'no TikTok ad with {cr} in {mk}')); continue
            for ad_id in ids:
                tt_rows[ad_id] = {'cr': cr, 'market': mk, 'ad_id': ad_id, 'notion': nl, 'drive': dl}
            continue
        prev = found.get((cr, mk))
        new = {'notion': nl, 'drive': dl, 'src': f'{tab} col {i + 2}'}
        if prev:
            if (nl and prev['notion'] and nl != prev['notion']) or (dl and prev['drive'] and dl != prev['drive']):
                conflicts.append((cr, mk, prev['src'], new['src']))
            # newer column (further right) wins; keep the other's value if this one is blank
            new['notion'] = nl or prev['notion']; new['drive'] = dl or prev['drive']
        found[(cr, mk)] = new
rows = [{'cr': cr, 'market': mk, 'ad_id': '', 'notion': v['notion'], 'drive': v['drive']} for (cr, mk), v in found.items()]
rows += list(tt_rows.values())
json.dump(rows, open(os.path.join(ROOT, 'sync', 'raw', 'links.json'), 'w'), indent=1)
json.dump({'conflicts': conflicts, 'unmatched': unmatched}, open(os.path.join(ROOT, 'sync', 'out', 'import_report.json'), 'w'), indent=1)
print('rows:', len(rows), '| TikTok ad-id rows:', len(tt_rows), '| notion:', sum(bool(r['notion']) for r in rows), '| drive:', sum(bool(r['drive']) for r in rows))
print('conflicts:', len(conflicts), '| unmatched columns:', len(unmatched))
print(collections.Counter(u[3].split(',')[0] for u in unmatched))

