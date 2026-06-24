# NUGGET

A personal PWA that turns your YouTube-homepage habit into an infinite feed of **useful, educational
nuggets** (AI · building/entrepreneurship · short-term rental), extracted from real video transcripts —
with one-tap deep-links to the source and a rare "worth the full watch" badge.

```
nugget/
├── app/          # the PWA (Vite + React + TS + Tailwind, Supabase, PWA). `npm run build` verified.
├── backend/      # discovery + extraction pipeline (yt-dlp + Webshare proxy + Haiku → Supabase)
│   ├── pipeline.py        # discover → transcript → extract → write
│   ├── interests.json     # the AI-heavy discovery corpus
│   ├── PROMPT.md          # the $0 Max-routine extraction path
│   └── seed/              # the 58 real seed nuggets already loaded
├── poc/          # the proof-of-concept (REVIEW.md, EXTRACTION_PROMPT.md = the production prompt)
├── INFRA.md      # Supabase project id / url / keys
└── HANDOFF.md    # the few operator-only steps to go live
```

**Status:** backend live (Supabase, 58 nuggets, ranked feed RPC). App builds + serves + installs.
See `HANDOFF.md` for the last-mile steps (deploy, auth email, routine).
