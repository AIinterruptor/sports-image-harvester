#!/usr/bin/env python3
"""
Sports Figure Image Harvester
Version: 1.2.0

Downloads images of sports figures from Wikimedia Commons, keeping ONLY files
released under licenses free for public use (Public Domain, CC0, CC BY, CC BY-SA).
Every download is recorded in manifest.json with full attribution metadata so
license terms (attribution, share-alike) can be honored downstream.

Stdlib only — no third-party dependencies.

Usage:
    python harvest.py                     # harvest all athletes in config.json
    python harvest.py --athlete "Name"    # harvest a single athlete
    python harvest.py --limit 5           # cap new downloads per athlete
"""

import argparse
import hashlib
import html
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

API_URL = "https://commons.wikimedia.org/w/api.php"
USER_AGENT = (
    "SportsImageHarvester/1.0.0 "
    "(https://github.com/AIinterruptor/sports-image-harvester; javellanajd@gmail.com)"
)
ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config.json"
MANIFEST_PATH = ROOT / "manifest.json"
IMAGES_DIR = ROOT / "images"

# License short names accepted as "free for public use". Anything containing
# NC (non-commercial) or ND (no-derivatives) is rejected even if it starts
# with an allowed prefix.
ALLOWED_LICENSE_PREFIXES = (
    "cc0",
    "cc by",
    "cc-by",
    "public domain",
    "pd",
    "no restrictions",
)
FORBIDDEN_TOKENS = ("nc", "nd", "sampling", "fair use", "copyright")


def log(msg: str) -> None:
    print(f"[harvest] {msg}", flush=True)


def api_get(params: dict) -> dict:
    params = {**params, "format": "json", "maxlag": "5"}
    url = API_URL + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def license_is_free(short_name: str) -> bool:
    s = short_name.strip().lower()
    if not s:
        return False
    # Token check: "CC BY-NC 2.0" splits into tokens containing "nc"
    tokens = re.split(r"[\s\-/,]+", s)
    if any(t in FORBIDDEN_TOKENS for t in tokens):
        return False
    return any(s.startswith(p) for p in ALLOWED_LICENSE_PREFIXES)


def strip_html(text: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", text or "")).strip()


def sanitize_filename(title: str) -> str:
    # "File:Foo bar.jpg" -> "Foo_bar.jpg", safe for all filesystems
    name = title.split(":", 1)[-1]
    name = re.sub(r"[^\w.\-]+", "_", name)
    return name[:180]


def load_json(path: Path, default):
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return default


def search_commons(athlete: str, search_limit: int) -> list[dict]:
    """Return candidate file pages with imageinfo + license metadata."""
    data = api_get({
        "action": "query",
        "generator": "search",
        "gsrsearch": f'"{athlete}"',
        "gsrnamespace": 6,          # File: namespace
        "gsrlimit": search_limit,
        "prop": "imageinfo",
        "iiprop": "url|size|mime|sha1|extmetadata",
    })
    pages = data.get("query", {}).get("pages", {})
    return list(pages.values())


def evaluate_candidate(page: dict, min_width: int) -> dict | None:
    """Return a normalized record if the file is freely licensed and usable."""
    infos = page.get("imageinfo")
    if not infos:
        return None
    info = infos[0]
    if info.get("mime") not in ("image/jpeg", "image/png", "image/webp"):
        return None
    if info.get("width", 0) < min_width:
        return None

    meta = info.get("extmetadata", {})
    def meta_val(key):
        return strip_html(str(meta.get(key, {}).get("value", "")))

    license_short = meta_val("LicenseShortName")
    if not license_is_free(license_short):
        return None

    title = page.get("title", "")
    return {
        "commons_title": title,
        "commons_page": "https://commons.wikimedia.org/wiki/"
                        + urllib.parse.quote(title.replace(" ", "_")),
        "download_url": info["url"],
        "sha1": info.get("sha1", ""),
        "width": info.get("width"),
        "height": info.get("height"),
        "mime": info.get("mime"),
        "license": license_short,
        "license_url": meta_val("LicenseUrl"),
        "artist": meta_val("Artist"),
        "credit": meta_val("Credit"),
        "attribution_required": meta_val("AttributionRequired").lower() != "false",
    }


def download(url: str, dest: Path) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = resp.read()
    dest.write_bytes(data)
    return hashlib.sha256(data).hexdigest()


def harvest_athlete(athlete: str, cfg: dict, manifest: dict, limit: int) -> list[dict]:
    seen_sha1 = {rec["sha1"] for recs in manifest.values() for rec in recs if rec.get("sha1")}
    seen_titles = {rec["commons_title"] for recs in manifest.values() for rec in recs}

    candidates = search_commons(athlete, cfg.get("search_limit", 30))
    slug = re.sub(r"[^\w]+", "_", athlete.strip()).strip("_").lower()
    out_dir = IMAGES_DIR / slug
    new_records = []

    for page in candidates:
        if len(new_records) >= limit:
            break
        rec = evaluate_candidate(page, cfg.get("min_width", 600))
        if rec is None:
            continue
        if rec["sha1"] in seen_sha1 or rec["commons_title"] in seen_titles:
            continue

        out_dir.mkdir(parents=True, exist_ok=True)
        filename = sanitize_filename(rec["commons_title"])
        dest = out_dir / filename
        try:
            sha256 = download(rec["download_url"], dest)
        except Exception as e:
            log(f"  download failed for {rec['commons_title']}: {e}")
            continue

        rec.update({
            "athlete": athlete,
            "path": str(dest.relative_to(ROOT)).replace("\\", "/"),
            "sha256": sha256,
            "retrieved_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        })
        manifest.setdefault(athlete, []).append(rec)
        seen_sha1.add(rec["sha1"])
        seen_titles.add(rec["commons_title"])
        new_records.append(rec)
        log(f"  + {filename} [{rec['license']}] by {rec['artist'] or 'unknown'}")
        time.sleep(cfg.get("request_delay_seconds", 1.0))

    return new_records


def notify_discord(new_records: list[dict]) -> None:
    """Post per-image detail (license, artist, size, storage links) to Discord."""
    webhook = os.environ.get("DISCORD_WEBHOOK", "").strip()
    if not webhook or not new_records:
        return

    repo = os.environ.get("GITHUB_REPOSITORY", "AIinterruptor/sports-image-harvester")
    branch = os.environ.get("GITHUB_REF_NAME", "main")

    lines = []
    for rec in new_records:
        path_quoted = urllib.parse.quote(rec["path"])
        view_url = f"https://github.com/{repo}/blob/{branch}/{path_quoted}"
        raw_url = f"https://raw.githubusercontent.com/{repo}/{branch}/{path_quoted}"
        lines.append(
            f"**{rec['athlete']}** — {rec['path'].rsplit('/', 1)[-1]}\n"
            f"  {rec['width']}x{rec['height']} | {rec['license']}"
            f" | by {rec['artist'] or 'unknown'}\n"
            f"  repo: `{rec['path']}` · [view]({view_url}) · [direct]({raw_url})"
            f" · [source]({rec['commons_page']})"
        )

    header = f"📸 **{len(new_records)} new image(s) harvested**\n"
    # Discord caps content at 2000 chars — send in chunks.
    chunk = header
    chunks = []
    for line in lines:
        if len(chunk) + len(line) + 1 > 1900:
            chunks.append(chunk)
            chunk = ""
        chunk += line + "\n"
    chunks.append(chunk)

    for body in chunks:
        payload = {"username": "Sports Image Harvester", "content": body}
        req = urllib.request.Request(
            webhook,
            data=json.dumps(payload).encode("utf-8"),
            headers={"User-Agent": USER_AGENT, "Content-Type": "application/json"},
        )
        try:
            urllib.request.urlopen(req, timeout=30).read()
        except Exception as e:
            log(f"discord notify failed: {e}")
            return
        time.sleep(0.5)
    log(f"discord notification sent ({len(chunks)} message(s))")


def main() -> int:
    parser = argparse.ArgumentParser(description="Harvest freely-licensed sports figure images")
    parser.add_argument("--athlete", help="harvest a single athlete by name")
    parser.add_argument("--limit", type=int, default=None,
                        help="max NEW downloads per athlete this run")
    args = parser.parse_args()

    cfg = load_json(CONFIG_PATH, {})
    athletes = [args.athlete] if args.athlete else cfg.get("athletes", [])
    if not athletes:
        log("no athletes configured — add names to config.json")
        return 1
    limit = args.limit if args.limit is not None else cfg.get("max_new_per_athlete", 10)

    manifest = load_json(MANIFEST_PATH, {})
    new_records = []
    for athlete in athletes:
        log(f"searching Commons for: {athlete}")
        try:
            new_records.extend(harvest_athlete(athlete, cfg, manifest, limit))
        except Exception as e:
            log(f"  ERROR harvesting {athlete}: {e}")
        time.sleep(cfg.get("request_delay_seconds", 1.0))

    MANIFEST_PATH.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    log(f"done — {len(new_records)} new image(s); manifest updated")
    notify_discord(new_records)
    return 0


if __name__ == "__main__":
    sys.exit(main())
