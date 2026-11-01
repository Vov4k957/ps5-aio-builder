"""Regression checks for PM's release rules, independently of AIO profiles."""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

PM = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('pm_catalog', PM / 'generate_catalog.py')
catalog = importlib.util.module_from_spec(spec)
spec.loader.exec_module(catalog)


def release(repo, version, name, date):
    return {'tag_name': version, 'draft': False, 'published_at': date,
            'assets': [{'name': name, 'size': 256, 'digest': 'sha256:' + 'a'*64,
                        'browser_download_url': f'https://github.com/{repo}/releases/download/{version}/{name}'}]}


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.config = json.loads((PM.parent / 'config/payloads.json').read_text())

    def test_retired_payload_is_absent_from_all_catalogs_and_profiles(self):
        self.assertNotIn('yt-blocker', catalog.PUBLIC_IDS)
        self.assertNotIn('yt-blocker', self.config['payloads'])
        for profile in self.config['profiles'].values():
            self.assertNotIn('yt-blocker', profile)
        retired_source = json.loads((PM.parent/'pm-sources/yt-blocker.json').read_text())
        self.assertEqual(retired_source['payloads'], [])
        with tempfile.TemporaryDirectory() as tmp, self.assertRaises(ValueError):
            catalog.entry('yt-blocker', {'kind': 'github'}, [], Path(tmp))

    def test_drakmor_stable_and_ps5_asset_only(self):
        cfg = catalog.pm_source('ftpsrv', self.config)
        stable = release(cfg['repo'], '1.16-ng-stable', 'ftpsrv-ps5.elf', '2026-10-20')
        stable['assets'] += release(cfg['repo'], '1.16-ng-stable', 'ftpsrv-ps4.elf', '2026-10-20')['assets']
        beta = release(cfg['repo'], '1.17-ng-test1', 'ftpsrv-ps5.elf', '2026-10-21')
        with tempfile.TemporaryDirectory() as tmp:
            item = catalog.entry('ftpsrv', cfg, [beta, stable], Path(tmp))
        self.assertEqual(item['version'], '1.16-ng-stable')
        self.assertEqual(item['filename'], 'ftpsrv-ps5.elf')
        self.assertTrue(catalog.can_reuse(item, cfg))
        self.assertFalse(catalog.can_reuse(dict(item, url=item['url'].replace('drakmor/', 'ps5-payload-dev/')), cfg))


if __name__ == '__main__':
    unittest.main()
