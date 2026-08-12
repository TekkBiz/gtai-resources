#!/usr/bin/env python3
"""Build an RSS 2.0 feed of micro1 referral jobs.

Source: unauthenticated public API prod-api.micro1.ai, keyed by referral code.
Item links use each job's apply_url verbatim - micro1 already appends the
referralCode + UTM params server-side, so attribution tracks without edits.

Deps: stdlib only. Runs in GitHub Actions (3.12) or any py3.10+.
"""

import email.utils
import html
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

API_HOST = os.environ.get("API_HOST", "https://prod-api.micro1.ai")
REFERRAL_CODE = os.environ["REFERRAL_CODE"]
PAGE_LIMIT = 100
OUTPUT = os.environ.get("OUTPUT", "feed.xml")

LANG_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; micro1-rss-bot/1.0)",
    "Accept": "application/json",
    "x-custom-lang": "en",
}

DATE_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S.%f")


class JobError(RuntimeError):
    pass


def fetch_json(url: str, attempts: int = 3) -> dict:
    req = urllib.request.Request(url, headers=LANG_HEADERS)
    backoff = 2
    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(req, timeout=60) as res:
                return json.load(res)
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and attempt < attempts:
                print(f"  HTTP {e.code} on attempt {attempt}; retrying in {backoff}s", flush=True)
                time.sleep(backoff)
                backoff += 3
                continue
            raise JobError(f"HTTP {e.code} for {url}: {e.read()[:300]!r}") from e
        except (urllib.error.URLError, TimeoutError) as e:
            reason = getattr(e, "reason", None) or e
            if attempt < attempts:
                print(f"  Network error on attempt {attempt}; retrying in {backoff}s", flush=True)
                time.sleep(backoff)
                backoff += 3
                continue
            raise JobError(f"Network error for {url}: {reason}") from e
    raise JobError(f"Exhausted retries for {url}")


def fetch_all_jobs(referral_code: str) -> list[dict]:
    base = f"{API_HOST}/api/v1/job/portal/referral/{urllib.parse.quote(referral_code)}/jobs"
    jobs: list[dict] = []
    page = 1
    total = None
    while True:
        payload = fetch_json(f"{base}?page={page}&limit={PAGE_LIMIT}")
        if not payload.get("status"):
            raise JobError(f"API rejected: {payload.get('message')}")
        if total is None:
            total = int(payload.get("total", 0))
        rows = payload.get("data") or []
        jobs.extend(rows)
        if not rows or len(jobs) >= total:
            break
        page += 1
        if page > 20:  # safety valve
            break
    return jobs


def parse_pub_date(value: str | None) -> str:
    if not value:
        return email.utils.formatdate(usegmt=True)
    text = value.strip()
    for fmt in DATE_FORMATS:
        try:
            dt = datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
            return email.utils.format_datetime(dt, usegmt=True)
        except ValueError:
            continue
    return email.utils.formatdate(usegmt=True)


def job_sort_key(job: dict):
    ts = (job.get("date_posted") or job.get("job_posted_on") or "")[:19]
    for fmt in DATE_FORMATS[:2]:
        try:
            return datetime.strptime(ts, fmt)
        except ValueError:
            continue
    return datetime.min


def reward_display(job: dict) -> str:
    raw = job.get("referral_reward_amount")
    if raw in (None, "", 0):
        return ""
    try:
        return f"${float(raw):,.0f}"
    except (TypeError, ValueError):
        return str(raw)


def comp_display(job: dict) -> str:
    h = job.get("ideal_hourly_rate")
    if isinstance(h, dict) and (h.get("min") is not None or h.get("max") is not None):
        lo, hi = h.get("min"), h.get("max")
        if lo and hi:
            return f"${lo:g}-${hi:g}/hr"
        if hi:
            return f"up to ${hi:g}/hr"
        if lo:
            return f"from ${lo:g}/hr"
    lo = job.get("ideal_monthly_salary_min") or 0
    hi = job.get("ideal_monthly_salary_max") or 0
    if lo and hi:
        return f"${lo:,.0f}-${hi:,.0f}/mo"
    if hi:
        return f"up to ${hi:,.0f}/mo"
    return ""


def build_description(job: dict) -> str:
    esc = html.escape
    bits = []
    if job.get("company_name"):
        bits.append(f"<b>Company:</b> {esc(str(job['company_name']))}")
    if reward_display(job):
        bits.append(f"<b>Referral reward:</b> {esc(reward_display(job))}")
    if job.get("no_of_openings"):
        bits.append(f"<b>Openings:</b> {job['no_of_openings']}")
    if job.get("job_type"):
        bits.append(f"<b>Job type:</b> {esc(str(job['job_type']))}")
    if job.get("domain_slug"):
        bits.append(f"<b>Domain:</b> {esc(str(job['domain_slug']).replace('-', ' ').title())}")
    if comp_display(job):
        bits.append(f"<b>Compensation:</b> {esc(comp_display(job))}")
    if job.get("is_high_demand_job"):
        bits.append("<b>Flag:</b> High-demand job")
    skills = job.get("skills") or job.get("required_skills") or []
    if skills:
        bits.append("<b>Skills:</b> " + ", ".join(esc(str(s)) for s in skills))
    link = job.get("apply_url") or ""
    if link:
        bits.append(f"<a href='{esc(link)}'>Apply now</a>")
    return "<br/>".join(bits)


def build_feed(jobs: list[dict]) -> bytes:
    jobs_sorted = sorted(jobs, key=job_sort_key, reverse=True)
    rss = ET.Element("rss", {"version": "2.0", "xmlns:atom": "http://www.w3.org/2005/Atom"})
    channel = ET.SubElement(rss, "channel")
    ET.SubElement(channel, "title").text = "micro1 Referral Jobs"
    ET.SubElement(channel, "link").text = (
        f"https://refer.micro1.ai/referral/jobs?referralCode={REFERRAL_CODE}"
    )
    ET.SubElement(channel, "description").text = (
        "Live micro1 hiring opportunities. Every link already carries your "
        "referral code so applications are tracked to you."
    )
    ET.SubElement(channel, "language").text = "en-US"
    ET.SubElement(channel, "lastBuildDate").text = email.utils.formatdate(usegmt=True)
    ET.SubElement(
        channel, "atom:link",
        {"href": OUTPUT, "rel": "self", "type": "application/rss+xml"},
    )

    for job in jobs_sorted:
        item = ET.SubElement(channel, "item")
        title = str(job.get("job_name") or "micro1 job")
        company = job.get("company_name")
        if company and not title.startswith(str(company)):
            title = f"{title} @ {company}"
        if reward_display(job):
            title = f"{title} ({reward_display(job)})"
        ET.SubElement(item, "title").text = title
        link = job.get("apply_url") or job.get("job_description_url") or ""
        ET.SubElement(item, "link").text = link
        if job.get("job_id"):
            ET.SubElement(item, "guid", {"isPermaLink": "false"}).text = str(job["job_id"])
        ET.SubElement(item, "pubDate").text = parse_pub_date(
            job.get("date_posted") or job.get("job_posted_on")
        )
        ET.SubElement(item, "description").text = build_description(job)

    ET.indent(rss, space="  ")
    return ET.tostring(rss, encoding="utf-8", xml_declaration=True)


def main() -> int:
    print(f"Fetching jobs for referral code {REFERRAL_CODE} ...", flush=True)
    jobs = fetch_all_jobs(REFERRAL_CODE)
    print(f"Fetched {len(jobs)} jobs", flush=True)
    xml = build_feed(jobs)
    with open(OUTPUT, "wb") as f:
        f.write(xml)
    print(f"Wrote {OUTPUT} ({len(xml)} bytes, {len(jobs)} items)", flush=True)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except JobError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
