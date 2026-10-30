#!/usr/bin/env python3
"""Publish PM metadata only. Never fetch or publish any kstuff binary."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import tempfile

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location('aio_builder', ROOT / 'scripts/build.py')
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)
PUBLIC_IDS = ('nanodns', 'elfldr', 'ftpsrv', 'websrv', 'shadowmountplus',
              'yt-blocker', 'hush', 'dump-forge')

def entry(key, cfg, releases, cache):
    if key not in PUBLIC_IDS or 'kstuff' in key.lower() or cfg.get('kind') != 'github':
        raise ValueError('Only the eight selected public payloads may enter this catalog')
    rel, asset = builder.select_asset(releases, cfg['asset_regex'], cfg.get('include_prerelease', True))
    if key == 'yt-blocker' and rel['tag_name'] != 'v1.0.2':
        raise ValueError('YT Blocker must remain pinned to v1.0.2')
    digest = asset.get('digest') or ''
    if re.fullmatch(r'sha256:[0-9a-fA-F]{64}', digest):
        checksum = digest[7:].lower()
    else:
        path = cache / (key + '.elf')
        builder.download_asset(asset, path)
        builder.validate_elf(path)
        checksum = builder.hash_file(path)
        path.unlink()
    url = asset.get('browser_download_url', '')
    expected = 'https://github.com/' + cfg['repo'] + '/releases/download/'
    if not url.lower().startswith(expected.lower()) or not 64 <= asset.get('size', 0) <= builder.MAX_ELF_BYTES:
        raise ValueError('Unexpected asset URL or size for ' + key)
    name = asset['name']
    if Path(name).name != name or not name.endswith('.elf'):
        raise ValueError('Unexpected ELF asset filename')
    version = rel['tag_name']
    if len(version.encode()) >= 64:
        raise ValueError('Version does not fit PM')
    return {'id': key, 'name': cfg['name'], 'filename': name, 'url': url,
            'version': version, 'checksum': checksum,
            'last_update': (asset.get('updated_at') or rel['published_at'])[:10],
            'description': cfg.get('note') or cfg['name'],
            'category': 'Vov4k957 Startup', 'author': cfg['repo'].split('/')[0],
            'source': 'https://github.com/' + cfg['repo'],
            'details_url': 'https://raw.githubusercontent.com/Vov4k957/ps5-aio-builder/main/pm/README_RU.md'}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fixtures', type=Path, help='Offline release API snapshots for validation')
    parser.add_argument('--output', type=Path, default=ROOT / 'pm/payloads.json')
    args = parser.parse_args()
    config = json.loads((ROOT / 'config/payloads.json').read_text())
    builder.validate_config(config)
    token = os.environ.get('GITHUB_TOKEN')
    entries = []
    with tempfile.TemporaryDirectory() as directory:
        for key in PUBLIC_IDS:
            cfg = config['payloads'][key]
            releases = (json.loads((args.fixtures / (key + '.json')).read_text()) if args.fixtures else
                        builder.release_assets(cfg['repo'], token, cfg.get('release_tag')))
            entries.append(entry(key, cfg, releases, Path(directory)))
    data = {'name': 'Vov4k957 PS5 Startup (kstuff local only)', 'payloads': entries}
    text = json.dumps(data, ensure_ascii=False, indent=2) + '\n'
    # No timestamps unrelated to releases: unchanged upstream = no commit.
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if not args.output.exists() or args.output.read_text() != text:
        temporary = args.output.with_suffix('.tmp')
        temporary.write_text(text)
        temporary.replace(args.output)
        print('Catalog updated:', ', '.join(e['id'] + ' ' + e['version'] for e in entries))
    else:
        print('Catalog unchanged')

if __name__ == '__main__':
    main()
