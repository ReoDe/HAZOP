---
name: verify-hazop
description: Drive the real HAZOP desktop app (PySide6 + QtWebEngine, Windows) the way a user does, with keyboard and mouse, and capture evidence. Use to prove a UI change works in the running app, to measure keyboard/mouse convenience (clicks, keys, KLM time, latency, focus, accessibility names, clipping), or to rerun the S1~S6 user scenarios.
---

# Verify HAZOP as a user

Human usage doc and metric definitions: `docs/2026-11-07-user-scenario-check/README.md`. Read it once.

## Launch

One command prepares a temp work root, launches the app, runs the scenarios, writes the report and cleans up:

```
%USERPROFILE%\.hazop\venv-py312\Scripts\python.exe scripts/check_user_scenarios.py --out <dir> [--only S1,S3] [--keep-temp]
```

- Preparation runs offscreen in a subprocess (`--_prepare`): copies `출력/추출|그래프/SNP-M-102`, `출력/지식그래프`, `참고자료/`, confirms study nodes, fills ⑤ with the fake AI client from `scripts/shoot_results.py`. No network.
- The app under test is `check_user_scenarios.py --_app <settings>`: the same `MainWindow` as `run_app.py` with ⑤'s AI client swapped for a slow fake (`AI_DELAY` seconds per call). Never point a scenario at the real API.
- S15 switches the AI connection to Claude subscription, runs ⑤ through the fake CLI (`tests/fake_claude_flow.py`, injected only inside `--_app`), cancels mid-run and closes the window with "기다렸다 닫기". It closes the app, so it runs last.
- Launch sets `HAZOP_WORK_ROOT`, `HAZOP_STORE_ROOT` (temp), `QTWEBENGINE_REMOTE_DEBUGGING=127.0.0.1:9339`, `--settings <temp>/settings.json` with a reviewer name (so no startup dialog).
- Ready means the UIA window `HAZOP 분석 도구` (class `MainWindow`) exists for the launcher pid or its child. The venv `python.exe` spawns the real interpreter as a child, so never match windows by the launcher pid alone.

## Doctor

- `git status --short`. Other sessions edit this folder. If `hazop/` is mid-edit and does not import, test a commit in a detached worktree instead (see the doc).
- Is anyone else driving the desktop? Look for other `run_app.py` processes: `Get-CimInstance Win32_Process -Filter "Name like 'python%'" | ? CommandLine -like '*run_app.py*'`. If another agent's instance is open, do not run. Inputs go to the foreground window.
- Port 9339 free (the script refuses otherwise).

## Drive

- Widgets: `scripts/uia_server.ps1` (stdin/stdout JSON lines: `windows`, `tree`, `children`, `focus`). Stable handles are UIA AutomationIds, which Qt builds from objectName chains, for example `...header.where` (current location text), `...header.cmdbox`, `...rail.step` CheckBoxes named `① 자료 등록`…`⑤ 분석 결과`, `...explorer_filter`, `...matrix` (⑤), `palette_list`, `rel_list`, `_SegList` (④ node list, items are checkable, Space toggles).
- Webview (②③④): CDP `Runtime.evaluate` over the stdlib WebSocket client in the script. There is no page on ①.
- Input: Win32 `keybd_event`/`SendInput`/`SetCursorPos`. Text goes as Unicode events (IME-independent). The Hangul/English mode is set with `WM_IME_CONTROL` to `ImmGetDefaultIMEWnd`. An injected `VK_HANGUL` does nothing.
- Every input goes through `Driver._guard`: the foreground pid must be the app or its child, else it flashes the window and waits `--focus-wait` seconds for a human click, then aborts the scenario.
- Add a scenario as a function `sN_name(d)` in `SCENARIOS`, using `d.step`, `d.key`, `d.type`, `d.click`, `d.wait`, `d.expect`, `d.shot`, `d.audit`. Verify side effects from saved files (`d.entry_counts()` reads `work/데이터/분석결과`), not just the screen.

## Evidence

`<out>/report.html` (scenario table, defects by severity with repro steps and screenshot, screen audit, KLM sources), `<out>/results.json`, `<out>/shots/`. These survive cleanup. A defect from a failed `expect` is a claim about the app only after you check its screenshot. Harness misses look the same.

## Cleanup

The script kills only the process tree it launched (`taskkill /T /PID <launcher>`) and deletes the temp root unless `--keep-temp`. Never kill other `run_app.py` processes: they belong to the user or other sessions. Remove any detached worktree you created with `git worktree remove`.

## Feature map

See `features/README.md`.
