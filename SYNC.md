# Sync runbook

Instructions for the Claude session that refreshes this dashboard. A person can start it by asking Claude to "sync the TNX creative dashboard", or it runs on a schedule.

Data is pulled through Claude's connectors (Meta Ads, TikTok for Business, Google Drive), not with API keys. The scripts in `sync/` only transform what was pulled; they never call Meta or TikTok themselves.

## Accounts

| Platform | Account | ID |
|---|---|---|
| Meta Ads | Teleport Next Day | `535902558289665` |
| TikTok Ads | Teleport Next Day | `7533075564996100097` |
| Google Sheet | TNX Creative Links (same folder as TNX Master Creative Sheet) | `1UxknhrzVLaGwgy1RB4_DbGWs5yb-1ebOuA_n4JaR_jE` |

## Steps

1. **Meta ads.** `ads_get_ad_entities`, level `ad`, fields `id, name, campaign_id, campaign_name, adset_id, adset_name, effective_status, creative_id, created_time`, filter `created_time > 2025-01-01`, `date_preset=maximum`, limit 500, follow `next_cursor`. Save the combined list as `sync/raw/ads_all.json` (a JSON array).
2. **Meta creatives.** `ads_get_creatives` with `creative_ids` in batches of 100, fields `id, name, object_type, body, title, call_to_action_type, link_url, thumbnail_url, image_url, video_id, asset_feed_spec, child_attachments`. `child_attachments` gives the carousel cards, used for the "Creatives: X in this ad" count. Save as `sync/raw/creatives.json`, an object keyed by creative id.
3. **Meta video previews.** `ads_get_ad_videos` with `video_ids` in batches of 100 (each creative's `video_id`, or the first video in `asset_feed_spec`), fields `id, picture, permalink_url`. Save as `sync/raw/videos.json`: `{video_id: {"pic": picture, "perm": permalink_url}}`.
4. **TikTok ads.** `smart_plus_ad_get` for advertiser `7533075564996100097`, page_size 100, all pages, `include_effective_status=true`. Save the raw response as `sync/raw/tt_sp.json`. Then the previews: collect each creative's `creative_info.video_info.video_id` and call `file_video_ad_info_get` (via `tool_execute`, max 60 IDs per call); save `{video_id: video_cover_url}` as `sync/raw/tt_videos.json`. For creatives with no video, take `creative_info.image_info[0].web_uri` and call `file_image_ad_info_get`; save `{image_id: image_url}` as `sync/raw/tt_images.json`. Only new ads need this: ads that already have `images/tt_<ad id>.jpg` are skipped.
5. **Links.** Google Drive `get_file_metadata` on the TNX Creative Links sheet with `snippetVerbosity=MAX_ALLOWED`. Save the whole result to a file and run `python3 sync/read_links.py <that file>`, which writes `sync/raw/links.json`. If the result says the snippet was cut short, report it: links past that point were not read.
5b. **Notion briefs.** Read every brief card in the Marketing DB with the Notion connector (`notion-query-data-sources`, SQL mode, data source `collection://2c494b00-b6ca-802b-b6ea-000bc53e465a`):
   `SELECT "Name", url, "createdTime", "date:Live Date:start" AS "liveDate" FROM "collection://2c494b00-b6ca-802b-b6ea-000bc53e465a" WHERE upper("Name") LIKE '[TNX PAID%' AND "Name" LIKE '%atch%' ORDER BY "createdTime" DESC LIMIT 100 OFFSET 0`
   and repeat with OFFSET 100, 200 ... until fewer than 100 rows come back. Save all rows as `sync/raw/notion_cards.json`: `{"results": [{"Name", "url", "createdTime", "liveDate"}, ...]}`. Copy names and URLs exactly; a script reads them.
   `build.py` then gives every ad launched since 2026-10-01 that has no Notion link in the Links sheet the card that matches its language, batch number, format and batch/angle words (`sync/notion_match.py`). The Links sheet always wins. Split cards ("#1", "#2", or "15a", "15b") are launch waves of one batch: creatives first launched on the batch's first launch day go to #1, creatives first launched later go to #2, and so on; a re-launch of the same creative keeps its wave. Ads it cannot place with confidence stay unlinked and are printed by `build.py` as "no Notion brief found" with the reason; include those lines in the summary.
6. **Images.** `python3 sync/fetch_images.py` saves new Meta creative images and `python3 sync/fetch_tt_images.py` saves new TikTok previews, both to `images/`. Run this in the same session as steps 2 and 3: Meta's image links expire within days.
7. **Build.** `RUN_AT="<time of step 1, YYYY-MM-DD HH:MM MYT>" python3 sync/build.py` writes `data/ads.json` and `sync/out/TNX_Creative_Library.xlsx`.
8. **Check.** Ad count in `data/ads.json` is not lower than the previous commit's (ads are paused, not deleted). Open the page locally and confirm images load.
9. **Publish.** Commit `data/` and `images/` and push the `dashboard` branch. GitHub Pages redeploys in about a minute.
10. **Links sheet rows for new ads.** Drive can't edit the Links sheet, so new CR codes are not added to it automatically. List the new CR code + market pairs in the summary so the team can add a row for each.
11. **Summary.** Report: new ads since the last sync, ads that changed status, new name issues, how many ads have Notion/Drive links, and the new CR codes that need a Links row.

The old TNX Creative Library sheet is retired; do not update or re-create it.

## Not built yet

- **Weekly performance.** Planned: one row per ad per week (spend, leads, cost per lead, outbound clicks, outbound CTR, reach, impressions, CPM) in `data/performance.json` and the Sheet's Performance tab, shown on each card.
