#!/usr/bin/env python3
"""Generate editable runtime defaults from the existing fpkg13 AIO profile."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
IDS = ['nanodns', 'kstuff-local', 'elfldr', 'ftpsrv', 'websrv',
       'shadowmountplus', 'yt-blocker', 'hush', 'dump-forge']
SOURCE = 'https://raw.githubusercontent.com/Vov4k957/ps5-aio-builder/main/pm/payloads.json'

def defaults():
    cfg = json.loads((ROOT.parent / 'config/payloads.json').read_text())
    expected = ['kstuff-fpkg-manual', 'elfldr', 'ftpsrv', 'nanodns', 'websrv',
                'shadowmountplus', 'yt-blocker', 'hush', 'dump-forge']
    if cfg['profiles']['fpkg13'] != expected:
        raise ValueError('fpkg13 changed: review the PM sequence before building')
    sequence = []
    for key in IDS:
        old = 'kstuff-fpkg-manual' if key == 'kstuff-local' else key
        delay = cfg.get('profile_delays', {}).get('fpkg13', {}).get(
            old, cfg['payloads'][old].get('delay_ms', 0))
        sequence.append({'id': key, 'delay_ms': delay, 'enabled': True})
    return {
        'schema': 1, 'source_url': SOURCE, 'auto_update': True,
        'bootstrap_nanodns': '/data/pldmgr/nanodns.elf',
        'local_kstuff': '/data/pldmgr/kstuff.elf',
        'pm_ready_timeout_ms': 15000, 'api_timeout_ms': 5000,
        'dns_timeout_ms': 5000, 'refresh_timeout_ms': 10000,
        'install_timeout_ms': 200000, 'update_budget_ms': 300000,
        'launch_timeout_ms': 40000, 'sequence': sequence,
    }

def main():
    data = defaults()
    (ROOT / 'pm-autoupdate.json').write_text(json.dumps(data, indent=2) + '\n')
    compact = json.dumps(data, separators=(',', ':'))
    (ROOT / 'generated_defaults.h').write_text(
        '/* Generated from config/payloads.json; do not edit. */\n'
        '#define PM_UPDATER_VERSION "1.0.0"\n'
        'static const char default_config[] = ' + json.dumps(compact) + ';\n')

if __name__ == '__main__':
    main()
