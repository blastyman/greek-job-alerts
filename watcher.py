"""Greek job watcher.

Checks LinkedIn, Kariera.gr, Skywalker.gr and Indeed GR for listings matching
config.json and pushes new ones to your phone through ntfy (https://ntfy.sh).
Standard library only, so it runs anywhere Python 3.9+ is installed.

Env vars:
  NTFY_TOPIC   your private ntfy topic name (required to send alerts)
  NTFY_SERVER  defaults to https://ntfy.sh
  DRY_RUN=1    print what would be sent instead of sending it
"""

import hashlib
import html
import json
import os
import re
import shutil
import subprocess
import sys
import time
import unicodedata
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(ROOT, "config.json")
FIELDS_PATH = os.path.join(ROOT, "docs", "fields.json")
SEEN_PATH = os.path.join(ROOT, "seen.json")
STATUS_PATH = os.path.join(ROOT, "docs", "status.json")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")
MAX_ALERTS_PER_RUN = 15
MAX_LISTED = 50     # listings per site shown on the settings page
SEEN_DAYS = 30      # forget a sent job once it's been gone from results this long
TODAY = datetime.now(timezone.utc).date().isoformat()

MAX_LOCATIONS = 3
REMOTE_WORDS = ["remote", "τηλεργασια", "εξ αποστασεως", "work from home"]
ALL_GREECE = {"", "greece", "ελλαδα", "all", "ολη η ελλαδα"}


def norm(text):
    """Lowercase, strip Greek accents, unify final sigma."""
    text = unicodedata.normalize("NFD", text or "")
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", text.lower().replace("ς", "σ")).strip()


def strip_tags(fragment):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", fragment))).strip()


def fetch(url):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept-Language": "el-GR,el;q=0.9,en;q=0.8",
    })
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", errors="replace")


def fetch_with_curl(url):
    """Some sites (Indeed, Skywalker) reject Python's TLS handshake but accept curl's."""
    if not shutil.which("curl"):
        return fetch(url)
    out = subprocess.run(
        ["curl", "-sSL", "--compressed", "--max-time", "30", "-A", UA,
         "-H", "Accept-Language: el-GR,el;q=0.9,en;q=0.8", "-w", "\n%{http_code}", url],
        capture_output=True, check=True)
    body, _, code = out.stdout.decode("utf-8", errors="replace").rpartition("\n")
    if code.strip() != "200":
        raise RuntimeError(f"HTTP {code.strip()} (probably blocked)")
    return body


def location_names(place):
    """Every spelling of a place from docs/fields.json (English, Greek, genitive, suburbs)."""
    key = norm(place)
    places = load_json(FIELDS_PATH, {}).get("locations", [])
    # Exact place first, so "Chania" is the city and not the Crete region that lists it as an alias.
    for match in (lambda p: key in (norm(p["name"]), norm(p.get("el", ""))),
                  lambda p: key in (norm(a) for a in p.get("aliases", []))):
        for p in places:
            if match(p):
                return [n for n in [p["name"], p.get("el", "")] + p.get("aliases", []) if n]
    return [place]


def name_in(name, text):
    # Long names match at the start of a word (so "khalandri" finds "Khalándrion"),
    # short ones only as a whole word (so "Kos" doesn't match inside other words).
    n = re.escape(norm(name))
    return re.search(rf"(?<!\w){n}" + (r"(?!\w)" if len(name) < 5 else ""), text) is not None


def matches_location(text, cfg):
    if not cfg["locations"]:
        return True
    t = norm(text)
    if cfg.get("include_remote", True) and (t in ALL_GREECE or any(w in t for w in REMOTE_WORDS)):
        return True  # remote, or listed for "Greece" as a whole
    return any(name_in(n, t) for place in cfg["locations"] for n in location_names(place))


def matches_keywords(title, keywords):
    if not keywords:
        return True
    t = norm(title)
    return any(norm(k) in t for k in keywords)


def job(source, job_id, title, company, location, url):
    return {
        "id": f"{source}:{job_id}",
        "source": source,
        "title": strip_tags(title),
        "company": strip_tags(company),
        "location": strip_tags(location),
        "url": html.unescape(url),
    }


# ---------------------------------------------------------------- sources

def search_linkedin(cfg):
    locations = [f"{location_names(place)[0]}, Greece" for place in cfg["locations"]] or ["Greece"]
    searches = [(k, loc) for k in cfg["keywords"] or [""] for loc in locations]
    # Results are newest first, so with many searches the first page is enough between
    # 15-minute checks, and it keeps the request count low enough not to get blocked.
    starts = (0, 10, 20) if len(searches) <= 3 else (0,)
    jobs = []
    for keyword, location in searches:
        for start in starts:
            time.sleep(0.5)
            qs = urllib.parse.urlencode({
                "keywords": keyword, "location": location,
                "f_TPR": "r86400", "sortBy": "DD", "start": start,
            })
            page = fetch("https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?" + qs)
            cards = page.split("<li")[1:]
            for card in cards:
                link = re.search(r'base-card__full-link[^>]*href="([^"]+)"', card)
                title = re.search(r'base-search-card__title[^>]*>(.*?)</h3>', card, re.S)
                if not (link and title):
                    continue
                url = link.group(1).split("?")[0]
                job_id = re.search(r"(\d{6,})", url)
                company = re.search(r'base-search-card__subtitle[^>]*>(.*?)</h4>', card, re.S)
                place = re.search(r'job-search-card__location[^>]*>(.*?)</span>', card, re.S)
                jobs.append(job("LinkedIn", job_id.group(1) if job_id else url, title.group(1),
                                company.group(1) if company else "", place.group(1) if place else "", url))
            if len(cards) < 10:
                break
    return jobs


def search_kariera(cfg):
    # Kariera filters in the browser, so read the newest listings and filter here.
    jobs = []
    for page_no in (1, 2, 3):
        page = fetch(f"https://www.kariera.gr/en/jobs?page={page_no}")
        parts = re.split(r'(?=<a class="job-title-link)', page)[1:]
        for part in parts:
            m = re.match(r'<a class="job-title-link[^"]*" href="(/en/jobs/[^"]+/(\d+))"><h3[^>]*>(.*?)</h3>', part, re.S)
            if not m:
                continue
            details = strip_tags(part[:4000])
            if not matches_keywords(m.group(3), cfg["keywords"]) or not matches_location(details, cfg):
                continue
            jobs.append(job("Kariera", m.group(2), m.group(3), "", details[len(strip_tags(m.group(3))):][:80],
                            "https://www.kariera.gr" + m.group(1)))
    return jobs


def search_skywalker(cfg):
    jobs = []
    for keyword in cfg["keywords"] or [""]:
        qs = urllib.parse.urlencode({"keywords": keyword})
        page = fetch_with_curl("https://www.skywalker.gr/el/aggelies-ergasias?" + qs)
        parts = re.split(r'(?=<a\s+class="previewJob")', page)[1:]
        for part in parts:
            m = re.match(r'<a\s+class="previewJob"\s+href="([^"]*/aggelia-ergasias/([a-z0-9]+)/[^"]*)"', part)
            title = re.search(r'class="listing-title">(.*?)</span>', part, re.S)
            if not (m and title):
                continue
            if not matches_location(strip_tags(part[:3000]), cfg):
                continue
            jobs.append(job("Skywalker", m.group(2), title.group(1), "", "", m.group(1)))
    return jobs


def search_indeed(cfg):
    jobs = []
    for keyword, place in [(k, p) for k in cfg["keywords"] or [""] for p in cfg["locations"] or [""]]:
        qs = urllib.parse.urlencode({"q": keyword, "l": place, "fromage": 3, "sort": "date"})
        page = fetch_with_curl("https://gr.indeed.com/jobs?" + qs)
        marker = 'window.mosaic.providerData["mosaic-provider-jobcards"]='
        at = page.find(marker)
        if at < 0:
            raise RuntimeError("no job data in page (probably blocked)")
        data, _ = json.JSONDecoder().raw_decode(page, at + len(marker))
        results = data["metaData"]["mosaicProviderJobCardsModel"]["results"]
        for r in results:
            jobs.append(job("Indeed", r["jobkey"], r.get("displayTitle") or r.get("title", ""),
                            r.get("company", ""), r.get("formattedLocation", ""),
                            "https://gr.indeed.com/viewjob?jk=" + r["jobkey"]))
    return jobs


SOURCES = {
    "linkedin": search_linkedin,
    "kariera": search_kariera,
    "skywalker": search_skywalker,
    "indeed": search_indeed,
}


# ---------------------------------------------------------------- alerts

def notify(title, message, url=None, tags="briefcase"):
    topic = os.environ.get("NTFY_TOPIC", "").strip()
    if os.environ.get("DRY_RUN") or not topic:
        print(f"  [alert] {title} | {message} | {url or ''}")
        return
    body = {"topic": topic, "title": title, "message": message, "tags": [tags]}
    if url:
        body["click"] = url
        body["actions"] = [{"action": "view", "label": "Open listing", "url": url}]
    server = os.environ.get("NTFY_SERVER", "https://ntfy.sh").rstrip("/")
    req = urllib.request.Request(server, data=json.dumps(body).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=20).read()


def load_json(path, default):
    try:
        with open(path, encoding="utf-8-sig") as f:  # -sig: tolerate Notepad's BOM
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def search_signature(cfg):
    locs = sorted(norm(p) for p in cfg["locations"])
    # One location is stored as a plain string so searches saved before multi-location keep their history.
    key = json.dumps([sorted(norm(k) for k in cfg["keywords"]), locs if len(locs) > 1 else "".join(locs)])
    return hashlib.sha1(key.encode()).hexdigest()[:12]


def main():
    cfg = load_json(CONFIG_PATH, {})
    # Search terms = the terms of each field picked on the settings page + any typed ones.
    fields = {f["id"]: f for f in load_json(FIELDS_PATH, {}).get("fields", [])}
    picked = [fields[i] for i in cfg.get("fields", []) if i in fields]
    custom = [k.strip() for k in cfg.get("keywords", []) if k.strip()]
    terms = [t for f in picked for t in f["terms"]] + custom
    cfg["keywords"] = list(dict.fromkeys(terms))
    what = ", ".join([f["label"] for f in picked] + custom) or "any job"
    # Older configs had a single "location"; empty means all of Greece.
    places = cfg.get("locations") or [cfg.get("location", "")]
    cfg["locations"] = [p.strip() for p in places if p.strip() and norm(p) not in ALL_GREECE][:MAX_LOCATIONS]
    status = {"last_run": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "active": bool(cfg.get("active")), "sources": {}, "new": 0}

    if not cfg.get("active"):
        print("Watcher is turned off in config.json; nothing to do.")
        save_json(STATUS_PATH, status)
        return

    seen = load_json(SEEN_PATH, {})
    first_run = seen.get("signature") != search_signature(cfg)
    # id -> date it last showed up in results. Older files stored a plain list of ids.
    last_seen = {} if first_run else seen.get("last_seen") or {i: TODAY for i in seen.get("ids", [])}

    found = []
    for name, enabled in cfg.get("sources", {}).items():
        if not enabled or name not in SOURCES:
            continue
        try:
            # Keyword search is done by each site (it matches descriptions too), but LinkedIn
            # pads thin results with jobs from elsewhere, so re-check the location.
            results = [j for j in SOURCES[name](cfg)
                       if not j["location"] or matches_location(j["location"], cfg)]
            results = list({j["id"]: j for j in results}.values())  # same job found by several keywords
            status["sources"][name] = {"ok": True, "count": len(results)}
            print(f"{name}: {len(results)} matching listings")
            found.extend(results)
        except Exception as e:  # one broken site shouldn't stop the others
            status["sources"][name] = {"ok": False, "error": str(e)[:200]}
            print(f"{name}: FAILED - {e}", file=sys.stderr)

    unique = {}
    for j in found:
        unique.setdefault(j["id"], j)
    new_jobs = [j for j in unique.values() if j["id"] not in last_seen]
    status["new"] = len(new_jobs)

    # Listings behind the "N matching" counts on the settings page.
    new_ids = {j["id"] for j in new_jobs}
    for name, info in status["sources"].items():
        if info["ok"]:
            info["jobs"] = [{**{k: j[k] for k in ("title", "company", "location", "url")},
                             "new": j["id"] in new_ids and not first_run}
                            for j in unique.values() if j["source"].lower() == name][:MAX_LISTED]

    where = ", ".join(cfg["locations"]) or "all of Greece"
    if first_run:
        notify("Job alerts are on",
               f"Watching for {what} in {where}. {len(unique)} listings are already open; "
               f"you'll get an alert for each new one.", tags="white_check_mark")
    else:
        for j in new_jobs[:MAX_ALERTS_PER_RUN]:
            line = " · ".join(x for x in (j["company"], j["location"], j["source"]) if x)
            notify(j["title"], line, j["url"])
        if len(new_jobs) > MAX_ALERTS_PER_RUN:
            notify(f"+{len(new_jobs) - MAX_ALERTS_PER_RUN} more new jobs",
                   f"More new listings for {what} in {where} than fit in one batch.")

    # Refresh every listing still online, and forget ones gone for SEEN_DAYS so the file
    # doesn't grow forever. Jobs still listed are never forgotten, so they never re-alert.
    for j in unique.values():
        last_seen[j["id"]] = TODAY
    cutoff = (datetime.now(timezone.utc) - timedelta(days=SEEN_DAYS)).date().isoformat()
    last_seen = {i: d for i, d in last_seen.items() if d >= cutoff}
    save_json(SEEN_PATH, {"signature": search_signature(cfg), "last_seen": last_seen})
    save_json(STATUS_PATH, status)
    print(f"{len(new_jobs)} new listing(s){' (baseline run)' if first_run else ''}.")


if __name__ == "__main__":
    main()
