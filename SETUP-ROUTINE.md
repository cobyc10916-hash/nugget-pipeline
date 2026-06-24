# Set up the NUGGET daily pull (one-time, ~10 min)

The autonomous path: a **GitHub Actions** job runs every morning in GitHub's cloud (your laptop
can be closed). It pulls the newest uploads from reputable AI channels, fetches transcripts via the
Webshare proxy, extracts nuggets to your taste, and writes them into your feed. Free compute (public
repo); the only cost is the Anthropic API for extraction (~$4.50/mo at 5 videos/day on Haiku).

The code + workflow are already in this repo (`.github/workflows/nugget-daily.yml`). You only need
to add 4 secrets and fire it.

## 1. Add the 4 repo secrets
Go to **github.com/cobyc10916-hash/nugget-pipeline → Settings → Secrets and variables → Actions →
New repository secret**. Add each (Name, then value):

| Name | Value |
|---|---|
| `WEBSHARE_PROXY_USERNAME` | `beyrsdzt` |
| `WEBSHARE_PROXY_PASSWORD` | `09zh5ozv865r` |
| `SUPABASE_SERVICE_KEY` | from Supabase dashboard (step 2) |
| `ANTHROPIC_API_KEY` | from the Anthropic console (step 3) |

## 2. Get the Supabase service key
**supabase.com/dashboard → project `nugget` → Project Settings (gear) → API → `service_role` key →
Reveal → copy.** It's a long string starting `eyJ...`. Paste it as `SUPABASE_SERVICE_KEY`.
(This bypasses RLS so the job can write content. It lives only in GitHub's encrypted secrets, never
in the repo.)

## 3. Get an Anthropic API key
**console.anthropic.com → Settings → API Keys → Create Key** → copy it (starts `sk-ant-...`) →
paste as `ANTHROPIC_API_KEY`. Then **Billing → add a payment method / buy ~$5 of credits.**
Note: your Claude **Max** subscription does **not** cover API calls; this is billed separately
(it's small: ~$4.50/mo at 5 videos/day on Haiku, ~$13/mo if you switch to Sonnet).

## 4. Fire it (test now, don't wait for 7am)
**Actions tab** → if it asks, click "I understand my workflows, enable them" → left side
**"NUGGET daily pull"** → **"Run workflow"** button → green **Run workflow**. It takes ~3-5 min.
A green check = success; click the run to read the log (`extracted ~N nuggets from M videos`).
Then open **nugget-sigma.vercel.app → Feed**, pull to refresh: new videos should be there.

## What happens every morning after that
The cron `0 12 * * *` (= 7:00 AM US Central) fires the same job daily, hands-off. You wake up to
~5 fresh videos. If a strict 24h window is thin it auto-widens to 48h.

## Levers
- **Sharper nuggets:** in the workflow file, set `EXTRACT_MODEL: claude-sonnet-4-6` (~3x cost).
- **More/fewer videos:** the "Run workflow" button takes `limit` and `hours` inputs; the daily
  cron uses 5 / 24h.
- **Different time:** edit the `cron:` hour (it's UTC; 12 = 7am Central in summer / 6am in winter).
