"""화면에 나오는 글에 내부 말이 없는지. 실행: python -m unittest tests.test_screen_words

INTENT §3.8: 엔진 사정을 사용자에게 시키지 않고, 화면 글은 사람 말로 쓴다. 아래 표의 왼쪽(내부 말)이 화면 글(웹 JS의 글자 값, 셸 Python의 문자열 값)에 들어가면 실패한다.
주석·docstring은 개발자용이라 센다. 바꾼 말의 표는 이 파일의 WORDS가 기준이고 규격 문서(ux-mockups 세션)와 맞춘다.

| 내부 말 | 화면 말 |
| --- | --- |
| 묘비, lost:… | 찾지 못한 구성요소 |
| 판 이전(하기) | 도면 변경 반영(하기) |
| 그래프 판이 바뀌었습니다 | 도면이 다시 읽혀 바뀌었습니다 |
| 자리 확인 안 됨 | 위치를 아직 확인하지 않음 |
| 참조 확인 필요 | 다시 확인할 곳 |
| 엔진이 … | 프로그램이 … |
"""

import ast
import os
import re
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BANNED = ("묘비", "판 이전", "판 사진", "lost:", "그래프 판")
BANNED_WEB = BANNED + ("엔진이", "엔진은")      # 웹 글에는 '엔진'도 쓰지 않는다(Python 문자열은 개발자용 명령 설명에 쓰여 센다 않음)


def js_strings(path):
    """JS 파일에서 주석을 뺀 글(문자열·템플릿 안의 글을 포함한 나머지)."""
    with open(path, encoding="utf-8") as fh:
        src = fh.read()
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    out = []
    for line in src.splitlines():
        # 줄 끝 주석(//)은 문자열 밖의 것만 뺀다: 따옴표 안의 //(주소)는 그대로 둔다
        in_str, quote, cut = False, "", None
        i = 0
        while i < len(line):
            c = line[i]
            if in_str:
                if c == "\\":
                    i += 1
                elif c == quote:
                    in_str = False
            elif c in "'\"`":
                in_str, quote = True, c
            elif c == "/" and line[i:i + 2] == "//":
                cut = i
                break
            i += 1
        out.append(line if cut is None else line[:cut])
    return "\n".join(out)


def py_strings(path):
    """Python 파일의 문자열 값(docstring 제외)."""
    with open(path, encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    doc_ids = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                doc_ids.add(id(first.value))
    return [(n.lineno, n.value) for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in doc_ids]


class ScreenWordsTest(unittest.TestCase):
    def test_web_texts_have_no_internal_words(self):
        bad = []
        root = os.path.join(REPO, "hazop", "shell", "web", "js")
        for d, _s, files in os.walk(root):
            for f in files:
                if not f.endswith(".js"):
                    continue
                p = os.path.join(d, f)
                text = js_strings(p)
                for w in BANNED_WEB:
                    for m in re.finditer(re.escape(w), text):
                        bad.append("%s: %s … %s" % (os.path.relpath(p, REPO), w, text[max(0, m.start() - 20):m.end() + 20].replace("\n", " ")))
        self.assertEqual(bad, [])

    def test_shell_messages_have_no_internal_words(self):
        bad = []
        files = [os.path.join(REPO, "hazop", "shell", n) for n in sorted(os.listdir(os.path.join(REPO, "hazop", "shell"))) if n.endswith(".py")]
        for p in files:
            for line, s in py_strings(p):
                for w in BANNED:
                    if w in s:
                        bad.append("%s:%d: %s … %s" % (os.path.relpath(p, REPO), line, w, s[:60].replace("\n", " ")))
        self.assertEqual(bad, [])

    def test_the_guide_shared_by_the_screens_has_no_internal_words(self):
        from hazop.study import follow
        for w in BANNED:
            self.assertNotIn(w, follow.STALE)
        self.assertIn("도면 변경 반영하기", follow.STALE)


if __name__ == "__main__":
    unittest.main()
