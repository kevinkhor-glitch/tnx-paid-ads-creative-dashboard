# TNX Creative Library

Dashboard of every Teleport Next Day ad on Meta and TikTok: creative, copy, campaign and naming tags, one card per ad.

- `index.html`: the dashboard (single page, no build step).
- `data/ads.json`: the data the page reads. Regenerated from Meta Ads and TikTok Ads on each sync.

The source of truth is the **TNX Creative Library** Google Sheet (Marketing shared drive). Notes, Notion links and analysis are typed there, not here.

## Publishing

Settings → Pages → Source: *Deploy from a branch* → Branch: `main`, folder `/ (root)`.

Note: GitHub Pages sites are public to anyone with the link unless the organization is on GitHub Enterprise Cloud.

## Image previews

Meta's image links expire within days, so each creative's image is saved in `images/<creative_id>.jpg` at sync time and the page uses those copies. Static ads are saved at up to 640px. Meta only provides 160px frames for videos, so video previews are low resolution; use the "Watch video" link.

## Updating

See `SYNC.md`. Scripts are in `sync/`.
