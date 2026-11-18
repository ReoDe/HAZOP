"""새 웹 화면이 배포본에 들어가는지(단위 새 화면 1단계, docs/design/app-shell-web.md §6). 실행: python -m unittest tests.test_shell_packaging

빌드 목록(datas)에 웹 폴더가 있고, 검증 스크립트(`packaging/verify_bundle.py`)가 묶음 안 웹 폴더를 저장소와 바이트까지 견주며,
묶음 라이브러리 고지가 실행 파일 옆 licenses/에 있는지 본다. 실제 PyInstaller 빌드는 하지 않는다.
"""

import importlib.util
import os
import shutil
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(REPO, "hazop", "shell", "web")


def load(name, rel):
    spec = importlib.util.spec_from_file_location(name, os.path.join(REPO, *rel.split("/")))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class WebPackagingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bp = load("bp_shell", "scripts/build_package.py")
        cls.vb = load("vb_shell", "packaging/verify_bundle.py")

    def test_web_folder_is_in_the_build_datas(self):
        srcs = {s for s, _ in self.bp.datas_list()}
        for rel in ("index.html", "app.css", "tokens.css", "shell.css", "js/main.js", "vendor/preact.module.js",
                    "vendor/hooks.module.js", "vendor/htm.module.js"):
            self.assertIn("hazop/shell/web/" + rel, srcs)

    def test_web_unit_tests_are_not_in_the_build_datas(self):
        srcs = {s for s, _ in self.bp.datas_list()}
        self.assertFalse([s for s in srcs if s.startswith("hazop/shell/web/test")], "web/test/는 배포본에 들어가지 않는다")

    def make_bundle(self):
        tmp = tempfile.mkdtemp(prefix="hazop-webbundle-")
        self.addCleanup(shutil.rmtree, tmp, True)
        shutil.copytree(WEB, os.path.join(tmp, "_internal", "hazop", "shell", "web"), ignore=shutil.ignore_patterns("test"))
        for name in ("preact", "htm"):
            os.makedirs(os.path.join(tmp, "licenses", name))
            shutil.copy(os.path.join(REPO, "licenses", name, "LICENSE"), os.path.join(tmp, "licenses", name, "LICENSE"))
        return tmp

    def test_a_faithful_bundle_has_no_problems(self):
        self.assertEqual(self.vb.web_problems(self.make_bundle()), [])

    def test_missing_changed_extra_and_license_are_found(self):
        tmp = self.make_bundle()
        web = os.path.join(tmp, "_internal", "hazop", "shell", "web")
        os.remove(os.path.join(web, "vendor", "htm.module.js"))
        probs = self.vb.web_problems(tmp)
        self.assertIn("웹 파일 빠짐: vendor/htm.module.js", probs)
        self.assertIn("필수 웹 파일 없음: vendor/htm.module.js", probs)
        with open(os.path.join(web, "app.css"), "ab") as fh:
            fh.write("/* 바뀜 */".encode("utf-8"))
        self.assertIn("웹 파일 바이트 다름: app.css", self.vb.web_problems(tmp))
        with open(os.path.join(web, "extra.js"), "w", encoding="utf-8") as fh:
            fh.write("x")
        self.assertIn("묶음에만 있는 웹 파일: extra.js", self.vb.web_problems(tmp))
        os.makedirs(os.path.join(web, "test"))
        with open(os.path.join(web, "test", "run.js"), "w", encoding="utf-8") as fh:
            fh.write("x")
        self.assertIn("묶음에만 있는 웹 파일: test/run.js", self.vb.web_problems(tmp), "시험 파일이 묶음에 있으면 문제")
        shutil.rmtree(os.path.join(tmp, "licenses", "htm"))
        self.assertIn("묶음 라이브러리 고지 없음: licenses/htm/LICENSE", self.vb.web_problems(tmp))

    def test_no_web_folder_in_the_bundle(self):
        tmp = tempfile.mkdtemp(prefix="hazop-webbundle-")
        self.addCleanup(shutil.rmtree, tmp, True)
        self.assertEqual(self.vb.web_problems(tmp), ["묶음에 새 웹 화면 폴더가 없음"])

    def test_notices_for_bundled_libraries_exist(self):
        for name in ("preact", "htm"):
            self.assertTrue(os.path.isfile(os.path.join(REPO, "licenses", name, "LICENSE")), name)


if __name__ == "__main__":
    unittest.main()
