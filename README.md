# NUGGET

**A personal, self-feeding stream of useful knowledge.** It replaces the doom-scroll habit with an
infinite TikTok-style feed where every card is a save-worthy, *non-obvious, tactical* insight ("nugget")
pulled from real YouTube transcripts across three lanes: **AI / building with AI**, **business ideas /
entrepreneurship**, and **short-term-rental operating**. Educational, not motivational. Single user (Coby).

> Live app: **nugget-sigma.vercel.app** · It runs itself. New nuggets arrive all day with nothing open.

---

## What it does, in one paragraph

Every few hours, a job in the cloud checks ~57 hand-picked, verified channels for new 2026 videos,
pulls each transcript, and uses an AI model to mine it for the handful of genuinely useful, non-obvious
tactics inside (dropping the filler, the hype, and the macro stats). Those nuggets land in a ranked,
swipeable feed on your phone. You read, save what's good, and tell it what you think. Once a day it reads
your feedback and gets sharper. You never open a laptop for any of it.

---

## How it works (end to end)

```
  GitHub Actions (cloud, 5x/day):
    57 channels -> newest 2026 videos -> transcript (Webshare proxy)
    -> AI extraction (Gemini) -> nuggets -> Supabase -> embeddings
                                   |
                                   v
  Supabase (Postgres + pgvector):
    videos . nuggets . feedback . library . taste_weights
    get_feed() = live recency-biased, taste-weighted ranking
                                   |
                                   v
  PWA on Vercel (your phone):
    Feed (swipe) . Library (saved) . You (what you've taught it)
                                   |   your Notes
                                   v
  GitHub Actions (cloud, 1x/day):
    learn: distill Notes -> TASTE.md -> commit -> future pulls improve
```

**1. Discovery + extraction — autonomous, 5x/day.** `nugget-daily.yml` runs `pipeline.py recent` at
6am / 9am / 12pm / 3pm / 6pm Central. It finds new 2026 videos across all channels, dedupes against
what's already stored, transcribes via the Webshare proxy, and extracts nuggets with **Gemini
3.1 Flash-Lite** guided by `poc/EXTRACTION_PROMPT.md` + `TASTE.md`. A quality gate drops weak nuggets.

**2. Ranking — computed live.** `get_feed()` scores each video by the sum of its nugget quality
(times actionability, topic/scope/channel weights, look-alike suppression) and a **recency bias** (today's
videos float to the top, good older ones still appear below). Changing your taste re-ranks everything
instantly, no re-processing.

**3. The feed — your phone.** One video per screen, swipe sideways through its nuggets. Per-card actions:
**Save** a nugget (or, on the cover, **Save** the whole video) - **Watch later** - **Note** (free-write
feedback) - **Done** (dismiss it from the feed; recoverable under the Done filter). Filters: topic
(All/AI/Building/STR), recency (dropdown), and Active/Done.

**4. The learning loop — autonomous, 1x/day.** `nugget-learn.yml` runs `pipeline.py learn` at 8am
Central: it reads your new Notes, has AI distill the durable preference behind them, appends it to
`TASTE.md`, and commits it back, so the *next* pulls extract to your sharpened taste. It costs nothing
on days you leave no notes.

---

## Status (live)

- **57 channels** monitored (AI 28 - Building 16 - STR 13), all IDs verified, all active in 2026.
- **5 pulls/day** + **1 learn/day**, fully autonomous on GitHub Actions (laptop-off).
- Feed: ~30 videos / ~170 nuggets and climbing (AI deep, STR seeded, Building still thin).
- **2026-only** hard rule on every video.
- **Backfill** (the ~1,372-video 2026 back-catalog at `backend/backfill_2026.json`) is drained
  on-demand on the Claude Max subscription, see `PICKUP.md`.

## Cost

Only AI extraction costs money: **~0.4 cents/video**, and only for genuinely-new videos (dedup means an
empty check is free). Realistically **~$2-4/month**. GitHub Actions (compute), Supabase, and Vercel are
all free tiers; Webshare (transcripts) is a flat sub. More-frequent checks do **not** cost more.

## Repo / where things live

```
nugget/
  app/                       # the PWA, its own repo (cobyc10916-hash/nugget -> Vercel auto-deploy)
  backend/
    pipeline.py              # discover -> transcript -> extract -> write, plus learn
    interests.json           # the 57 channels (ai/build/str) + topic-search corpus
    backfill_2026.json       # the 2026 back-catalog list (drained on Max)
  poc/EXTRACTION_PROMPT.md   # the canonical extraction spec the AI follows
  TASTE.md                   # the curation brain; what Coby likes/dislikes; the learn loop edits this
  .github/workflows/         # nugget-daily.yml (pulls) + nugget-learn.yml (feedback loop)
  PICKUP.md                  # how to resume the backfill grind
  INFRA.md                   # Supabase ids/urls (no secrets)
```

- **This repo** (`cobyc10916-hash/nugget-pipeline`, public) = the pipeline + workflows.
- **App repo** (`cobyc10916-hash/nugget`) = the PWA, auto-deploys to Vercel.
- **Supabase** project `nugget` / `ellnuqqlssupsrglxmwn` = the database.
- **Secrets** (Webshare, Supabase service key, Gemini key) live only in GitHub repo Settings -> Secrets,
  never in code. The app login is kept in the operator's private notes (not in this public repo).

## The principle

The feed is a **filter, not a backlog**. You never "get through" it. Recency plus your taste hand you the
right slice; Done clears what you're finished with; Save and your Notes are the only memory that matters.
The whole point is that it gets better the more you use it, and asks nothing of you to keep running.
