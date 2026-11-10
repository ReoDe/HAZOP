"""이름 이전 도구(scripts/migrate_names.py) 시험. 실행: python -m unittest tests.test_migrate_names

대응표의 이름은 HZ-GOV-02 §5.4에서 실제로 옮기는 것들이다.
"""

import csv
import os
import subprocess
import sys
import tempfile
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))

import migrate_names as mn  # noqa: E402

ROWS = [
    mn.Row("2", "docs/screenshots-pdf", "docs/2026-11-07-screenshots-pdf"),
    mn.Row("2", "docs/2026-11-05-packaging/evidence/w3-경로.md", "docs/2026-11-05-packaging/evidence/w3-paths.md"),
    mn.Row("2", "docs/2026-11-09-symbol-library/그림/범례", "docs/2026-11-09-symbol-library/figures/legend"),
    mn.Row("2", "docs/2026-11-09-symbol-library/범례항목.csv", "docs/2026-11-09-symbol-library/legend-items.csv"),
    mn.Row("3", "flow chart", "specs/flows"),
    mn.Row("3", "기획서/인터페이스.md", "specs/interface.md"),
]
AFTER = {
    "docs/2026-11-07-screenshots-pdf/a.png", "docs/2026-11-05-packaging/evidence/w3-paths.md",
    "docs/2026-11-05-packaging/README.md", "docs/2026-11-09-symbol-library/figures/legend/L1-001.png",
    "docs/2026-11-09-symbol-library/legend-items.csv", "specs/flows/00-overview.md", "specs/interface.md", "README.md",
    "메모리/결정로그.md",
}


def exists(path):
    return path in AFTER or any(p.startswith(path + "/") for p in AFTER)


def rewrite(doc, text):
    return mn.rewrite_text(doc, text, ROWS, exists)


def link_spans(doc, text):
    return [(r.line, r.start, r.end) for r in mn.rules.doc_refs(doc, text) if r.kind == "link"]


def link_targets(doc, text):
    lines = text.splitlines()
    return [lines[no - 1][s:e] for no, s, e in link_spans(doc, text)]


def without_link_targets(doc, text):
    lines = text.splitlines()
    for no, s, e in sorted(link_spans(doc, text), reverse=True):
        lines[no - 1] = lines[no - 1][:s] + lines[no - 1][e:]
    return lines


class RewriteText(unittest.TestCase):
    def test_relative_link(self):
        new, changes = rewrite("메모리/결정로그.md", "근거는 [경로 조사](../docs/2026-11-05-packaging/evidence/w3-경로.md#3-결과)다.\n")
        self.assertEqual("근거는 [경로 조사](../docs/2026-11-05-packaging/evidence/w3-paths.md#3-결과)다.\n", new)
        self.assertEqual([("메모리/결정로그.md", 1, "link", "../docs/2026-11-05-packaging/evidence/w3-경로.md#3-결과",
                           "../docs/2026-11-05-packaging/evidence/w3-paths.md#3-결과")], changes)

    def test_link_with_space_and_title(self):
        new, _ = rewrite("README.md", '[흐름](flow chart/00-overview.md) [흐름](<flow chart/00-overview.md> "제목")\n')
        self.assertEqual('[흐름](specs/flows/00-overview.md) [흐름](<specs/flows/00-overview.md> "제목")\n', new)

    def test_backtick_path_with_a_space_in_the_old_name(self):
        new, changes = rewrite("README.md", "흐름도는 `flow chart/`의 `flow chart/00-overview.md`, `../flow chart/00-overview.md`다. `flow` `chart`\n")
        self.assertEqual("흐름도는 `specs/flows/`의 `specs/flows/00-overview.md`, `../flow chart/00-overview.md`다. `flow` `chart`\n", new)
        self.assertEqual(["code"] * 2, [c[2] for c in changes])

    def test_backtick_repo_path_inside_a_moved_folder(self):
        """옮긴 폴더 안의 문서가 저장소 기준 경로를 적으면, 문서 폴더 기준으로 잘못 풀지 않고 저장소 기준으로 푼다."""
        new, _ = rewrite("docs/2026-11-07-screenshots-pdf/README.md",
                         "`docs/screenshots-pdf/`와 `docs/screenshots-pdf/지운그림.png`, `docs/screenshots-pdf/*.png`\n")
        self.assertEqual("`docs/2026-11-07-screenshots-pdf/`와 `docs/2026-11-07-screenshots-pdf/지운그림.png`, "
                         "`docs/2026-11-07-screenshots-pdf/*.png`\n", new)

    def test_word_that_equals_a_folder_name_is_not_a_path(self):
        rows = ROWS + [mn.Row("3d", "기획서", "specs")]
        text = "[기획서](기획서/인터페이스.md)의 `기획서` 폴더, `기획서/` 아래\n"
        new, _ = mn.rewrite_text("README.md", text, rows, exists)
        self.assertEqual("[기획서](specs/interface.md)의 `기획서` 폴더, `specs/` 아래\n", new)

    def test_urls_and_unmoved_siblings_inside_a_moved_folder_are_left_alone(self):
        text = "`https://example.com/a/`와 `file://`, `ws(s)://`, 같은 폴더의 `a.png`와 `./a.png`\n"
        new, changes = rewrite("docs/2026-11-07-screenshots-pdf/README.md", text)
        self.assertEqual(text, new)
        self.assertEqual([], changes)

    def test_backtick_repo_path_and_folder_prefix(self):
        text = ("그림은 `docs/screenshots-pdf/`와 `docs/2026-11-09-symbol-library/그림/범례/L1-001.png`에 있고 "
                "`python scripts/x.py docs/2026-11-09-symbol-library/범례항목.csv`로 만든다.\n")
        new, changes = rewrite("README.md", text)
        self.assertEqual("그림은 `docs/2026-11-07-screenshots-pdf/`와 `docs/2026-11-09-symbol-library/figures/legend/L1-001.png`에 있고 "
                         "`python scripts/x.py docs/2026-11-09-symbol-library/legend-items.csv`로 만든다.\n", new)
        self.assertEqual(["code"] * 3, [c[2] for c in changes])

    def test_backtick_path_relative_to_the_document(self):
        new, _ = rewrite("docs/2026-11-05-packaging/README.md", "자세한 것은 `evidence/w3-경로.md`를 본다.\n")
        self.assertEqual("자세한 것은 `evidence/w3-paths.md`를 본다.\n", new)

    def test_link_text_that_repeats_the_target(self):
        new, changes = rewrite("docs/2026-11-05-packaging/README.md",
                               "[evidence/w3-경로.md](evidence/w3-경로.md#절) [w3-경로.md](evidence/w3-경로.md) [경로 조사](evidence/w3-경로.md)\n")
        self.assertEqual("[evidence/w3-paths.md](evidence/w3-paths.md#절) [w3-paths.md](evidence/w3-paths.md) [경로 조사](evidence/w3-paths.md)\n", new)
        self.assertEqual(["link-text", "link", "link-text", "link", "link"], [c[2] for c in changes])

    def test_backtick_line_number_and_workspace_relative_and_bare_name(self):
        new, _ = rewrite("docs/2026-11-05-packaging/evidence/w3-paths.md",
                         "`docs/2026-11-05-packaging/evidence/w3-경로.md:25`, `evidence/w3-경로.md` §8, `w3-경로.md:24-68`.\n")
        self.assertEqual("`docs/2026-11-05-packaging/evidence/w3-paths.md:25`, `evidence/w3-paths.md` §8, `w3-paths.md:24-68`.\n", new)
        new, _ = rewrite("README.md", "이름을 붙였다(`범례항목.csv`). `README.md`와 `없는이름.csv`는 그대로다.\n")
        self.assertEqual("이름을 붙였다(`legend-items.csv`). `README.md`와 `없는이름.csv`는 그대로다.\n", new)

    def test_body_sentences_and_fences_stay(self):
        text = ("2026-11-07 docs/screenshots-pdf/ 아래에 그림을 두기로 했다. w3-경로.md 참고.\n"
                "```\npython scripts/x.py docs/screenshots-pdf\n```\n"
                "이름이 비슷한 `docs/screenshots-pdf-old/`와 `mydocs/screenshots-pdf`는 다른 폴더다.\n")
        self.assertEqual((text, []), rewrite("메모리/결정로그.md", text))

    def test_record_documents_change_link_targets_only(self):
        """기록 문서에 적힌 옛 이름은 그 시점의 기록이다(§6.9). 링크 대상을 지운 글이 고치기 전과 같아야 한다."""
        text = ("| DEC-0243 | `flow chart/`→`specs/flows/`로 옮긴다. `기획서/인터페이스.md`를 썼다 | "
                "[기획서/인터페이스.md](../기획서/인터페이스.md#절) [w3-경로.md](../docs/2026-11-05-packaging/evidence/w3-경로.md) |\n"
                "- `docs/screenshots-pdf/a.png`는 [그림](../docs/screenshots-pdf/a.png)이다.\n")
        for doc in ("records/decision-log.md", "records/backlog.md", "메모리/결정로그.md", "메모리/남은작업.md"):
            new, changes = rewrite(doc, text)
            self.assertEqual(["link"] * 3, [c[2] for c in changes], doc)
            self.assertEqual(["../specs/interface.md#절", "../docs/2026-11-05-packaging/evidence/w3-paths.md",
                              "../docs/2026-11-07-screenshots-pdf/a.png"], link_targets(doc, new), doc)
            self.assertEqual(without_link_targets(doc, text), without_link_targets(doc, new), doc)

    def test_line_that_already_names_the_new_path_is_left_alone(self):
        """옮긴 일을 적은 줄에서 옛 이름을 바꾸면 `새`→`새`가 되어 뜻이 사라진다."""
        text = "`docs/screenshots-pdf/`→`docs/2026-11-07-screenshots-pdf/`, 그림은 [여기](docs/screenshots-pdf/a.png)\n"
        new, changes = rewrite("README.md", text)
        self.assertEqual("`docs/screenshots-pdf/`→`docs/2026-11-07-screenshots-pdf/`, 그림은 [여기](docs/2026-11-07-screenshots-pdf/a.png)\n", new)
        self.assertEqual(["link"], [c[2] for c in changes])
        other = "`docs/screenshots-pdf/a.png`와 `docs/2026-11-07-screenshots-pdf/`\n"
        self.assertEqual("`docs/2026-11-07-screenshots-pdf/a.png`와 `docs/2026-11-07-screenshots-pdf/`\n", rewrite("README.md", other)[0])

    def test_quote_that_holds_backticks_is_left_alone(self):
        text = "임시 문서에 `` `docs/screenshots-pdf/a.png` ``를 적고 검사를 돌렸다.\n"
        self.assertEqual((text, []), rewrite("docs/2026-11-05-packaging/README.md", text))

    def test_moved_document_keeps_its_links_working(self):
        new, _ = rewrite("specs/flows/00-overview.md", "[인터페이스](../기획서/인터페이스.md) [의도](../README.md)\n")
        self.assertEqual("[인터페이스](../interface.md) [의도](../../README.md)\n", new)

    def test_html_href_and_code(self):
        text = '<a href="../screenshots-pdf/a.png">그림</a> <code>docs/screenshots-pdf</code>\n'
        new, changes = rewrite("docs/2026-11-05-packaging/README.html", text)
        self.assertEqual('<a href="../2026-11-07-screenshots-pdf/a.png">그림</a> <code>docs/2026-11-07-screenshots-pdf</code>\n', new)
        self.assertEqual(["link", "code"], [c[2] for c in changes])

    def test_second_run_changes_nothing(self):
        text = ("[경로](evidence/w3-경로.md) `evidence/w3-경로.md` `docs/screenshots-pdf/a.png` "
                "[흐름](../../flow chart/00-overview.md)\n")
        once, changes = rewrite("docs/2026-11-05-packaging/README.md", text)
        self.assertEqual(4, len(changes))
        self.assertEqual((once, []), rewrite("docs/2026-11-05-packaging/README.md", once))
        moved = "[인터페이스](../기획서/인터페이스.md) [의도](../README.md)\n"
        once, _ = rewrite("specs/flows/00-overview.md", moved)
        self.assertEqual((once, []), rewrite("specs/flows/00-overview.md", once))

    def test_link_text_is_fixed_even_when_the_target_was_already_rewritten(self):
        new, changes = rewrite("docs/2026-11-05-packaging/README.md", "[w3-경로.md](evidence/w3-paths.md) [경로](evidence/w3-paths.md)\n")
        self.assertEqual("[w3-paths.md](evidence/w3-paths.md) [경로](evidence/w3-paths.md)\n", new)
        self.assertEqual(["link-text"], [c[2] for c in changes])

    def test_folder_name_alone_is_not_a_path(self):
        text = "`도면`과 `범례`를 나눠 담는다.\n"
        self.assertEqual((text, []), rewrite(".claude/skills/verify-hazop/features/README.md", text))

    def test_lines_that_quote_an_old_name_on_purpose_stay(self):
        text = "예: `docs/screenshots-pdf`에서 실패함을 보인다.\n다음 줄 `docs/screenshots-pdf`\n"
        new, changes = mn.rewrite_text("a.md", text, ROWS, exists, keep_lines=(("a.md", "실패함을 보인다"),))
        self.assertEqual("예: `docs/screenshots-pdf`에서 실패함을 보인다.\n다음 줄 `docs/2026-11-07-screenshots-pdf`\n", new)
        self.assertEqual(1, len(changes))

    def test_line_endings_are_kept(self):
        new, _ = rewrite("README.md", "`docs/screenshots-pdf`\r\n끝\r\n")
        self.assertEqual("`docs/2026-11-07-screenshots-pdf`\r\n끝\r\n", new)


class MapFile(unittest.TestCase):
    def check(self, rows):
        return mn.map_problems([mn.Row(*r) for r in rows])

    def test_chained_or_duplicate_rows_are_refused(self):
        self.assertTrue(self.check([("2", "a", "b"), ("3", "b", "c")]))
        self.assertTrue(self.check([("2", "a", "b"), ("2", "a", "c")]))
        self.assertTrue(self.check([("2", "a", "c"), ("2", "b", "c")]))
        self.assertEqual([], self.check([("2", "a", "b"), ("2", "a/x.md", "b/y.md")]))

    def test_repo_map_is_consistent(self):
        self.assertEqual([], mn.map_problems(mn.load_map()))


class RealRepo(unittest.TestCase):
    """임시 git 저장소에서 옮기기와 링크 바꾸기를 끝까지 돌린다."""

    FILES = {
        "docs/screenshots-pdf/a.png": "그림",
        "docs/2026-11-05-packaging/evidence/w3-경로.md": "[그림](../../screenshots-pdf/a.png)\n",
        "docs/2026-11-05-packaging/README.md": "`evidence/w3-경로.md`\n",
        "docs/2026-11-10-naming-rules/README.md": "| `docs/screenshots-pdf/` | `docs/2026-11-07-screenshots-pdf/` |\n",
        "INTENT.md": "docs/screenshots-pdf/를 만들었다. 근거 `docs/screenshots-pdf/a.png`\n",
        "메모리/결정로그.md": "`docs/screenshots-pdf/`를 만들었다. 근거 [그림](../docs/screenshots-pdf/a.png)\n",
        "CLAUDE.md": "규칙: `docs/screenshots-pdf/`\n",
        ".claude/agents/a.md": "[그림](../../docs/screenshots-pdf/a.png)\n",
        "data/sample.json": '{"source": "docs/screenshots-pdf/a.png"}\n',
        "data/sample.csv": "path\ndocs/screenshots-pdf/a.png\n",
        "scripts/x.py": 'P = "docs/screenshots-pdf"\n',
    }

    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="hazop-migrate-")
        self.addCleanup(tmp.cleanup)
        self.repo = tmp.name
        for rel, text in self.FILES.items():
            full = os.path.join(self.repo, rel)
            os.makedirs(os.path.dirname(full), exist_ok=True)
            with open(full, "w", encoding="utf-8", newline="") as f:
                f.write(text)
        self.git("init", "-q")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "docs: 처음")
        self.rows = ROWS[:2]
        self.report = os.path.join(self.repo, "rewritten.csv")

    def git(self, *args):
        r = subprocess.run(["git", "-C", self.repo, "-c", "user.name=t", "-c", "user.email=t@example.invalid",
                            "-c", "commit.gpgsign=false", "-c", "core.quotepath=off", "-c", "core.autocrlf=false"]
                           + list(args), capture_output=True)
        self.assertEqual(0, r.returncode, r.stderr.decode("utf-8", "replace"))
        return r.stdout.decode("utf-8")

    def read(self, rel):
        with open(os.path.join(self.repo, rel), encoding="utf-8", newline="") as f:
            return f.read()

    def test_move_is_rename_only_and_repeatable(self):
        self.assertEqual(2, len(mn.move(self.rows, self.repo)))
        status = self.git("status", "--porcelain").splitlines()
        self.assertEqual(2, len(status))
        self.assertTrue(all(line.startswith("R  ") for line in status), status)
        self.assertFalse(os.path.exists(os.path.join(self.repo, "docs", "screenshots-pdf")))
        self.assertEqual([], mn.move(self.rows, self.repo))

    def test_move_refuses_to_overwrite(self):
        os.makedirs(os.path.join(self.repo, "docs", "2026-11-07-screenshots-pdf"))
        with self.assertRaises(mn.MigrateError):
            mn.move(self.rows, self.repo)
        self.assertEqual("", self.git("status", "--porcelain", "-uno"))

    def test_rewrite_touches_only_links_and_backticks_in_md_and_html(self):
        mn.move(self.rows, self.repo)
        self.git("commit", "-q", "-m", "refactor: 옮김")
        changes = mn.rewrite_links(self.rows, self.repo, write=True, report=self.report)
        changed = sorted(line[3:] for line in self.git("status", "--porcelain", "-uno").splitlines())
        self.assertEqual(["INTENT.md", "docs/2026-11-05-packaging/README.md", "docs/2026-11-05-packaging/evidence/w3-paths.md",
                          "메모리/결정로그.md"], changed)
        self.assertEqual("[그림](../../2026-11-07-screenshots-pdf/a.png)\n", self.read("docs/2026-11-05-packaging/evidence/w3-paths.md"))
        self.assertEqual("`evidence/w3-paths.md`\n", self.read("docs/2026-11-05-packaging/README.md"))
        self.assertEqual("docs/screenshots-pdf/를 만들었다. 근거 `docs/2026-11-07-screenshots-pdf/a.png`\n", self.read("INTENT.md"))
        self.assertEqual("`docs/screenshots-pdf/`를 만들었다. 근거 [그림](../docs/2026-11-07-screenshots-pdf/a.png)\n", self.read("메모리/결정로그.md"))
        for rel in ("data/sample.json", "data/sample.csv", "scripts/x.py", "CLAUDE.md", ".claude/agents/a.md",
                    "docs/2026-11-10-naming-rules/README.md"):
            self.assertEqual(self.FILES[rel], self.read(rel), rel)
        self.assertEqual(6, len(changes))

        with open(self.report, encoding="utf-8-sig", newline="") as f:
            rows = list(csv.DictReader(f))
        self.assertEqual({"예": 4, "아니오(총괄 몫)": 2},
                         {k: sum(r["적용"] == k for r in rows) for k in {r["적용"] for r in rows}})
        self.assertEqual({"CLAUDE.md", ".claude/agents/a.md"}, {r["파일"] for r in rows if r["적용"] != "예"})

        before = {rel: self.read(rel) for rel in changed}
        again = mn.rewrite_links(self.rows, self.repo, write=True, report=self.report)
        self.assertEqual([], [c for c in again if c.applied])
        self.assertEqual(before, {rel: self.read(rel) for rel in changed})
        with open(self.report, encoding="utf-8-sig", newline="") as f:
            self.assertEqual(rows, list(csv.DictReader(f)))

    def test_only_rewrites_the_named_operating_files(self):
        mn.move(self.rows, self.repo)
        self.git("commit", "-q", "-m", "refactor: 옮김")
        changes = mn.rewrite_links(self.rows, self.repo, write=True, only=[".claude"])
        self.assertEqual([(".claude/agents/a.md", True)], [(c.file, c.applied) for c in changes])
        self.assertEqual([".claude/agents/a.md"],
                         [line[3:] for line in self.git("status", "--porcelain", "-uno").splitlines()])
        self.assertEqual("[그림](../../docs/2026-11-07-screenshots-pdf/a.png)\n", self.read(".claude/agents/a.md"))
        self.assertEqual(self.FILES["CLAUDE.md"], self.read("CLAUDE.md"))
        self.assertEqual([], mn.rewrite_links(self.rows, self.repo, write=True, only=[".claude"]))

    def test_untracked_folder_moved_by_hand_is_rewritten_once_it_is_on_disk(self):
        """git이 추적하지 않는 폴더(대응표 stage 5u)는 이 PC에 새 이름으로 옮겨져 있을 때만 문서의 백틱 경로를 바꾼다."""
        rows = [mn.Row("5u", "big/원본", "big/source")]
        with open(os.path.join(self.repo, "README.md"), "w", encoding="utf-8", newline="") as f:
            f.write("원본은 `big/원본/`에 둔다.\n")
        self.git("add", "README.md")
        self.assertEqual([], mn.rewrite_links(rows, self.repo, write=True))
        os.makedirs(os.path.join(self.repo, "big", "source"))
        self.assertEqual(1, len(mn.rewrite_links(rows, self.repo, write=True)))
        self.assertEqual("원본은 `big/source/`에 둔다.\n", self.read("README.md"))
        self.assertEqual([], mn.rewrite_links(rows, self.repo, write=True))

    def test_dry_run_writes_nothing(self):
        mn.move(self.rows, self.repo)
        self.git("commit", "-q", "-m", "refactor: 옮김")
        self.assertEqual(6, len(mn.rewrite_links(self.rows, self.repo, write=False, report=None)))
        self.assertEqual("", self.git("status", "--porcelain"))


if __name__ == "__main__":
    unittest.main()
