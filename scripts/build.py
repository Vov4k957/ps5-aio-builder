#!/usr/bin/env python3
"""Resolve public GitHub and locally provided PS5 ELF images and build an AIO ELF."""
import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import urllib.error
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parent.parent
MAX_ELF_BYTES = 120 * 1024 * 1024
ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,60}$")
REPO_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


class BuildError(Exception):
    pass


def api_json(url, token=None):
    headers = {"Accept": "application/vnd.github+json",
               "User-Agent": "ps5-aio-builder/0.1"}
    if token:
        headers["Authorization"] = "Bearer " + token
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=35) as response:
            return json.load(response)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise BuildError("GitHub API error for %s: %s" % (url, exc)) from exc


def release_assets(repo, token, tag=None):
    if not REPO_PATTERN.fullmatch(repo):
        raise BuildError("Invalid GitHub repository: " + repo)
    base = "https://api.github.com/repos/%s/releases" % repo
    if tag is not None:
        if not re.fullmatch(r"[A-Za-z0-9._-]{1,100}", tag):
            raise BuildError("Invalid release tag")
        return [api_json(base + "/tags/" + tag, token)]
    releases = api_json(base + "?per_page=40", token)
    if not isinstance(releases, list):
        raise BuildError("Unexpected GitHub releases response for " + repo)
    return releases


def select_asset(releases, asset_regex, include_prerelease=True):
    pattern = re.compile(asset_regex)
    usable = [r for r in releases if not r.get("draft")
              and (include_prerelease or not r.get("prerelease"))]
    usable.sort(key=lambda r: (r.get("published_at") or r.get("created_at") or ""),
                reverse=True)
    if not usable:
        raise BuildError("No matching published GitHub releases")
    latest = usable[0]
    candidates = [a for a in latest.get("assets", [])
                  if pattern.fullmatch(a.get("name", ""))]
    if len(candidates) != 1:
        raise BuildError("Release %s has %d assets matching %s (expected exactly one)" %
                         (latest.get("tag_name"), len(candidates), asset_regex))
    return latest, candidates[0]


def download_asset(asset, destination):
    url = asset.get("browser_download_url")
    if not isinstance(url, str) or not url.startswith("https://github.com/"):
        raise BuildError("Not an allowed GitHub release asset URL")
    request = urllib.request.Request(url, headers={
        "User-Agent": "ps5-aio-builder/0.1"})
    try:
        with urllib.request.urlopen(request, timeout=120) as response, \
             destination.open("wb") as output:
            size = 0
            while True:
                part = response.read(65536)
                if not part:
                    break
                size += len(part)
                if size > MAX_ELF_BYTES:
                    raise BuildError("ELF exceeds size limit")
                output.write(part)
    except (urllib.error.URLError, OSError) as exc:
        destination.unlink(missing_ok=True)
        raise BuildError("Unable to download %s: %s" % (url, exc)) from exc
    expected = asset.get("size")
    if isinstance(expected, int) and destination.stat().st_size != expected:
        destination.unlink(missing_ok=True)
        raise BuildError("ELF byte size changed during download")
    return url


def validate_elf(path):
    size = path.stat().st_size
    if not (64 <= size <= MAX_ELF_BYTES):
        raise BuildError("Invalid ELF size: %s (%d bytes)" % (path, size))
    with path.open("rb") as stream:
        header = stream.read(20)
    if header[:6] != b"\x7fELF\x02\x01":
        raise BuildError("Not ELF64 little-endian: " + str(path))
    if header[18:20] != b"\x3e\x00":
        raise BuildError("Not an x86-64 ELF: " + str(path))
    return size


def hash_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for part in iter(lambda: stream.read(65536), b""):
            digest.update(part)
    return digest.hexdigest()


def validate_config(config):
    if config.get("schema") != 1 or not isinstance(config.get("payloads"), dict):
        raise BuildError("Unsupported config schema")
    if not isinstance(config.get("profiles"), dict):
        raise BuildError("Missing build profiles")
    for key, cfg in config["payloads"].items():
        if not ID_PATTERN.fullmatch(key):
            raise BuildError("Invalid payload identifier: " + key)
        if cfg.get("kind") not in ("github", "manual"):
            raise BuildError("Unsupported source kind: " + key)
        if cfg["kind"] == "github":
            if not REPO_PATTERN.fullmatch(cfg.get("repo", "")):
                raise BuildError("Invalid repository in " + key)
            re.compile(cfg.get("asset_regex", ""))
        else:
            filename = cfg.get("manual_filename", "")
            if not filename.endswith(".elf") or Path(filename).name != filename:
                raise BuildError("Manual filename must be an ELF basename: " + key)
        delay = cfg.get("delay_ms", 0)
        if type(delay) is not int or not 0 <= delay <= 60000:
            raise BuildError("Invalid delay_ms in " + key)
    for name, ids in config["profiles"].items():
        if not ID_PATTERN.fullmatch(name) or not isinstance(ids, list) or not ids:
            raise BuildError("Invalid profile " + name)
        if len(ids) != len(set(ids)):
            raise BuildError("Duplicate payload identifiers in " + name)
        for key in ids:
            if key not in config["payloads"]:
                raise BuildError("Unknown payload %s in profile %s" % (key, name))


def resolve_payload(key, cfg, repo_owner, token, manual_dir, cache_dir):
    target = cache_dir / (key + ".elf")
    manual_file = manual_dir / cfg.get("manual_filename", key + ".elf")
    if cfg["kind"] == "manual":
        if not manual_file.is_file():
            raise BuildError("Manual ELF %s not found. Put the verified file in %s "
                             "and build locally; never upload restricted Discord "
                             "binaries to a public repository." %
                             (cfg["manual_filename"], manual_dir))
        target.write_bytes(manual_file.read_bytes())
        origin = {"kind": "local", "source": str(manual_file)}
    else:
        releases = release_assets(cfg["repo"], token)
        release, asset = select_asset(releases, cfg["asset_regex"],
                                      cfg.get("include_prerelease", True))
        url = download_asset(asset, target)
        origin = {"kind": "github", "repo": cfg["repo"],
                  "version": release["tag_name"],
                  "prerelease": bool(release.get("prerelease")),
                  "asset": asset["name"], "url": url}
    size = validate_elf(target)
    digest = hash_file(target)
    if cfg.get("sha256") and cfg["sha256"].lower() != digest:
        raise BuildError("SHA-256 mismatch for " + key)
    return {"id": key, "name": cfg["name"], "filename": target.name,
            "bytes": size, "sha256": digest,
            "delay_ms": cfg.get("delay_ms", 0), "origin": origin,
            "note": cfg.get("note", "")}


def generate_sources(payloads, build_dir):
    assembly = ["/* Generated; embedded images are used verbatim. */",
                ".section .rodata", ".p2align 3"]
    c = ['/* Auto-generated. */', '#include "payloads.h"']
    for i, payload in enumerate(payloads):
        start, end = "aio_blob_%d_start" % i, "aio_blob_%d_end" % i
        assembly += [".p2align 3", ".global " + start, start + ":",
                     '.incbin "build/payloads/%s"' % payload["filename"],
                     ".global " + end, end + ":"]
        c.append("extern const unsigned char %s[], %s[];" % (start, end))
    c.append("const aio_payload_t aio_payloads[] = {")
    for i, payload in enumerate(payloads):
        name = json.dumps(payload["name"], ensure_ascii=True)
        c.append("    {%s, aio_blob_%d_start, aio_blob_%d_end, %du}," %
                 (name, i, i, payload["delay_ms"]))
    c.extend(["};",
              "const size_t aio_payload_count = "
              "sizeof(aio_payloads)/sizeof(aio_payloads[0]);"])
    (build_dir / "embedded.S").write_text("\n".join(assembly) + "\n", encoding="utf8")
    (build_dir / "generated.c").write_text("\n".join(c) + "\n", encoding="utf8")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default="standard")
    parser.add_argument("--config", type=Path, default=ROOT / "config/payloads.json")
    parser.add_argument("--manual-dir", type=Path, default=ROOT / "manual")
    parser.add_argument("--no-compile", action="store_true")
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args(argv)

    root = args.root.resolve()
    config = json.loads(args.config.read_text(encoding="utf8"))
    validate_config(config)
    if args.profile not in config["profiles"]:
        raise BuildError("Unknown profile: " + args.profile)
    cache_dir = root / "build" / "payloads"
    cache_dir.mkdir(parents=True, exist_ok=True)
    for old in cache_dir.glob("*.elf"):
        old.unlink()
    for filename in ("embedded.S", "generated.c", "manifest.json"):
        (root / "build" / filename).unlink(missing_ok=True)

    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    resolved = []
    for key in config["profiles"][args.profile]:
        cfg = config["payloads"][key]
        print("Resolving", key, flush=True)
        resolved.append(resolve_payload(key, cfg, "", token, args.manual_dir, cache_dir))
        print("  ->", resolved[-1]["origin"].get("version", "manual"),
              resolved[-1]["bytes"], "bytes")
    generate_sources(resolved, root / "build")
    manifest = {"schema": 1, "profile": args.profile,
                "generated_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
                "target_port": 9021, "payloads": resolved}
    (root / "build" / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf8")

    if not args.no_compile:
        if not os.environ.get("PS5_PAYLOAD_SDK"):
            raise BuildError("PS5_PAYLOAD_SDK required for a real console ELF")
        subprocess.run(["make", "PROFILE=" + args.profile], cwd=root, check=True)
        dist = root / "dist"
        (dist / ("manifest-" + args.profile + ".json")).write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf8")
        filename = "ps5-aio-" + args.profile
        with zipfile.ZipFile(dist / (filename + ".zip"), "w",
                             compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            archive.write(dist / (filename + ".elf"), filename + ".elf")
            archive.write(dist / ("manifest-" + args.profile + ".json"),
                          "manifest.json")
        print("Built", dist / (filename + ".zip"))
    print("Resolved", len(resolved), "payloads for profile", args.profile)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (BuildError, ValueError, OSError, subprocess.CalledProcessError) as error:
        print("ERROR:", error, file=sys.stderr)
        sys.exit(1)
