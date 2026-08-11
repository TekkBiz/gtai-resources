# micro1 Referral Jobs RSS Feed

Automated RSS feed of live micro1 referral jobs for referral code `6169d433-2a46-407a-9317-40fb3df9cd2c`.

## Feed URL

```
https://tekkbiz.github.io/gtai-resources/feed.xml
```

Add it to any RSS reader (Feedly, Inoreader, NewsBlur, etc.). It refreshes every 6 hours via GitHub Actions.

## How it works

- `rss_generator.py` hits the unauthenticated micro1 public API:
  `GET https://prod-api.micro1.ai/api/v1/job/portal/referral/{code}/jobs?page=N&limit=100`
- Paginates all pages (currently ~311 jobs), then renders an RSS 2.0 feed.
- Every item's link is the job's `apply_url` **verbatim** — micro1 already appends
  `?referralCode=...&utm_source=referral&utm_medium=share&utm_campaign=job_referral`
  server-side, so applications through feed links are credited to you.

## Run locally

```bash
REFERRAL_CODE=6169d433-2a46-407a-9317-40fb3df9cd2c python3 rss_generator.py
```

Stdlib only — no `pip install`. Output: `feed.xml` (overridable with `OUTPUT`).

## Change cadence or code

Edit the `schedule.cron` + `REFERRAL_CODE` in `.github/workflows/rss.yml`.

## Manual refresh

Actions → "Build micro1 RSS feed" → **Run workflow** (also run after any code change).