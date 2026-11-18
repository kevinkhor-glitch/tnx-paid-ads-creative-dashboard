# Sync runbook

Instructions for the Claude session that refreshes this dashboard. A person can start it by asking Claude to "sync the TNX creative dashboard", or it runs on a schedule.

Data is pulled through Claude's connectors (Meta Ads, TikTok for Business, Google Drive), not with API keys. The scripts in `sync/` only transform what was pulled; they never call Meta or TikTok themselves.

## Accounts

| Platform | Account | ID |
|---|---|---|
| Meta Ads | Teleport Next Day | `535902558289665` |
| TikTok Ads | Teleport Next Day | `7533075564996100097` |
| Google Sheet | TNX Creative Library (same folder as TNX Master Creative Sheet) | `1oRGzPDToDoroscaImBHMk_5luXAyJwDXFGTfslYeDbA` |

## Steps

1. **Meta ads.** `ads_get_ad_entities`, level `ad`, fields `id, name, campaign_id, campaign_name, adset_id, adset_name, effective_status, creative_id, created_time`, filter `created_time > 2025-01-01`, `date_preset=maximum`, limit 500, follow `next_cursor`. Save the combined list as `sync/raw/ads_all.json` (a JSON array).
2. **Meta creatives.** `ads_get_creatives` with `creative_ids` in batches of 100, fields `id, name, object_type, body, title, call_to_action_type, link_url, thumbnail_url, image_url, video_id, asset_feed_spec`. Save as `sync/raw/creatives.json`, an object keyed by creative id.
3. **Meta video previews.** `ads_get_ad_videos` with `video_ids` in batches of 100 (each creative's `video_id`, or the first video in `asset_feed_spec`), fields `id, picture, permalink_url`. Save as `sync/raw/videos.json`: `{video_id: {"pic": picture, "perm": permalink_url}}`.
4. **TikTok ads.** `smart_plus_ad_get` for advertiser `7533075564996100097`, page_size 100, all pages, `include_effective_status=true`. Save the raw response as `sync/raw/tt_sp.json`.
5. **Images.** `python3 sync/fetch_images.py` saves new creative images to `images/`. Run this in the same session as steps 2 and 3: Meta's image links expire within days.
6. **Build.** `RUN_AT="<time of step 1, YYYY-MM-DD HH:MM MYT>" python3 sync/build.py` writes `data/ads.json` and `sync/out/TNX_Creative_Library.xlsx`.
7. **Check.** Ad count in `data/ads.json` is not lower than the previous commit's (ads are paused, not deleted). Open the page locally and confirm images load.
8. **Publish.** Commit `data/` and `images/` and push the `dashboard` branch. GitHub Pages redeploys in about a minute.
9. **Google Sheet.** With the Google Sheets connector: rewrite the Meta Ads, TikTok Ads, Campaigns and Name Issues tabs in place, and add a Notes row for each new Ad ID. Never overwrite the Notes tab's typed columns (Notion Link, Folder Link, Analysis, Hypothesis, Next Step). Without the Sheets connector, skip this step and say so in the run summary; do not upload a new copy.
10. **Summary.** Report: new ads since the last sync, ads that changed status, new name issues.

## Not built yet

- **Weekly performance.** Planned: one row per ad per week (spend, leads, cost per lead, outbound clicks, outbound CTR, reach, impressions, CPM) in `data/performance.json` and the Sheet's Performance tab, shown on each card.
