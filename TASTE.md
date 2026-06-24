# NUGGET — Taste (Coby's working model of what makes a nugget useful)

This file is the **curation brain**. The extraction agent reads it *before* deciding what to keep
and how to score, so Coby's taste shapes the feed at ingest — not just after the fact. It is
refined over time from in-app feedback (Useful / Not useful + reason, Saves). Coby can also edit
it directly. The numeric dials in Supabase (`taste_weights`) are the fast real-time re-rank layer;
THIS file is the slow, expressive layer that governs what gets extracted at all.

> When extracting, apply this. Drop what Coby dislikes; score what he likes high. When in doubt
> about a macro/awareness nugget, drop it.

## What Coby WANTS (keep, score high)
- **Tactical and actionable** — something he can DO. ("send a 6-8 sentence plain-text cold email",
  "set minimum-stay from the length of the high-demand run", "wire a sub-agent to the Playwright MCP").
- **Non-obvious** — a smart generalist wouldn't already know it.
- **Founder / operator STRATEGY + MARKETING tactics** — GTM, pricing, distribution mechanics, sales
  motions, positioning, productizing. (He keeps these even from "founder story" videos.)
- **AI-building tactics** — Claude Code, agents, MCP, eval/workflow patterns, concrete tool stacks.
- **STR pricing & operations tactics** — PriceLabs edges, Airbnb rule sets, occupancy forecasting,
  the lean operating kit.
- **Mental models that change how you'd ACT** (not just frame a fact).
- **Named frameworks WITH the actual steps; real numbers/benchmarks WITH the mechanism.**

## What Coby does NOT want (drop, or score low — actionability < 3, scope = macro)
- **Macro / bragging stats with no action** — "AI revenue ramps are faster now", "$10M ARR in 3-4
  months", "software cost collapsed 4000x", "AI is changing everything". Awareness, not leverage. DROP.
- **Obvious advice** — "talk to customers", "be consistent", "distribution matters".
- **Motivational / mindset / inspirational founder lore** — "go the distance", "Jobs ran NeXT at a
  loss for 10 years". Coby wants education, not inspiration. DROP.
- **Pure industry observation / awareness** with no thing-to-do.
- **Restatements of the video title; self-promo; sponsor reads; subscribe CTAs.**

## Hard style rules
- **NO em dashes, ever** (use colon, comma, period, or parentheses).
- Layman but not dumbed-down; middle-school readability; rich `context` + `payload` so a non-expert
  can use the nugget standalone.
- Role-first naming.

## How feedback works (free-write notes, not thumbs)
The app has ONE feedback action: **Note** — Coby free-writes what he thinks of a nugget and why.
(There is also Save = keep, and Watch later = the video.) The daily routine reads all notes
(`pipeline.py taste`) and does two things: (1) appends a refined bullet to "Learned specifics"
below, and (2) re-tunes the feed — nudge `taste_weights` (scope/tag/area) and/or re-grade or mute
existing nuggets that violate the new understanding. The notes are the evidence; THIS file is the
durable knowledge. Read each note for its *reason*, not just its sentiment — "just a stat, no
takeaway" is a scope complaint (suppress macro everywhere), not a topic complaint.

## Learned specifics (refined from feedback — newest on top; the routine appends here)
- 2026-06-23 (seed): Dropped "software cost collapsed ~4000x" and "$10M ARR in 3-4 months" as
  not-nugget-worthy. Reinforces: suppress macro AI/startup bragging stats hard, regardless of how
  surprising the number sounds. Founder *strategy/marketing* from the same videos stays valuable.
