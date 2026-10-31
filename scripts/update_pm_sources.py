#!/usr/bin/env python3
"""Keep existing single-payload URLs working from the same verified catalog."""
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=ROOT / 'pm-sources')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    for item in json.loads((ROOT / 'pm/payloads.json').read_text())['payloads']:
        # Existing PM slots use these IDs; keep subscriptions and favorites valid.
        catalog = {'name': f"PS5 {item['name']} (upstream)",
                   'payloads': [dict(item, id='aio-' + item['id'])]}
        dest = args.output / (item['id'] + '.json')
        dest.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + '\n')


if __name__ == '__main__':
    main()
