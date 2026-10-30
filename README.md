# PS5 AIO Builder

[Русская инструкция](README_RU.md)

Configurable PS5 all-in-one ELF builder that bundles selected release ELF files and sequentially sends them to an already-running local ELF loader at `127.0.0.1:9021`.

**Status:** experimental. Built for testing on firmware 13.60, but no compatibility or FPKG functionality is guaranteed. A successful build does not imply a working payload on the console.

## Features

- Automatically download the newest available published release (including prereleases) of each configured GitHub repository.
- Use exact file name matching to select ELF64 x86-64 assets.
- Select payload profiles, order and per-payload delays in [config/payloads.json](config/payloads.json).
- Produce version, source, byte count and SHA-256 manifest alongside the resulting ELF and ZIP.
- GitHub Actions can run public-source profiles, manually or nightly; resulting build artifacts are **not private** in this public repository.
- Discord-only/manual ELF files are **local-only**. Never upload restricted binaries to this public repository or its workflow artifacts.

## Start a cloud build

Go to **Actions → Build PS5 AIO → Run workflow**, choose `standard`, `extended`, or `zftpd`. Download the output from the run's Artifacts.

## Local build, including your manually sourced ELF

Install [PS5 Payload SDK](https://github.com/ps5-payload-dev/sdk), set `PS5_PAYLOAD_SDK`, and run:

```bash
python3 -m unittest discover -s tests -v
python3 scripts/build.py --profile standard
# Or, after placing your own authorized kstuff file into manual/
python3 scripts/build.py --profile fpkg13
```

The `fpkg13` profile expects `manual/kstuff1.13-fpkg-dr-test8-restmode.elf` and intentionally fails if it is absent; it never substitutes a different kstuff version.

## Notes

- This is an ELF orchestration tool, **not** a jailbreak or a replacement for Y2JB.
- The local ELF loader must already be running on the PS5.
- Loading a new upstream prerelease can break older workflows; inspect the manifest before running.
- Third-party payloads are downloaded from the authors' release pages; this repository does not relicense them or bundle them in the source tree.
- [Reference analysis](docs/REFERENCE.md) describes the user-supplied AIO ELF whose behavior informed this implementation.

This repository is open-source under MIT for the builder's own code only.
