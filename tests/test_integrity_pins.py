"""패키징 W5: 신뢰 경계 해시 고정(패턴 라이브러리·지침서 추가). 실행: python -m unittest discover -s tests -t .

실제 데이터/·기획서/ 파일은 바꾸지 않는다. 자원 루트(기준 자료 4종·지침서)와 작업 루트(구간 JSON·그래프·고정 응답)를
임시 폴더에 복사하고, 자원 사본의 1바이트를 바꿔 ④ 분석(api.run_analysis)이 입력 차단되고 사유가 표시되는지 본다.
"""

import json
import os
import re
import shutil
import tempfile
import unittest
from unittest import mock

from hazop import paths
from hazop.analysis import api, catalog_md, integrity, run
from tests.test_analysis import CRIT, FIXED_DIR, GRAPH, REGION_FILE, REPO_ROOT, _load

GUIDE_REL = "/".join(integrity.GUIDE_PARTS)
REGION = _load(REGION_FILE)
RESOURCE_RELS = sorted(REGION["inputs"][r] for r in paths.RESOURCE_INPUT_ROLES) + [GUIDE_REL]
PATTERNS_REL = REGION["inputs"]["patterns"]


def _bump_version_digit(data):
    """JSON 바이트에서 첫 '<이름>_version": <숫자>'의 숫자 한 자리를 바꾼다(1바이트, JSON 유효 유지).
    고정 해시를 갱신하지 않고 버전만 올린 '미승인 변경'과 같다."""
    m = re.search(rb'_version": ([0-8])', data)
    assert m, "버전 숫자를 찾지 못함"
    i = m.start(1)
    return data[:i] + bytes([data[i] + 1]) + data[i + 1:]


class PinnedValuesTest(unittest.TestCase):

    def test_repo_resources_match_pins(self):
        pat = _load(os.path.join(REPO_ROOT, PATTERNS_REL))
        self.assertEqual(integrity.check_patterns(pat), [])
        self.assertEqual(integrity.guide_sha256(os.path.join(REPO_ROOT, *integrity.GUIDE_PARTS)), integrity.GUIDE_SHA256)

    def test_guide_hash_ignores_crlf_only(self):
        """autocrlf 체크아웃(CRLF)과 git 저장 내용(LF)은 같은 값, 단독 CR·BOM은 다른 값."""
        with open(os.path.join(REPO_ROOT, *integrity.GUIDE_PARTS), "rb") as fh:
            lf = fh.read().replace(b"\r\n", b"\n")
        tmp = tempfile.mkdtemp(prefix="hazop-w5-guide-")
        self.addCleanup(shutil.rmtree, tmp, True)

        def sha(data):
            p = os.path.join(tmp, "g.md")
            with open(p, "wb") as fh:
                fh.write(data)
            return integrity.guide_sha256(p)
        self.assertEqual(sha(lf), integrity.GUIDE_SHA256)
        self.assertEqual(sha(lf.replace(b"\n", b"\r\n")), integrity.GUIDE_SHA256)
        self.assertNotEqual(sha(lf.replace(b"\n", b"\r", 1)), integrity.GUIDE_SHA256)
        self.assertNotEqual(sha(b"\xef\xbb\xbf" + lf), integrity.GUIDE_SHA256)

    def _broken_guide(self):
        """§5.3·§6 표가 없는 지침서(파싱 불가)."""
        tmp = tempfile.mkdtemp(prefix="hazop-w5-broken-")
        self.addCleanup(shutil.rmtree, tmp, True)
        p = os.path.join(tmp, "g.md")
        with open(p, "wb") as fh:
            fh.write("# 표 없는 지침서\n".encode("utf-8"))
        return p

    def test_hash_mismatch_reported_before_parse(self):
        """해시가 다르면 파싱하지 않고 그 사유만 돌려준다(파싱 예외가 사유를 가리지 않음)."""
        g = self._broken_guide()
        cat, crit = _load(os.path.join(REPO_ROOT, REGION["inputs"]["candidate_catalog"])), CRIT
        self.assertEqual(integrity.check_catalog(cat, None, guide=g),
                         ["지침서 파일 해시가 고정값과 다름(변조 또는 미승인 변경) — 카탈로그 대조 불가: %s" % g])
        self.assertEqual(integrity.check_criteria(crit, guide=g),
                         ["지침서 파일 해시가 고정값과 다름(변조 또는 미승인 변경) — 기준표 대조 불가: %s" % g])

    def test_parse_failure_becomes_blocker(self):
        g = self._broken_guide()
        cat = _load(os.path.join(REPO_ROOT, REGION["inputs"]["candidate_catalog"]))
        with mock.patch.object(integrity, "GUIDE_SHA256", integrity.guide_sha256(g)):
            e1 = integrity.check_catalog(cat, None, guide=g)
            e2 = integrity.check_criteria(CRIT, guide=g)
        self.assertEqual(len(e1), 1, e1)
        self.assertTrue(e1[0].startswith("지침서 §5.3 표 파싱 실패 — 대조 불가: %s (ValueError" % g), e1)
        self.assertEqual(len(e2), 1, e2)
        self.assertTrue(e2[0].startswith("지침서 §6 표 파싱 실패 — 대조 불가: %s (ValueError" % g), e2)

    def test_read_failure_becomes_blocker(self):
        """존재 확인 뒤 읽기 실패(권한 등)·파싱 직전 삭제(OSError)는 경로와 원인을 담은 사유가 된다."""
        g = os.path.join(REPO_ROOT, *integrity.GUIDE_PARTS)
        cat = _load(os.path.join(REPO_ROOT, REGION["inputs"]["candidate_catalog"]))
        with mock.patch.object(integrity, "guide_sha256", side_effect=PermissionError(13, "거부됨")):
            self.assertEqual(integrity.check_criteria(CRIT, guide=g),
                             ["지침서 읽기 실패 — 기준표 대조 불가: %s (PermissionError: [Errno 13] 거부됨)" % g])
        with mock.patch.object(catalog_md, "parse_guide_table", side_effect=FileNotFoundError(2, "없음")), \
                mock.patch.object(catalog_md, "parse_risk_tables", side_effect=FileNotFoundError(2, "없음")):
            self.assertEqual(integrity.check_catalog(cat, None, guide=g),
                             ["지침서 §5.3 표 파싱 실패 — 대조 불가: %s (FileNotFoundError: [Errno 2] 없음)" % g])
            self.assertEqual(integrity.check_criteria(CRIT, guide=g),
                             ["지침서 §6 표 파싱 실패 — 대조 불가: %s (FileNotFoundError: [Errno 2] 없음)" % g])

    def test_unpinned_library_blocks(self):
        pat = _load(os.path.join(REPO_ROOT, PATTERNS_REL))
        pat["library_id"] = "user-added-library"
        self.assertTrue(any("고정 해시 없음" in e for e in integrity.check_patterns(pat)))


class TamperedResourceRootTest(unittest.TestCase):
    """임시 자원 루트 사본에서 파일 1바이트를 바꾸면 분석이 입력 차단되고 사유가 표시된다."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hazop-w5-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.res, self.work = os.path.join(self.tmp, "res"), os.path.join(self.tmp, "work")
        for rel in RESOURCE_RELS:
            dst = os.path.join(self.res, *rel.split("/"))
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copyfile(os.path.join(REPO_ROOT, *rel.split("/")), dst)
        self.region_path = os.path.join(self.work, "데이터", "구간", os.path.basename(REGION_FILE))
        os.makedirs(os.path.dirname(self.region_path))
        shutil.copyfile(REGION_FILE, self.region_path)
        gpath = os.path.join(self.work, REGION["graph_ref"]["graph_file"])
        os.makedirs(os.path.dirname(gpath))
        with open(gpath, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(GRAPH, fh, ensure_ascii=False, indent=2)
        env = {k: v for k, v in os.environ.items() if k not in (paths.ENV_STORE_ROOT,)}
        env.update({paths.ENV_RESOURCE_ROOT: self.res, paths.ENV_WORK_ROOT: self.work})
        patcher = mock.patch.dict(os.environ, env, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _analyze(self, run_id):
        return api.run_analysis(self.region_path, response_dir=FIXED_DIR, run_id=run_id)

    def _tamper(self, rel, change):
        p = os.path.join(self.res, *rel.split("/"))
        with open(p, "rb") as fh:
            before = fh.read()
        after = change(before)
        self.assertEqual(len(after), len(before))
        self.assertEqual(sum(a != b for a, b in zip(before, after)), 1)  # 정확히 1바이트
        with open(p, "wb") as fh:
            fh.write(after)

    def test_untampered_copy_passes(self):
        """바이트 사본과 줄바꿈만 바꾼 사본(CRLF↔LF)은 고정 해시와 맞아 분석이 통과한다."""
        for rel in RESOURCE_RELS:
            p = os.path.join(self.res, *rel.split("/"))
            with open(p, "rb") as fh:
                data = fh.read()
            with open(p, "wb") as fh:
                fh.write(data.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))
        r = self._analyze("analysis-w5-ok")
        self.assertEqual((r["status"], r["blockers"]), ("passed", []))

    def test_one_byte_change_blocks_each_resource(self):
        reasons = {
            PATTERNS_REL: "패턴 라이브러리 'hazop-cause-consequence-patterns': 내용 해시가 고정값과 다름",
            REGION["inputs"]["candidate_catalog"]: "이탈 후보 카탈로그 'kosha-p86-2017-deviation-chart': 내용 해시가 고정값과 다름",
            REGION["inputs"]["applicability"]: "적용 판단 파일 'applicability-region-SNP-M-102-pzr': 내용 해시가 고정값과 다름",
            REGION["inputs"]["risk_criteria"]: "위험도 기준표 'kosha-p86-2017-risk-example': 내용 해시가 고정값과 다름",
        }
        for rel, want in sorted(reasons.items()):
            with self.subTest(rel=rel):
                src = os.path.join(self.res, *rel.split("/"))
                with open(src, "rb") as fh:
                    original = fh.read()
                self._tamper(rel, _bump_version_digit)
                try:
                    r = self._analyze("analysis-w5-bad")
                finally:
                    with open(src, "wb") as fh:
                        fh.write(original)
                self.assertEqual(r["status"], "input_blocked")
                self.assertIsNone(r["run_dir"])
                self.assertTrue(any(want in b for b in r["blockers"]), r["blockers"])

    def test_one_byte_change_in_guide_prose_blocks(self):
        """표 밖 문장 1바이트 변경: 표 대조로는 못 잡고 파일 해시로만 잡힌다."""
        self._tamper(GUIDE_REL, lambda b: b.replace(b"# HAZOP", b"# hAZOP", 1))
        r = self._analyze("analysis-w5-guide")
        self.assertEqual(r["status"], "input_blocked")
        guide = os.path.join(self.res, *integrity.GUIDE_PARTS)
        self.assertEqual(r["blockers"], [  # 카탈로그·기준표 검사가 각각 지침서 해시를 확인하고, 그 뒤 표 대조는 하지 않음
            "지침서 파일 해시가 고정값과 다름(변조 또는 미승인 변경) — 카탈로그 대조 불가: %s" % guide,
            "지침서 파일 해시가 고정값과 다름(변조 또는 미승인 변경) — 기준표 대조 불가: %s" % guide])

    def test_guide_bom_or_lone_cr_blocks(self):
        for label, change in (("bom", lambda b: b"\xef\xbb\xbf" + b),
                              ("lone-cr", lambda b: b.replace(b"\n", b"\r", 1))):
            with self.subTest(label):
                p = os.path.join(self.res, *integrity.GUIDE_PARTS)
                with open(p, "rb") as fh:
                    original = fh.read()
                lf = original.replace(b"\r\n", b"\n")
                with open(p, "wb") as fh:
                    fh.write(change(lf))
                try:
                    r = self._analyze("analysis-w5-" + label)
                finally:
                    with open(p, "wb") as fh:
                        fh.write(original)
                self.assertEqual(r["status"], "input_blocked")
                self.assertTrue(all("지침서 파일 해시가 고정값과 다름" in b for b in r["blockers"]), r["blockers"])
                self.assertEqual(len(r["blockers"]), 2)

    def test_json_representation_only_passes_value_change_blocks(self):
        """키 순서·들여쓰기·줄바꿈만 다른 JSON은 통과, 값(문자 하나)이 바뀌면 차단."""
        p = os.path.join(self.res, *PATTERNS_REL.split("/"))
        doc = _load(p)
        reordered = dict(reversed(list(doc.items())))
        with open(p, "w", encoding="utf-8", newline="\r\n") as fh:
            json.dump(reordered, fh, ensure_ascii=False, indent=4)
        r = self._analyze("analysis-w5-repr")
        self.assertEqual((r["status"], r["blockers"]), ("passed", []))
        reordered["note"] = reordered["note"].replace("MVP", "MVQ", 1)
        with open(p, "w", encoding="utf-8") as fh:
            json.dump(reordered, fh, ensure_ascii=False)
        r = self._analyze("analysis-w5-value")
        self.assertEqual(r["status"], "input_blocked")
        self.assertEqual(r["blockers"], ["패턴 라이브러리 'hazop-cause-consequence-patterns': 내용 해시가 고정값과 다름"
                                         "(변조 또는 미승인 변경)"])

    def test_alternate_resource_root_is_checked(self):
        """검사는 호출 시점의 자원 루트(HAZOP_RESOURCE_ROOT)의 지침서를 쓴다: 저장소 지침서로 대체하지 않는다."""
        guide = os.path.join(self.res, *integrity.GUIDE_PARTS)
        self.assertEqual(integrity.check_catalog(_load(os.path.join(self.res, *REGION["inputs"]["candidate_catalog"]
                                                               .split("/"))), None), [])
        os.remove(guide)
        crit = _load(os.path.join(self.res, *REGION["inputs"]["risk_criteria"].split("/")))
        self.assertEqual(integrity.check_criteria(crit), ["지침서 없음 — 기준표 대조 불가: %s" % guide])
        r = self._analyze("analysis-w5-noguide")
        self.assertEqual(r["status"], "input_blocked")
        self.assertEqual(r["blockers"], ["지침서 없음 — 카탈로그 대조 불가: %s" % guide,
                                         "지침서 없음 — 기준표 대조 불가: %s" % guide])

    def test_check_criteria_alone_checks_guide_hash(self):
        guide = os.path.join(self.res, *integrity.GUIDE_PARTS)
        self._tamper(GUIDE_REL, lambda b: b.replace(b"# HAZOP", b"# hAZOP", 1))
        crit = _load(os.path.join(self.res, *REGION["inputs"]["risk_criteria"].split("/")))
        self.assertEqual(integrity.check_criteria(crit),
                         ["지침서 파일 해시가 고정값과 다름(변조 또는 미승인 변경) — 기준표 대조 불가: %s" % guide])

    def test_resume_blocked_after_pin_mismatch(self):
        """정상 실행 뒤 입력 사본의 패턴이 고정값과 다르면(예: 이전 패턴 버전으로 만든 실행) 재시도가 차단된다."""
        r = self._analyze("analysis-w5-resume")
        self.assertEqual(r["status"], "passed")
        with mock.patch.dict(integrity.PINNED_SHA256, {"hazop-cause-consequence-patterns": "0" * 64}):
            with self.assertRaises(run.InputError) as cm:
                run.resume(r["run_dir"], api.make_client("fixed_response", FIXED_DIR))
        self.assertIn("패턴 라이브러리", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
