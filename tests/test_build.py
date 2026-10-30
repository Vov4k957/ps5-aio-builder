import json
import tempfile
import unittest
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import build


class BuildTests(unittest.TestCase):
    def test_profiles_and_sources(self):
        cfg = json.loads((build.ROOT / "config/payloads.json").read_text())
        build.validate_config(cfg)
        self.assertEqual(len(cfg["profiles"]["standard"]), 6)
        self.assertEqual(cfg["profiles"]["fpkg13"][0], "kstuff-fpkg-manual")

    def test_latest_prerelease_and_exact_asset(self):
        versions = [
            {"tag_name":"v1", "published_at":"2026-01-01T00:00:00Z",
             "prerelease":False, "assets":[{"name":"app-ps5.elf"}]},
            {"tag_name":"v2-beta", "published_at":"2026-02-01T00:00:00Z",
             "prerelease":True, "assets":[{"name":"app-ps5.elf"},{"name":"app-ps4.elf"}]}
        ]
        rel, asset = build.select_asset(versions, r"^app-ps5\.elf$", True)
        self.assertEqual((rel["tag_name"],asset["name"]), ("v2-beta","app-ps5.elf"))
        rel, _ = build.select_asset(versions, r"^app-ps5\.elf$", False)
        self.assertEqual(rel["tag_name"], "v1")

    def test_missing_latest_asset_fails(self):
        versions = [
            {"tag_name":"v2","published_at":"2026-02-01","assets":[{"name":"bad.zip"}]},
            {"tag_name":"v1","published_at":"2026-01-01","assets":[{"name":"test.elf"}]}
        ]
        with self.assertRaises(build.BuildError):
            build.select_asset(versions, r"^test\.elf$")

    def test_elf_validation_and_generated_files(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path / "build").mkdir()
            elf = path / "test.elf"
            data = bytearray(64)
            data[:6] = b"\x7fELF\x02\x01"
            data[18:20] = b"\x3e\x00"
            elf.write_bytes(data)
            self.assertEqual(build.validate_elf(elf), 64)
            build.generate_sources([{"filename":"test.elf","name":"Test",
                                     "delay_ms":100}], path / "build")
            self.assertIn('.incbin "build/payloads/test.elf"',
                          (path / "build/embedded.S").read_text())
            elf.write_bytes(b"not an elf")
            with self.assertRaises(build.BuildError):
                build.validate_elf(elf)

    def test_manual_elf(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)
            (path/"manual").mkdir()
            (path/"cache").mkdir()
            cfg={"kind":"manual","name":"Test","manual_filename":"custom.elf"}
            with self.assertRaisesRegex(build.BuildError, "not found"):
                build.resolve_payload("manual-test",cfg,"public/repo",None,
                                      path/"manual",path/"cache")
            data=bytearray(64)
            data[:6]=b"\x7fELF\x02\x01"
            data[18:20]=b"\x3e\x00"
            (path/"manual/custom.elf").write_bytes(data)
            result=build.resolve_payload("manual-test",cfg,"",None,
                                         path/"manual",path/"cache")
            self.assertEqual(result["origin"]["kind"],"local")


if __name__ == "__main__":
    unittest.main()
