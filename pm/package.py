#!/usr/bin/env python3
"""Package only the coordinator, configuration and instructions."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import zipfile

ROOT = Path(__file__).resolve().parent.parent
dist = ROOT / 'dist'
target = dist / 'pm-autoupdate.elf'
data = target.read_bytes()
if data[:6] != b'\x7fELF\x02\x01' or data[18:20] != b'\x3e\x00':
    raise SystemExit('Output is not an x86-64 ELF')
shutil.copyfile(ROOT / 'pm/pm-autoupdate.json', dist / 'pm-autoupdate.json')
shutil.copyfile(ROOT / 'pm/README_RU.md', dist / 'README_RU.md')
info = {'version': '1.0.0', 'source_commit': os.environ.get('GITHUB_SHA', 'local'),
        'sdk': 'ps5-payload-dev/sdk v0.45', 'pm_api': '0.6.3',
        'hardware_tested': False, 'embedded_third_party_payloads': 0,
        'elf_bytes': len(data), 'elf_sha256': hashlib.sha256(data).hexdigest()}
(dist / 'build-info.json').write_text(json.dumps(info, indent=2) + '\n')
files = ['pm-autoupdate.elf', 'pm-autoupdate.json', 'README_RU.md', 'build-info.json']
(dist / 'SHA256SUMS').write_text(''.join(hashlib.sha256((dist/f).read_bytes()).hexdigest() + '  ' + f + '\n' for f in files))
with zipfile.ZipFile(dist / 'pm-autoupdate.zip', 'w', zipfile.ZIP_DEFLATED) as z:
    for filename in files + ['SHA256SUMS']:
        z.write(dist / filename, filename)
print(json.dumps(info, indent=2))
