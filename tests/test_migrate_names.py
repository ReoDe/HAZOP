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


class RewriteText(unittest.TestCase):
    def test_relative_link(self):
        new, changes = rewrite("메모리/결정로그.md", "근거는 [경로 조사](../docs/2026-11-05-packaging/evidence/w3-경로.md#3-결과)다.\n")
        self.assertEqual("근거는 [경로 조사](../docs/2026-11-05-packaging/evidence/w3-paths.md#3-결과)다.\n", new)
        self.assertEqual([("메모리/결정로그.md", 1, "link", "../docs/2026-11-05-packaging/evidence/w3-경로.md#3-결과",
                           "../docs/2026-11-05-packaging/evidence/w3-paths.md#3-결과")], changes)

    def test_link_with_space_and_title(self):
        new, _ = rewrite("README.md", '[흐름](flow chart/00-overview.md) [흐름](<flow chart/00-overview.md> "제목")\n')
        self.assertEqual('[흐름](specs/flows/00-overview.md) [흐름](<specs/flows/00-overview.md> "제목")\n', new)

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
        new, _ = rewrite("메모리/결정로그.md", "이름을 붙였다(`범례항목.csv`). `README.md`와 `없는이름.csv`는 그대로다.\n")
        self.assertEqual("이름을 붙였다(`legend-items.csv`). `README.md`와 `없는이름.csv`는 그대로다.\n", new)

    def test_body_sentences_and_fences_stay(self):
        text = ("2026-11-07 docs/screenshots-pdf/ 아래에 그림을 두기로 했다. w3-경로.md 참고.\n"
                "```\npython scripts/x.py docs/screenshots-pdf\n```\n"
                "이름이 비슷한 `docs/screenshots-pdf-old/`와 `mydocs/screenshots-pdf`는 다른 폴더다.\n")
        self.assertEqual((text, []), rewrite("메모리/결정로그.md", text))

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
        "메모리/결정로그.md": "docs/screenshots-pdf/를 만들었다. 근거 `docs/screenshots-pdf/a.png`\n",
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
        self.assertEqual(["docs/2026-11-05-packaging/README.md", "docs/2026-11-05-packaging/evidence/w3-paths.md",
                          "메모리/결정로그.md"], changed)
        self.assertEqual("[그림](../../2026-11-07-screenshots-pdf/a.png)\n", self.read("docs/2026-11-05-packaging/evidence/w3-paths.md"))
        self.assertEqual("`evidence/w3-paths.md`\n", self.read("docs/2026-11-05-packaging/README.md"))
        self.assertEqual("docs/screenshots-pdf/를 만들었다. 근거 `docs/2026-11-07-screenshots-pdf/a.png`\n", self.read("메모리/결정로그.md"))
        for rel in ("data/sample.json", "data/sample.csv", "scripts/x.py", "CLAUDE.md", ".claude/agents/a.md",
                    "docs/2026-11-10-naming-rules/README.md"):
            self.assertEqual(self.FILES[rel], self.read(rel), rel)
        self.assertEqual(5, len(changes))

        with open(self.report, encoding="utf-8-sig", newline="") as f:
            rows = list(csv.DictReader(f))
        self.assertEqual({"예": 3, "아니오(총괄 몫)": 2},
                         {k: sum(r["적용"] == k for r in rows) for k in {r["적용"] for r in rows}})
        self.assertEqual({"CLAUDE.md", ".claude/agents/a.md"}, {r["파일"] for r in rows if r["적용"] != "예"})

        before = {rel: self.read(rel) for rel in changed}
        again = mn.rewrite_links(self.rows, self.repo, write=True, report=self.report)
        self.assertEqual([], [c for c in again if c.applied])
        self.assertEqual(before, {rel: self.read(rel) for rel in changed})
        with open(self.report, encoding="utf-8-sig", newline="") as f:
            self.assertEqual(rows, list(csv.DictReader(f)))

    def test_dry_run_writes_nothing(self):
        mn.move(self.rows, self.repo)
        self.git("commit", "-q", "-m", "refactor: 옮김")
        self.assertEqual(5, len(mn.rewrite_links(self.rows, self.repo, write=False, report=None)))
        self.assertEqual("", self.git("status", "--porcelain"))


if __name__ == "__main__":
    unittest.main()
