# NUGGET — pickup state (last updated 2026-06-24)

Where we are and exactly how to resume. No secrets in this file (repo is public).

## TL;DR
- **Going-forward monitoring is LIVE and autonomous.** 57 channels, 3 verticals, 2026-only, 3 runs/day on Gemini via GitHub Actions. The feed fills itself.
- **Backfill is in progress, Max-only lane (Coby's call).** Older 2026 videos get extracted in-session by fanning out parallel extraction subagents (free on Max). First batch done. The backlog list is saved at `backend/backfill_2026.json`.

## LIVE: daily monitoring (no action needed)
- `.github/workflows/nugget-daily.yml`: cron `0 11,17,23 * * *` (6am/12pm/6pm Central), `pipeline.py recent --limit 20 --hours 24`.
- 57 channels in `backend/interests.json`: `ai_channels` (28), `build_channels` (16), `str_channels` (13). All IDs yt-dlp-verified, all 2026-active.
- Hard rule `ONLY_YEAR=2026` in `pipeline.py` (discovery drops any non-2026 video).
- Extractor: `gemini-3.1-flash-lite` (env `EXTRACT_MODEL`, set in the workflow). ~$0.004/video.
- Feed state as of this checkpoint: ~23 videos / ~131 nuggets (AI-heavy; build + STR still thin — see backfill priority).

## BACKFILL: Max-grind loop (how to resume)
**Goal:** extract older 2026 videos to give the feed depth. ~1,500-2,000 total across all channels. We do NOT have to finish all of it; prioritize the thin verticals.

**Backlog list:** `backend/backfill_2026.json` — array of `{video_id, title, channel, area, published}`, **1,372 videos enumerated across all 57 channels** (AI 694, build 374, STR 304), via `yt-dlp --break-match-filters "upload_date>=20260101"`. Complete as of 2026-06-24.

**Progress tracking:** the `videos` table IS the tracker. A backlog video is "done" if its `video_id` is already in `videos`. Exclude those each batch.

**The grind loop (repeat each session, ~15-20 videos/batch):**
1. Read `backend/backfill_2026.json`. Query existing `select video_id from videos`. Drop already-done ones. **Prioritize area = build, then str** (AI is already deep).
2. Fetch transcripts locally via the Webshare proxy (youtube-transcript-api, `WebshareProxyConfig`, creds in GitHub repo Secrets / ask Coby). Save each to a temp file; skip ones with disabled/empty captions.
3. Fan out one **general-purpose extraction subagent per video** (parallel). Each reads its transcript and returns nugget JSON per `poc/EXTRACTION_PROMPT.md` + `TASTE.md` (the exact agent prompt template is in the session history; key rules: non-obvious/tactical only, drop motivational+macro, NO em dashes, `context` REQUIRED when a term/person/company is named, quality 1-10).
4. Apply the quality gate (drop quality<5; skip a video if <3 remain). Generate escaped INSERT SQL for `videos` + `nuggets` (set `interest_area` to the channel's area, `published_at` from the backlog, `dedup_hash = md5(re.sub(r"\W+"," ",payload.lower()))[:16]`).
5. Write via the **Supabase MCP `execute_sql`** connector (no service key needed locally; project `ellnuqqlssupsrglxmwn`).
6. Embed: `curl -s -X POST .../functions/v1/embed-nuggets -H "Authorization: Bearer <anon>"` until `{"remaining":0}`.

**Re-run / extend the enumerator** (scratchpad, parallel, ~3min/channel): a script that, for each channel in `interests.json`, runs `yt-dlp --no-warnings --break-match-filters "upload_date>=20260101" --playlist-end 30 --print "%(id)s|%(upload_date)s|%(title)s" --proxy <webshare>` and writes `{video_id,published,title,channel,area}` to `backfill_2026.json`. (Original lived at the session scratchpad as `backfill_enum.py`.)

## DONE so far in the backfill
- 4 January-2026 videos (IndyDevDan x3 + AI Explained), 34 nuggets, written + embedded. (`VqDs46A8pqE`, `-WBHNFAB0OE`, `wYs6HWZ2FdM`, `u5GkG71PkR0`.)

## Key files
- `backend/pipeline.py` — discovery + `recent`/`run_recent` + `extract()` (Gemini/Anthropic router) + `monitored_channels()`.
- `backend/interests.json` — the 57 channels (3 vertical lists).
- `poc/EXTRACTION_PROMPT.md` + `TASTE.md` — the extraction spec + curation brain (subagents apply both).
- `backend/backfill_2026.json` — the backlog list.
- `.github/workflows/nugget-daily.yml` — the 3x/day cron.

## Credentials (NOT in this repo)
All live in **GitHub repo Settings -> Secrets** (`WEBSHARE_PROXY_USERNAME/PASSWORD`, `SUPABASE_SERVICE_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`). For a LOCAL grind you need Webshare (transcripts) + the Supabase anon key (embed). Ask Coby or pull from prior session notes; do not commit them.

## Open follow-ups (not blocking)
- Persist/refresh `backfill_2026.json` for build + STR channels (enumeration was AI-first).
- Taste-learning loop (notes -> TASTE.md) not yet wired into the GH job.
- `gemini-2.5-flash-lite` is ~4x cheaper than 3.1 but was 503-throttled on 2026-06-24; revisit later.
