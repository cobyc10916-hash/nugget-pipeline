# NUGGET — handoff (what's done, and the few steps only you can do)

## ✅ Built and working (autonomously, this session)
- **Supabase backend** (project `nugget` / `ellnuqqlssupsrglxmwn`): full schema, RLS, pgvector,
  and the `get_feed` RPC (ranked video-cards with nested nuggets, keyset pagination). Security
  advisors reviewed.
- **58 real nuggets** from 8 videos (AI/build/STR + a 69-min podcast) seeded and verified —
  `get_feed` returns them ranked (podcast top, then YC sales, STR pricing…).
- **The PWA** (`nugget/app/`): vertical scroll-snap feed of video-cards, each with a horizontal
  **nugget carousel** (swipe through every nugget — nothing buried), topic-tinted, with the
  action rail (Save / Watch@timestamp / More / Act-on / Trash), the **Library** (Act-on
  checklist / Saved / Watch-later), a **You** tab, magic-link auth gate, and full PWA config
  (manifest, service worker, offline thumbnail cache, iOS install meta, icons).
  **`npm run build` passes; preview serves HTTP 200.**
- **The self-updating pipeline** (`nugget/backend/`): topic-search discovery (AI-weighted corpus)
  + RSS + Webshare-proxy transcripts + Haiku extraction (or the $0 Max-routine path) → Supabase.
- **The production extraction prompt** (`nugget/poc/EXTRACTION_PROMPT.md`) tuned to your feedback:
  rich hook+context+payload, and the single rare **WATCH** badge (no skim/skip).

## 🔧 The 4 steps only you can do (each is quick)

### 1. Run it locally right now (2 min) — see the feed today
```bash
cd nugget/app
npm install      # already done once this session
npm run dev      # open the printed localhost URL
```
You'll hit the magic-link login. To make login work you need step 2 first (or use the Supabase
dashboard → Authentication → Users → "Add user" to create your account + set a password, then
swap the Auth screen to password — but magic link is the intended path).

### 2. Turn on magic-link email (Supabase, 1 min)
Supabase dashboard → **Authentication → Providers → Email**: ensure **Email** is enabled and
"Confirm email" / magic link is on. Free tier sends magic links out of the box (low volume).
Then disable public signups: **Authentication → Settings → "Allow new users to sign up" = off**
*after* you've logged in once, so only you can get in.

### 3. Deploy the PWA to your phone (Vercel, ~5 min)
- Push `nugget/app/` to a GitHub repo (or `vercel` CLI from the folder).
- Import it at **vercel.com** (free Hobby tier). Framework auto-detects as Vite.
- Set two env vars in Vercel → Settings → Environment Variables (Production):
  `VITE_SUPABASE_URL` = `https://ellnuqqlssupsrglxmwn.supabase.co`
  `VITE_SUPABASE_ANON_KEY` = `sb_publishable_wlBUZ4v1CF6iC5sABH-aDw_aN_8S-Vh`
- Deploy → open the `*.vercel.app` URL on your iPhone → Share → **Add to Home Screen**. Done.

### 4. Keep the feed filling (pick ONE)
- **$0 Max path (recommended):** create a Claude Code routine from `nugget/backend/PROMPT.md`,
  Haiku model, scheduled 3am + 3pm. Needs GitHub connected to routines. Extracts on your Max sub.
- **VPS path:** put `SUPABASE_SERVICE_KEY` (Supabase dashboard → Settings → API → service_role)
  and `ANTHROPIC_API_KEY` in `nugget/backend/.env`, then cron `python pipeline.py run --limit 20`
  twice daily. ~$0.60/day.
- Either way, run the **back-catalog seed later** (Phase 8) to bulk-fill the "infinite" backlog —
  ~2,000 videos on Max, deferred until you've used the app and confirmed the feel.

## Cost
$0/mo on the Max-routine path (or ~$18/mo all-API). Supabase free, Vercel free. The only real
ongoing cost is extraction, which is cents-per-video and covered by Max when run off-hours.

## Notes / next refinements (non-blocking)
- Embedding-based dedup (pgvector) is wired in the schema but not yet populated — add when scaling.
- The "You" tab shows stats now; the draggable topic-weight sliders are a fast follow.
- The feed currently shows all unseen videos; auto-"seen" marking is intentionally off until the
  back-catalog is loaded (so your 8 seed videos stay re-viewable).
