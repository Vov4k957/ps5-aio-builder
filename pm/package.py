#!/usr/bin/env python3
"""Package the PS5 coordinator and the corresponding bootstrap source."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import zipfile

from generate_defaults import VERSION

ROOT = Path(__file__).resolve().parent.parent
dist = ROOT / 'dist'
target = dist / 'pm-autoupdate.elf'
data = target.read_bytes()
seed = (ROOT / 'build/pm-seed/nanodns.elf').read_bytes()
seed_hash = 'fcfb7d47c3b295560ea1603dc015f7c4950353ef0faca16428bd425680ef1fc5'
if (data[:6] != b'\x7fELF\x02\x01' or data[16:20] != b'\x03\x00\x3e\x00'
        or hashlib.sha256(seed).hexdigest() != seed_hash or data.count(seed) != 1):
    raise SystemExit('Invalid coordinator ELF or nanoDNS bootstrap')
files = ['pm-autoupdate.elf']
for source in ['pm-autoupdate.json', 'README_RU.md', 'THIRD_PARTY.md',
               'third_party/COPYING', 'bootstrap/nanoDNS-0.4-source.tar.gz']:
    path = ROOT / 'pm' / source
    shutil.copyfile(path, dist / path.name)
    files.append(path.name)
info = {'version': VERSION, 'source_commit': os.environ.get('GITHUB_SHA', 'local'),
        'sdk': 'ps5-payload-dev/sdk v0.45', 'pm_api': '0.6.3', 'hardware_tested': False,
        'bootstrap': {'name': 'drakmor/nanoDNS', 'version': '0.4', 'sha256': seed_hash},
        'elf_bytes': len(data), 'elf_sha256': hashlib.sha256(data).hexdigest()}
(dist / 'build-info.json').write_text(json.dumps(info, indent=2) + '\n')
files.append('build-info.json')
(dist / 'SHA256SUMS').write_text(''.join(hashlib.sha256((dist / f).read_bytes()).hexdigest() + '  ' + f + '\n' for f in files))
with zipfile.ZipFile(dist / 'pm-autoupdate.zip', 'w', zipfile.ZIP_DEFLATED) as z:
    for filename in files + ['SHA256SUMS']:
        z.write(dist / filename, filename)
print(json.dumps(info, indent=2))
