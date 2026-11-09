# HAZOP user-facing features

Each row is a scenario in `scripts/check_user_scenarios.py`. The end state is what proves it works.

| Feature | Reach it | Scenario | Proof |
| --- | --- | --- | --- |
| Stage navigation | Ctrl+1~5, rail, Alt+←/→ | S1 | `header.where` starts with ①~⑤ |
| Shortcut table | F1 or ? | S1 | text `Ctrl+1 ~ Ctrl+5` in the dialog |
| Command palette | Ctrl+P, `@` component, `#` node, `>` command | S2, S6 | `palette_list` items, then `header.where` changes on Enter |
| Related panel | Ctrl+Alt+B, right pane on ⑤ | S2 | `rel_list` items, double-click moves to another stage |
| ⑤ review keys | J next unreviewed, A approve, R reject, Ctrl+Z undo | S3, S4 | entry `status` counts in `work/데이터/분석결과/**.json` |
| ① register + extract | "파일 선택…", file dialog, "등록", "추출·그래프 만들기" | S5 | ② webview has an svg and shows the registered drawing number |
| Long AI run feedback | ⑤ palette `>실패 칸 다시 실행` (fake client, 4 s per call) | S7 | progress text samples, results file re-saved per call |
| Operating during a run | explorer Sx click, Ctrl+P, Ctrl+4 then Ctrl+5 while running | S8 | stage unchanged, progress still shown, entry counts not lower |
| ④ selection highlight | click `_SegList` rows | S9 | CDP count of `.selected`-style vs all drawing elements |
| Explorer structure | ⑤ explorer groups | S10 | '자료' count > 0 when a drawing is open, a path to results |
| Explorer per stage | Ctrl+1~5 | S14 | explorer title starts with the current ①~⑤, only that stage's groups (`STAGE_GROUPS`) are listed |
| Cross-drawing node | ④ click a `⇄` row in `_SegList`, then the `… 에서 계속` chip, then Ctrl+5 | S11 | row name has `[101 → 102]`, panel shows `시작:`·`끝:`, `이 도면 N / 전체 M` and both coverages, chip opens the other drawing with the same node selected (CDP `SEL_JS`), ⑤ row name keeps the range |
| ③ knowledge graph | Ctrl+3, type in `태그·이름으로 찾기`, Ctrl+A Backspace, hover a node, click it, `로컬` button | S13 | `hzKG.state()`: `matches` > 0 then 0, `hover` set and non-neighbours fade (canvas alpha), `sel.id` set, `mode` local with fewer visible nodes, no `errors` |
| ⑤ Excel export | palette `>Excel`, Enter in the scope dialog, type a path in the native save dialog | S12 | xlsx exists, worksheet scenario rows = saved entries, toast buttons `열기`·`폴더 열기` |
| ④ node merge + confirm | palette `>확정 해제`, Space on `_SegList` items, M, Ctrl+Enter | S6 | `_SegList` item count drops, confirm text appears |

## Gotchas

- Screen shortcuts (J, A, R, M) use `WidgetWithChildrenShortcut`. They only fire when focus is inside that screen. After Ctrl+5, focus may stay in the explorer.
- ② PDF "unconfirmed items" editing has no scenario yet. It needs webview clicks located through CDP.
- S5 and S6 change saved data. Keep them last.
