"""Match ads to their Notion brief card in the Marketing DB.

Cards are titled like "[TNX PAID - TH] Batch 1 - Festive Angle - Static" or
"[TNX PAID TT - EN] Batch 3 - Static Images (Claude) - Static". Notion holds no
CR codes, so an ad is matched on what both sides share:

  1. language (EN / CN / TH / BM) and channel (TikTok cards say "PAID TT")
  2. batch number (and letter, e.g. 25a / 25b) from the ad name's batch segment
  3. format (Video / Static / Animations ...) when the card states one
  4. the words of the batch slug and angle against the card title; when the ad's
     batch has its own words (batch-25-warehouse) at least one must appear in
     the title, unless the card's Live Date is the ad's launch or name date
  5. the card's Live Date equal to the ad's launch date (or name date) counts
     strongly; the card must be created before the ad was launched; among
     equals the most recent such card wins (e.g. "Batch 33 #1" vs "#2")
  6. if the ad's batch has no letter but several lettered cards fit equally
     (Batch 15a / 15b), it is reported as ambiguous
  7. split cards: a batch's creatives are sometimes launched in waves and the card
     split into "#1" (first launch) and "#2", "#3" (creatives launched later). Each
     creative (CR code, else angle) gets the wave of the day it FIRST went live within
     its language + batch + format; re-launches of the same creative keep that wave.
     Wave N goes to card #N (or letter a, b, c when the ad's batch has no letter).
     Call assign_waves(ads) once before matching.

Only a clear winner is returned. Ties and weak matches are reported as
ambiguous and left unlinked rather than guessed.

Input:  sync/raw/notion_cards.json  {"results": [{"Name", "url", "createdTime"}]}
Usage:  from notion_match import load_cards, match_ad
"""
import json, re

STOP = {'tnx', 'paid', 'batch', 'the', 'and', 'a', 'an', 'to', 'for', 'of', 'in', 'with', 'video',
        'static', 'single', 'animations', 'animation', 'carousel', 'ads', 'ad', 'tiktok', 'en', 'cn',
        'th', 'bm', 'my', 'sg', 'claude', 'eng', 'chinese', 'expansion', 'gtm', 'vid'}
FORMATS = {'video': 'video', 'videos': 'video', 'static': 'static', 'statics': 'static',
           'animations': 'animation', 'animation': 'animation', 'carousel': 'carousel',
           'image': 'static', 'images': 'static'}


def words(s):
    return {w for w in re.findall(r'[a-z0-9]+', (s or '').lower().replace('’', "'")) if w not in STOP and not w.isdigit()}


def parse_card(name, url, created='', live=''):
    m = re.match(r'\[TNX PAID\s*(TT)?\s*-\s*([A-Z]{2})\s*\]', name, re.I)
    if not m:
        return None
    lang = m.group(2).upper()
    rest = name[m.end():]
    batches = {}
    # "Batch 9 (EN) + Batch 5 (BM)" names a batch per language
    for b, sfx, lg in re.findall(r'Batch\s*(\d+)([a-z]?)\s*\((EN|CN|TH|BM)\)', rest, re.I):
        batches[lg.upper()] = (int(b), sfx.lower())
    if not batches:
        bm = re.search(r'Batch\s*(\d+)([a-z]?)\b', rest, re.I)
        if not bm:
            return None
        batches[lang] = (int(bm.group(1)), bm.group(2).lower())
    pm = re.search(r'#\s*(\d+)', rest)
    part = int(pm.group(1)) if pm else None
    tail = re.split(r'\s+-\s+', rest.strip())[-1].lower()
    fmts = {FORMATS[w] for w in re.findall(r'[a-z]+', tail) if w in FORMATS}
    return dict(name=name, url=url, created=created or '', live=live or '', tt=bool(m.group(1)), lang=lang, part=part,
                batches=batches, fmts=fmts, words=words(rest))


def load_cards(path='sync/raw/notion_cards.json'):
    d = json.load(open(path))
    rows = d.get('results', d) if isinstance(d, dict) else d
    out = []
    for r in rows:
        c = parse_card(r.get('Name', ''), r.get('url', ''), (r.get('createdTime') or '')[:10],
                       (r.get('liveDate') or r.get('date:Live Date:start') or '')[:10])
        if c:
            out.append(c)
    return out


def ad_batch(batch):
    m = re.search(r'batch-?(\d+)([a-z]?)(?![0-9])', (batch or '').lower())
    return (int(m.group(1)), m.group(2)) if m else None


def batch_words(batch):
    """Words of an ad's batch segment beyond the number: 'festive-niche-batch-1-festive-angle' -> {festive, angle}."""
    bw = words(re.sub(r'batch-?\d+[a-z]?', ' ', (batch or '').lower()))
    return {w for w in bw if not re.match(r'^(sprint|old)\d*$', w) and w not in ('niche', 'gen')}


def _fmt_family(f):
    f = FORMATS.get((f or '').lower(), (f or '').lower())
    return 'static' if f in ('static', 'carousel') else f


def assign_waves(ads):
    """Set ad['_wave'] = 1, 2, ... : the launch wave of the ad's creative within its batch."""
    first = {}                                  # (group, creative) -> first launch day
    def key(a):
        ab = ad_batch(a.get('b'))
        if not ab:
            return None, None
        g = (a.get('p') == 'tt', (a.get('lg') or '').upper(), ab, frozenset(batch_words(a.get('b'))),
             _fmt_family(a.get('f')))
        return g, (a.get('c') or a.get('an') or a.get('n'))
    for a in ads:
        g, cr = key(a)
        if g and a.get('cr'):
            k = (g, cr)
            first[k] = min(first.get(k, a['cr']), a['cr'])
    days = {}
    for (g, cr), d in first.items():
        days.setdefault(g, set()).add(d)
    order = {g: sorted(ds) for g, ds in days.items()}
    for a in ads:
        g, cr = key(a)
        if g and (g, cr) in first:
            a['_wave'] = order[g].index(first[(g, cr)]) + 1


def match_ad(ad, cards):
    """ad: dashboard row (p, lg, b, f, an, hk, cr). Returns (card, reason) or (None, reason)."""
    ab = ad_batch(ad.get('b'))
    if not ab:
        return None, 'no batch number in ad name'
    lang = (ad.get('lg') or '').upper()
    tt = ad.get('p') == 'tt'
    fmt = FORMATS.get((ad.get('f') or '').lower(), (ad.get('f') or '').lower())
    bw = batch_words(ad.get('b'))
    aw = bw | words(ad.get('an') or '')
    day = ad.get('cr') or ''
    anim = bool(re.search(r'animation', ((ad.get('b') or '') + ' ' + (ad.get('an') or '')).lower()))
    days = {day, ad.get('ld') or ''} - {''}
    cands = []
    for c in cards:
        if c['tt'] != tt or lang not in c['batches']:
            continue
        num, sfx = c['batches'][lang]
        if num != ab[0]:
            continue
        if sfx and ab[1] and sfx != ab[1]:
            continue
        if c['created'] and day and c['created'] > day:
            continue                      # brief written after the ad went live: not its brief
        cf = c['fmts']
        exact = fmt in cf or (fmt == 'carousel' and 'static' in cf)
        loose = fmt == 'video' and 'animation' in cf
        fmt_ok = (not cf) or exact or loose
        if c.get('strict') and cf and not exact:
            continue                      # Drive folders name their format exactly
        overlap = len(aw & c['words'])
        live_hit = bool(c['live']) and c['live'] in days
        if bw and not overlap and not live_hit:
            continue                      # ad batch has its own words, none in this title
        wave = ad.get('_wave')
        part_adj = 0
        cpart = c.get('part') or (ord(sfx) - 96 if sfx and not ab[1] else None)   # 15a/15b split like #1/#2
        if cpart and wave:
            part_adj = 5 if cpart == wave else -5
        # an ad named "...-animations-..." belongs to an Animations card, not a plain Video one
        hint = 3 if (anim and 'animation' in cf) else (-2 if anim and cf and 'animation' not in cf else 0)
        score = hint * 2 + overlap * 3 + (2 if exact else 1 if loose else 0) - (3 if not fmt_ok else 0) \
            + (1 if sfx and sfx == ab[1] else 0) + (4 if live_hit else 0) + part_adj
        cands.append((score, c['created'], c, sfx, live_hit))
    if not cands:
        return None, 'no card with this language and batch number'
    cands.sort(key=lambda x: (x[0], x[1]), reverse=True)
    best = cands[0]
    if best[0] < 0:
        return None, 'only cards with a different format'
    if len(cands) > 1 and cands[1][0] == best[0]:
        # equal score: e.g. "#1" vs "#2" briefs. Only a Live Date hit separates them.
        return None, 'tie: ' + ' | '.join(x[2]['name'] for x in cands[:2])
    if not ab[1] and best[3] and any(x[0] == best[0] and x[3] and x[3] != best[3] for x in cands[1:]):
        return None, 'tie: lettered batches ' + ' | '.join(x[2]['name'] for x in cands[:2])
    if len(cands) > 1 and cands[1][0] == best[0] and best[0] <= 0:
        return None, 'weak: ' + ' | '.join(x[2]['name'] for x in cands[:2])
    return best[2], 'score %d of %d candidate(s)' % (best[0], len(cands))


def page_id(url):
    m = re.search(r'([0-9a-f]{32})(?:\?|$)', (url or '').replace('-', ''))
    return m.group(1) if m else ''


# ---------- Drive final-output folders ----------
# Folders are titled "TH - Batch 16 Shipping Collage Video", "EN TT - Batch 3 Static",
# "EN - Batch 1 Festive Angle #2". They are matched with the same rules as the Notion cards,
# except that a folder may be created after the ad went live (finals are often filed later),
# so the creation-date rule is not applied. Other folders (raw footage, "20261111 - Batch 1") are ignored.
def parse_folder(title, fid, created=''):
    m = re.match(r'\s*(EN|CN|TH|BM)\s*(TT)?\s*-\s*', title or '', re.I)
    if not m or not re.search(r'Batch\s*\d', title, re.I):
        return None
    name = '[TNX PAID%s - %s] %s' % (' TT' if m.group(2) else '', m.group(1).upper(), title[m.end():])
    c = parse_card(name, 'https://drive.google.com/drive/folders/' + fid)
    if c:
        c['name'] = title
        c['created'] = ''               # no "created before launch" rule for folders
        c['strict'] = True              # format in the folder name must match the ad's
        if not c['fmts']:
            low = title.lower()
            c['fmts'] = {f for w, f in FORMATS.items() if re.search(r'\b%s\b' % w, low)}
    return c


def load_folders(path='sync/raw/drive_folders.json'):
    d = json.load(open(path))
    rows = d.get('files', d) if isinstance(d, dict) else d
    out = []
    for r in rows:
        c = parse_folder(r.get('title', ''), r.get('id', ''), r.get('createdTime', ''))
        if c:
            out.append(c)
    return out
