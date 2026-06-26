#!/usr/bin/env python3
"""
NUGGET Curator — the OPERATOR agent of the system.

This is not a single narrow API call. It is a reasoning loop (Claude with tools) that, once or
twice a day, looks at the WHOLE system the way a human curator would and decides what to change:

  - Reads Coby's brain (declared profile + its own prior learned notes), his recent saves, his
    free-write notes, his dismissals, the area mix he's been served, and what's flowing through
    the feed + pulse right now.
  - CONSOLIDATES the learned profile (rewrites it bounded, prunes stale/contradicted bullets) so it
    sharpens over time instead of bloating forever.
  - Sets durable ANCHORS on taste dials (persistent preferences that survive nightly decay) and
    makes transient nudges where behavior warrants.
  - FLAGS GAPS / blind spots ("you've ignored Building for 2 weeks — intentional?").
  - Writes a transparent operator_log entry: what it changed and why. The app shows this.

Everything the operator can do is a TOOL it calls; the loop applies each call to Supabase. Declared
preferences are authoritative and never overwritten here — the operator only maintains the LEARNED
layer and the dials.

Env:
  SUPABASE_URL, SUPABASE_SERVICE_KEY   (service role; writes brain + dials + operator_log)
  ANTHROPIC_API_KEY                    (required — this agent is judgment-heavy)
  CURATOR_MODEL                        (default claude-sonnet-4-6)
Usage:
  python curator.py run            # one operator pass
  python curator.py run --dry      # reason + print, apply nothing (no DB writes)
"""
from __future__ import annotations
import argparse, json, os, sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
try:
    from dotenv import load_dotenv
    load_dotenv(HERE / ".env")
    load_dotenv(HERE.parents[1] / ".env")
except Exception:
    pass

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY")
ANTHROPIC_KEY = os.environ.get("ANTHROPIC_API_KEY")
MODEL = os.environ.get("CURATOR_MODEL", "claude-sonnet-4-6")

def sb():
    from supabase import create_client
    if not (SUPABASE_URL and SUPABASE_KEY):
        sys.exit("Set SUPABASE_URL + SUPABASE_SERVICE_KEY")
    return create_client(SUPABASE_URL, SUPABASE_KEY)

# ---------------- gather the full picture ----------------
def _gather(client) -> dict:
    prof = (client.table("app_profile").select("declared_md,learned_md,priorities,gaps").eq("id", 1).execute().data or [{}])[0]
    dials = client.table("taste_weights").select("dimension,key,weight,anchor").execute().data or []

    saves = client.table("library").select(
        "kind,created_at,nugget_id,video_id,nuggets(hook,interest_area,scope,topic_tags),videos(title,interest_area)"
    ).neq("status", "archived").order("created_at", desc=True).limit(40).execute().data or []

    fb = client.table("feedback").select(
        "action,note_text,reason,created_at,nuggets(hook,interest_area,scope,topic_tags)"
    ).in_("action", ["note", "not_useful", "trash"]).order("created_at", desc=True).limit(40).execute().data or []

    # what he's actually been SERVED lately, by area (exposure) — last 14 days
    vids = client.table("videos").select("interest_area,published_at,extracted_at,relevance").execute().data or []
    cutoff = datetime.now(timezone.utc) - timedelta(days=14)
    def _recent(v):
        ts = v.get("extracted_at") or v.get("published_at")
        try:
            return ts and datetime.fromisoformat(ts.replace("Z", "+00:00")) >= cutoff
        except Exception:
            return False
    exposure = {}
    for v in vids:
        if _recent(v):
            exposure[v.get("interest_area") or "?"] = exposure.get(v.get("interest_area") or "?", 0) + 1

    # what's flowing right now (sample) — feed cards + pulse items
    try:
        feed = client.rpc("get_feed", {"p_limit": 18}).execute().data or []
    except Exception:
        feed = []
    try:
        pulse = client.rpc("get_pulse_items", {"p_hours": 24, "p_area": None, "p_limit": 30}).execute().data or []
    except Exception:
        pulse = []

    prior = client.table("operator_log").select("run_at,summary,gaps").order("run_at", desc=True).limit(3).execute().data or []
    return {"prof": prof, "dials": dials, "saves": saves, "fb": fb,
            "exposure": exposure, "feed": feed, "pulse": pulse, "prior": prior}

def _fmt_context(ctx: dict) -> str:
    p = ctx["prof"]
    out = []
    out.append("# DECLARED PROFILE (Coby-owned, AUTHORITATIVE — do not contradict or rewrite this):\n" + (p.get("declared_md") or "(empty)"))
    out.append("\n# PRIORITIES (declared):\n" + "\n".join(f"- {x}" for x in (p.get("priorities") or [])))
    out.append("\n# YOUR CURRENT LEARNED NOTES (you maintain this — consolidate/prune it):\n" + (p.get("learned_md") or "(empty)"))
    gaps = p.get("gaps") or []
    out.append("\n# OPEN GAPS you previously flagged:\n" + ("\n".join(f"- {g}" for g in gaps) if gaps else "(none)"))

    out.append("\n# TASTE DIALS (weight = live, anchor = durable baseline it decays toward):")
    for d in sorted(ctx["dials"], key=lambda x: -(x.get("weight") or 1)):
        out.append(f"- {d['dimension']}:{d['key']}  weight={round(d.get('weight') or 1,2)} anchor={round(d.get('anchor') or 1,2)}")

    out.append("\n# RECENT SAVES (strongest positive signal — what he chose to keep):")
    for s in ctx["saves"][:25]:
        n = s.get("nuggets") or {}; v = s.get("videos") or {}
        label = n.get("hook") or v.get("title") or s.get("video_id") or "?"
        area = n.get("interest_area") or v.get("interest_area") or "?"
        tags = ",".join((n.get("topic_tags") or [])[:4])
        out.append(f"- [{s.get('kind')}] ({area}) {str(label)[:90]}" + (f"  #{tags}" if tags else ""))

    notes = [f for f in ctx["fb"] if f.get("action") == "note" and (f.get("note_text") or "").strip()]
    negs = [f for f in ctx["fb"] if f.get("action") in ("not_useful", "trash")]
    out.append("\n# FREE-WRITE NOTES (his own words — read for the underlying REASON):")
    for f in notes[:20]:
        n = f.get("nuggets") or {}
        out.append(f'- "{f["note_text"].strip()[:200]}"  (on: {str(n.get("hook") or "a video")[:70]})')
    if not notes:
        out.append("- (none new)")
    out.append("\n# RECENT NEGATIVES (dismissed/not-useful):")
    for f in negs[:12]:
        n = f.get("nuggets") or {}
        out.append(f'- {f.get("action")}: {str(n.get("hook") or "?")[:80]} (reason={f.get("reason")})')
    if not negs:
        out.append("- (none)")

    out.append("\n# EXPOSURE (videos he was served, last 14d, by area): " + (json.dumps(ctx["exposure"]) or "{}"))
    out.append("\n# IN THE FEED RIGHT NOW (top cards):")
    for v in ctx["feed"][:15]:
        out.append(f"- ({v.get('interest_area')}) {str(v.get('title'))[:90]}")
    out.append("\n# IN PULSE RIGHT NOW (last 24h, top items):")
    for it in ctx["pulse"][:20]:
        out.append(f"- ({it.get('area')}) {str(it.get('title'))[:90]}")

    if ctx["prior"]:
        out.append("\n# YOUR LAST RUNS (for continuity — don't repeat yourself):")
        for r in ctx["prior"]:
            out.append(f"- {r.get('run_at','')[:16]}: {str(r.get('summary') or '')[:160]}")
    return "\n".join(out)

# ---------------- the operator's charter ----------------
SYSTEM = """You are the OPERATOR of NUGGET — Coby's personal intelligence system. You are not a
one-shot summarizer; you are the standing curator who keeps the whole system tuned to him.

NUGGET has two surfaces:
- FEED: precision. Only what is genuinely useful to Coby, ranked by his taste. Guardrails keep it
  from collapsing into a bubble.
- PULSE: recall. A daily brief so he misses nothing important in AI (plus light build/STR).

Your purpose, every run:
1. UNDERSTAND him from evidence: his declared profile + priorities (authoritative), what he SAVED
   (strongest signal), what he wrote in NOTES (read for the underlying reason, not just sentiment),
   what he dismissed, and the MIX he's actually been served.
2. MAINTAIN THE LEARNED LAYER. You own a short "learned notes" section of his profile. Rewrite it
   each run: merge duplicates, drop anything stale or contradicted by newer behavior, keep only
   durable, generalizable preferences. HARD CAP ~200 words. This is how the brain sharpens instead
   of bloating. Never restate the declared profile; capture only what you've LEARNED beyond it.
3. SET DURABLE ANCHORS for preferences that should persist (survive nightly decay): use set_anchor
   for areas/scopes/tags/channels he clearly and repeatedly cares about (anchor 1.3-1.8) or clearly
   wants less of (0.4-0.7). Anchor 1.0 = neutral. Be conservative; anchors are commitments.
4. NUDGE transient signals with nudge_weight (factor 0.8-1.2) when a recent pattern warrants a small
   reversible adjustment but not a standing commitment.
5. FLAG GAPS with flag_gap: blind spots or drift worth his attention — an area he used to engage and
   now ignores, an over-concentration (bubble risk), a stated priority the feed isn't serving, or a
   recurring topic in Pulse he might want pulled into the Feed. Phrase each as a short, direct
   observation or question addressed to Coby.

Principles: prefer a few high-confidence changes over many speculative ones. Honor anti-bubble — if
one area dominates exposure and saves, consider whether other declared priorities are being starved.
Do not punish areas just because they're quiet; ask (flag_gap) before suppressing. No em dashes.

Workflow: call tools to make your changes (you may call several). When you are done, STOP and reply
with a 2-4 sentence summary of what you changed and why — that summary becomes the operator log Coby
reads. If nothing meaningfully warrants a change, make no tool calls and say so briefly."""

TOOLS = [
    {"name": "update_learned_profile",
     "description": "Replace your LEARNED notes section (consolidated, pruned, <=200 words). This is the only profile text you own; the declared profile is Coby's and off-limits.",
     "input_schema": {"type": "object", "required": ["learned_md"],
         "properties": {"learned_md": {"type": "string", "description": "The full new learned-notes markdown (bullets). Replaces the old one entirely."}}}},
    {"name": "set_anchor",
     "description": "Set a DURABLE anchor on a taste dial — a persistent preference that survives nightly decay. The live weight relaxes toward this baseline over time.",
     "input_schema": {"type": "object", "required": ["dimension", "key", "anchor", "reason"],
         "properties": {
             "dimension": {"type": "string", "enum": ["area", "scope", "tag", "channel"]},
             "key": {"type": "string", "description": "e.g. area 'ai'|'build'|'str'; scope 'tactical'|'macro'|'mixed'; a tag; or a channel_id"},
             "anchor": {"type": "number", "description": "0.3-2.5. >1 = lean in (durably), <1 = pull back, 1 = neutral"},
             "reason": {"type": "string"}}}},
    {"name": "nudge_weight",
     "description": "Make a small, reversible nudge to a taste dial's live weight (not a standing commitment).",
     "input_schema": {"type": "object", "required": ["dimension", "key", "factor", "reason"],
         "properties": {
             "dimension": {"type": "string", "enum": ["area", "scope", "tag", "channel"]},
             "key": {"type": "string"},
             "factor": {"type": "number", "description": "0.8-1.2. >1 more, <1 less"},
             "reason": {"type": "string"}}}},
    {"name": "flag_gap",
     "description": "Flag a blind spot, drift, bubble risk, or suggestion for Coby. Shown in the app. Short and direct.",
     "input_schema": {"type": "object", "required": ["text"],
         "properties": {"text": {"type": "string"}}}},
]

def _apply_tool(client, name, inp, state, dry):
    """Execute one operator tool call against Supabase; record it. Returns a short result string."""
    if name == "update_learned_profile":
        md = (inp.get("learned_md") or "").strip()
        state["learned_md"] = md
        if not dry:
            client.table("app_profile").update({"learned_md": md}).eq("id", 1).execute()
        state["actions"].append({"tool": "update_learned_profile", "chars": len(md)})
        return f"learned profile updated ({len(md)} chars)"
    if name == "set_anchor":
        d, k = inp.get("dimension"), (inp.get("key") or "").strip()
        a = float(inp.get("anchor", 1.0))
        if not dry:
            client.rpc("set_taste_anchor", {"p_dim": d, "p_key": k, "p_anchor": a}).execute()
        state["actions"].append({"tool": "set_anchor", "dimension": d, "key": k, "anchor": a, "reason": inp.get("reason")})
        return f"anchor set {d}:{k} -> {a}"
    if name == "nudge_weight":
        d, k = inp.get("dimension"), (inp.get("key") or "").strip()
        f = max(0.8, min(1.2, float(inp.get("factor", 1.0))))
        if not dry:
            client.rpc("_taste_nudge", {"p_dim": d, "p_key": k, "p_factor": f}).execute()
        state["actions"].append({"tool": "nudge_weight", "dimension": d, "key": k, "factor": f, "reason": inp.get("reason")})
        return f"nudged {d}:{k} *= {f}"
    if name == "flag_gap":
        t = (inp.get("text") or "").strip()
        if t:
            state["gaps"].append(t)
        return "gap flagged"
    return f"unknown tool {name}"

def run(dry=False):
    if not ANTHROPIC_KEY:
        sys.exit("[curator] ANTHROPIC_API_KEY required")
    import anthropic
    client = sb()
    ctx = _gather(client)
    user_msg = _fmt_context(ctx) + "\n\nDo your operator pass now."
    state = {"actions": [], "gaps": [], "learned_md": None}

    ac = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    messages = [{"role": "user", "content": user_msg}]
    summary = ""
    for turn in range(10):
        msg = ac.messages.create(model=MODEL, max_tokens=3000, system=SYSTEM, tools=TOOLS, messages=messages)
        # collect any text + tool calls in this assistant turn
        text_parts = [b.text for b in msg.content if b.type == "text"]
        if text_parts:
            summary = "\n".join(t for t in text_parts if t.strip()) or summary
        tool_uses = [b for b in msg.content if b.type == "tool_use"]
        messages.append({"role": "assistant", "content": msg.content})
        if not tool_uses or msg.stop_reason != "tool_use":
            break
        results = []
        for tu in tool_uses:
            try:
                res = _apply_tool(client, tu.name, tu.input or {}, state, dry)
            except Exception as e:
                res = f"error: {type(e).__name__}: {str(e)[:120]}"
            print(f"  [tool] {tu.name} {json.dumps(tu.input or {})[:160]} -> {res}")
            results.append({"type": "tool_result", "tool_use_id": tu.id, "content": res})
        messages.append({"role": "user", "content": results})

    summary = (summary or "(no summary)").strip()
    # Recompose profile_md (= declared + learned) so the extractor and Pulse synth read one combined brain.
    declared = (ctx["prof"].get("declared_md") or ctx["prof"].get("learned_md") or "")
    learned = state["learned_md"] if state["learned_md"] is not None else (ctx["prof"].get("learned_md") or "")
    composed = declared + (("\n\n## Learned (operator-maintained)\n" + learned) if learned.strip() else "")
    now = datetime.now(timezone.utc)
    if not dry:
        client.table("app_profile").update({
            "profile_md": composed, "gaps": state["gaps"], "operator_updated_at": now.isoformat(),
        }).eq("id", 1).execute()
        client.table("operator_log").insert({
            "model": MODEL, "summary": summary, "actions": state["actions"], "gaps": state["gaps"],
            "stats": {"saves": len(ctx["saves"]), "notes": len([f for f in ctx["fb"] if f.get("action") == "note"]),
                      "exposure": ctx["exposure"]},
        }).execute()
    print(f"\n[curator] {'DRY ' if dry else ''}done. {len(state['actions'])} action(s), {len(state['gaps'])} gap(s).")
    print("SUMMARY:\n" + summary)
    return summary

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["run"])
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()
    run(dry=a.dry)
