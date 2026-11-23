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
| graph-material-…-p0, SCN__material-… | 사람용 도면 이름(번호, 없으면 '파일 · n쪽') |
"""

import ast
import os
import re
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BANNED = ("묘비", "판 이전", "판 사진", "lost:", "그래프 판",
          "graph-material-", "SCN__material")     # 번호 없는 시트의 임시 이름·폴더 이름 꼴(시트 정체 U4: 화면은 sheets.display_name만 쓴다)
BANNED_WEB = BANNED + ("엔진이", "엔진은")      # 웹 글에는 '엔진'도 쓰지 않는다(Python 문자열은 개발자용 명령 설명에 쓰여 센다 않음)
# 화면의 사람 말(INTENT §3.8 ④, 2026-11-23): 한글이 든 글(사람에게 보이는 문장)에만 센다. 코드의 이름(graph_id 같은 열쇠)은 세지 않는다
BANNED_TEXT = ("지문", "열린 끝", "번호가 밀", "기준 추출", "입력 연산", "엔진 확인", "옛 판", "새 판", "도면 판", "읽은 판", "파일 판", "후보 판",
               "판 대응", "①", "②", "③", "④", "⑤", "⑥", "⑦", "(ver)", "graph_id", "material_id", "link_candidates", "프로젝트 그래프",
               "그래프를 다시 만들지", "노드 없음")
HANGUL = re.compile(r"[가-힣]")


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


def js_literals(path):
    """JS 파일의 글자 값(따옴표 글, 템플릿의 글 조각; ${…} 안의 코드는 다시 훑어 그 안의 글도 넣음)과 줄 번호. 주석은 뺀다."""
    with open(path, encoding="utf-8") as fh:
        src = fh.read()
    out = []

    def line_at(k):
        return src.count("\n", 0, k) + 1

    def code(i, close):
        """코드를 훑는다. close면 짝 맞는 '}'에서 멈춘다. → 멈춘 자리."""
        depth = 0
        n = len(src)
        while i < n:
            c = src[i]
            if c == "/" and src[i:i + 2] == "//":
                j = src.find("\n", i)
                i = n if j < 0 else j
                continue
            if c == "/" and src[i:i + 2] == "/*":
                j = src.find("*/", i + 2)
                i = n if j < 0 else j + 2
                continue
            if c in "'\"":
                j, buf = i + 1, []
                while j < n and src[j] != c and src[j] != "\n":
                    if src[j] == "\\":
                        buf.append(src[j:j + 2]); j += 2; continue
                    buf.append(src[j]); j += 1
                out.append((line_at(i), "".join(buf)))
                i = j + 1
                continue
            if c == "`":
                i = template(i + 1)
                continue
            if close:
                if c == "{":
                    depth += 1
                elif c == "}":
                    if depth == 0:
                        return i + 1
                    depth -= 1
            i += 1
        return i

    def template(i):
        start, buf, n = i, [], len(src)
        while i < n:
            c = src[i]
            if c == "\\":
                buf.append(src[i:i + 2]); i += 2; continue
            if c == "`":
                out.append((line_at(start), "".join(buf)))
                return i + 1
            if src[i:i + 2] == "${":
                buf.append(" ")
                i = code(i + 2, True)
                continue
            buf.append(c); i += 1
        out.append((line_at(start), "".join(buf)))
        return i

    code(0, False)
    return out


# 사람 화면이 아니라서 세지 않는 글(까닭을 적는다)
ALLOW = (
    ("hazop/extract/ai_review.py", "열린 끝"),          # AI에 보내는 물음(프롬프트) 글: 모델용 말
    ("hazop/shell/chat_edits.py", "graph_id"),         # 채팅 도구 인자 검사 글: 모델이 고칠 인자 이름을 알아야 한다
    ("hazop/shell/chat_edits.py", "material_id"),
    ("hazop/shell/api_corrections.py", "노드 없음"),    # REASON_TEXT의 찾을 머리(엔진 글): 화면에는 오른쪽 사람 말만 나간다
    ("hazop/shell/api_corrections.py", "열린 끝"),
)


def _log_or_doc_ids(tree):
    """로그 호출(LOG.*)의 글과 명령 설명(Command·put의 넷째 인자)은 사람 화면이 아니라 뺀다."""
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            f = node.func
            name = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")
            owner = getattr(f.value, "id", "") if isinstance(f, ast.Attribute) else ""
            if owner in ("LOG", "log", "logger", "logging") or name in ("debug",):
                for a in ast.walk(node):
                    if isinstance(a, ast.Constant):
                        out.add(id(a))
            if name in ("put", "Command", "C") and len(node.args) >= 3 and isinstance(node.args[-1], ast.Constant):
                out.add(id(node.args[-1]))
    return out


def screen_py_strings(path, constants_only=False):
    """Python 파일의 사람 글(한글이 든 문자열). constants_only면 모듈 맨 위 대문자 이름 상수(REASONS·TEXTS 같은 표)의 글만."""
    with open(path, encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    skip = _log_or_doc_ids(tree)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                skip.add(id(first.value))
    roots = [tree]
    if constants_only:
        roots = [st.value for st in tree.body if isinstance(st, (ast.Assign, ast.AnnAssign)) and st.value is not None
                 and any(isinstance(t, ast.Name) and t.id.isupper() for t in (st.targets if isinstance(st, ast.Assign) else [st.target]))]
    out = []
    for r in roots:
        for n in ast.walk(r):
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in skip and HANGUL.search(n.value):
                out.append((n.lineno, n.value))
    return out


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

    def test_screen_sentences_have_no_internal_words(self):
        """화면의 사람 말(INTENT §3.8 ④): 웹 글자 값·index.html, 셸의 한글 문자열, 엔진(study·extract·register·graph)의 대문자 글 상수."""
        bad = []

        def check(where, line, text):
            where_ = where.replace("\\", "/")
            for w in BANNED_TEXT:
                hit = re.search(re.escape(w) + ("(?!단|정)" if w.endswith("판") else ""), text)     # '판단'·'판정'은 판(버전) 합성어가 아니다
                if hit and (where_, w) not in ALLOW:
                    bad.append("%s:%d: %s … %s" % (where, line, w, text[:70].replace("\n", " ")))
        for d, _s, files in os.walk(os.path.join(REPO, "hazop", "shell", "web", "js")):
            for f in files:
                if f.endswith(".js"):
                    p = os.path.join(d, f)
                    for line, t in js_literals(p):
                        if HANGUL.search(t):
                            check(os.path.relpath(p, REPO), line, t)
        html = os.path.join(REPO, "hazop", "shell", "web", "index.html")
        with open(html, encoding="utf-8") as fh:
            for i, t in enumerate(fh.read().splitlines(), 1):
                if HANGUL.search(t):
                    check(os.path.relpath(html, REPO), i, t)
        shell = os.path.join(REPO, "hazop", "shell")
        for n in sorted(os.listdir(shell)):
            if n.endswith(".py"):
                for line, t in screen_py_strings(os.path.join(shell, n)):
                    check(os.path.join("hazop", "shell", n), line, t)
        for pkg in ("study", "extract", "register", "graph"):
            root = os.path.join(REPO, "hazop", pkg)
            for d, _s, files in os.walk(root):
                for f in files:
                    if f.endswith(".py"):
                        p = os.path.join(d, f)
                        for line, t in screen_py_strings(p, constants_only=True):
                            check(os.path.relpath(p, REPO), line, t)
        self.assertEqual(bad, [], "\n".join(bad))

    def test_the_guide_shared_by_the_screens_has_no_internal_words(self):
        from hazop.study import follow
        for w in BANNED:
            self.assertNotIn(w, follow.STALE)
        self.assertIn("도면 변경 반영하기", follow.STALE)


if __name__ == "__main__":
    unittest.main()
