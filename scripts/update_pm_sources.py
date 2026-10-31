#!/usr/bin/env python3
"""Regenerate one separate Payload Manager v0.6.3 JSON source per public upstream."""
import argparse
import json
import os
from pathlib import Path
import re
import urllib.request

CONFIG = {
    "elfldr": ("ELF Loader", "ps5-payload-dev/elfldr", r"^elfldr-ps5\.elf$", "Loaders", None),
    "ftpsrv": ("FTP Server", "ps5-payload-dev/ftpsrv", r"^ftpsrv-ps5\.elf$", "Networking", None),
    "nanodns": ("nanoDNS", "drakmor/nanoDNS", r"^nanodns\.elf$", "Networking", None),
    "websrv": ("Web Server", "ps5-payload-dev/websrv", r"^websrv-ps5\.elf$", "Networking", None),
    "shadowmountplus": ("ShadowMountPlus", "drakmor/ShadowMountPlus", r"^shadowmountplus\.elf$", "Games", None),
    "yt-blocker": ("YT Blocker", "Epinorr/y2jb-update-blocker", r"^YT-Blocker_v1\.0\.2\.elf$", "Utilities", "v1.0.2"),
    "hush": ("Hush", "disco-trooper/hush", r"^hush\.elf$", "Utilities", None),
    "dump-forge": ("Dump Forge", "quer3q/ps5-dump-forge", r"^ps5-dump-forge-[^/]+-ps5\.elf$", "Utilities", None),
}

def get_json(url):
    req = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": "PS5-PM-Catalog-Updater/1.0",
    })
    token = os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    with urllib.request.urlopen(req, timeout=30) as conn:
        return json.load(conn)

def select_release(releases, tag=None):
    valid = [r for r in releases if not r.get("draft")]
    if tag is not None:
        valid = [r for r in valid if r.get("tag_name") == tag]
    if not valid:
        raise ValueError("No matching published release")
    return max(valid, key=lambda r: r.get("published_at") or r.get("created_at") or "")

def make_catalog(key, setting, releases):
    name, repo, asset_expr, category, tag = setting
    release = select_release(releases, tag)
    assets = [a for a in release.get("assets", []) if re.fullmatch(asset_expr, a.get("name", ""))]
    if len(assets) != 1:
        raise ValueError(f"{key}: expected one ELF asset in {release.get('tag_name')}, got {len(assets)}")
    asset = assets[0]
    checksum = asset.get("digest") or ""
    if not re.fullmatch(r"sha256:[a-fA-F0-9]{64}", checksum):
        raise ValueError(f"{key}: GitHub release asset does not provide a SHA-256 digest")
    url = asset["browser_download_url"]
    if not url.startswith("https://github.com/" + repo + "/releases/download/"):
        raise ValueError(f"{key}: invalid release URL")
    if not 64 <= asset.get("size", 0) <= 120 * 1024 * 1024:
        raise ValueError(f"{key}: unexpected ELF size")
    return {
        "name": f"PS5 {name} (upstream)",
        "payloads": [
            {
                "id": "aio-" + key,
                "name": name,
                "filename": asset["name"],
                "url": url,
                "version": release["tag_name"],
                "last_update": (release.get("published_at") or release.get("created_at") or "")[:10],
                "checksum": checksum[7:].lower(),
                "category": category,
                "source": "https://github.com/" + repo,
                "description": "Official public upstream ELF; validate firmware compatibility before updating.",
            }
        ],
    }

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="pm-sources")
    args = parser.parse_args()
    root = Path(args.output)
    root.mkdir(parents=True, exist_ok=True)
    for key, settings in CONFIG.items():
        repo = settings[1]
        releases = get_json(f"https://api.github.com/repos/{repo}/releases?per_page=40")
        catalog = make_catalog(key, settings, releases)
        dest = root / (key + ".json")
        payload = json.dumps(catalog, ensure_ascii=False, indent=2) + "\n"
        if not dest.exists() or dest.read_text(encoding="utf-8") != payload:
            dest.write_text(payload, encoding="utf-8")
            print(f"{key}: {catalog['payloads'][0]['version']} updated")
        else:
            print(f"{key}: {catalog['payloads'][0]['version']} unchanged")
    print("8 separate PS5 Payload Manager sources ready")

if __name__ == "__main__":
    main()
