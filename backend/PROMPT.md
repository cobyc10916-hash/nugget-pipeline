# NUGGET — Max routine prompt (the $0 extraction path)

Use this as a Claude Code **routine** (claude.ai/code/routines) scheduled ~2x/day at off-hours
(e.g. 3am + 3pm) so it doesn't compete with interactive use. Model: **Haiku**. It extracts on
your Max subscription — no ANTHROPIC_API_KEY needed. (Alternative: set ANTHROPIC_API_KEY and run
`python pipeline.py run` on the VPS cron — same result, ~$0.60/day.)

## Steps

1. **Discover** — run: `python nugget/backend/pipeline.py discover`
   (fills the `discovery_queue` table via topic search + RSS; free, no model use.)

2. **Pull the work** — query Supabase (project `ellnuqqlssupsrglxmwn`, via the Supabase
   connector): select up to 20 rows from `discovery_queue` where `status='pending'`
   order by `seed_score desc`.

3. **For each pending video:**
   a. Fetch its transcript: `python nugget/backend/get_transcript.py <video_id>`
      (prints the transcript text; uses the Webshare proxy. On failure, set that row's
      status to `no_captions` and skip.)
   b. **Extract nuggets** by following `nugget/poc/EXTRACTION_PROMPT.md` exactly — the rich
      hook+context+payload format, the binary `worth_full_watch` flag, the quality gate.
   c. Drop nuggets with quality < 5. If fewer than 3 remain, set the row's status to
      `low_yield` and move on (keep the verdict, don't insert nuggets).
   d. **Insert** into Supabase via the connector: upsert the `videos` row (with
      worth_full_watch, watch_reason, gist, cover_bullets (text array), nugget_count, interest_area,
      published_at (the video's upload date; get it with
      `yt-dlp --skip-download --print "%(upload_date)s" <url>` → format YYYY-MM-DD),
      thumbnail_url = `https://i.ytimg.com/vi/<id>/hqdefault.jpg`, url) and insert the `nuggets` rows
      (hook, context, payload, timestamp_hint, order_in_video, interest_area, topic_tags,
      nugget_type, quality, **actionability** 0-10, **scope** tactical|macro|mixed).
      Then set the queue row's status to `extracted`.

   e. **Embed the new nuggets** so look-alike suppression works: POST to the `embed-nuggets`
      edge function repeatedly until it returns `{"remaining":0}`:
      `curl -s -X POST "$SUPABASE_URL/functions/v1/embed-nuggets" -H "Authorization: Bearer $SUPABASE_ANON_KEY"`
      (it embeds a small batch per call, server-side gte-small, free).

4. **Refine the taste model from Coby's notes** (the curation brain): run
   `python nugget/backend/pipeline.py taste` — it prints Coby's free-write **Notes**, each joined to
   the nugget it's on. Read them for the *reason* behind each, find patterns, then:
   a. **Edit `nugget/TASTE.md`** — append a dated bullet under "Learned specifics" capturing what to
      pull back on / lean into (e.g. "noted 'just a stat, no takeaway' on 3 macro nuggets →
      reinforce: suppress macro bragging stats"). Commit it. The next extraction reads it, so this is
      what makes curation actually learn.
   b. **Re-tune the existing feed** so the notes take effect immediately, not just on new videos:
      nudge `taste_weights` (dimension scope/tag/area, weight 0.1–5.0) and/or re-grade or mute
      nuggets that clearly violate the refined taste (e.g. lower `actionability`, set `scope='macro'`,
      or for an explicit reject insert a `feedback` row `action='not_useful'` on it to fire the
      look-alike suppression). The in-app Notes are the evidence; TASTE.md is the durable knowledge.

## Rules
- Stay within the ~20-video budget per run so it fits the Max off-hours window.
- Anti-slip: only mark a queue row `extracted` after its nuggets are written. A failed/half
  run just leaves rows `pending` and the next run picks them up — nothing is lost.
- Educational only; reject motivational filler (the extraction prompt enforces this).
