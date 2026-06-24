# NUGGET — infrastructure

## Supabase (project: `nugget`)
- **project_id:** `ellnuqqlssupsrglxmwn`
- **URL:** `https://ellnuqqlssupsrglxmwn.supabase.co`
- **publishable key (safe in client):** `sb_publishable_wlBUZ4v1CF6iC5sABH-aDw_aN_8S-Vh`
- **anon (legacy JWT, also fine):** stored in app `.env` as `VITE_SUPABASE_ANON_KEY`
- **service-role key:** NOT stored here. The backend pipeline (`nugget_run.py`) needs it to
  write content (bypasses RLS). Get it from Supabase dashboard → Settings → API →
  `service_role` and set `SUPABASE_SERVICE_KEY` in `nugget/backend/.env` at deploy time.
  Seeding in-session is done via the Supabase MCP (no key needed).

## Schema (applied)
Tables: `channels, videos, nuggets, discovery_queue, candidate_queries, feedback, library, taste_weights`.
RLS on all. Content tables = read-only to authenticated (service-role writes). User tables = full
access to authenticated (single-user). Backend-only tables = service-role only.
Feed RPC: `get_feed(p_cursor_score, p_cursor_id, p_limit)` → ranked video-cards with nested nuggets (keyset pagination).
`vector` extension moved to `extensions` schema. Security advisors: clean except 3 documented single-user accept-with-rationale lints.

## Other infra (reused from repo)
- Webshare rotating proxy (transcripts) — in repo `.env`.
- yt-dlp (discovery) — installed.
- Extraction: Claude Max (routine) ongoing; this session for the PoC/seed.
