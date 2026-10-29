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
import unicodedata
import urllib.parse
import urllib.request
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(ROOT, "config.json")
SEEN_PATH = os.path.join(ROOT, "seen.json")
STATUS_PATH = os.path.join(ROOT, "docs", "status.json")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")
MAX_ALERTS_PER_RUN = 15
MAX_SEEN = 5000

# Each group: the first entry is the English name sent to LinkedIn/Indeed,
# the rest are spellings we accept when filtering listing text.
LOCATION_ALIASES = [
    ["Athens", "athina", "αθηνα", "αθηνων", "attica", "attiki", "αττικη", "αττικης",
     # suburbs that sites list instead of "Athens"
     "halandri", "χαλανδρι", "marous", "μαρουσι", "kifisi", "κηφισια", "psychik", "psihik", "ψυχικο",
     "paiania", "παιανια", "glyfad", "γλυφαδα", "kallithe", "καλλιθεα", "peristeri", "περιστερι",
     "nea smyrni", "νεα σμυρνη", "agia paraskevi", "αγια παρασκευη", "koropi", "κορωπι",
     "gerakas", "γερακα", "pallini", "παλληνη", "vrilissia", "βριλησσια", "alimos", "αλιμο",
     "elliniko", "ελληνικο", "nea ionia", "νεα ιωνια", "ilioupoli", "ηλιουπολη", "zografou",
     "ζωγραφου", "metamorfosi", "μεταμορφωση", "moschato", "μοσχατο", "piraeus", "pireas", "πειραια"],
    ["Thessaloniki", "salonica", "θεσσαλονικη", "θεσσαλονικης"],
    ["Patras", "patra", "πατρα", "πατρας"],
    ["Heraklion", "iraklio", "irakleio", "ηρακλειο", "ηρακλειου"],
    ["Crete", "kriti", "κρητη", "κρητης", "chania", "χανια", "rethymno", "ρεθυμνο"],
    ["Larissa", "larisa", "λαρισα", "λαρισας"],
    ["Volos", "βολος", "βολου"],
    ["Ioannina", "ιωαννινα", "ιωαννινων"],
    ["Kalamata", "καλαματα", "καλαματας"],
    ["Rhodes", "rodos", "ροδος", "ροδου"],
    ["Corfu", "kerkyra", "κερκυρα", "κερκυρας"],
    ["Piraeus", "pireas", "πειραιας", "πειραια"],
    ["Kavala", "καβαλα", "καβαλας"],
    ["Chalkida", "χαλκιδα", "χαλκιδας"],
]
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
    """Some sites (Indeed) reject Python's TLS handshake but accept curl's."""
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


def location_group(location):
    key = norm(location)
    for group in LOCATION_ALIASES:
        if key in (norm(a) for a in group):
            return group
    return [location]


def matches_location(text, cfg):
    loc = norm(cfg.get("location", ""))
    if loc in ALL_GREECE:
        return True
    t = norm(text)
    if cfg.get("include_remote", True) and (t in ALL_GREECE or any(w in t for w in REMOTE_WORDS)):
        return True  # remote, or listed for "Greece" as a whole
    return any(norm(a) in t for a in location_group(cfg["location"]))


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
    loc = norm(cfg.get("location", ""))
    location = "Greece" if loc in ALL_GREECE else f"{location_group(cfg['location'])[0]}, Greece"
    jobs = []
    for keyword in cfg["keywords"] or [""]:
        for start in (0, 10, 20):
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
        page = fetch("https://www.skywalker.gr/el/aggelies-ergasias?" + qs)
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
    loc = norm(cfg.get("location", ""))
    jobs = []
    for keyword in cfg["keywords"] or [""]:
        qs = urllib.parse.urlencode({
            "q": keyword, "l": "" if loc in ALL_GREECE else cfg["location"],
            "fromage": 3, "sort": "date",
        })
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
    key = json.dumps([sorted(norm(k) for k in cfg["keywords"]), norm(cfg.get("location", ""))])
    return hashlib.sha1(key.encode()).hexdigest()[:12]


def main():
    cfg = load_json(CONFIG_PATH, {})
    cfg["keywords"] = [k.strip() for k in cfg.get("keywords", []) if k.strip()]
    status = {"last_run": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "active": bool(cfg.get("active")), "sources": {}, "new": 0}

    if not cfg.get("active"):
        print("Watcher is turned off in config.json; nothing to do.")
        save_json(STATUS_PATH, status)
        return

    seen = load_json(SEEN_PATH, {"signature": None, "ids": []})
    first_run = seen.get("signature") != search_signature(cfg)
    seen_ids = set() if first_run else set(seen["ids"])

    found = []
    for name, enabled in cfg.get("sources", {}).items():
        if not enabled or name not in SOURCES:
            continue
        try:
            # Keyword search is done by each site (it matches descriptions too), but LinkedIn
            # pads thin results with jobs from elsewhere, so re-check the location.
            results = [j for j in SOURCES[name](cfg)
                       if not j["location"] or matches_location(j["location"], cfg)]
            status["sources"][name] = {"ok": True, "count": len(results)}
            print(f"{name}: {len(results)} matching listings")
            found.extend(results)
        except Exception as e:  # one broken site shouldn't stop the others
            status["sources"][name] = {"ok": False, "error": str(e)[:200]}
            print(f"{name}: FAILED - {e}", file=sys.stderr)

    unique = {}
    for j in found:
        unique.setdefault(j["id"], j)
    new_jobs = [j for j in unique.values() if j["id"] not in seen_ids]
    status["new"] = len(new_jobs)

    what = ", ".join(cfg["keywords"]) or "any job"
    where = cfg.get("location") or "Greece"
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

    ids = (seen["ids"] if not first_run else []) + [j["id"] for j in new_jobs]
    save_json(SEEN_PATH, {"signature": search_signature(cfg), "ids": ids[-MAX_SEEN:]})
    save_json(STATUS_PATH, status)
    print(f"{len(new_jobs)} new listing(s){' (baseline run)' if first_run else ''}.")


if __name__ == "__main__":
    main()
