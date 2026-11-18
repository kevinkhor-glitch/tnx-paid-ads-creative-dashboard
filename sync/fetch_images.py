"""Save each Meta creative's image to images/<creative_id>.jpg (Meta links expire in days). Skips ones already saved."""
import json, sys, os, io, concurrent.futures, urllib.request
from PIL import Image
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
D = os.path.join(ROOT, 'sync', 'raw') + '/'
cr = json.load(open(D + 'creatives.json')); vids = json.load(open(D + 'videos.json'))
jobs = {}
for cid, c in cr.items():
    afs = c.get('asset_feed_spec') or {}
    vid = c.get('video_id') or next((v['video_id'] for v in afs.get('videos', [])), None)
    url = c.get('image_url') or (vids.get(vid or '', {}).get('pic')) or c.get('thumbnail_url')
    if url: jobs[cid] = url
def get(item):
    cid, url = item
    out = os.path.join(ROOT, 'images', f'{cid}.jpg')
    if os.path.exists(out): return cid, 'cached'
    try:
        data = urllib.request.urlopen(url, timeout=30).read()
        im = Image.open(io.BytesIO(data)).convert('RGB')
        im.thumbnail((640, 800))
        im.save(out, 'JPEG', quality=78, optimize=True, progressive=True)
        return cid, 'ok'
    except Exception as e:
        return cid, f'fail {e}'
res = dict(concurrent.futures.ThreadPoolExecutor(16).map(get, jobs.items()))
import collections
print(len(jobs), collections.Counter(v.split()[0] for v in res.values()))
json.dump({k: v for k, v in res.items()}, open(os.path.join(ROOT, 'sync', 'out', 'image_fetch_log.json'), 'w'))
