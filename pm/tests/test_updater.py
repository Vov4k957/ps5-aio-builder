"""Run the actual C coordinator against a loopback PM API fixture.

These validate orchestration and failure handling, not PS5 hardware behavior.
"""
import copy
import hashlib
import http.server
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import time
import unittest
from urllib.parse import parse_qs, unquote, urlsplit

ROOT = Path(__file__).resolve().parents[2]
PM = ROOT / 'pm'
spec = importlib.util.spec_from_file_location('defaults', PM / 'generate_defaults.py')
defaults = importlib.util.module_from_spec(spec)
spec.loader.exec_module(defaults)
IDS = defaults.IDS
PUBLIC = [x for x in IDS if x != 'kstuff-local']

def elf(label):
    h = bytearray(64)
    h[:6] = b'\x7fELF\x02\x01'
    h[18:20] = b'\x3e\x00'
    return bytes(h) + label.encode()

class Fixture:
    def __init__(self, root):
        self.root = root
        self.source = defaults.SOURCE
        self.items = []
        self.available = []
        self.release_bytes = {}
        self.events = []
        self.loads = []
        self.installs = []
        self.source_present = True
        self.multi = True
        self.autoload = 'local/pm-autoupdate'
        self.refresh_mode = 'ok'
        self.install_mode = {}
        self.load_fail = None
        self.bad_header = False
        for key in PUBLIC:
            data = elf(key + '-old')
            self.release_bytes[key] = data
            path = root / (key + '.elf')
            path.write_bytes(data)
            checksum = hashlib.sha256(data).hexdigest()
            self.items.append({'id': key, 'kind': 'repo', 'slot': 'repo/' + key + '@test',
                               'path': str(path), 'filename': path.name,
                               'source_url': self.source, 'version': '1',
                               'checksum': checksum})
            self.available.append({'id': key, 'version': '1',
                                   'checksum': checksum, 'url': 'https://github.com/example/project/releases/download/v1/' + key + '.elf'})
        self.kstuff = root / 'kstuff.elf'
        self.kstuff.write_bytes(elf('private-manual-kstuff'))
        self.items.append({'kind': 'local', 'slot': 'local/kstuff', 'path': str(self.kstuff), 'filename': 'kstuff.elf'})

    def change(self, key):
        item = next(x for x in self.available if x['id'] == key)
        item['version'] = '2'
        self.release_bytes[key] = elf(key + '-new')
        item['checksum'] = hashlib.sha256(elf(key + '-new')).hexdigest()

    def handler(self):
        fixture = self
        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def reply(self, value, status=200, truncate=False):
                data = value.encode() if isinstance(value, str) else json.dumps(value).encode()
                self.send_response(status)
                self.send_header('Content-Length', str(len(data) + (10 if truncate else 0)))
                self.send_header('Content-Type', 'text/plain' if isinstance(value, str) else 'application/json')
                self.end_headers()
                try:
                    self.wfile.write(data)
                except (BrokenPipeError, ConnectionResetError):
                    pass

            def do_GET(self):
                fixture.events.append(('GET', self.path, time.monotonic()))
                if self.path == '/get_config':
                    return self.reply({'AUTOLOAD_ENABLED': True, 'AUTOLOAD_LIST': fixture.autoload,
                                       'MULTI_SOURCES_ENABLED': fixture.multi})
                if self.path == '/list_payloads':
                    return self.reply({'items': fixture.items})
                if self.path == '/sources_list':
                    return self.reply({'sources': [{'url': fixture.source}] if fixture.source_present else []})
                return self.reply({'error': 'unexpected'}, 404)

            def do_POST(self):
                if self.headers.get('X-PLDMGR-Request') != '1':
                    return self.reply({'error': 'missing marker'}, 403)
                parsed = urlsplit(self.path)
                path, query = parsed.path, parse_qs(parsed.query)
                body = self.rfile.read(int(self.headers.get('Content-Length', '0')))
                fixture.events.append(('POST', path, time.monotonic()))
                if path == '/set_config':
                    assert json.loads(body) == {'MULTI_SOURCES_ENABLED': True}
                    fixture.multi = True
                    return self.reply('OK')  # Actual PM 0.6.3 is plain text here.
                if path == '/sources_add':
                    assert query == {'url': [fixture.source]}
                    fixture.source_present = True
                    return self.reply({'ok': True})
                if path == '/repository_refresh':
                    assert fixture.multi
                    if fixture.refresh_mode == 'timeout':
                        time.sleep(.25)
                    if fixture.refresh_mode == 'malformed':
                        return self.reply('{"sources": [')
                    if fixture.refresh_mode == 'duplicate':
                        return self.reply('{"sources":[],"sources":[]}')
                    result = {'sources': [{'url': fixture.source, 'error': fixture.refresh_mode == 'stale',
                                           'payloads': fixture.available}]}
                    return self.reply(result, truncate=fixture.refresh_mode == 'truncated')
                if path == '/repository_install':
                    key = query['id'][0]
                    fixture.installs.append(key)
                    assert key != 'kstuff-local' and 'kstuff' not in key
                    assert query['source_url'] == [fixture.source]
                    assert query['mode'] == ['replace'] and 'replace_slot' not in query
                    mode = fixture.install_mode.get(key, 'ok')
                    if mode == 'reject':
                        return self.reply({'ok': False, 'message': 'checksum failed'}, 400)
                    if mode == 'timeout':
                        time.sleep(.3)
                    old = next((x for x in fixture.items if x.get('id') == key and x.get('source_url') == fixture.source), None)
                    if old is None:
                        slot = 'repo/' + key + '@' + hashlib.sha256(fixture.source.encode()).hexdigest()[:8]
                        folder = fixture.root / 'payloads' / slot
                        folder.mkdir(parents=True, exist_ok=True)
                        old = {'id': key, 'kind': 'repo', 'slot': slot, 'source_url': fixture.source,
                               'path': str(folder / (key + '.elf')), 'filename': key + '.elf'}
                        fixture.items.append(old)
                    candidate = next(x for x in fixture.available if x['id'] == key)
                    old.update(version=candidate['version'], checksum=candidate['checksum'])
                    Path(old['path']).write_bytes(fixture.release_bytes[key])
                    if old['path'].startswith(str(fixture.root / 'payloads') + '/'):
                        (Path(old['path']).parent / 'meta.json').write_text(json.dumps(old))
                    if mode == 'wrong_hash':
                        old['checksum'] = 'e' * 64
                    return self.reply({'ok': True, 'slot': old['slot']}, truncate=mode == 'truncated')
                if path.startswith('/loadpayload:'):
                    target = unquote(path[len('/loadpayload:'):])
                    data = Path(target).read_bytes()
                    fixture.loads.append((target, data, time.monotonic()))
                    if fixture.load_fail and fixture.load_fail in target:
                        return self.reply('Failed to launch payload', 500)
                    return self.reply('OK')
                return self.reply({'error': 'unexpected'}, 404)
        return Handler

class UpdaterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.builddir = tempfile.TemporaryDirectory()
        cls.binary = Path(cls.builddir.name) / 'pm-updater-host'
        subprocess.run(['python3', str(PM / 'generate_defaults.py')], check=True)
        seed = Path(cls.builddir.name) / 'bootstrap-dns.elf'
        seed.write_bytes(elf('bundled-nanodns'))
        options = ['-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-no-pie'] if os.getenv('PM_SANITIZE') else []
        subprocess.run(['cc', '-DPM_HOST_TEST', '-std=gnu11', '-O1', '-g', '-Wall', '-Wextra', '-Werror',
                        *options, f'-DPM_DNS_SEED="{seed}"', '-I' + str(PM), '-I' + str(PM / 'src'),
                        str(PM / 'third_party/sha256.c'), str(PM / 'bootstrap/seed.S'),
                        *(str(PM / 'src' / f) for f in ['main.c', 'json.c', 'http.c']), '-o', str(cls.binary)], check=True)

    @classmethod
    def tearDownClass(cls):
        cls.builddir.cleanup()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.fx = Fixture(self.root)
        self.config = defaults.defaults()
        self.config.update(local_kstuff=str(self.fx.kstuff), bootstrap_nanodns=str(self.root / 'nanodns.elf'),
                           pm_ready_timeout_ms=500, api_timeout_ms=500, dns_timeout_ms=50,
                           refresh_timeout_ms=100, install_timeout_ms=100, launch_timeout_ms=500,
                           update_budget_ms=5000)
        for step in self.config['sequence']:
            step['delay_ms'] = 0
        self.server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), self.fx.handler())
        self.server.daemon_threads = False
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.tmp.cleanup()

    def run_updater(self, *, dns='1', text=None, boot='test-boot'):
        path = self.root / 'config.json'
        path.write_text(text if text is not None else json.dumps(self.config))
        env = dict(os.environ, PM_CONFIG=str(path), PM_STATE_DIR=str(self.root / 'state'),
                   PM_PORT=str(self.server.server_port), PM_TEST_DNS=dns, PM_TEST_BOOT=boot)
        result = subprocess.run([str(self.binary)], env=env, text=True, capture_output=True, timeout=20)
        self.assertNotIn('AddressSanitizer', result.stderr)
        self.assertNotIn('runtime error:', result.stderr)
        return result

    def test_unchanged_checks_before_launching_rest(self):
        r = self.run_updater()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.fx.installs, [])
        self.assertEqual([Path(x[0]).stem for x in self.fx.loads], [x.replace('-local', '') for x in IDS])
        refresh = next(e[2] for e in self.fx.events if e[1] == '/repository_refresh')
        self.assertLess(self.fx.loads[0][2], refresh)
        self.assertGreater(self.fx.loads[1][2], refresh)

    def test_only_changed_elf_installed(self):
        self.fx.change('shadowmountplus')
        original = self.fx.kstuff.read_bytes()
        r = self.run_updater()
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertEqual(self.fx.installs, ['shadowmountplus'])
        self.assertEqual(self.fx.kstuff.read_bytes(), original)
        self.assertIn(b'shadowmountplus-new', self.fx.loads[5][1])
        self.assertIn(b'shadowmountplus-old', (self.root / 'state/fallback/shadowmountplus.elf').read_bytes())

    def test_install_order_and_no_second_dns_launch(self):
        for key in PUBLIC:
            self.fx.change(key)
        r = self.run_updater()
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertEqual(self.fx.installs, PUBLIC)
        self.assertEqual(len(self.fx.loads), 8)
        self.assertIn(b'nanodns-old', self.fx.loads[0][1])
        self.assertIn(b'nanodns-new', (self.root / 'nanodns.elf').read_bytes())

    def test_source_registration_and_plaintext_config_reply(self):
        self.fx.source_present = False
        self.fx.multi = False
        r = self.run_updater()
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertTrue(self.fx.source_present and self.fx.multi)
        self.assertTrue(any(e[1] == '/repository_refresh' for e in self.fx.events))

    def test_no_dns_uses_local_and_never_calls_remote_routes(self):
        r = self.run_updater(dns='0')
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertEqual(len(self.fx.loads), 8)
        self.assertFalse(any(e[1].startswith('/repository') or e[1] == '/sources_add' for e in self.fx.events))

    def test_refresh_failures_keep_local(self):
        for mode in ['stale', 'malformed', 'duplicate', 'timeout', 'truncated']:
            with self.subTest(mode=mode):
                self.fx.refresh_mode = mode
                marker = self.root / 'state/started-boot.txt'
                marker.unlink(missing_ok=True)
                self.fx.loads.clear()
                self.fx.change('websrv')
                r = self.run_updater(boot=mode)
                self.assertEqual(r.returncode, 0, r.stdout)
                self.assertEqual(self.fx.installs, [])
                self.assertEqual(len(self.fx.loads), 8)

    def test_rejected_install_uses_old_copy(self):
        self.fx.change('websrv')
        self.fx.install_mode['websrv'] = 'reject'
        r = self.run_updater()
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn('/fallback/websrv.elf', self.fx.loads[4][0])
        self.assertIn(b'websrv-old', self.fx.loads[4][1])

    def test_unknown_install_outcome_freezes_current_boot(self):
        for mode in ['timeout', 'truncated', 'wrong_hash']:
            with self.subTest(mode=mode):
                (self.root / 'state/started-boot.txt').unlink(missing_ok=True)
                self.fx.loads.clear()
                self.fx.installs.clear()
                self.fx.change('websrv')
                self.fx.change('hush')
                item = next(x for x in self.fx.items if x.get('id') == 'websrv')
                old = elf('websrv-old')
                Path(item['path']).write_bytes(old)
                item['checksum'] = hashlib.sha256(old).hexdigest()
                self.fx.install_mode['websrv'] = mode
                r = self.run_updater(boot=mode)
                self.assertEqual(r.returncode, 0, r.stdout)
                self.assertEqual(self.fx.installs, ['websrv'])
                self.assertIn('/fallback/websrv.elf', self.fx.loads[4][0])
                self.assertEqual(self.fx.loads[4][1], old)
                time.sleep(.35)  # Let fixture's late installation finish before the next case.

    def test_first_install_keeps_payloads_separate(self):
        self.fx.items = [x for x in self.fx.items if x.get('id') == 'nanodns' or x['kind'] == 'local']
        r = self.run_updater()
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertEqual(self.fx.installs, [x for x in PUBLIC if x != 'nanodns'])
        self.assertEqual(len(self.fx.loads), 8)

    def test_missing_manual_kstuff_still_launches_all_seven(self):
        self.fx.kstuff.unlink()
        r = self.run_updater()
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertEqual([Path(x[0]).stem for x in self.fx.loads], PUBLIC)
        self.assertEqual(self.fx.installs, [])
        self.assertIn('Skipping missing kstuff-local', r.stdout)

    def test_missing_public_and_offline_launches_every_available_file(self):
        next(Path(x['path']) for x in self.fx.items if x.get('id') == 'websrv').unlink()
        r = self.run_updater(dns='0')
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertEqual(len(self.fx.loads), 7)
        self.assertFalse(any('websrv' in x[0] for x in self.fx.loads))

    def test_does_not_repeat_sequence_same_boot(self):
        self.assertEqual(self.run_updater().returncode, 0)
        self.assertEqual(self.run_updater().returncode, 0)
        self.assertEqual(len(self.fx.loads), 8)

    def test_extra_autoload_entry_rejected(self):
        self.fx.autoload += ',local/allinOne-full'
        r = self.run_updater()
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(self.fx.loads, [])

    def test_launch_failure_aborts_without_retry(self):
        self.fx.load_fail = 'kstuff'
        r = self.run_updater()
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(len(self.fx.loads), 2)
        self.run_updater()
        self.assertEqual(len(self.fx.loads), 2)

    def test_retired_blocker_in_old_config_and_cached_catalog_is_ignored(self):
        retired = self.root / 'YT-Blocker_v1.0.2.elf'
        retired.write_bytes(elf('retired-blocker'))
        self.fx.items.append(dict(id='yt-blocker', kind='repo', slot='repo/yt-blocker@test',
                                  path=str(retired), filename=retired.name, source_url=self.fx.source,
                                  version='1', checksum=hashlib.sha256(retired.read_bytes()).hexdigest()))
        self.fx.available.append(dict(id='yt-blocker', version='999', checksum='a'*64,
                                      url='https://github.com/example/removed/releases/download/999/retired.elf'))
        self.config.update(schema=2)
        self.config['sequence'].append(dict(id='yt-blocker', delay_ms=0, enabled=True))
        self.fx.change('hush')
        r = self.run_updater()
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertEqual(self.fx.installs, ['hush'])
        self.assertEqual([Path(x[0]).stem for x in self.fx.loads], [x.replace('-local', '') for x in IDS])
        self.assertFalse(any(e[1] == '/processes_list' for e in self.fx.events))
        self.assertEqual(json.loads((self.root/'state/status.json').read_text())['phase'], 'done')

    def test_legacy_pending_blocker_is_discarded_without_resuming(self):
        state = self.root / 'state'
        state.mkdir()
        (state/'started-boot.txt').write_text('test-boot')
        retired = self.root / 'YT-Blocker_v1.0.2.elf'
        retired.write_bytes(elf('retired-blocker'))
        (state/'pending-yt.txt').write_text(f'test-boot\n0\n0\n{retired}')
        r = self.run_updater()
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertEqual(self.fx.events, [])
        self.assertFalse((state/'pending-yt.txt').exists())
        self.assertEqual(json.loads((state/'status.json').read_text())['phase'], 'already_started')

    def test_configured_delays_are_observed(self):
        self.config['sequence'][5]['delay_ms'] = 65
        self.assertEqual(self.run_updater().returncode, 0)
        self.assertGreaterEqual(self.fx.loads[6][2] - self.fx.loads[5][2], .060)

    def test_invalid_config_does_nothing(self):
        for text in ['{', '{"schema":01}', '{"schema":1,"source_url":"\\u0000"}',
                     json.dumps(self.config).replace('"schema": 3', '"schema": 3, "schema": 3'),
                     json.dumps(self.config).replace('"delay_ms": 0', '"delay_ms": -1', 1)]:
            with self.subTest(text=text[:80]):
                r = self.run_updater(text=text)
                self.assertNotEqual(r.returncode, 0)
        self.assertEqual(self.fx.events, [])

    def test_disabled_payload_is_neither_updated_nor_launched(self):
        self.config['sequence'][-1]['enabled'] = False
        self.fx.change('dump-forge')
        r = self.run_updater()
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertNotIn('dump-forge', self.fx.installs)
        self.assertFalse(any('dump-forge' in x[0] for x in self.fx.loads))

    def test_catalog_without_hash_does_not_install(self):
        self.fx.available[0]['checksum'] = ''
        r = self.run_updater()
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertEqual(self.fx.installs, [])

    def test_local_kstuff_never_selected_from_remote_catalog(self):
        self.fx.available.insert(0, {'id': 'kstuff-local', 'version': '999', 'checksum': 'a'*64,
                                     'url': 'https://github.com/someone/kstuff/releases/download/999/kstuff.elf'})
        self.assertEqual(self.run_updater().returncode, 0)
        self.assertEqual(self.fx.installs, [])
        self.assertIn(b'private-manual-kstuff', self.fx.loads[1][1])

    def test_empty_install_bootstraps_dns_then_builds_seven_slots(self):
        for item in self.fx.items:
            Path(item['path']).unlink()
        self.fx.items.clear()
        self.fx.source_present = self.fx.multi = False
        r = self.run_updater()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.fx.loads[0][1], elf('bundled-nanodns'))
        self.assertEqual(self.fx.installs, PUBLIC)
        self.assertEqual(len(self.fx.loads), 7)
        dns_load = next(i for i,e in enumerate(self.fx.events) if '/loadpayload:' in e[1])
        add = next(i for i,e in enumerate(self.fx.events) if e[1]=='/sources_add')
        self.assertLess(dns_load, add)
        for item in self.fx.items:
            path = Path(item['path'])
            self.assertEqual(path.parent.parent, self.root / 'payloads/repo')
            self.assertTrue((path.parent / 'meta.json').exists())
        # The stored DNS is preferred on the next boot; no new installs.
        (self.root / 'state/started-boot.txt').unlink()
        (self.root / 'state/dns-boot.txt').unlink()
        self.fx.loads.clear()
        self.fx.installs.clear()
        r = self.run_updater()
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertEqual(self.fx.installs, [])
        self.assertEqual(self.fx.loads[0][1], elf('nanodns-old'))

    def test_identical_local_import_is_not_downloaded(self):
        ftp = next(x for x in self.fx.items if x.get('id')=='ftpsrv')
        ftp.update(filename='ftpsrv-ps5.elf', kind='local')
        for field in ('id','version','source_url','checksum'):
            del ftp[field]
        r = self.run_updater()
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertEqual(self.fx.installs, [])
        self.assertEqual(self.fx.loads[3][1], elf('ftpsrv-old'))

    def test_corrupt_managed_file_is_downloaded_even_if_metadata_current(self):
        ftp = next(x for x in self.fx.items if x.get('id')=='ftpsrv')
        Path(ftp['path']).write_bytes(elf('damaged-file'))
        r = self.run_updater()
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertEqual(self.fx.installs, ['ftpsrv'])
        self.assertEqual(self.fx.loads[3][1], elf('ftpsrv-old'))

    def test_new_dump_forge_release_installs_and_starts_last(self):
        self.fx.change('dump-forge')
        r = self.run_updater()
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertEqual(self.fx.installs, ['dump-forge'])
        self.assertEqual(self.fx.loads[-1][1], elf('dump-forge-new'))

    def test_failed_dns_send_is_not_resent_same_boot(self):
        self.fx.load_fail = 'nanodns'
        self.assertNotEqual(self.run_updater().returncode, 0)
        self.assertEqual(len(self.fx.loads), 1)
        self.fx.load_fail = None
        # A lost reply could have delivered the DNS ELF, so do not send it again.
        self.assertNotEqual(self.run_updater().returncode, 0)
        self.assertEqual(len(self.fx.loads), 1)

    def test_gap_before_last_payload_applies_to_installs_and_launch(self):
        self.fx.change('hush')
        self.fx.change('dump-forge')
        self.config['sequence'][-2]['delay_ms'] = 90
        r = self.run_updater()
        self.assertEqual(r.returncode, 0, r.stdout)
        times = [e[2] for e in self.fx.events if e[1]=='/repository_install']
        self.assertEqual(len(times), 2)
        self.assertGreaterEqual(times[1]-times[0], .085)
        self.assertGreaterEqual(self.fx.loads[-1][2]-self.fx.loads[-2][2], .085)

    def test_duplicate_imports_reuse_matching_copy(self):
        old = next(x for x in self.fx.items if x.get('id')=='ftpsrv')
        old.update(kind='local', filename='ftpsrv-ps5.elf', source_url='')
        duplicate = dict(old, path=str(self.root / 'ftp-copy.elf'))
        Path(duplicate['path']).write_bytes(elf('obsolete-copy'))
        self.fx.items.insert(0,duplicate)
        self.assertEqual(self.run_updater().returncode, 0)
        self.assertEqual(self.fx.installs, [])
        self.assertEqual(self.fx.loads[3][1], elf('ftpsrv-old'))

    def test_one_local_private_build_is_discovered_but_ambiguity_is_skipped(self):
        self.config['local_kstuff'] = '/data/pldmgr/kstuff.elf'
        self.fx.items[-1]['filename'] = 'kstuff1.13-fpkg-dr-test8-restmode.elf'
        self.assertEqual(self.run_updater().returncode, 0)
        self.assertEqual(self.fx.loads[1][1], elf('private-manual-kstuff'))
        self.fx.loads.clear()
        other = self.root / 'other-private.elf'
        other.write_bytes(elf('another-private-kstuff'))
        self.fx.items.append(dict(kind='local', slot='local/kstuff-other', path=str(other),
                                  filename='kstuff1.13-fpkg-dr-test8-rest-fast.elf'))
        r = self.run_updater(boot='second')
        self.assertEqual(r.returncode, 0)
        self.assertIn('Several local kstuff builds', r.stdout)
        self.assertEqual(len(self.fx.loads), 7)

    def test_legacy_defaults_migrate_without_losing_custom_kstuff_path(self):
        old = ['nanodns','kstuff-local','elfldr','ftpsrv','websrv',
               'shadowmountplus','yt-blocker','hush','dump-forge']
        self.config.update(schema=1, sequence=[dict(id=k, delay_ms=d, enabled=k!='hush')
                           for k,d in zip(old,[1000]*5+[3000,0,0,0])])
        result = self.run_updater()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual([Path(x[0]).stem for x in self.fx.loads],
                         [x.replace('-local','') for x in IDS if x!='hush'])

    def test_v2_defaults_migrate_and_keep_opt_out(self):
        self.config.update(schema=2)
        self.config['sequence'] = [dict(id=k, delay_ms=d, enabled=k!='hush')
                                  for k,d in zip(IDS + ['yt-blocker'], [1000]*7 + [3000,0])]
        result = self.run_updater()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual([Path(x[0]).stem for x in self.fx.loads],
                         [x.replace('-local','') for x in IDS if x!='hush'])

    def test_legacy_custom_order_is_preserved_except_retired_entry(self):
        self.config['schema'] = 2
        self.config['sequence'][-2:] = self.config['sequence'][-2:][::-1]
        self.config['sequence'].insert(3, dict(id='yt-blocker', delay_ms=0, enabled=True))
        result = self.run_updater()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual([Path(x[0]).stem for x in self.fx.loads],
                         [x.replace('-local','') for x in IDS[:-2] + ['dump-forge','hush']])

    def test_retired_entry_does_not_hide_missing_or_duplicate_active_payloads(self):
        original = copy.deepcopy(self.config['sequence'])
        cases = [original[:-1] + [dict(id='yt-blocker', delay_ms=0, enabled=True)],
                 original[:-1] + [original[2]],
                 original + [dict(id='unknown-payload', delay_ms=0, enabled=True)]]
        for steps in cases:
            with self.subTest(steps=steps):
                self.config.update(schema=2, sequence=steps)
                self.assertNotEqual(self.run_updater().returncode, 0)
        self.assertEqual(self.fx.events, [])


class SourceTests(unittest.TestCase):
    def test_default_delays_and_final_dump_forge(self):
        d = defaults.defaults()
        self.assertEqual([x['id'] for x in d['sequence']], IDS)
        self.assertEqual(IDS, ['nanodns','kstuff-local','elfldr','ftpsrv','websrv',
                               'shadowmountplus','hush','dump-forge'])
        self.assertEqual([x['delay_ms'] for x in d['sequence']], [1000]*7 + [0])

    def test_catalog_contains_exactly_public_set(self):
        data = json.loads((PM / 'payloads.json').read_text())
        self.assertEqual([x['id'] for x in data['payloads']], PUBLIC)
        self.assertFalse(any('kstuff' in x['url'].lower() for x in data['payloads']))
        self.assertEqual(next(x['source'] for x in data['payloads'] if x['id']=='ftpsrv'), 'https://github.com/drakmor/ftpsrv')
        for x in data['payloads']:
            self.assertRegex(x['checksum'], r'^[0-9a-f]{64}$')
            self.assertTrue(x['url'].startswith('https://github.com/'))

if __name__ == '__main__':
    unittest.main()
