# Set up the NUGGET daily routine (one-time, ~10 min)

The autonomous $0 path: a Claude Code routine runs every morning on your Max subscription, pulls the
newest videos from reputable AI channels, extracts nuggets to your taste, and loads them into the feed.

## 1. The code is on GitHub
I pushed it to **`cobyc10916-hash/nugget-pipeline`**. It has the pipeline, the channel list, the
extraction prompt, `TASTE.md` (your taste model), and `ROUTINE.md` (the prompt to paste).

## 2. Create the routine (claude.ai/code → Routines)
- **New routine** → connect the GitHub repo **`cobyc10916-hash/nugget-pipeline`**.
- **Prompt:** paste the entire contents of **`ROUTINE.md`** from that repo.
- **Model:** Sonnet (better extraction for judging the PoC) — you can drop to Haiku later for volume.
- **Schedule:** daily at **7:00 AM** your timezone.

## 3. Connect Supabase + add secrets
- The **Supabase connector** must be connected to your Claude account (it already is — we've been
  using it). The routine writes nuggets through it.
- **GitHub** must be connected (so the routine can read the repo and commit TASTE.md updates).
- Add these as routine **secrets / env vars** (values are in your chat with me, not committed here):
  - `WEBSHARE_PROXY_USERNAME`
  - `WEBSHARE_PROXY_PASSWORD`
  - `SUPABASE_ANON_KEY`

## 4. Test-fire it (don't skip this)
Hit **Run now**. Watch it pull ~5 videos, extract, and write. Then open the app → Feed: new videos
should appear. If they do, the 7am schedule is trustworthy and you'll wake up to fresh nuggets.

## What it does each morning
Pulls the 5 newest uploads (last 24–48h) from 13 reputable AI channels → transcribes → extracts
only your kind of nuggets (applying TASTE.md) → writes them to the feed → embeds them for look-alike
suppression → reads any feedback notes you left and sharpens TASTE.md. Fully hands-off.
