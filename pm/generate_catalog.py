#!/usr/bin/env python3
"""Publish PM metadata only. Never fetch or publish any kstuff binary."""
import argparse
import hashlib
import importlib.util
import json
import os
import sys
from pathlib import Path
import re
import tempfile

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location('aio_builder', ROOT / 'scripts/build.py')
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)
PUBLIC_IDS = ('nanodns', 'elfldr', 'ftpsrv', 'websrv', 'shadowmountplus',
              'hush', 'dump-forge')


def pm_source(key, config):
    cfg = config['payloads'][key].copy()
    if key == 'ftpsrv':
        cfg.update(repo='drakmor/ftpsrv', name='FTP Server (Drakmor stable)',
                   include_prerelease=False)
    return cfg


def entry(key, cfg, releases, cache):
    if key not in PUBLIC_IDS or 'kstuff' in key.lower() or cfg.get('kind') != 'github':
        raise ValueError('Only the seven selected public payloads may enter this catalog')
    if key == 'ftpsrv':
        # Drakmor also publishes test/beta builds without GitHub's prerelease flag.
        releases = [r for r in releases if re.search(r'(?:^|[-._])stable$', r['tag_name'], re.I)]
    rel, asset = builder.select_asset(releases, cfg['asset_regex'], cfg.get('include_prerelease', True))
    url = asset.get('browser_download_url', '')
    expected = 'https://github.com/' + cfg['repo'] + '/releases/download/'
    if not url.lower().startswith(expected.lower()) or not 64 <= asset.get('size', 0) <= builder.MAX_ELF_BYTES:
        raise ValueError('Unexpected asset URL or size for ' + key)
    digest = asset.get('digest') or ''
    if re.fullmatch(r'sha256:[0-9a-fA-F]{64}', digest):
        checksum = digest[7:].lower()
    else:
        path = cache / (key + '.elf')
        builder.download_asset(asset, path)
        builder.validate_elf(path)
        checksum = builder.hash_file(path)
        path.unlink()
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

def can_reuse(item, cfg):
    prefix = 'https://github.com/' + cfg['repo'] + '/releases/download/'
    return (item and item.get('url', '').lower().startswith(prefix.lower())
            and re.fullmatch(cfg['asset_regex'], item.get('filename', ''))
            and re.fullmatch(r'[0-9a-f]{64}', item.get('checksum', '')))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fixtures', type=Path, help='Offline release API snapshots for validation')
    parser.add_argument('--output', type=Path, default=ROOT / 'pm/payloads.json')
    args = parser.parse_args()
    config = json.loads((ROOT / 'config/payloads.json').read_text())
    builder.validate_config(config)
    token = os.environ.get('GITHUB_TOKEN')
    previous = {}
    if args.output.exists():
        previous = {p['id']: p for p in json.loads(args.output.read_text())['payloads']}
    entries = []
    with tempfile.TemporaryDirectory() as directory:
        for key in PUBLIC_IDS:
            cfg = pm_source(key, config)
            try:
                releases = (json.loads((args.fixtures / (key + '.json')).read_text()) if args.fixtures else
                            builder.release_assets(cfg['repo'], token))
                item = entry(key, cfg, releases, Path(directory))
            except (builder.BuildError, KeyError, ValueError, OSError) as error:
                item = previous.get(key)
                if not can_reuse(item, cfg):
                    raise
                print(f'::warning::{key}: {error}. Retaining last verified release.', file=sys.stderr)
            entries.append(item)
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
