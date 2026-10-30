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
            path = root / (key + '.elf')
            path.write_bytes(data)
            checksum = hashlib.sha256(data).hexdigest()
            self.items.append({'id': key, 'kind': 'repo', 'slot': 'repo/' + key + '@test',
                               'path': str(path), 'filename': path.name,
                               'source_url': self.source, 'version': 'v1.0.2' if key == 'yt-blocker' else '1',
                               'checksum': checksum})
            self.available.append({'id': key, 'version': 'v1.0.2' if key == 'yt-blocker' else '1',
                                   'checksum': checksum, 'url': 'https://github.com/example/project/releases/download/v1/' + key + '.elf'})
        self.kstuff = root / 'kstuff.elf'
        self.kstuff.write_bytes(elf('private-manual-kstuff'))
        self.items.append({'kind': 'local', 'slot': 'local/kstuff', 'path': str(self.kstuff), 'filename': 'kstuff.elf'})

    def change(self, key):
        item = next(x for x in self.available if x['id'] == key)
        item['version'] = 'v1.0.2' if key == 'yt-blocker' else '2'
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
                        old = {'id': key, 'kind': 'repo', 'slot': 'repo/' + key + '@test',
                               'source_url': fixture.source, 'path': str(fixture.root / (key + '.elf')),
                               'filename': key + '.elf'}
                        fixture.items.append(old)
                    candidate = next(x for x in fixture.available if x['id'] == key)
                    old.update(version=candidate['version'], checksum=candidate['checksum'])
                    Path(old['path']).write_bytes(elf(key + '-new'))
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
        options = ['-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-no-pie'] if os.getenv('PM_SANITIZE') else []
        subprocess.run(['cc', '-DPM_HOST_TEST', '-std=gnu11', '-O1', '-g', '-Wall', '-Wextra', '-Werror',
                        *options, '-I' + str(PM), '-I' + str(PM / 'src'),
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

    def run_updater(self, *, dns='1', closed='1', text=None):
        path = self.root / 'config.json'
        path.write_text(text if text is not None else json.dumps(self.config))
        env = dict(os.environ, PM_CONFIG=str(path), PM_STATE_DIR=str(self.root / 'state'),
                   PM_PORT=str(self.server.server_port), PM_TEST_DNS=dns, PM_TEST_YOUTUBE_CLOSED=closed)
        result = subprocess.run([str(self.binary)], env=env, text=True, capture_output=True, timeout=10)
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
        self.assertEqual(len(self.fx.loads), 9)
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
        self.assertEqual(len(self.fx.loads), 9)
        self.assertFalse(any(e[1].startswith('/repository') or e[1] == '/sources_add' for e in self.fx.events))

    def test_refresh_failures_keep_local(self):
        for mode in ['stale', 'malformed', 'duplicate', 'timeout', 'truncated']:
            with self.subTest(mode=mode):
                self.fx.refresh_mode = mode
                marker = self.root / 'state/started-boot.txt'
                marker.unlink(missing_ok=True)
                self.fx.loads.clear()
                self.fx.change('websrv')
                r = self.run_updater()
                self.assertEqual(r.returncode, 0, r.stdout)
                self.assertEqual(self.fx.installs, [])
                self.assertEqual(len(self.fx.loads), 9)

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
                r = self.run_updater()
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
        self.assertEqual(len(self.fx.loads), 9)

    def test_missing_kstuff_stops_before_network_and_launch(self):
        self.fx.kstuff.unlink()
        r = self.run_updater()
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(self.fx.loads, [])
        self.assertEqual(self.fx.installs, [])

    def test_missing_public_and_offline_stops_before_kernel(self):
        next(Path(x['path']) for x in self.fx.items if x.get('id') == 'websrv').unlink()
        r = self.run_updater(dns='0')
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(len(self.fx.loads), 1)

    def test_does_not_repeat_sequence_same_boot(self):
        self.assertEqual(self.run_updater().returncode, 0)
        self.assertEqual(self.run_updater().returncode, 0)
        self.assertEqual(len(self.fx.loads), 9)

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

    def test_youtube_running_skips_blocker_only(self):
        r = self.run_updater(closed='0')
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertEqual(len(self.fx.loads), 8)
        self.assertFalse(any('yt-blocker' in x[0] for x in self.fx.loads))
        self.assertTrue(any('dump-forge' in x[0] for x in self.fx.loads))

    def test_configured_delays_are_observed(self):
        self.config['sequence'][5]['delay_ms'] = 65
        self.assertEqual(self.run_updater().returncode, 0)
        self.assertGreaterEqual(self.fx.loads[6][2] - self.fx.loads[5][2], .060)

    def test_invalid_config_does_nothing(self):
        for text in ['{', '{"schema":01}', '{"schema":1,"source_url":"\\u0000"}',
                     json.dumps(self.config).replace('"schema": 1', '"schema": 1, "schema": 1'),
                     json.dumps(self.config).replace('"delay_ms": 0', '"delay_ms": -1', 1)]:
            with self.subTest(text=text[:80]):
                r = self.run_updater(text=text)
                self.assertNotEqual(r.returncode, 0)
        self.assertEqual(self.fx.events, [])

    def test_disabled_payload_is_neither_updated_nor_launched(self):
        self.config['sequence'][6]['enabled'] = False
        self.fx.change('yt-blocker')
        r = self.run_updater()
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertNotIn('yt-blocker', self.fx.installs)
        self.assertFalse(any('yt-blocker' in x[0] for x in self.fx.loads))

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

class SourceTests(unittest.TestCase):
    def test_defaults_preserve_existing_delays(self):
        d = defaults.defaults()
        self.assertEqual([x['id'] for x in d['sequence']], IDS)
        self.assertEqual([x['delay_ms'] for x in d['sequence']], [1000,1000,1000,1000,1000,3000,0,0,0])
        self.assertEqual(sum(x['delay_ms'] for x in d['sequence']), 8000)

    def test_catalog_contains_exactly_public_set_and_pins(self):
        data = json.loads((PM / 'payloads.json').read_text())
        self.assertEqual([x['id'] for x in data['payloads']], PUBLIC)
        self.assertFalse(any('kstuff' in x['url'].lower() for x in data['payloads']))
        self.assertEqual(next(x['version'] for x in data['payloads'] if x['id']=='yt-blocker'), 'v1.0.2')
        for x in data['payloads']:
            self.assertRegex(x['checksum'], r'^[0-9a-f]{64}$')
            self.assertTrue(x['url'].startswith('https://github.com/'))

if __name__ == '__main__':
    unittest.main()
