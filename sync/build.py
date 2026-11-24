"""Build the TNX Creative Library from raw Meta + TikTok pulls.

Inputs (sync/raw/, written by the Claude sync run, see SYNC.md):
  ads_all.json     Meta ads (ads_get_ad_entities, level=ad)
  creatives.json   Meta creatives keyed by creative id (ads_get_creatives)
  videos.json      Meta video thumbnails keyed by video id (ads_get_ad_videos)
  tt_sp.json       TikTok Smart+ ads (smart_plus_ad_get raw response)
Outputs:
  sync/out/TNX_Creative_Library.xlsx   workbook for the Google Sheet
  data/ads.json                        data the dashboard reads
Usage: python3 sync/build.py  (run from the repo root)
"""
import json, re, collections, datetime
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.comments import Comment
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

import os
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
D = os.path.join(ROOT, 'sync', 'raw') + '/'
RUN_AT = os.environ.get('RUN_AT') or datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).strftime('%Y-%m-%d %H:%M MYT')
META_ACCT = '535902558289665'
TT_ADV = '7533075564996100097'

ads = json.load(open(D + 'ads_all.json'))
cr = json.load(open(D + 'creatives.json'))
tt = json.load(open(D + 'tt_sp.json'))['data']['list']
vids = json.load(open(D + 'videos.json'))

COUNTRIES = {'my', 'th', 'sg', 'hk', 'my-th'}
LANGS = {'en', 'cn', 'bm', 'th', 'en-th'}
FORMATS = {'video', 'static', 'image', 'img', 'carousel'}
OBJECTIVES = {'opportunity', 'registration', 'reach', 'lead', 'conversion', 'awareness'}
CAMP_TYPES = {'evergreen', 'omni', 'offer'}
CR_RE = re.compile(r'(CR\d+(?:_\d+)?)')


def clean_prefix(name):
    n = name
    m = re.match(r'^\(WRONG AD NAME\)\s*', n)
    if m:
        n = n[m.end():]
    # TikTok ad_get names start with "<file>.mp4_" — Smart+ names don't, but be safe
    m = re.search(r'(?:^|_)((?:tt|fb|ig)/tnx/.*)$', n)
    if m:
        n = m.group(1)
    return n


def parse_date(s):
    if not re.fullmatch(r'\d{8}', s):
        return None
    try:
        if s.startswith('20'):
            return datetime.date(int(s[:4]), int(s[4:6]), int(s[6:]))
        return datetime.date(int(s[4:]), int(s[2:4]), int(s[:2]))  # DDMMYYYY
    except ValueError:
        return None


def parse_name(name):
    n = re.sub(r'\s*\([^)]*\)\s*$', '', clean_prefix(name))
    s = n.split('/')
    out = dict(platform=s[0].lower() if s else '', country='', language='', camp_type='',
               objective='', destination='', targeting='', batch='', name_date=None,
               framework='', fmt='', hook='', angle='', cr='')
    i = 2
    if len(s) > i and s[i].lower() in COUNTRIES:
        out['country'] = s[i].lower(); i += 1
    if len(s) > i and s[i].lower() in LANGS:
        out['language'] = s[i].lower(); i += 1
    for seg in s:
        if not out['objective'] and seg.lower() in OBJECTIVES:
            out['objective'] = seg.lower()
        if not out['camp_type'] and seg.lower() in CAMP_TYPES:
            out['camp_type'] = seg.lower()
        if not out['batch'] and 'batch' in seg.lower():
            out['batch'] = seg
        if out['name_date'] is None and parse_date(seg):
            out['name_date'] = parse_date(seg)
        if seg.startswith('prospecting') and not out['destination']:
            d = seg.split('-', 1)
            out['destination'] = d[1] if len(d) > 1 else ''
    codes = CR_RE.findall(n)
    out['cr'] = codes[-1] if codes else ''
    # format + what follows it
    fi = next((k for k, seg in enumerate(s) if seg.lower() in FORMATS), None)
    if fi is not None:
        out['fmt'] = {'img': 'image'}.get(s[fi].lower(), s[fi].lower())
        # framework = segments between the date and the format (new convention)
        di = next((k for k, seg in enumerate(s) if parse_date(seg)), None)
        if di is not None and di < fi:
            out['framework'] = '/'.join(x for x in s[di + 1:fi] if x)
        rest = [x for x in s[fi + 1:] if x and not CR_RE.search(x) and not re.fullmatch(r'v\d+c\d+', x)
                and not re.fullmatch(r'(HE|CO|DE)\d+(_\d+)?', x)]
        if len(rest) >= 2:
            out['hook'] = rest[0]; out['angle'] = '/'.join(rest[1:])
        elif rest:
            out['angle'] = rest[0]
    # targeting: segment right after the prospecting segment
    pi = next((k for k, seg in enumerate(s) if seg.startswith('prospecting')), None)
    if pi is not None and pi + 1 < len(s):
        t = s[pi + 1]
        if not parse_date(t) and 'batch' not in t.lower():
            out['targeting'] = t
    return out


MYT = datetime.timezone(datetime.timedelta(hours=8))
def meta_time(t):   # '2026-11-18T12:51:49+0800'
    return datetime.datetime.strptime(t, '%Y-%m-%dT%H:%M:%S%z').astimezone(MYT)
def tt_time(t):     # '2026-11-12 06:21:08' in UTC
    return datetime.datetime.strptime(t, '%Y-%m-%d %H:%M:%S').replace(tzinfo=datetime.timezone.utc).astimezone(MYT)


def camp_group(objective):
    return {'opportunity': 'Lead Gen', 'lead': 'Lead Gen', 'conversion': 'Lead Gen',
            'registration': 'Registration', 'reach': 'Awareness',
            'awareness': 'Awareness'}.get(objective, 'Other')


def camp_theme(cname):
    s = [x for x in cname.split('/') if x]
    last = s[-1] if s else ''
    last = re.sub(r'\s*\(.*?\)\s*', '', last).strip()
    if last.startswith('prospecting-') and last.split('-', 1)[1] not in ('leadform', 'order', 'lp'):
        return last.split('-', 1)[1]
    if last.startswith('prospecting') or last in ('retargeting',):
        return ''
    return last


def dest_label(d):
    return {'leadform': 'Lead form', 'order': 'Sign-up page', 'lp': 'Landing page'}.get(d, '')


def market_label(country, lang):
    c = country.upper() if country else '?'
    return f"{c}-{lang.upper()}" if lang else c


# ---------- Meta campaigns from ads ----------
camps = {}
for a in ads:
    camps.setdefault(a['campaign_id'], a['campaign_name'])

meta_rows = []
for a in ads:
    p = parse_name(a['name'])
    cp = parse_name(a['campaign_name'])
    c = cr.get(a['creative_id'], {})
    afs = c.get('asset_feed_spec') or {}
    body = c.get('body') or '\n\n---\n\n'.join(b.get('text', '') for b in afs.get('bodies', []))
    title = c.get('title') or ' | '.join(t.get('text', '') for t in afs.get('titles', []))
    cta = c.get('call_to_action_type') or ', '.join(afs.get('call_to_action_types', []) or [])
    link = c.get('link_url') or ', '.join(l.get('website_url', '') for l in afs.get('link_urls', []) or [])
    vid = c.get('video_id') or next((v['video_id'] for v in afs.get('videos', [])), None)
    vinfo = vids.get(vid or '', {})
    img = c.get('image_url') or vinfo.get('pic') or c.get('thumbnail_url') or ''
    video_url = ('https://www.facebook.com' + vinfo['perm']) if vinfo.get('perm') else ''
    # Creatives in this ad: carousel = number of cards; flexible (non-placement) = number of
    # images + videos; placement-size variants of one creative and single image/video = 1.
    kids = c.get('child_attachments') or []
    if kids:
        n_cre = len(kids)
    elif afs and afs.get('optimization_type') != 'PLACEMENT':
        n_cre = max(1, len(afs.get('images') or []) + len(afs.get('videos') or []))
    else:
        n_cre = 1
    meta_rows.append(dict(
        ad_id=a['id'], platform=p['platform'], country=cp['country'] or p['country'],
        language=cp['language'] or p['language'], group=camp_group(cp['objective']),
        theme=camp_theme(a['campaign_name']), destination=dest_label(cp['destination'] or p['destination']),
        campaign_id=a['campaign_id'], campaign=a['campaign_name'], adset_id=a['adset_id'],
        adset=a['adset_name'], ad_name=a['name'], status=a['effective_status'],
        created=meta_time(a['created_time']).date(), created_ts=meta_time(a['created_time']), name_date=p['name_date'],
        batch=p['batch'], framework=p['framework'], fmt=p['fmt'], hook=p['hook'], angle=p['angle'],
        cr=p['cr'], targeting=p['targeting'], creative_id=a['creative_id'],
        creative_type=c.get('object_type', ''), flexible='Yes' if afs else 'No',
        headline=title, primary=body, cta=cta, link=link, img=img, video_url=video_url, is_video=bool(vid), n_creatives=n_cre,
        name_objective=p['objective'], camp_objective=cp['objective'],
        name_country=p['country'], name_lang=p['language']))

# ---------- TikTok ----------
tt_rows = []
tt_camps = {}
for x in tt:
    p = parse_name(x['ad_name'])
    cp = parse_name(x['campaign_name'])
    tt_camps.setdefault(x['campaign_id'], (x['campaign_name'], x.get('create_time', '')))
    files = [cl.get('creative_info', {}).get('material_name', '') for cl in x.get('creative_list', [])]
    fmts = {cl.get('creative_info', {}).get('ad_format', '') for cl in x.get('creative_list', [])}
    texts = [t['ad_text'] for t in x.get('ad_text_list', [])]
    tt_rows.append(dict(
        ad_id=x['smart_plus_ad_id'], platform='tt', country=cp['country'] or p['country'],
        language=cp['language'] or p['language'], group=camp_group(cp['objective']),
        theme=camp_theme(x['campaign_name']), destination=dest_label(cp['destination']),
        campaign_id=x['campaign_id'], campaign=x['campaign_name'], adset_id=x['adgroup_id'],
        adset=x['adgroup_name'], ad_name=x['ad_name'], status=x.get('effective_status', ''),
        created=tt_time(x['create_time']).date(), created_ts=tt_time(x['create_time']), name_date=p['name_date'],
        batch=p['batch'], framework=p['framework'], fmt=p['fmt'], hook=p['hook'], angle=p['angle'],
        cr=p['cr'], targeting=p['targeting'], n_creatives=len(files), files='\n'.join(files),
        tt_format=', '.join(sorted(f for f in fmts if f)), ad_text='\n\n---\n\n'.join(texts),
        name_objective=p['objective'], camp_objective=cp['objective'],
        name_country=p['country'], name_lang=p['language']))

# ---------- Name issues ----------
issues = []
def flag(r, platform, issue, detail):
    issues.append([r['ad_id'], platform, r['ad_name'], issue, detail])

all_rows = [(r, 'Meta') for r in meta_rows] + [(r, 'TikTok') for r in tt_rows]
for r, plat in all_rows:
    n = r['ad_name']
    if n.startswith('(WRONG AD NAME)'):
        flag(r, plat, 'Marked as wrong name', 'Ad name starts with "(WRONG AD NAME)".')
    if '//' in clean_prefix(n):
        flag(r, plat, 'Empty segment', 'Name contains "//" (a blank segment).')
    if re.search(r'[ ?]', clean_prefix(n)):
        flag(r, plat, 'Space or ? in name', 'Spaces and question marks break filters and URLs.')
    if not r['cr'] and r['group'] in ('Lead Gen', 'Registration') and r['created'] >= datetime.date(2026, 3, 1):
        flag(r, plat, 'No CR code', 'Lead Gen / Registration ad created after Mar 2026 without a CR code.')
    if r['name_objective'] and r['camp_objective'] and camp_group(r['name_objective']) != camp_group(r['camp_objective']) \
            or (r['name_objective'] in ('opportunity', 'registration') and r['camp_objective'] in ('opportunity', 'registration')
                and r['name_objective'] != r['camp_objective']):
        flag(r, plat, 'Objective mismatch', f"Ad name says '{r['name_objective']}', campaign says '{r['camp_objective']}'.")
    if r['name_country'] and r['country'] and r['name_country'] != r['country']:
        flag(r, plat, 'Market mismatch', f"Ad name says '{r['name_country']}', campaign says '{r['country']}'.")
    if r['name_lang'] and r['language'] and r['name_lang'] != r['language']:
        flag(r, plat, 'Language mismatch', f"Ad name says '{r['name_lang']}', campaign says '{r['language']}'.")
    if plat == 'Meta' and r.get('is_video') and r['fmt'] in ('static', 'image'):
        flag(r, plat, 'Format mismatch', f"Ad name says '{r['fmt']}', but the creative uploaded to Meta is a video.")
    if len(clean_prefix(n).split('/')) > 16:
        flag(r, plat, 'Name pasted twice', 'Name has more segments than the convention; part of it looks duplicated.')

# Same CR code, same market, different batch and different copy = two creatives sharing one code
def mk(r):
    return market_label(r['country'], r['language'])
grp_b = collections.defaultdict(set); grp_t = collections.defaultdict(set)
for r, plat in all_rows:
    if r['cr']:
        k = (r['cr'], mk(r))
        grp_b[k].add(r['batch'] or '(no batch)')
        grp_t[k].add(re.sub(r'\W+', '', (r.get('primary') or r.get('ad_text') or ''))[:60].lower())
for r, plat in all_rows:
    k = (r['cr'], mk(r))
    if r['cr'] and len(grp_b[k]) > 1 and len(grp_t[k]) > 1:
        flag(r, plat, 'CR code reused for different creative',
             f"In {mk(r)}, {r['cr']} appears in batches {', '.join(sorted(grp_b[k]))} with different copy.")

# TikTok duplicate names
tt_names = collections.Counter(r['ad_name'] for r in tt_rows)
for r in tt_rows:
    if tt_names[r['ad_name']] > 1:
        flag(r, 'TikTok', 'Duplicate ad name', f"{tt_names[r['ad_name']]} TikTok ads share this exact name.")

# ---------- Workbook ----------
FONT = 'Arial'
HDR_FILL = PatternFill('solid', fgColor='1F2A44')
HDR_FONT = Font(name=FONT, bold=True, color='FFFFFF', size=10)
MAN_FILL = PatternFill('solid', fgColor='FFF2CC')  # manual columns
BODY = Font(name=FONT, size=10)
LINK = Font(name=FONT, size=10, color='1155CC', underline='single')
WRAP = Alignment(wrap_text=True, vertical='top')
TOP = Alignment(vertical='top')

wb = Workbook()


def make_sheet(title, headers, widths, first=False):
    ws = wb.active if first else wb.create_sheet()
    ws.title = title
    for j, (h, w) in enumerate(zip(headers, widths), 1):
        c = ws.cell(row=1, column=j, value=h)
        c.font = HDR_FONT; c.fill = HDR_FILL; c.alignment = Alignment(vertical='center', wrap_text=True)
        ws.column_dimensions[get_column_letter(j)].width = w
    ws.freeze_panes = 'B2'
    ws.row_dimensions[1].height = 30
    return ws


def put(ws, r, c, v, wrap=False, link=None, fmt=None):
    cell = ws.cell(row=r, column=c, value=v)
    cell.font = LINK if link else BODY
    cell.alignment = WRAP if wrap else TOP
    if link:
        cell.hyperlink = link
    if fmt:
        cell.number_format = fmt
    return cell


# README
ws = wb.active
ws.title = 'README'
ws.column_dimensions['A'].width = 26
ws.column_dimensions['B'].width = 110
readme = [
    ('TNX Creative Library', None),
    ('What this is', 'One row per ad, pulled straight from Meta Ads and TikTok Ads. Replaces the column-per-ad Creative Breakdown tabs. This workbook stores the data; the dashboard reads from it.'),
    ('Key', 'Ad ID is the unique key. Ad names are split into tags (market, batch, angle, CR code) but are never used to join data, because names repeat and contain mistakes.'),
    ('Tabs', 'Meta Ads and TikTok Ads: synced from the platforms, do not type in them. Campaigns: one row per campaign. Notes: the only tab you type in. Name Issues: ads whose names break the convention. Performance: reserved, not built yet. Data Sources: where each table came from.'),
    ('Typing', 'Yellow header = you fill it in. Everything else is overwritten on each sync. Notion Link, Folder Link and analysis live on the Notes tab and show up on the ad tabs through a lookup on Ad ID.'),
    ('Campaign Group', 'From the objective segment of the campaign name: opportunity / lead / conversion = Lead Gen; registration = Registration; reach / awareness = Awareness.'),
    ('Name convention (current)', 'platform/brand/country/language/campaign-type/objective/prospecting-destination/targeting/batch/YYYYMMDD/framework/format/hook/angle/CRcode'),
    ('Example', 'fb/tnx/my/cn/evergreen/registration/prospecting-order/broad/batch-16-eoy-promo-2/20261118/fcb-value/static/painpoint/eoy2026-promo2-year-end-rush/CR81_2'),
    ('Platform prefix', 'fb and ig = Meta (placement), tt = TikTok.'),
    ('TikTok text', 'TikTok ads carry one Ad Text field and no headline. TikTok ads here are Smart+ ads, so one ad can hold several videos; they are listed in Creative Files.'),
    ('Images', 'Meta image and thumbnail URLs expire after a few weeks. They refresh on each sync; do not paste them elsewhere.'),
    ('Last synced', RUN_AT),
]
for i, (k, v) in enumerate(readme, 1):
    a = ws.cell(row=i, column=1, value=k); b = ws.cell(row=i, column=2, value=v)
    a.font = Font(name=FONT, bold=True, size=14 if i == 1 else 10)
    b.font = BODY; a.alignment = TOP; b.alignment = WRAP

# Meta Ads
meta_headers = ['Ad ID', 'Platform', 'Market', 'Language', 'Campaign Group', 'Campaign Theme', 'Destination',
                'Status', 'Created', 'Launch Date (name)', 'Batch', 'Framework', 'Format', 'Hook', 'Angle',
                'CR Code', 'Targeting', 'Headline', 'Primary Text', 'CTA', 'Landing URL', 'Notion Link',
                'Folder Link', 'Ad Link', 'Image URL', 'Creative ID', 'Creative Type', 'Flexible Creative',
                'Campaign ID', 'Campaign Name', 'Ad Set ID', 'Ad Set Name', 'Ad Name']
meta_w = [20, 9, 8, 9, 14, 18, 13, 16, 11, 12, 26, 18, 9, 18, 30, 10, 16, 40, 60, 14, 30, 28, 28, 12, 14,
          18, 11, 10, 20, 50, 20, 50, 70]
ws = make_sheet('Meta Ads', meta_headers, meta_w)
ws.cell(row=1, column=22).fill = MAN_FILL; ws.cell(row=1, column=22).font = Font(name=FONT, bold=True, size=10)
ws.cell(row=1, column=23).fill = MAN_FILL; ws.cell(row=1, column=23).font = Font(name=FONT, bold=True, size=10)
meta_rows.sort(key=lambda r: (r['created'], r['ad_id']), reverse=True)
for i, r in enumerate(meta_rows, 2):
    vals = [r['ad_id'], r['platform'], r['country'].upper(), r['language'].upper(), r['group'], r['theme'],
            r['destination'], r['status'], r['created'], r['name_date'], r['batch'], r['framework'], r['fmt'],
            r['hook'], r['angle'], r['cr'], r['targeting'], r['headline'], r['primary'], r['cta'], r['link']]
    for j, v in enumerate(vals, 1):
        put(ws, i, j, v, wrap=(j in (18, 19)), fmt='yyyy-mm-dd' if j in (9, 10) else None)
    put(ws, i, 22, f'=IFERROR(INDEX(Notes!$D:$D,MATCH($A{i},Notes!$A:$A,0))&"","")')
    put(ws, i, 23, f'=IFERROR(INDEX(Notes!$E:$E,MATCH($A{i},Notes!$A:$A,0))&"","")')
    url = f'https://adsmanager.facebook.com/adsmanager/manage/ads?act={META_ACCT}&selected_ad_ids={r["ad_id"]}'
    put(ws, i, 24, 'Open in Ads Manager', link=url)
    put(ws, i, 25, 'Image' if r['img'] else '', link=r['img'] or None)
    for j, v in enumerate([r['creative_id'], r['creative_type'], r['flexible'], r['campaign_id'], r['campaign'],
                           r['adset_id'], r['adset'], r['ad_name']], 26):
        put(ws, i, j, v)
    ws.row_dimensions[i].height = 45
ws.auto_filter.ref = f'A1:{get_column_letter(len(meta_headers))}{len(meta_rows) + 1}'
ws.cell(row=1, column=1).comment = Comment(
    f'Source: Meta Ads, ad account Teleport Next Day ({META_ACCT}), ads created since 2025-01-01, '
    f'{len(meta_rows)} rows, run {RUN_AT}. Pulled by Claude via the Meta Ads connector. See Data Sources tab.', 'Claude')

# TikTok Ads
tt_headers = ['Ad ID', 'Platform', 'Market', 'Language', 'Campaign Group', 'Campaign Theme', 'Destination',
              'Status', 'Created', 'Launch Date (name)', 'Batch', 'Framework', 'Format', 'Hook', 'Angle',
              'CR Code', 'Targeting', 'Ad Text', 'Notion Link', 'Folder Link', 'No. of Creatives',
              'Creative Files', 'TikTok Format', 'Campaign ID', 'Campaign Name', 'Ad Group ID', 'Ad Group Name',
              'Ad Name']
tt_w = [20, 9, 8, 9, 14, 18, 13, 11, 11, 12, 26, 18, 9, 18, 30, 10, 16, 60, 28, 28, 10, 40, 14, 20, 50, 20,
        50, 70]
ws = make_sheet('TikTok Ads', tt_headers, tt_w)
for col in (19, 20):
    ws.cell(row=1, column=col).fill = MAN_FILL; ws.cell(row=1, column=col).font = Font(name=FONT, bold=True, size=10)
tt_rows.sort(key=lambda r: (r['created'], r['ad_id']), reverse=True)
for i, r in enumerate(tt_rows, 2):
    vals = [r['ad_id'], r['platform'], r['country'].upper(), r['language'].upper(), r['group'], r['theme'],
            r['destination'], r['status'], r['created'], r['name_date'], r['batch'], r['framework'], r['fmt'],
            r['hook'], r['angle'], r['cr'], r['targeting'], r['ad_text']]
    for j, v in enumerate(vals, 1):
        put(ws, i, j, v, wrap=(j == 18), fmt='yyyy-mm-dd' if j in (9, 10) else None)
    put(ws, i, 19, f'=IFERROR(INDEX(Notes!$D:$D,MATCH($A{i},Notes!$A:$A,0))&"","")')
    put(ws, i, 20, f'=IFERROR(INDEX(Notes!$E:$E,MATCH($A{i},Notes!$A:$A,0))&"","")')
    for j, v in enumerate([r['n_creatives'], r['files'], r['tt_format'], r['campaign_id'], r['campaign'],
                           r['adset_id'], r['adset'], r['ad_name']], 21):
        put(ws, i, j, v, wrap=(j == 22))
    ws.row_dimensions[i].height = 45
ws.auto_filter.ref = f'A1:{get_column_letter(len(tt_headers))}{len(tt_rows) + 1}'
ws.cell(row=1, column=1).comment = Comment(
    f'Source: TikTok Ads, advertiser Teleport Next Day ({TT_ADV}), Smart+ ads, {len(tt_rows)} rows, run {RUN_AT}. '
    'Pulled by Claude via the TikTok for Business connector. See Data Sources tab.', 'Claude')

# Campaigns
c_headers = ['Campaign ID', 'Platform', 'Campaign Name', 'Campaign Group', 'Market', 'Language', 'Campaign Theme',
             'Destination', 'Created', 'No. of Ads']
ws = make_sheet('Campaigns', c_headers, [20, 9, 70, 14, 8, 9, 22, 13, 11, 10])
crow = []
first_created = {}
for r in meta_rows:
    first_created[r['campaign_id']] = min(first_created.get(r['campaign_id'], r['created']), r['created'])
for cid, cname in camps.items():
    cp = parse_name(cname)
    crow.append(['Meta', cid, cname, cp, first_created[cid], "'Meta Ads'"])
for cid, (cname, ct) in tt_camps.items():
    cp = parse_name(cname)
    created = min(r['created'] for r in tt_rows if r['campaign_id'] == cid)
    crow.append(['TikTok', cid, cname, cp, created, "'TikTok Ads'"])
crow.sort(key=lambda x: x[4], reverse=True)
for i, (plat, cid, cname, cp, created, tab) in enumerate(crow, 2):
    vals = [cid, plat, cname, camp_group(cp['objective']), cp['country'].upper(), cp['language'].upper(),
            camp_theme(cname), dest_label(cp['destination']), created]
    for j, v in enumerate(vals, 1):
        put(ws, i, j, v, fmt='yyyy-mm-dd' if j == 9 else None)
    col = 'AC' if plat == 'Meta' else 'X'
    put(ws, i, 10, f'=COUNTIF({tab}!${col}:${col},$A{i})')
ws.auto_filter.ref = f'A1:J{len(crow) + 1}'

# Notes (manual)
n_headers = ['Ad ID', 'Platform', 'Ad Name', 'Notion Link', 'Folder Link', 'Analysis', 'Hypothesis', 'Next Step']
ws = make_sheet('Notes', n_headers, [20, 9, 60, 32, 32, 50, 40, 30])
for col in range(4, 9):
    ws.cell(row=1, column=col).fill = MAN_FILL; ws.cell(row=1, column=col).font = Font(name=FONT, bold=True, size=10)
note_rows = [(r['ad_id'], 'Meta', 'Meta Ads') for r in meta_rows] + [(r['ad_id'], 'TikTok', 'TikTok Ads') for r in tt_rows]
for i, (aid, plat, tab) in enumerate(note_rows, 2):
    put(ws, i, 1, aid); put(ws, i, 2, plat)
    lastcol = 'AG' if plat == 'Meta' else 'AB'
    put(ws, i, 3, f"=IFERROR(INDEX('{tab}'!${lastcol}:${lastcol},MATCH($A{i},'{tab}'!$A:$A,0)),\"\")")
ws.auto_filter.ref = f'A1:H{len(note_rows) + 1}'
ws.cell(row=1, column=4).comment = Comment('Type here. Columns D to H are the only manual columns in the workbook. '
                                           'New ads get a row on each sync; existing notes are kept.', 'Claude')

# Name Issues
ws = make_sheet('Name Issues', ['Ad ID', 'Platform', 'Ad Name', 'Issue', 'Detail'], [20, 9, 80, 26, 60])
issues.sort(key=lambda x: (x[3], x[2]))
for i, row in enumerate(issues, 2):
    for j, v in enumerate(row, 1):
        put(ws, i, j, v, wrap=(j in (3, 5)))
ws.auto_filter.ref = f'A1:E{len(issues) + 1}'

# Performance (reserved)
ws = make_sheet('Performance', ['Ad ID', 'Platform', 'Period Start', 'Period End', 'Spend (RM)', 'Leads',
                                'Cost per Lead (RM)', 'Outbound Clicks', 'Outbound CTR', 'Reach', 'Impressions',
                                'CPM (RM)'], [20, 9, 12, 12, 12, 9, 14, 12, 11, 11, 12, 10])
ws.cell(row=2, column=1, value='Reserved. Performance will be pulled from Meta Ads once the structure is agreed.').font = Font(name=FONT, italic=True, size=10, color='666666')

# Data Sources
ds_headers = ['Written to', 'Source', 'Object', 'Obtained via', 'Query or request', 'Parameters', 'Run at',
              'Requested by', 'Row count', 'Changes after retrieval', 'Notes']
ws = make_sheet('Data Sources', ds_headers, [24, 14, 40, 26, 50, 50, 18, 14, 10, 50, 30])
ds = [
    [f"'Meta Ads'!A1:AG{len(meta_rows)+1}", 'Meta Ads', f'Ad account {META_ACCT} (Teleport Next Day): ads, ad creatives',
     'Run by Claude (Meta Ads connector)', 'ads_get_ad_entities level=ad; ads_get_creatives by creative_id',
     'created_time > 2025-01-01; fields id, name, campaign, ad set, effective_status, creative_id, created_time; creative body, title, CTA, link, image, asset_feed_spec',
     RUN_AT, '', len(meta_rows), 'Ad name split into tags; flexible creatives: multiple texts joined with ---; sorted newest first', ''],
    [f"'TikTok Ads'!A1:AB{len(tt_rows)+1}", 'TikTok Ads', f'Advertiser {TT_ADV} (Teleport Next Day): Smart+ ads',
     'Run by Claude (TikTok for Business connector)', 'smart_plus_ad_get', 'all Smart+ ads, page_size 100',
     RUN_AT, '', len(tt_rows), 'Ad name split into tags; sorted newest first', ''],
]
for i, row in enumerate(ds, 2):
    for j, v in enumerate(row, 1):
        put(ws, i, j, v, wrap=True)

for s in wb.worksheets:
    s.sheet_view.zoomScale = 100

os.makedirs(os.path.join(ROOT, 'sync', 'out'), exist_ok=True)
out = os.path.join(ROOT, 'sync', 'out', 'TNX_Creative_Library.xlsx')
wb.save(out)
print('meta', len(meta_rows), 'tt', len(tt_rows), 'camps', len(crow), 'issues', len(issues))
print(collections.Counter(x[3] for x in issues))
print(collections.Counter((r['group'], market_label(r['country'], r['language'])) for r in meta_rows if r['status'] == 'ACTIVE'))

# ---------- Links (Notion + Drive folder), typed by the team in the TNX Creative Links sheet ----------
# sync/raw/links.json: [{"cr": "CR81_2", "market": "MY-CN", "ad_id": "", "notion": "https://...", "drive": "https://..."}]
# Match order: Ad ID, then CR code + market, then CR code alone (rows with no market).
def _norm(x):
    return (x or '').strip()
links = json.load(open(D + 'links.json')) if os.path.exists(D + 'links.json') else []
by_ad, by_crm, by_cr = {}, {}, {}
for L in links:
    v = {'notion': _norm(L.get('notion')), 'drive': _norm(L.get('drive'))}
    if not (v['notion'] or v['drive']):
        continue
    if _norm(L.get('ad_id')):
        by_ad[_norm(L['ad_id'])] = v
    elif _norm(L.get('cr')) and _norm(L.get('market')):
        by_crm[(_norm(L['cr']).upper(), _norm(L['market']).upper())] = v
    elif _norm(L.get('cr')):
        by_cr[_norm(L['cr']).upper()] = v
def link_for(ad_id, cr, mk):
    return by_ad.get(ad_id) or by_crm.get(((cr or '').upper(), mk)) or by_cr.get((cr or '').upper()) or {}

# ---------- Dashboard data ----------
import os
def iso(d):
    return d.isoformat() if d else ''
STATUS = {'ACTIVE': 'Active', 'PAUSED': 'Paused', 'CAMPAIGN_PAUSED': 'Campaign paused',
          'ADSET_PAUSED': 'Ad set paused', 'WITH_ISSUES': 'With issues'}
dash = []
for r in meta_rows:
    dash.append(dict(id=r['ad_id'], p=r['platform'], mk=r['country'].upper(), lg=r['language'].upper(),
        g=r['group'], th=r['theme'], de=r['destination'], st=STATUS.get(r['status'], r['status'].title()),
        cr=r['created'].isoformat(), ts=r['created_ts'].strftime('%Y-%m-%d %H:%M'), ld=iso(r['name_date']), b=r['batch'], fw=r['framework'], f=r['fmt'],
        hk=r['hook'], an=r['angle'], c=r['cr'], h=r['headline'], t=r['primary'], cta=r['cta'], url=r['link'],
        img=(f"images/{r['creative_id']}.jpg" if os.path.exists(os.path.join(ROOT, "images", f"{r['creative_id']}.jpg")) else r['img']),
        lr=bool(re.search(r'p64x64|[ps]160x160', r['img'] or '')), vu=r['video_url'], v=r['is_video'], ct=r['creative_type'], cid=r['campaign_id'], cn=r['campaign'], n=r['ad_name'], nc=r['n_creatives'],
        am=f'https://adsmanager.facebook.com/adsmanager/manage/ads?act={META_ACCT}&selected_ad_ids={r["ad_id"]}'))
for r in tt_rows:
    dash.append(dict(id=r['ad_id'], p='tt', mk=r['country'].upper(), lg=r['language'].upper(),
        g=r['group'], th=r['theme'], de=r['destination'], st=STATUS.get(r['status'], r['status'].title()),
        cr=r['created'].isoformat(), ts=r['created_ts'].strftime('%Y-%m-%d %H:%M'), ld=iso(r['name_date']), b=r['batch'], fw=r['framework'], f=r['fmt'],
        hk=r['hook'], an=r['angle'], c=r['cr'], h='', t=r['ad_text'], cta='', url='',
        img=(f"images/tt_{r['ad_id']}.jpg" if os.path.exists(os.path.join(ROOT, 'images', f"tt_{r['ad_id']}.jpg")) else ''),
        v='VIDEO' in r['tt_format'], lr=False, ct=r['tt_format'],
        cid=r['campaign_id'], cn=r['campaign'], n=r['ad_name'], files=r['files'], nc=r['n_creatives'], am=''))
# Notion briefs: ads with no Notion link in the Links sheet get their "[TNX PAID - XX] Batch N ..."
# card from the Marketing DB (sync/raw/notion_cards.json, see SYNC.md step 5b). Links sheet wins.
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from notion_match import load_cards, load_folders, match_ad, assign_waves
NOTION_FROM = '2026-10-01'   # card titles follow "[TNX PAID - XX] Batch N - Angle - Format" from here on
cards = load_cards(D + 'notion_cards.json') if os.path.exists(D + 'notion_cards.json') else []
folders = load_folders(D + 'drive_folders.json') if os.path.exists(D + 'drive_folders.json') else []
# Hand-added links (sync/manual_links.json): used when the Links sheet has none for that field.
_ml = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'manual_links.json'))).get('links', []) \
    if os.path.exists(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'manual_links.json')) else []
def manual_for(a):
    mk = f"{a['mk']}-{a['lg']}" if a['lg'] else a['mk']
    base = re.sub(r'_\d+$', '', a['c'] or '').upper()
    for m in _ml:
        if m.get('ad_id') and m['ad_id'] == a['id']:
            return m
    for m in _ml:
        cr = (m.get('cr') or '').upper()
        if cr and m.get('market') and m['market'].upper() == mk.upper() and cr in ((a['c'] or '').upper(), base):
            return m
    for m in _ml:
        cr = (m.get('cr') or '').upper()
        if cr and not m.get('market') and cr in ((a['c'] or '').upper(), base):
            return m
    return {}
assign_waves(dash)
n_linked = n_auto = n_dauto = 0
unmatched = {}
no_folder = {}
for a in dash:
    mk = f"{a['mk']}-{a['lg']}" if a['lg'] else a['mk']
    lk = link_for(a['id'], a['c'], mk)
    a['nl'] = lk.get('notion', ''); a['dl'] = lk.get('drive', '')
    ml = manual_for(a)
    a['nl'] = a['nl'] or ml.get('notion', ''); a['dl'] = a['dl'] or ml.get('drive', '')
    if not a['nl'] and cards and a['cr'] >= NOTION_FROM:
        card, why = match_ad(a, cards)
        if card:
            a['nl'] = card['url'].replace('https://app.notion.com/', 'https://app.notion.com/p/') \
                if '/p/' not in card['url'] else card['url']
            a['na'] = 1          # auto-matched from Notion (shown as such on the card)
            n_auto += 1
        else:
            unmatched.setdefault(why[:140], []).append(a['c'] or a['n'][-40:])
    if not a['dl'] and folders and a['cr'] >= NOTION_FROM:
        fo, why = match_ad(a, folders)
        if fo:
            a['dl'] = fo['url']; a['da'] = 1; n_dauto += 1
        else:
            no_folder.setdefault(f"{a['mk']}-{a['lg']} {a['b']} {a['f']}", []).append(a['c'] or a['n'][-40:])
    n_linked += bool(a['nl'] or a['dl'])
for a in dash:
    a.pop('_wave', None)
print('ads with links', n_linked, '(Notion auto-matched:', n_auto, '| Drive folder auto-matched:', n_dauto, ')')
for why, crs in sorted(unmatched.items(), key=lambda x: -len(x[1])):
    print('  no Notion brief found (%d): %s -> %s' % (len(crs), why, ', '.join(sorted(set(crs))[:8])))
for grp, crs in sorted(no_folder.items()):
    print('  no Drive folder found: %s -> %s' % (grp, ', '.join(sorted(set(crs))[:8])))
out_d = {'synced': RUN_AT, 'ads': dash,
         'issues': [dict(id=i[0], p=i[1], n=i[2], issue=i[3], detail=i[4]) for i in issues]}
import os
os.makedirs(os.path.join(ROOT, 'data'), exist_ok=True)
json.dump(out_d, open(os.path.join(ROOT, 'data', 'ads.json'), 'w'), ensure_ascii=False, separators=(',', ':'))
print('dashboard ads', len(dash))
