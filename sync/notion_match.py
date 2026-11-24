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
    tail = re.split(r'\s+-\s+', rest.strip())[-1].lower()
    fmts = {FORMATS[w] for w in re.findall(r'[a-z]+', tail) if w in FORMATS}
    return dict(name=name, url=url, created=created or '', live=live or '', tt=bool(m.group(1)), lang=lang,
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


def match_ad(ad, cards):
    """ad: dashboard row (p, lg, b, f, an, hk, cr). Returns (card, reason) or (None, reason)."""
    ab = ad_batch(ad.get('b'))
    if not ab:
        return None, 'no batch number in ad name'
    lang = (ad.get('lg') or '').upper()
    tt = ad.get('p') == 'tt'
    fmt = FORMATS.get((ad.get('f') or '').lower(), (ad.get('f') or '').lower())
    bw = words(re.sub(r'batch-?\d+[a-z]?', ' ', (ad.get('b') or '').lower()) .replace('sprint', ' '))
    bw = {w for w in bw if not re.match(r'^(sprint|old)\d*$', w)}
    aw = bw | words(ad.get('an') or '')
    day = ad.get('cr') or ''
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
        overlap = len(aw & c['words'])
        live_hit = bool(c['live']) and c['live'] in days
        if bw and not overlap and not live_hit:
            continue                      # ad batch has its own words, none in this title
        score = overlap * 3 + (2 if exact else 1 if loose else 0) - (3 if not fmt_ok else 0) \
            + (1 if sfx and sfx == ab[1] else 0) + (4 if live_hit else 0)
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
