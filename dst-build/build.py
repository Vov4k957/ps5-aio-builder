#!/usr/bin/env python3
"""Build the MihawkOS 8.1 D3D9 test DLL from its exact pinned inputs."""
import hashlib
import json
import os
from pathlib import Path
import resource
import shutil
import struct
import subprocess
import tarfile
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
WORK = ROOT / 'dst-work'
DIST = ROOT / 'dst-dist'
SPEC = json.loads((HERE / 'inputs.json').read_text())
JOBS = '2'


def run(args, **kwargs):
    print('+', ' '.join(str(a) for a in args), flush=True)
    return subprocess.run([str(a) for a in args], check=True, **kwargs)


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def download(url, path, expected=None, git_blob=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    run(['curl', '--fail', '--location', '--retry', '3', '--silent', '--show-error',
         '--output', path, url])
    if expected and sha(path) != expected:
        raise RuntimeError('SHA256 mismatch: ' + path.name)
    if git_blob:
        data = path.read_bytes()
        actual = hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()
        if actual != git_blob:
            raise RuntimeError('Git blob mismatch: ' + path.name)


def extract(archive, destination):
    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive) as stream:
        for member in stream.getmembers():
            parts = Path(member.name).parts
            if len(parts) <= 1:
                continue
            member.name = str(Path(*parts[1:]))
            stream.extract(member, destination, filter='data')


def apply(path, cwd):
    with path.open('rb') as stream:
        run(['patch', '--batch', '--forward', '--fuzz=0', '-p1'], cwd=cwd, stdin=stream)


def host_check(source, host_build, expected_failure):
    if not (host_build / 'build.ninja').exists():
        run(['meson', 'setup', host_build, source, '--buildtype=debug', '--wrap-mode=nodownload',
             '-Db_ndebug=false', '-Denable_sm3=true', '-Denable_sm5=false',
             '-Denable_spirv=false', '-Denable_tests=false', '-Denable_tools=false'])
    run(['ninja', '-C', host_build, '-j', JOBS])
    exe = WORK / ('sm3-before' if expected_failure else 'sm3-after')
    run(['c++', '-std=c++17', '-O0', '-g', '-I' + str(source), HERE / 'sm3_check.cpp',
         host_build / 'libdxbc_spv.a', '-pthread', '-o', exe])
    test = subprocess.run([str(exe)], text=True, capture_output=True)
    log = test.stdout + test.stderr
    print(log, flush=True)
    result = {'returncode': test.returncode, 'output': log}
    if expected_failure:
        assert test.returncode != 0 and 'eSrcReg' in log and 'getSwizzle' in log, result
    else:
        assert test.returncode == 0 and 'PASS:' in log, result
    return result


def inspect_pe(path):
    data = path.read_bytes()
    assert data[:2] == b'MZ'
    off = struct.unpack_from('<I', data, 0x3c)[0]
    assert data[off:off + 4] == b'PE\0\0'
    machine, count, stamp, _, _, optional_size, characteristics = struct.unpack_from('<HHIIIHH', data, off + 4)
    optional = off + 24
    assert machine == 0x8664 and struct.unpack_from('<H', data, optional)[0] == 0x20b
    assert characteristics & 0x2000
    sections = []
    for index in range(count):
        item = optional + optional_size + index * 40
        size, rva, raw_size, raw = struct.unpack_from('<IIII', data, item + 8)
        sections.append((rva, max(size, raw_size), raw))
    def file_offset(rva):
        for start, size, raw in sections:
            if start <= rva < start + size:
                return raw + rva - start
        raise ValueError('RVA outside sections')
    export_rva = struct.unpack_from('<I', data, optional + 112)[0]
    exp = file_offset(export_rva)
    names_count, names_rva = struct.unpack_from('<I', data, exp + 24)[0], struct.unpack_from('<I', data, exp + 32)[0]
    names = []
    for index in range(names_count):
        name_rva = struct.unpack_from('<I', data, file_offset(names_rva) + index * 4)[0]
        name_off = file_offset(name_rva)
        names.append(data[name_off:data.index(0, name_off)].decode('ascii'))
    assert {'Direct3DCreate9', 'Direct3DCreate9Ex'} <= set(names), names
    assert SPEC['output_version'].encode() in data
    return {'machine': 'AMD64', 'pe': 'PE32+', 'dll': True, 'timestamp': stamp, 'exports': names}


def main():
    started = time.monotonic()
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    WORK.mkdir(exist_ok=True)
    DIST.mkdir(exist_ok=True)
    owned = WORK / 'mihawkos'
    for item in SPEC['owned_inputs']:
        url = ('https://raw.githubusercontent.com/' + SPEC['mihawkos_repository'] + '/' +
               SPEC['mihawkos_commit'] + '/' + item['path'])
        download(url, owned / item['path'], git_blob=item['sha'])
    pins = json.loads((owned / 'platform/dxvk/pins.json').read_text())
    source = WORK / 'source'
    source.mkdir()
    for pin in pins:
        archive = WORK / 'archives' / pin['archive']
        download('https://codeload.github.com/' + pin['repo'] + '/tar.gz/' + pin['revision'], archive, pin['sha256'])
        extract(archive, source / pin['path'])
    ps5_patches = sorted((owned / 'platform/dxvk/patches').glob('*.patch'))
    assert len(ps5_patches) == 7
    for patch in ps5_patches:
        apply(patch, source)
    compiler = source / 'subprojects/dxbc-spirv'
    host_build = WORK / 'host-sm3'
    before = host_check(compiler, host_build, True)
    fix = HERE / 'texkill-constant-swizzle.patch'
    apply(fix, compiler)
    after = host_check(compiler, host_build, False)
    meson_file = source / 'meson.build'
    original = meson_file.read_text()
    old_version = "command: ['printf', 'v3.1-19-g601930949-ps5-1']"
    assert original.count(old_version) == 1
    meson_file.write_text(original.replace(old_version, "command: ['printf', '" + SPEC['output_version'] + "']"))
    archive = WORK / 'llvm-mingw.tar.xz'
    download(SPEC['toolchain']['url'], archive, SPEC['toolchain']['sha256'])
    toolchain = WORK / 'toolchain'
    extract(archive, toolchain)
    binaries = toolchain / 'bin'
    env = dict(os.environ, PATH=str(binaries) + os.pathsep + os.environ['PATH'])
    cross = WORK / 'cross-x86_64.ini'
    cross.write_text('[binaries]\n' + '\n'.join(
        key + " = '" + str(binaries / value) + "'" for key, value in [
            ('c', 'x86_64-w64-mingw32-clang'), ('cpp', 'x86_64-w64-mingw32-clang++'),
            ('ar', 'llvm-ar'), ('strip', 'llvm-strip'), ('windres', 'x86_64-w64-mingw32-windres')]) +
        "\npkg-config = 'false'\n[properties]\nneeds_exe_wrapper = true\n" +
        "[host_machine]\nsystem = 'windows'\ncpu_family = 'x86_64'\ncpu = 'x86_64'\nendian = 'little'\n")
    build = WORK / 'build-x86_64'
    run(['meson', 'setup', build, source, '--cross-file', cross, '--wrap-mode=nodownload',
         '--buildtype=release', '-Dc_link_args=-Wl,--no-insert-timestamp',
         '-Dcpp_link_args=-Wl,--no-insert-timestamp'], env=env)
    run(['ninja', '-C', build, '-j', JOBS, 'src/d3d9/d3d9.dll'], env=env)
    output = DIST / 'd3d9.dll'
    shutil.copyfile(build / 'src/d3d9/d3d9.dll', output)
    image = inspect_pe(output)
    run([binaries / 'llvm-readobj', '--file-headers', '--coff-imports', '--coff-exports', output],
        stdout=(DIST / 'pe-inspection.txt').open('w'))
    licenses = DIST / 'licenses'
    licenses.mkdir()
    for name, relative in [('DXVK', 'LICENSE'), ('dxbc-spirv', 'subprojects/dxbc-spirv/LICENSE'),
                           ('libdisplay-info', 'subprojects/libdisplay-info/LICENSE'),
                           ('Vulkan-Headers', 'include/vulkan/LICENSE.md'),
                           ('SPIRV-Headers', 'include/spirv/LICENSE'),
                           ('compiler-SPIRV-Headers', 'subprojects/dxbc-spirv/submodules/spirv_headers/LICENSE')]:
        shutil.copyfile(source / relative, licenses / (name + '.txt'))
    shutil.copyfile(fix, DIST / fix.name)
    shutil.copyfile(HERE / 'inputs.json', DIST / 'inputs.json')
    info = {'mihawkos_release': SPEC['mihawkos_release'], 'mihawkos_commit': SPEC['mihawkos_commit'],
            'version': SPEC['output_version'], 'architecture': 'x86_64', 'dll_sha256': sha(output),
            'dll_bytes': output.stat().st_size, 'source_pins': pins,
            'ps5_patches': [{'name': p.name, 'sha256': sha(p)} for p in ps5_patches],
            'fix_sha256': sha(fix), 'toolchain_sha256': sha(archive),
            'synthetic_before': before, 'synthetic_after': after, 'pe': image,
            'console_tested': False, 'build_seconds': round(time.monotonic() - started, 1)}
    (DIST / 'build-info.json').write_text(json.dumps(info, indent=2) + '\n')
    (DIST / 'SHA256SUMS').write_text(sha(output) + '  d3d9.dll\n')
    print(json.dumps({'verdict': 'PASS', 'dll_sha256': sha(output), 'pe': image,
                      'version': SPEC['output_version'], 'console_tested': False}), flush=True)


if __name__ == '__main__':
    main()
