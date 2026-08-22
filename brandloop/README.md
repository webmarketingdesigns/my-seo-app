# BrandLoop

A brand intelligence and content automation app: **listen → analyse → generate → publish → measure.**

It combines the two halves of the products it was modelled on — [Brandwatch](https://brandwatch.com)-style
consumer intelligence (monitor mentions across sources, sentiment, trends, share of voice, alerts) and
[native.no](https://native.no)-style marketing automation (analyse the brand, auto-write posts, swipe-approve,
schedule, publish, report).

Everything runs on free, key-less data sources. There is no build step and no paid API is required to
run the whole loop end to end.

---

## The loop

| Stage | What happens | Where |
|---|---|---|
| **Listen** | Poll RSS/Atom, Hacker News and Reddit for your tracked terms | `ingest/` |
| **Analyse** | Score sentiment, extract trending phrases, compute share of voice, fire alerts | `analysis/` |
| **Generate** | Read the brand's own site for voice, then write per-channel drafts grounded in real quotes | `generate/` |
| **Publish** | Approve → schedule into the next free slot → publish to a channel | `scheduler.py`, `publish/` |
| **Measure** | Per-post impressions, engagements and engagement rate, rolled up by channel | `analysis/metrics.py` |

## Screens

- **Dashboard** — KPIs vs the prior week, volume by sentiment, sentiment trend, alerts, share of voice, trending topics
- **Mentions** — the full feed, filterable by sentiment, source, scope (your brand vs competitors) and free text
- **Insights** — 30-day trends, trending-phrase table with lift, source breakdown, loudest voices
- **Content studio** — generate drafts from a topic, edit inline with live character counts, approve or reject
- **Calendar** — four weeks of scheduled and published posts
- **Analytics** — every published post, per-channel engagement rates, top performers
- **Settings** — the brand, its boolean query (include / exclude / competitor terms), and its sources

---

## Running it

```bash
cd brandloop
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python wsgi.py           # http://127.0.0.1:5001
```

On first boot with an empty database, the app creates one worked example — a brand, its query, four
real sources, 30 days of seeded chatter and three weeks of posting history — so no screen starts empty.
Delete `brandloop.db` to start over.

### CLI

Everything the UI does is also a command (`export FLASK_APP=wsgi.py` first):

```bash
flask ingest          # poll every enabled source
flask seed            # add synthetic demo chatter (--days, --per-day)
flask generate        # draft posts from current trends (--count, --channel)
flask run-due         # publish scheduled posts that are due, refresh metrics
flask analyse-site    # re-derive the brand voice from the brand's website
flask rescore         # re-run sentiment over stored mentions after a lexicon change
```

`flask run-due` is the only thing that needs to run on a schedule. On Render, a cron job hitting
`POST /api/scheduler/run` does the same job — there is no background worker and nothing assumes a
long-lived process.

---

## Data sources

All are free and need no API key:

| Adapter | Source | Notes |
|---|---|---|
| `rss` | Any RSS/Atom feed | News sites, blogs, Google News queries, YouTube channels, Reddit RSS |
| `hackernews` | HN Algolia search | Stories and comments; points + comment count estimate reach |
| `reddit` | Reddit search | Falls back to the RSS endpoint automatically — the JSON API 403s from many networks |
| `seed` | Synthetic generator | Plausible chatter so dashboards have something to show on day one |

Adding a paid firehose (X, Meta, LinkedIn) means writing one adapter against the contract in
`ingest/base.py` and registering it in `ingest/pipeline.py`. The pipeline owns matching, sentiment and
deduplication, so adapters stay small.

## Sentiment

A dependency-free lexicon scorer (`analysis/sentiment.py`): valence lexicon, negation flipping,
intensifier scaling, emoji, and caps/exclamation emphasis, normalised to −1…+1. It is not as accurate
as a trained classifier, but it runs anywhere with no model download and every decision is
inspectable — which matters when someone asks why a mention was flagged negative.

Thresholds are deliberately asymmetric (positive at ≥ 0.15, negative at ≤ −0.10): everyday marketing
copy skews positive, so it should take less negativity to earn a flag.

## Copywriting

`generate/composer.py` has two engines behind one interface:

- **Template engine** (default) — deterministic, free, always available. Five angles (insight, question,
  tip, contrarian, news), fitted to each channel's character and hashtag limits.
- **Anthropic engine** — used automatically when `ANTHROPIC_API_KEY` is set. Prompted with the brand
  voice profile and real quotes from matching mentions, and instructed never to invent statistics or
  capabilities. Server-side refusal fallbacks are enabled so a declined request is retried on a
  fallback model inside the same call.

Any failure — no key, network error, rate limit, refusal, unparseable output — degrades silently to
the template engine. A generation hiccup never takes down the studio.

## Publishing

Real channels need an approved platform app and OAuth tokens, which is a procurement problem rather
than a code problem. Until those exist, every channel uses the **dry-run publisher**: posts move to
published, get a permalink, and accrue deterministic metrics shaped by channel benchmarks and post age
on a saturating curve. This makes scheduling and analytics exercisable before any API access lands.

To go live on a channel, implement the `publish/base.py` contract and swap that channel's entry in
`publish/__init__.py`. Nothing else changes.

---

## Deploying

`render.yaml` provisions a free web service plus a free Postgres instance:

```yaml
rootDir: brandloop
startCommand: gunicorn wsgi:app
```

Set `ANTHROPIC_API_KEY` in the dashboard if you want AI copy (it is marked `sync: false`, so it is
never committed). `DATABASE_URL` is wired from the database automatically; with no `DATABASE_URL` the
app falls back to local SQLite.

## Layout

```
brandloop/
  wsgi.py                  entrypoint
  render.yaml              Render blueprint
  brandloop/
    __init__.py            app factory
    config.py models.py    configuration, schema
    bootstrap.py cli.py    first-run demo data, CLI commands
    scheduler.py           approve → schedule → publish → measure
    ingest/                base, rss, hackernews, reddit, seed, pipeline
    analysis/              sentiment, topics, metrics, alerts
    generate/              brandvoice, composer, llm
    publish/               base, dryrun, metrics
    routes/                views (pages), api (JSON)
    templates/ static/     server-rendered pages, one stylesheet, two scripts
```

## Notes on the charts

Charts are hand-rolled inline SVG (`static/js/charts.js`) — no chart library, no external requests.
Colours come from CSS custom properties, so light and dark themes are handled once in the stylesheet.
The sentiment scale is diverging (two hues either side of a neutral midpoint) and the pole pair was
validated for colour-vision deficiency rather than picked by eye: protan ΔE 13.0 / normal ΔE 26.1 in
light, deutan ΔE 12.6 / normal ΔE 27.1 in dark, both above 3:1 contrast against their surface. Every
chart carries a legend and a hover tooltip so identity is never conveyed by colour alone.

## What is real and what is simulated

| Real | Simulated |
|---|---|
| Source polling, matching, deduplication | Channel publishing (dry-run adapter) |
| Sentiment scoring, topic extraction, trends, alerts | Post performance metrics |
| Brand voice analysis from a live website | Seeded demo mentions (`source_kind='seed'`) |
| AI copy generation (with a key) | — |
| Scheduling, approval workflow, the full data model | — |
