# Shared Ubuntu desktop verification — 2026-10-06

Draft extension of native GUI PR 7, based on `a1fe242`. Not deployed. No merge, HA reload, user-service restart, SSH/policy change or credential/password operation was performed.

## Changes

- Retains ChatGPT Native panel/window/profile; adds Ubuntu Desktop administrator panel at `/ubuntu-desktop` through the same protected API/VNC stream. Both panels share windows and visibly disclose that fact.
- Adds official Ubuntu Openbox, tint2, xterm and wmctrl from user-side extracted packages; uses installed Nautilus. Terminal/Files/ChatGPT launcher and task switcher operate on the virtual display, not physical GNOME/Wayland.
- Private D-Bus application activation keeps Files on the virtual display. Existing user runtime/keyring/application configs remain; Openbox-only configuration is restored before launching apps from its menus.
- Controls-only mode adds window manager/taskbar around an existing ChatGPT; it does not start or terminate ChatGPT. Future natural service starts use the reviewed full-session script. No additional listener or service is introduced.

## Isolated evidence

An authenticated Xvfb :119 with TCP disabled was used. The live :109 screen, live ChatGPT PID 87895, bridge PID 87894 and VNC PID 87893 were preserved. Before/after controls-only activation, isolated ChatGPT remained PID 226653, X11 window `0x00600003`. Launcher clicks opened a real xterm and Nautilus Home window; ChatGPT launcher focused the existing window. Actual pixels were captured at 1280×900, with desktop taskbar plus Terminal/Files/ChatGPT and ChatGPT-focused view. Screenshots contain user context and are retained privately for review, not committed to this public repository.

A new isolated-runtime experiment raised a keyring creation dialog. No password was entered and no new keyring was created by this task. That configuration was rejected; the final script retains the existing runtime/keyring and was visually tested without that prompt. Changing global XDG_CONFIG_HOME was also rejected in review; two failing then passing launcher regressions verify restoration of original app config.

## Checks

- `pytest -q tests/chatgpt_native`: **28 passed**, 6 warnings (HA/backoff deprecations and the test harness's HA request storage key).
- New panel-registration test fails on original base and passes on this branch. Launcher config restoration tests likewise fail before the fix and pass after it.
- Real loopback-only aiohttp WebSocket test verifies binary relay and connection closure after admin role revocation; only test recheck timing is accelerated, production code stays at 30 seconds.
- Assets and WebSocket reject missing/expired/nonadmin/inactive sessions before accessing upstream. Additional checks cover deleted/revoked admin, session user mismatch, scoped HttpOnly/Strict cookie, path traversal and rejection of non-HA bridge peers despite spoofed forwarding headers.
- Node panel rendering test passes for both elements, same existing protected API and explicit shared-session notice. No real account or authorization is changed by tests.
- Targeted Ruff 0.15.13 check/format passes; shell syntax and git whitespace checks pass. Secret-scanning commit hook passed.
- Full Ruff has **2265 existing findings**. Compared with PR 7's fixed baseline: **zero added and zero removed findings**.
- Bare full pytest was attempted: **55 collection errors**, due to absent test dependencies and unpopulated existing submodules in this isolated local clone. Missing modules include pytest_homeassistant_custom_component, existing home_generative_agent modules, langchain_ollama/langchain_core and u1_print_inspector. The complete suite is not claimed green; no unrelated files were edited or errors hidden.
- Read-only host checks confirm existing listeners remain 127.0.0.1/[::1]:5901 and 172.20.0.1:6081; native user service remains active, main PID 87884. No new VNC/HTTP listener was started for desktop testing.

## Review and remaining acceptance

Separate code review found and then confirmed the application-config preservation fix. Follow-up review reported no remaining critical/important findings and confirmed controls-only cleanup is restricted to its own Openbox/tint2 processes. Deployment lifetime and desktop-only rollback are documented in `native-chatgpt-ha.md`.

Live HA/phone testing of `/ubuntu-desktop` remains pending explicit acceptance of this draft PR and private screenshots. The panel is not advertised as already available. It is a virtual application desktop with a shared screen, not a physical GNOME mirror or an independent simultaneous view of ChatGPT.
