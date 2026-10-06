# Native GUI CI validation

Validated against PR 7's original head `50dbd9e`, using exact base commit `8e8f54c` and the CI-pinned Ruff 0.15.13.

## New failures fixed

- Original full Ruff result: base 2265 findings, PR 2317 findings. All 52 additional findings were in the new bridge/test sources.
- Bridge sources now have standard formatting, imports, documentation and annotations. Their source directory is `scripts/chatgpt_native` (a valid Python package); installed runtime paths and network behavior are unchanged.
- Authorization checks are now collected pytest regressions, rather than a script that executes at import. Eight tests cover active admin, missing/expired session, deleted/inactive/non-admin user, revoked role and the existing empty YAML configuration.
- Manifest declares the imported HTTP integration and documentation/issue tracker URLs. CONFIG_SCHEMA uses HA's empty-config helper for the existing `chatgpt_native: {}` package.

## Evidence

- Targeted Ruff check: passed. Targeted format check: five files already formatted.
- Full fixed-head Ruff: 2265 findings. A multiset comparison of file/line/column/code/message against the base gives zero added findings and zero removed baseline findings.
- Full format check: base 36 files would be reformatted / 72 already formatted; fixed head 36 would be reformatted / 77 already formatted. No formatting debt was introduced.
- `pytest -q tests/chatgpt_native`: 8 passed.
- Official `ghcr.io/home-assistant/hassfest`, limited to 1 CPU and 1 GiB RAM: 5 integrations, 0 invalid integrations, exit 0.
- `git diff --check`: passed. Normal commit hooks and GitHub CI remain enabled.

## Baseline blockers remain

The full lint workflow is not green because the base already contains 2265 Ruff findings across unrelated integrations/scripts/tests and 36 files requiring formatting. They were not edited or hidden with ignores/skips.

HACS also checks repository topics. The repository has no topics. Historical main validation run 36402232060 (2026-09-28, commit 28b09d9) already failed solely on topics. New manifest failures are fixed, but repository topics are unchanged.

Original failures: Lint run 37442063728; Validate run 37442063780. Current CI results must be read after this commit is pushed; this document does not claim the entire PR is green.

## Runtime and review scope

No active HA files, GUI profile, user service or deployed bridge were changed for this CI cleanup. The manifest/schema diff is available in the draft PR; a live rollout of those changes has not been performed. Empty-config acceptance is tested. No auth/proxy/port logic was changed. Existing GUI, HA and old Chrome container remain running.
