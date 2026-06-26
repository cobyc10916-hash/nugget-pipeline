#!/usr/bin/env python3
"""
NUGGET Pulse — the recall-first 24h multi-source AI digest.

Two commands (run on GitHub Actions crons):
  python pulse.py ingest        # fetch ALL free sources -> normalize -> score -> upsert pulse_items
  python pulse.py synthesize    # read last-24h items -> strong model writes the daily brief -> pulse_digest

Design contract (see plan): Pulse optimizes RECALL (miss nothing in 24h). Taste only ORDERS items
(a small importance nudge), it NEVER hides them. The Feed is the precision/tailored surface; Pulse is
the comprehensive one.

Env:
  SUPABASE_URL, SUPABASE_SERVICE_KEY      (service role; bypasses RLS to write pulse_*)
  ANTHROPIC_API_KEY and/or GEMINI_API_KEY (only `synthesize` needs a model; `ingest` is keyless)
  PULSE_SYNTH_MODEL                        (default claude-sonnet-4-6; falls back to gemini if no Anthropic key)
"""
from __future__ import annotations
import argparse, json, math, os, sys, re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))  # so `from sources import radar_fetch` works under `python backend/pulse.py`

try:
    from dotenv import load_dotenv
    load_dotenv(HERE / ".env")
    load_dotenv(HERE.parents[1] / ".env")
except Exception:
    pass

from sources import radar_fetch as rf

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY")
ANTHROPIC_KEY = os.environ.get("ANTHROPIC_API_KEY")
GEMINI_KEY = os.environ.get("GEMINI_API_KEY")
SYNTH_MODEL = os.environ.get("PULSE_SYNTH_MODEL", "claude-sonnet-4-6")

# Curated X/Twitter watchlist — only the highest-signal voices for Coby's lanes (agentic coding /
# Claude Code, frontier AI, AI building). Pulled via Apify (free syndication blocks CI IPs). Keep
# this tight: add/remove a handle here, nothing else changes.
X_HANDLES = [
    "AnthropicAI",   # his core stack (Claude / Claude Code) - official signal
    "alexalbert__",  # Claude Code / Anthropic - his #1 priority, agentic coding
    "simonw",        # Simon Willison - practical LLM + agentic-coding tooling
    "swyx",          # AI engineering / agent patterns (Latent Space)
    "karpathy",      # frontier AI, agents, first-principles
    "sama",          # Sam Altman - frontier / industry direction
]

def sb():
    from supabase import create_client
    if not (SUPABASE_URL and SUPABASE_KEY):
        sys.exit("Set SUPABASE_URL + SUPABASE_SERVICE_KEY")
    return create_client(SUPABASE_URL, SUPABASE_KEY)

# ---------------- normalization ----------------
# Source-type weights: labs/research/newsletters/claude-ecosystem rank above raw social.
SRC_W = {"lab": 1.6, "research": 1.3, "newsletter": 1.3, "claude": 1.5, "funding": 1.2,
         "market": 1.15, "models": 1.1, "repos": 1.1, "longform": 1.05, "social": 0.9}

VEL_KIND = {"ghtrend": "stars_today", "hn": "hn_points", "hf": "trendingScore"}

def velocity_kind(source_key: str) -> str | None:
    if not source_key:
        return None
    if source_key in VEL_KIND:
        return VEL_KIND[source_key]
    if source_key.startswith("x_"):
        return "likes"
    return None

# Recall-first light classifier: default everything to 'ai'; only peel off obvious build/STR items.
STR_KW = ("airbnb", "short-term rental", "short term rental", "str ", "occupancy", "pricelabs",
          "vacation rental", "vrbo", "nightly rate", "adr ")
BUILD_KW = ("startup", "founder", "fundrais", "seed round", "series a", "go-to-market", "gtm",
            "saas", " arr", "solopreneur", "indie hacker", "bootstrapp")

def classify_area(title: str, summary: str) -> str:
    t = (title + " " + (summary or "")).lower()
    if any(k in t for k in STR_KW):
        return "str"
    if any(k in t for k in BUILD_KW):
        return "build"
    return "ai"

def parse_date(s: str):
    if not s:
        return None
    s = s.strip()
    # RFC-822 (RSS) first, then a few ISO/Atom shapes.
    try:
        dt = parsedate_to_datetime(s)
        if dt:
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        pass
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S.%f%z",
                "%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(s, fmt)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except Exception:
            continue
    return None

# words too generic to be a useful interest signal when split out of a priority phrase
_STOP = {"with", "that", "what", "this", "into", "from", "your", "their", "about", "have", "more",
         "than", "then", "they", "them", "will", "when", "which", "just", "like", "make", "need",
         "want", "real", "good", "next", "early", "based", "apply", "stuff", "things", "genuinely"}

def _brain_keywords(client) -> dict:
    """Phrase -> weight map of what Coby actually cares about, from his anchored/strong tag dials and
    his stated priorities. This is what makes Pulse selection PERSONAL: his lanes rise above generic
    velocity, instead of a tiny afterthought nudge."""
    kw = {}
    try:
        tw = client.table("taste_weights").select("key,weight").eq("dimension", "tag").gt("weight", 1.05).execute().data or []
        for r in tw:
            k = (r.get("key") or "").lower().replace("-", " ").strip()
            if k:
                kw[k] = max(kw.get(k, 0), min(0.6, (float(r.get("weight") or 1) - 1) + 0.2))
    except Exception:
        pass
    try:
        prof = client.table("app_profile").select("priorities").eq("id", 1).execute().data
        for p in ((prof[0].get("priorities") if prof else []) or []):
            for tok in re.findall(r"[a-z][a-z\-]{3,}", (p or "").lower()):
                tok = tok.replace("-", " ")
                if tok not in _STOP:
                    kw[tok] = max(kw.get(tok, 0), 0.25)
    except Exception:
        pass
    return kw

def importance(item: dict, published_dt, now, kw) -> float:
    st = SRC_W.get(item.get("category"), 1.0)
    v = item.get("velocity")
    vel_norm = min(math.log1p(v) / 8.0, 1.0) if isinstance(v, (int, float)) and v > 0 else 0.0
    rec = 1.0
    if published_dt:
        hrs = (now - published_dt).total_seconds() / 3600.0
        rec = max(0.0, 1.0 - hrs / 48.0)
    text = (item.get("title", "") + " " + (item.get("summary", "") or "")).lower().replace("-", " ")
    personal = 0.0
    for phrase, w in kw.items():
        if phrase and phrase in text:
            personal += w
    personal = min(personal, 1.5)
    # personal is the LEAD signal (his lanes rise to the top); velocity + recency keep genuinely big
    # news visible even when it's outside his lanes ("my lanes first, then big news").
    return round((st + 1.2 * vel_norm + 1.0 * rec) * (1 + 1.3 * personal), 4)

# ---------------- ingest ----------------
def ingest(max_per_source=15, no_social=False, with_x=False):
    client = sb()
    now = datetime.now(timezone.utc)
    # Personalization signal: his anchored interests + priorities drive which items rise (not a tiny nudge).
    kw = _brain_keywords(client)

    out_dir = str(HERE / "state" / "radar_cache")
    items, status = rf.collect(max_per_source=max_per_source, no_social=no_social, out_dir=out_dir) \
        if hasattr(rf, "collect") else _collect_fallback(max_per_source, no_social, out_dir)

    # X/Twitter via Apify — the one source whose free syndication blocks CI datacenter IPs. Best-effort
    # bonus (used wisely: ~8 handles, ~3 each, only at brief hours not every hourly ingest); never
    # fails the run on its own.
    if with_x and not no_social and os.environ.get("APIFY_TOKEN"):
        try:
            from sources import apify_fetch as af
            xt = af.x_tweets(X_HANDLES, per=3, max_items=30)
            items.extend(xt)
            status.append(("OK", "X/Twitter (Apify)", f"{len(xt)} tweets"))
        except Exception as e:
            status.append(("FAIL", "X/Twitter (Apify)", f"{type(e).__name__}: {str(e)[:80]}"))

    ok = sum(1 for s in status if s[0] == "OK")
    failed = sum(1 for s in status if s[0] == "FAIL")
    print(f"[pulse-ingest] sources ok={ok} failed={failed}, raw items={len(items)}")
    for st, name, msg in sorted(status):
        print(f"  [{st}] {name} — {msg}")
    # Fail LOUD on a total outage (every source down) so a green check can't hide it.
    if ok == 0:
        sys.exit("[pulse-ingest] ABORT: every source failed — outage, nothing ingested")

    rows, seen_fp = [], set()
    for it in items:
        title = (it.get("title") or "").strip()
        if not title:
            continue
        fp = rf.fingerprint(it)
        if fp in seen_fp:
            continue
        seen_fp.add(fp)
        pub = parse_date(it.get("date", ""))
        summary = (it.get("summary") or "")[:600]
        area = classify_area(title, summary)
        rows.append({
            "external_id": fp,
            "source_type": it.get("category") or "other",
            "source_name": it.get("source") or "?",
            "source_key": it.get("source_key"),
            "url": it.get("link"),
            "title": title[:500],
            "summary": summary,
            "area": area,
            "velocity": it.get("velocity") if isinstance(it.get("velocity"), (int, float)) else None,
            "velocity_kind": velocity_kind(it.get("source_key", "")),
            "importance_score": importance(it, pub, now, kw),
            "published_at": pub.isoformat() if pub else None,
            # NOTE: fetched_at intentionally omitted -> DB default now() on insert, untouched on conflict
            "raw": it,
        })

    # Upsert in chunks on external_id (re-fetches refresh velocity/importance but keep first-seen fetched_at).
    n = 0
    for i in range(0, len(rows), 200):
        chunk = rows[i:i + 200]
        client.table("pulse_items").upsert(chunk, on_conflict="external_id").execute()
        n += len(chunk)
    print(f"[pulse-ingest] upserted {n} normalized items "
          f"(area mix: {_area_mix(rows)})")
    return n

def _collect_fallback(max_per_source, no_social, out_dir):
    """If the vendored radar_fetch has no collect() (older copy), assemble the tasks here."""
    import concurrent.futures as cf
    mx = max_per_source
    tasks = [(s[1], (lambda s=s: rf.fetch_rss(s, mx))) for s in rf.RSS_SOURCES]
    tasks += [("HN", lambda: rf.fetch_hn(mx)), ("HuggingFace", lambda: rf.fetch_hf(mx)),
              ("MCP Registry", lambda: rf.fetch_mcp(mx)), ("Claude Code changelog", rf.fetch_claude_changelog),
              ("GitHub Trending", lambda: rf.fetch_github_trending(mx)),
              ("YouTube", lambda: rf.fetch_youtube(mx, out_dir))]
    if not no_social:
        tasks += [("Reddit", lambda: rf.fetch_reddit(mx)), ("X/Twitter", lambda: rf.fetch_twitter(mx, out_dir))]
    results, status = [], []
    with cf.ThreadPoolExecutor(max_workers=6) as ex:
        futs = {ex.submit(fn): name for name, fn in tasks}
        for fut in cf.as_completed(futs):
            name = futs[fut]
            try:
                got = fut.result()
                errs = [x for x in got if x.get("_error")]
                good = [x for x in got if not x.get("_error")]
                results.extend(good)
                if errs:
                    for e in errs:
                        status.append(("FAIL", e.get("source", name), e["_error"]))
                else:
                    status.append(("OK", name, f"{len(good)} items"))
            except Exception as e:
                status.append(("FAIL", name, str(e)))
    return results, status

def _area_mix(rows):
    m = {}
    for r in rows:
        m[r["area"]] = m.get(r["area"], 0) + 1
    return m

# ---------------- synthesize ----------------
def _build_system(profile_md, priorities, leaning):
    pri = "\n".join(f"- {p}" for p in (priorities or [])) or "- (none set)"
    lean = ", ".join(leaning) if leaning else "(nothing strong yet)"
    return (
        "You are Coby's personal AI intelligence analyst. Produce his daily brief as a TIGHT, CURATED, "
        "PERSONAL digest where EVERY item visibly earns its place for HIM. Most candidates should not "
        "make the cut. This is the one tab he checks daily, so each item must feel deliberate.\n\n"
        "WHO COBY IS:\n" + (profile_md or "") + "\n\nHIS PRIORITIES (lead with these):\n" + pri +
        "\nHe has been leaning into: " + lean + "\n\n"
        "RULES:\n"
        "- LEAD with what is squarely in his lanes (agentic coding / Claude Code, AI building tactics, "
        "AI-native business + distribution with a real mechanism, short-term-rental / real-estate edges, "
        "early signal on what is worth building). THEN, in a clearly separate section, include ONLY "
        "genuinely MAJOR general AI news even if outside his lanes, so he never misses something big.\n"
        "- CUT hype, generic awareness stats, funding-as-spectacle, motivational lore, and anything he "
        "would find basic. If an item is not worth his attention, leave it out entirely.\n"
        "- For EVERY item the 'why' must be SPECIFIC TO HIM and concrete: e.g. 'fewer tokens on your big "
        "agent loops' or 'a pricing mechanic you can copy', NOT 'important for developers'. No em dashes.\n"
        "- Be tight: about 6 to 10 items total across 2 to 4 sections, readable in ~90 seconds. Group "
        "related items; never list the same story twice.\n\n"
        "OUTPUT: return ONLY valid JSON (no markdown, no code fences, no preamble) of this exact shape:\n"
        "{\n"
        '  "headline": "one tight sentence: the state of his day",\n'
        '  "sections": [\n'
        '    {"title": "short section name", "items": [\n'
        '      {"title": "the thing itself", "why": "why it matters to Coby, specific and concrete", '
        '"source": "source name", "url": "link or empty string", "area": "ai|build|str|other"}\n'
        "    ]}\n"
        "  ]\n"
        "}"
    )

def _parse_brief(raw):
    """Parse the model's JSON brief, tolerating code fences / stray prose. Returns a sanitized
    {headline, sections:[{title, items:[{title,why,source,url,area}]}]} or None if unusable."""
    s = (raw or "").strip()
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z]*\n?", "", s)
        s = re.sub(r"\n?```$", "", s).strip()
    a, b = s.find("{"), s.rfind("}")
    if a >= 0 and b > a:
        s = s[a:b + 1]
    try:
        obj = json.loads(s)
    except Exception:
        return None
    if not isinstance(obj, dict) or not isinstance(obj.get("sections"), list):
        return None
    secs = []
    for sec in obj["sections"]:
        if not isinstance(sec, dict):
            continue
        items = []
        for it in (sec.get("items") or []):
            if not isinstance(it, dict) or not it.get("title"):
                continue
            items.append({
                "title": str(it.get("title") or "").strip(),
                "why": str(it.get("why") or "").strip(),
                "source": str(it.get("source") or "").strip(),
                "url": str(it.get("url") or "").strip(),
                "area": it.get("area") if it.get("area") in ("ai", "build", "str", "other") else "ai",
            })
        if items:
            secs.append({"title": str(sec.get("title") or "").strip(), "items": items})
    if not secs:
        return None
    return {"headline": str(obj.get("headline") or "").strip(), "sections": secs}

def _brief_to_md(obj):
    """Readable markdown fallback (old clients / safety), derived from the structured brief."""
    out = [obj.get("headline", "")]
    for s in obj.get("sections", []):
        out.append("\n### " + s.get("title", ""))
        for it in s.get("items", []):
            link = f" [{it['source']}]({it['url']})" if it.get("url") else (f" ({it['source']})" if it.get("source") else "")
            out.append(f"- **{it['title']}** — {it['why']}{link}")
    return "\n".join(out)

def synthesize(hours=24, top_n=90):
    client = sb()
    now = datetime.now(timezone.utc)
    items = client.rpc("get_pulse_items", {"p_hours": hours, "p_area": None, "p_limit": top_n}).execute().data or []
    if not items:
        print("[pulse-synthesize] no items in window — nothing to synthesize"); return
    profile_md, priorities = "", []
    try:
        prof = client.table("app_profile").select("profile_md,priorities").eq("id", 1).execute().data
        if prof:
            profile_md = prof[0].get("profile_md") or ""
            priorities = prof[0].get("priorities") or []
    except Exception:
        pass
    leaning = list(_brain_keywords(client).keys())[:18]
    system = _build_system(profile_md, priorities, leaning)

    lines = []
    for it in items:
        vel = f" [{it.get('velocity_kind')}={it.get('velocity')}]" if it.get("velocity") else ""
        lines.append(f"- ({it.get('source_name')}) {it.get('title')}{vel} {it.get('url') or ''}\n    {(it.get('summary') or '')[:200]}")
    user_msg = (f"Here are the {len(items)} candidate items from the last {hours}h, pre-ranked by fit to him. "
                "Curate his brief now. Return ONLY the JSON.\n\n" + "\n".join(lines))

    raw, model_used = _synth_call(system, user_msg)
    if not raw:
        sys.exit("[pulse-synthesize] model returned nothing")

    brief_obj = _parse_brief(raw)
    by_source = {}
    for it in items:
        by_source[it.get("source_name")] = by_source.get(it.get("source_name"), 0) + 1
    stats = {"total_in_window": len(items), "by_source": by_source}
    today = now.date().isoformat()
    row = {"digest_date": today, "generated_at": now.isoformat(), "window_start": None,
           "window_end": now.isoformat(), "model": model_used, "stats": stats}
    if brief_obj:
        n_items = sum(len(s.get("items") or []) for s in brief_obj["sections"])
        row["sections"] = brief_obj
        row["brief_md"] = _brief_to_md(brief_obj)
        client.table("pulse_digest").upsert(row, on_conflict="digest_date").execute()
        print(f"[pulse-synthesize] wrote STRUCTURED digest for {today} "
              f"({model_used}, {n_items} items, {len(brief_obj['sections'])} sections)")
    else:
        row["sections"] = None
        row["brief_md"] = raw
        client.table("pulse_digest").upsert(row, on_conflict="digest_date").execute()
        print(f"[pulse-synthesize] JSON parse failed; stored raw markdown fallback for {today}")

def _synth_call(system, user_msg):
    """Strong model for the synthesis (Claude by default). Falls back to Gemini if no Anthropic key."""
    if ANTHROPIC_KEY and SYNTH_MODEL.startswith("claude"):
        try:
            import anthropic
            c = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
            m = c.messages.create(model=SYNTH_MODEL, max_tokens=2500,
                                  system=system,
                                  messages=[{"role": "user", "content": user_msg}])
            return "".join(b.text for b in m.content if b.type == "text").strip(), SYNTH_MODEL
        except Exception as e:
            print(f"  [synth] Claude failed ({type(e).__name__}: {str(e)[:120]}); falling back to Gemini")
    if GEMINI_KEY:
        import requests
        url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.1-flash-lite:generateContent"
        r = requests.post(url, params={"key": GEMINI_KEY},
                          json={"systemInstruction": {"parts": [{"text": system}]},
                                "contents": [{"role": "user", "parts": [{"text": user_msg}]}],
                                "generationConfig": {"maxOutputTokens": 2500, "temperature": 0.4}}, timeout=120)
        if r.status_code == 200:
            cand = r.json()["candidates"][0]
            return "".join(p.get("text", "") for p in cand.get("content", {}).get("parts", [])).strip(), "gemini-3.1-flash-lite"
        print(f"  [synth] Gemini {r.status_code}: {r.text[:140]}")
    return "", "none"

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["ingest", "synthesize"])
    ap.add_argument("--max-per-source", type=int, default=15)
    ap.add_argument("--hours", type=int, default=24)
    ap.add_argument("--no-social", action="store_true")
    ap.add_argument("--with-x", action="store_true", help="also pull X/Twitter via Apify (gate to brief hours)")
    a = ap.parse_args()
    if a.cmd == "ingest":
        ingest(a.max_per_source, a.no_social, with_x=a.with_x)
    else:
        synthesize(a.hours)
