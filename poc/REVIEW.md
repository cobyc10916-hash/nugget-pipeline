# NUGGET — Proof of Concept (what the nuggets look like)

**8 real videos** across AI / building / STR + one 69-min podcast → **70 nuggets**.
Extracted with the production prompt (`EXTRACTION_PROMPT.md`). This PoC was run on Opus
(this session = Max) to show the quality ceiling; production runs on Haiku, which the
Information-Coverage eval-loop tunes toward this bar.

**How to read a card:** each nugget = a **hook** (the scroll-stopper) + **payload** (the
self-contained insight) + a `[mm:ss]` deep-link + a quality score (1-10) + type. Each video
has a **verdict**: 🟢 WATCH / 🟡 SKIM / 🔴 SKIP + why + density.

> The filter is working: the Dan Koe video below dropped ~40% of its runtime as motivational
> filler and kept only the 7 tactical frameworks. No nugget is padded.

---

## 🤖 AI

### 🟢 WATCH — "800+ hours of Learning Claude Code in 8 min" · Edmund Yong · 8m
**9 nuggets · 1.1/min** — *Concrete Claude Code setup, almost no filler; watch end-to-end.*

1. **Sub-agents should be defined by TASK, not ROLE.** `[04:49]` Assigning sub-agents as "front-end dev / PM / UX designer" gave *worse* results than plain Claude. They shine on scoped tasks — cleaning up just-written code, generating docs, web research — not autonomous role-play. ★8 · counterintuitive-fact
2. **A self-reviewing UI/UX sub-agent.** `[05:15]` Wire a sub-agent to the Playwright MCP so it opens your app in a real browser, inspects the rendered components, and returns design/usability feedback — offloading work that would otherwise eat the main agent's context. ★7 · tactic
3. **Context7 MCP for live docs.** `[02:14]` Add "use Context7" to a prompt and Claude fetches the latest library docs instead of relying on stale training data — kills the Google-and-paste-docs loop. ★7 · tactic
4. **Build a custom slash-command library.** `[01:22]` Put repeated prompts in `.claude/commands/*.md` with arguments for reuse; organize into subdirectories as it grows. ★7 · tactic
5. **A solo-dev MCP stack.** `[03:06]` Supabase MCP (query DB, apply migrations, create tables), Chrome DevTools/Playwright (autonomous front-end debug), Stripe (payments), Vercel (settings/docs). ★7 · example
6. **`#` writes to Claude's memory.** `[00:57]` Press `#` to save an instruction to CLAUDE.md, local or global — stop repeating yourself every session. ★6 · tactic
7. **Plugins clone a whole power-user setup.** `[06:06]` Claude Code "plugins" + marketplaces bundle commands+subagents+MCP so you install someone's entire workflow with one command. ★6 · tactic
8. **Plan-mode Q&A before code.** `[06:57]` When the idea is vague, use plan mode to make Claude ask clarifying questions first, so you align before any code is written. ★6 · tactic
9. **Fresh-session pre-prod review.** `[07:23]` Before pushing, open a NEW session and have Claude review the recently-touched files for security/perf/error-handling — the building session won't catch its own gaps. ★6 · tactic

### 🟡 SKIM — "Claude Code NEW Sub Agents in 7 Minutes" · Developers Digest · 6m
**5 nuggets · 0.8/min** — *Mostly a feature demo; the per-agent tool-scoping and style-bias tips are the takeaways. Overlaps the video above (the system would dedupe/corroborate).*

1. **Give each sub-agent its OWN tool/MCP permissions.** `[01:44]` A backend agent gets DB-read + SQL + infra-logs; a front-end agent gets different tools — instead of cramming everything into one bloated system prompt. ★7 · tactic
2. **Bake your style biases into a sub-agent's system prompt.** `[02:34]` Tell it "no linear gradients, no thick fonts, no emojis" so the model stops doing the things you dislike. ★7 · tactic
3. **Sub-agents are portable markdown.** `[05:32]` They live in `.claude/agents/*.md` — commit them to the repo so the whole team shares them. ★6 · tactic
4. Scope an agent to project vs global (machine-wide). `[00:53]` ★5 · tactic
5. Hook sub-agents to non-coding MCPs (Gmail, Linear, Canva) for a broader "mini workforce." `[05:07]` ★5 · example

### 🟡 SKIM — "AI Agents, Clearly Explained" · Jeff Su · 10m
**5 nuggets · 0.5/min** — *Clean mental model for workflow-vs-agent; conceptual not tactical — skip if you already know it.* Best: 05:20-07:30.

1. **The single line between a workflow and an agent.** `[05:45]` A workflow = a human pre-defines the path; it becomes an *agent* the moment the LLM itself becomes the decision-maker (reasons + acts + iterates). ★7 · mental-model
2. **Agents self-improve by adding a critic LLM.** `[07:28]` The agent adds a *second* LLM to critique its own output against criteria (e.g. "LinkedIn best practices") and loops until met. *(This is literally your eval-loop idea.)* ★7 · tactic
3. **RAG demystified.** `[03:32]` RAG is just a type of AI workflow — "a process to look things up before answering." ★6 · mental-model
4. **ReAct = Reason + Act**, the most common agent configuration. `[06:37]` ★6 · mental-model
5. Two LLM traits to design around: limited knowledge of proprietary/personal data, and passivity (waits for a prompt). `[01:47]` ★5 · mental-model

---

## 🚀 BUILDING / ENTREPRENEURSHIP

### 🟢 WATCH — "How to Get Your First Customers" · Y Combinator · 22m
**10 nuggets · 0.5/min** — *Canonical, dense, zero filler — sales-email formula, funnel math, B2B-no-free-trials are immediately usable.*

1. **The cold sales-email formula.** `[06:28]` ≤6-8 sentences · plain text (no HTML, write like to a friend) · no jargon · name the customer's problem · say you're the founder · show-don't-tell social proof · a simple link (screenshots+bullets, not graphics) · one clear CTA. ★8 · framework
2. **In B2B, never offer a free trial — use a money-back guarantee + monthly opt-out.** `[13:42]` Charge, refund within 30/60 days if unhappy. If they won't pay, that's the signal to move on. Raise price until customers complain but still pay. ★8 · counterintuitive-fact
3. **Outbound is a numbers game because most people aren't early adopters.** `[12:24]` They archive your email not because they hate it but because they never try new products — you can't convert non-adopters, so send more to *find* the adopters. ★8 · mental-model
4. **Work backwards from the goal through funnel drop-offs.** `[15:27]` 500 emails → 50% open → 5% reply (20) → 50% to demo (10) → 2 close. To get 10 customers you need *far* more than 10 leads; track each conversion. ★8 · framework
5. **Your first customers should be your EASIEST, not the hardest.** `[10:44]` Don't chase every lead — pick the most-likely-to-close and make the process easy on yourself. ★7 · tactic
6. **Sell to startups (esp. software).** `[11:59]` Short decision lines, you reach the decision-maker directly, no procurement — vs big-company departments that negotiate for months. ★7 · tactic
7. **The #1 founder mistake: "sales doesn't work" after too few emails.** `[17:10]` 100 emails at normal rates = 0 customers; you didn't gather enough data to draw any conclusion. ★7 · counterintuitive-fact
8. **Do things that don't scale — manually recruit.** `[05:12]` Brex onboarded its first 10 customers by hand from its YC batch. Scalable channels (SEO/SEM/referrals) are end-states, not how you start. ★7 · mental-model
9. **Founders must do sales themselves first.** `[03:27]` Don't hire a sales team until you know what "good" looks like — you can't outsource learning the customer. ★6 · mental-model
10. **Don't be afraid to let customers go.** `[11:34]` If someone drags you through 2-3 calls: "let's talk again in 6 months," and move on. ★6 · tactic

### 🟡 SKIM — "The One-Person Business Model" · Dan Koe · 29m
**7 nuggets · 0.2/min** — *Real frameworks wrapped in heavy motivational filler — jump to the tactical middle.* Best: 08:00-09:00, 15:25-17:35, 23:10-29:00.
> **Filter demonstration:** ~40% of this video ("work less earn more," "just believe in yourself," the digital-nomad-beach bit, "money is self-transcendence," the course pitch) was **rejected as motivational filler.** Only the 7 tactical frameworks below survived.

1. **Be a generalist, not a specialist — specialists get automated.** `[08:09]` "If you work like a robot, you'll be outsourced to robots." High earners are generalists who hire specialists; move artfully within a domain instead of performing one repeatable skill. ★7 · mental-model
2. **The "domain of mastery" content system.** `[23:10]` Pick 3 interests — one that makes money, one that excites you, one development-based (psychology/philosophy) — and generate content from their principles, topics, mentors, and connections. ★7 · framework
3. **Minimum Viable Offer — monetize immediately.** `[25:43]` Start with either (a) a single freelance skill at $500-1k, or (b) a single-interest consulting service = 4 calls for $500-1k. Don't wait for a polished product. ★7 · tactic
4. **The development-based path beats selling one skill.** `[15:25]` Build around the four "eternal markets" (health/wealth/relationships/happiness) by pursuing your own goals and packaging the step-by-step system as the product. ★6 · framework
5. **Consulting/tutoring beats done-for-you freelance.** `[27:26]` Sell 4 calls teaching someone to do X rather than doing it for them — more scalable, and many buyers prefer to be taught. ★6 · counterintuitive-fact
6. **Four-pillar mapping.** `[20:33]` goals→brand · problems-in-the-way→content · systems-that-solve→product · benefits-to-your-life→marketing. ★6 · framework
7. **Use the MVO to build a product with proof.** `[28:17]` Run the calls, note what's common across them, package into a course/cohort, then shift off client work as the audience grows. ★6 · tactic

---

## 🏠 SHORT-TERM RENTAL

### 🟢 WATCH — "My 4 Most Powerful STR Pricing Tricks" · Sean Rakidzich · 13m
**8 nuggets · 0.6/min** — *Dense, genuinely non-obvious STR pricing tactics; skip the heavy webinar pitches.* Best: 01:40-05:55, 07:10-08:30, 09:40-13:10.

1. **PriceLabs has a "range of efficacy" — beat it at the edges.** `[09:43]` 70%+ of hosts use the same software, so everyone herds up/down together. PriceLabs may be accurate only ~60-84% occupancy in your market; above that it under-raises (you leave money), below it it won't cut enough to book. Deviate manually outside that band. ★8 · counterintuitive-fact
2. **Set minimum-length-of-stay from demand-color runs.** `[04:14]` Map MLS to the high-demand (dark-blue) run: a 5-day run → 4-day MLS; 2-day run → 3-day MLS; 7+ run → investigate, maybe 5-day — to capture the longer-stay guest in the run. ★8 · framework
3. **Airbnb "rule sets" are the most powerful lever — and unique to Airbnb.** `[01:42]` Day-by-day 3-day/4-day/early-bird/last-minute discounts other OTAs (Vrbo) don't offer; override a global discount one day at a time. ★7 · tactic
4. **The "drive-down" rule set.** `[02:32]` Stack a 3-day length-of-stay discount WITH last-minute discounts on the same day to auto-cut weekday prices you'd otherwise forget to drop. ★7 · tactic
5. **Feed your payout CSV to AI, split by property TYPE.** `[07:10]` All beach houses in one file, all apartments in another (apples-to-apples) — it surfaces per-weekday occupancy (85% overall can hide 2% Mondays). ★7 · tactic
6. **Weekdays are only worth as much as the weekends they're attached to.** `[05:04]` The core pricing physics — an isolated open midweek day after a booked weekend is no longer worth what the software thinks. ★7 · mental-model
7. **Project future occupancy from the PriceLabs chart.** `[11:52]` Compare last-year-today vs this-year-today, multiply by last-year-final, then adjust by booking-velocity/pickup to forecast 3-6 months out. ★7 · framework
8. **In peak season, push BOTH occupancy and ADR via restrictions** — it's the only time you have the power to do both. `[05:29]` ★6 · tactic

### 🟡 SKIM — "The (Overdue) Collapse Of Short Term Rentals" · How Money Works · 13m
**6 nuggets · 0.5/min** — *Solid macro on margin compression + regulatory risk; analysis not operating tactics — useful context for an analyst.* Best: 05:00-05:45, 06:38-07:30, 09:45-12:30.

1. **STR demand is price-driven, not experience-driven.** `[06:38]` A study found 61% chose Airbnb as a *budget* alternative even to budget hotels, and 70% booked a whole place to avoid sharing — yet Airbnb spends billions marketing "stay with a local host" (better PR + legal cover, since shared stays are harder to regulate). ★7 · counterintuitive-fact
2. **The margin-compression thesis.** `[05:19]` STRs pushed long-term rents up and the market oversaturated, narrowing the STR-vs-long-term yield gap; leveraged hosts who only qualified for loans via STR income may be forced to sell. ★7 · mental-model
3. **Regulatory risk is the real structural threat.** `[09:46]` Cities capping/banning STRs, forcing platforms to delist unregistered units, HOAs blocking short stays; ~45% of LA listings were non-compliant. ★6 · counterintuitive-fact
4. **Airbnb has no moat besides brand.** `[11:33]` Booking.com/Expedia/TripAdvisor are launching the same thing; hosts list via local agencies and split the ~17% fee savings with guests. ★6 · counterintuitive-fact
5. **Airbnb's margin advantage is structural.** `[11:58]` ~17% of a high-ticket stay vs Uber's few-dollars-per-ride, same tech overhead — why it's profitable where other peer-to-peer platforms aren't. ★6 · mental-model
6. **The "Airbnb Baron" low-effort operating kit.** `[03:59]` Remote-changeable keypad locks, easily-cleanable surfaces, cheap-but-fashionable fittings, minimal landscaping — to cut per-turn effort. ★6 · tactic

---

## 🎙 DENSE PODCAST (the packaging test)

### 🟢 WATCH — "How To Build A $10M AI App In 30 Seconds" · My First Million · 69m
**20 nuggets · 0.3/min** — *Replit CEO Amjad Masad on the AI app-building gold rush. Story-heavy but loaded.* Best: 35:55-57:44 (the AI core), 05:09-07:16 & 12:27-21:22 (founder lessons).
> **This is how a long podcast is packaged:** 20 nuggets, grouped into 3 topic clusters with timestamps, so a 69-minute episode is navigable in the "See all" view — nothing buried.

**▸ AI app-building / the "idea-guy" era**
1. **The repeatable AI playbook.** `[53:02]` Go into an inefficient industry you understand, build a "GPT wrapper" that automates the painful work, do it ~100× and one takes off (Magic School→teachers; Synthesis→tutoring). ★8 · framework
2. **Distribution is now the only moat.** `[52:37]` Building is commoditized; if you have an audience ("get on the microphone"), customer acquisition — the actually-hard part — is your edge over technical founders. ★8 · mental-model
3. **Software cost collapsed ~4000×.** `[43:34]` Apps that'd cost ~$100k in dev time can be built for ~$25 on a Replit agent. ★8 · counterintuitive-fact
4. **AI revenue ramps broke the frame.** `[49:12]` $10M ARR in 3-4 months; Jasper hit ~$50M ARR in ~10 months — ramps that "didn't exist" pre-AI. ★8 · counterintuitive-fact
5. **"Shopify for software."** `[55:36]` Just as Shopify+Alibaba let non-manufacturers build product brands (Sam ran a $50M e-com brand never having manufactured or built a site), agents let non-programmers be "software creators." ★8 · mental-model
6. **Magic School case.** `[44:01]` A teacher learned to code on Replit during COVID, built an AI lesson-plan/quiz generator, hit ~4M educators / ~$20M raised in ~1 year — selling into schools worked because it removed 4 hrs/night of grunt work. ★7 · example
7. **The GPT-wrapper moat critique — and the honest answer.** `[50:30]` Wrappers clone easily → price war, and the model company captures most ARR; moats only form over time via accumulated infrastructure + scale + switching costs. ★7 · mental-model
8. **Agent UX reality.** `[41:26]` Agents narrate what they're doing as they edit, so you learn the components — but they still wall on integrations (e.g. Twilio phone verification), needing prompting skill to coax through. ★6 · tactic
9. **AI-SDR leverage.** `[48:21]` One account-exec can run tens of AI SDRs (ElevenLabs) instead of hiring a sales team. ★6 · example

**▸ Founder lessons**
10. **Solve a problem you feel 10×.** `[05:09]` Amjad felt dev-environment-setup pain acutely because he coded in a Jordan internet cafe (re-setup every visit) — the hardship made him see the "$100 bill on the ground" others walked past. ★7 · mental-model
11. **Naval's networking rule.** `[12:27]` The only tip: "do something great and your network appears overnight." He didn't chase Brendan Eich — he built something Eich reached out about. ★7 · mental-model
12. **"Do what makes the best story."** `[20:30]` At a 50/50 fork with no obvious answer, pick the more interesting story (echoes "the most entertaining outcome is most likely"). ★7 · mental-model
13. **Public writing compounds into opportunity.** `[16:18]` He wrote articles about the hard problems they solved → repeatedly hit Hacker News → Paul Graham (who reads HN) noticed → that's how he got into YC after 4 rejections. ★7 · tactic
14. **Why good ideas get rejected: status pattern-matching.** `[14:10]` YC passed 4× because he didn't fit the patterns (no fancy school, married couple seen as a negative, "not on trend") — not because the idea was bad. ★6 · counterintuitive-fact
15. **Ramen profitability changes the conversation.** `[15:27]` ~$10k/mo from educators/API was enough to sustain them — modest real revenue beats a pretty deck. ★6 · tactic
16. **Have a goal when meeting powerful people.** `[19:15]` A specific ask puts you in a non-fanboy mindset that lets you talk at their level. ★6 · tactic
17. **"Go the distance" — the Jobs/Pixar story.** `[65:52]` Jobs ran NeXT + Pixar at a loss ~10 years (personal payroll checks); Pixar→$7B, and NeXT's OS literally became Mac OS and saved Apple. Endurance is underrated. ★6 · mental-model

**▸ Product strategy**
18. **Kill the learning curve.** `[59:00]` Amjad scrapped "100 days of code" — "no successful company requires 100 days to learn it" — and rebuilt Replit to be ChatGPT-like (just a prompt). Drive time-to-value toward zero. ★7 · mental-model
19. **Ride two exponentials.** `[42:44]` Replit improves from its own engineering AND from foundation models getting better — every model upgrade improves the product for free. Build on top of an improving substrate. ★7 · mental-model
20. **Value capture followed obvious ROI.** `[34:37]` Developers never paid — until AI, because the productivity benefit is immediate and obvious (credits model). Monetize where the ROI is self-evident, not by feature-gating. ★6 · mental-model

---

## What this PoC demonstrates
- **Real, non-obvious, tactical nuggets** across all 3 buckets — not summaries.
- **The editorial filter works** — Dan Koe's motivational ~40% was stripped; nothing padded.
- **Honest verdicts** — 4× WATCH, 4× SKIM, with density + best-segments so you know when to watch the full thing.
- **Dense-podcast packaging** — a 69-min interview → 20 timestamped nuggets in 3 topic clusters, navigable, nothing buried.
- **Deep-links work** — e.g. nugget #1 of the podcast → `youtube.com/watch?v=TOQtJch3kGk&t=3182s`.

**Your call:** does this quality clear the bar? If yes, we proceed to Phase 1 (Supabase + schema) and build the feed around exactly these cards. If a nugget type feels off (too long/short, wrong filter, want more/fewer per video), tell me and I tune the prompt before we scale.
