"""Save a preview image for each TikTok Smart+ ad to images/tt_<ad id>.jpg (first creative in the ad).

Inputs (sync/raw/): tt_sp.json (Smart+ ads), tt_videos.json {video_id: video_cover_url} from
file_video_ad_info_get, tt_images.json {image_id: image_url} from file_image_ad_info_get.
TikTok cover links expire, so images are stored. Existing files are kept.
"""
import json, os, io, concurrent.futures, urllib.request
from PIL import Image
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
R = os.path.join(ROOT, 'sync', 'raw')
ads = json.load(open(os.path.join(R, 'tt_sp.json')))['data']['list']
vids = json.load(open(os.path.join(R, 'tt_videos.json'))) if os.path.exists(os.path.join(R, 'tt_videos.json')) else {}
imgs = json.load(open(os.path.join(R, 'tt_images.json'))) if os.path.exists(os.path.join(R, 'tt_images.json')) else {}
jobs = {}
for a in ads:
    for cl in a.get('creative_list', []):
        ci = cl.get('creative_info', {})
        vid = (ci.get('video_info') or {}).get('video_id')
        url = vids.get(vid) if vid else None
        if not url and ci.get('image_info'):
            url = imgs.get(ci['image_info'][0].get('web_uri'))
        if url:
            jobs[a['smart_plus_ad_id']] = url
            break
def get(item):
    aid, url = item
    out = os.path.join(ROOT, 'images', f'tt_{aid}.jpg')
    if os.path.exists(out):
        return aid, 'cached'
    try:
        im = Image.open(io.BytesIO(urllib.request.urlopen(url, timeout=30).read())).convert('RGB')
        im.thumbnail((640, 800)); im.save(out, 'JPEG', quality=78, optimize=True, progressive=True)
        return aid, 'ok'
    except Exception as e:
        return aid, f'fail {e}'
res = dict(concurrent.futures.ThreadPoolExecutor(12).map(get, jobs.items()))
import collections
print(len(ads), 'TikTok ads,', len(jobs), 'with a preview source:', collections.Counter(v.split()[0] for v in res.values()))
