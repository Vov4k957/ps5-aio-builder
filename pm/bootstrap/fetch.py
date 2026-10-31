"""Fetch the immutable first-boot DNS asset and verify it before linking."""
import hashlib
import os
import sys
import tempfile
import urllib.request
from pathlib import Path

URL = 'https://github.com/drakmor/nanoDNS/releases/download/0.4/nanodns.elf'
SHA256 = 'fcfb7d47c3b295560ea1603dc015f7c4950353ef0faca16428bd425680ef1fc5'
SIZE = 132352


def verify(data):
    if len(data) != SIZE or hashlib.sha256(data).hexdigest() != SHA256:
        raise ValueError('Unexpected nanoDNS 0.4 PS5 release bytes')


def prepare(target):
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        verify(target.read_bytes())
        return
    with urllib.request.urlopen(URL, timeout=60) as response:
        data = response.read(SIZE + 1)
    verify(data)
    with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as temp:
        temp.write(data)
        temp.flush()
        os.fsync(temp.fileno())
    os.replace(temp.name, target)


if __name__ == '__main__':
    prepare(Path(sys.argv[1]))
