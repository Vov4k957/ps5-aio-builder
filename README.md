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

## Standard/fpkg13 payload order (9 payloads)

`kstuff → elfldr → ftpsrv → nanoDNS → websrv → ShadowMountPlus → [3000 ms] → YT Blocker v1.0.2 → [0 ms] → Hush → [0 ms] → Dump Forge`. Earlier gaps remain 1000 ms. Delays are applied **after transmission**, not after process initialization. The 3-second delay only affects standard/fpkg13 through `profile_delays`; other profiles are unchanged. YT Blocker is pinned to exactly v1.0.2; Hush and Dump Forge track latest releases.

**CAUTION:** YT Blocker's maintainer explicitly says to **close YouTube before running**, since it modifies system databases and application metadata. Loading this AIO through Y2JB while YouTube is still running may conflict with those requirements. Back up metadata, and do not enable this profile for automatic console startup before testing safe sequencing.

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

The `fpkg13` profile enforces the supplied ELF's exact SHA-256 and expects `manual/kstuff1.13-fpkg-dr-test8-rest-fast.elf` and intentionally fails if it is absent; it never substitutes a different kstuff version.

## Notes

- This is an ELF orchestration tool, **not** a jailbreak or a replacement for Y2JB.
- The local ELF loader must already be running on the PS5.
- Loading a new upstream prerelease can break older workflows; inspect the manifest before running.
- Third-party payloads are downloaded from the authors' release pages; this repository does not relicense them or bundle them in the source tree.
- [Reference analysis](docs/REFERENCE.md) describes the user-supplied AIO ELF whose behavior informed this implementation.

This repository is open-source under MIT for the builder's own code only.
