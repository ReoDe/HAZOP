"""④ 근거 묶음 내보내기(기획서/인터페이스.md §2.5 '근거 묶음 내보내기', '내보내기·응답 폴더 형식').

판단이 '선택'인 후보마다 근거 묶음(run.build_bundle 결과)과 요청 프롬프트를 폴더로 내보낸다. 사용자는 Claude Code 구독제
세션에서 이 폴더로 응답을 만들고, 프로그램은 응답 폴더를 고정 응답으로 다시 불러와 분석한다.
- AI를 호출하지 않고 네트워크를 쓰지 않는다. 분석 실행 폴더(출력/분석/...)와 analysis.json을 만들지 않는다.
- 근거 묶음은 시각을 담지 않으므로, 입력이 같으면 내보낼 때와 분석할 때의 bundle_sha256이 같다(분석과 같은 run.prepare_doc 사용).
- 반출: 근거 묶음은 도면 내용을 담는다. 보안 등급이 있는 실제 설계자료는 사용자 확인 뒤에만 내보낸다(HAZOP분석.md 모델 연결).

<out_root>/<region_id>/<내보낸 시각>/
  manifest.json, response_schema.json, system_prompt.txt, response_guide.txt
  <candidate_id>/bundle.json, <candidate_id>/user_prompt.txt
  responses/<candidate_id>.json   응답 틀(region_id·bundle_sha256 미리 채움, output은 null)
"""

import json
import os
import shutil
import tempfile

from hazop import paths

from . import ai, api, run

SCHEMA_VERSION = "0.1"
RESPONSES = "responses"
EXPORT_NOTE = ("근거 묶음은 도면 내용을 담음. 보안 등급이 있는 실제 설계자료는 사용자 확인 뒤에만 외부(AI 세션 등)로 보냄 "
               "(기획서/HAZOP분석.md 모델 연결)")

RESPONSE_GUIDE = """응답 파일 작성 안내 (hazop/analysis/ai.py FixedResponseClient 형식)

1. 응답 파일 위치: responses/<candidate_id>.json (후보마다 하나). 내보낸 틀에 region_id와 bundle_sha256이 미리 채워져 있음.
2. 필수 필드
   - region_id      : 구간 ID. 틀의 값을 바꾸지 않음. 다르면 input_mismatch로 처리되어 결과에 쓰이지 않음
   - bundle_sha256  : 근거 묶음 해시. 틀의 값을 바꾸지 않음. 분석 때 다시 계산한 값과 다르면 input_mismatch
   - stop_reason    : end_turn(정상) / refusal(거절) / max_tokens(잘림) 중 하나
   - output         : response_schema.json을 따르는 객체(틀에는 null). null이거나 형식이 맞지 않으면 검증 실패로 처리
   선택 필드: sample_note(메모), stop_details
3. 요청 내용: system_prompt.txt(시스템 지시), <candidate_id>/user_prompt.txt(사용자 입력), response_schema.json(응답 형식).
   <candidate_id>/bundle.json은 user_prompt.txt에 들어 있는 근거 묶음과 같은 내용임.
4. 불러오기: 분석 실행에서 응답 폴더로 responses/ 폴더를 고름
   (CLI: python scripts/analyze.py --region <구간 JSON> --fixed-dir <이 폴더>/responses)
5. 구간 JSON(후보 판단 변경 등)·그래프·기준 자료가 바뀌면 bundle_sha256이 달라지므로 다시 내보내야 함.
6. 반출: %s
""" % EXPORT_NOTE


def _write_json(path, obj):
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=2)
        fh.write("\n")


def _write_text(path, text):
    with open(path, "w", encoding="utf-8", newline="") as fh:  # 줄바꿈을 바꾸지 않고 그대로 쓴다
        fh.write(text)


def build_export(inputs, now=run.utc_now):
    """검사를 통과한 입력 -> (시각, 선택 후보 목록, {candidate_id: 근거 묶음}). 파일을 쓰지 않는다."""
    if inputs["blockers"]:
        raise run.InputError("입력 차단 오류 — 내보내지 않음: " + " / ".join(inputs["blockers"]))
    t = now()
    doc = run.prepare_doc(inputs, None, run_id="export", now=lambda: t)  # 분석 실행과 같은 근거 묶음 생성 경로
    selected = [c for c in doc["candidates"] if c["selection_status"] == "selected"]
    return t, selected, doc["evidence_bundles"]


def _write_export(export_dir, t, inputs, selected, bundles, names):
    """export_dir(비어 있는 폴더)에 내보내기 파일을 쓰고 manifest를 돌려준다."""
    region, graph = inputs["region"], inputs["graph"]
    os.makedirs(os.path.join(export_dir, RESPONSES))
    listed = []
    for c in selected:
        cid, name = c["candidate_id"], names[c["candidate_id"]]
        bundle = bundles[cid]
        request = ai.build_request(bundle)
        sub = paths.safe_join(export_dir, name)
        os.makedirs(sub)
        _write_json(os.path.join(sub, "bundle.json"), bundle)
        _write_text(os.path.join(sub, "user_prompt.txt"), request["user"])
        _write_json(paths.safe_join(os.path.join(export_dir, RESPONSES), name + ".json"),
                    {"region_id": request["region_id"], "bundle_sha256": request["bundle_sha256"],
                     "stop_reason": "end_turn", "output": None})
        listed.append({"candidate_id": cid, "item_id": c.get("item_id"), "deviation": c.get("deviation"),
                       "bundle_id": bundle["bundle_id"], "bundle_sha256": request["bundle_sha256"],
                       "user_sha256": request["user_sha256"], "bundle_file": name + "/bundle.json",
                       "user_prompt_file": name + "/user_prompt.txt",
                       "response_file": "%s/%s.json" % (RESPONSES, name)})
    manifest = {
        "schema_version": SCHEMA_VERSION, "export_type": "evidence_bundles", "exported_at": t,
        "region": {"region_id": region["region_id"], "region_version": region["region_version"]},
        "graph": {"graph_id": graph["graph_id"], "graph_version": graph["graph_version"]},
        "input_files": inputs["files"],
        "template": ai.template_info(),
        "target_rule": "판단이 선택(selected)인 후보만",
        "candidates": listed,
        "response_dir": RESPONSES,
        "export_note": EXPORT_NOTE,
        "note": "내보내기는 AI를 호출하지 않으며 분석 실행 폴더를 만들지 않음",
    }
    _write_json(os.path.join(export_dir, "response_schema.json"), ai.RESPONSE_SCHEMA)
    _write_text(os.path.join(export_dir, "system_prompt.txt"), ai.SYSTEM_PROMPT)
    _write_text(os.path.join(export_dir, "response_guide.txt"), RESPONSE_GUIDE)
    _write_json(os.path.join(export_dir, "manifest.json"), manifest)
    return manifest


def export_bundles(region_path, out_root=None, graph_path=None, now=run.utc_now):
    """근거 묶음을 <out_root>/<region_id>/<시각>/에 내보낸다. out_root 기본: <작업 루트>/출력/근거묶음.
    같은 폴더가 이미 있으면 덮어쓰지 않고 run.InputError.
    반환: {"export_dir", "response_dir", "manifest_file", "manifest"}"""
    inputs = api.load_region_inputs(region_path, graph_path)
    t, selected, bundles = build_export(inputs, now)
    region = inputs["region"]
    root = out_root or paths.output_root("근거묶음")
    stamp = paths.safe_name(t.replace("-", "").replace(":", ""))
    parent = paths.safe_join(root, paths.safe_name(region["region_id"]))
    export_dir = paths.safe_join(parent, stamp)
    if os.path.exists(export_dir):
        raise run.InputError("같은 시각의 내보내기 폴더가 이미 있음(덮어쓰지 않음): %s" % export_dir)
    names = {}
    for c in selected:
        # 묶음 폴더·응답 틀 파일 이름은 같은 safe_name. 분석(FixedResponseClient)은 <candidate_id>.json을 읽으므로
        # 이름이 바뀌어야 하는 후보 ID는 내보내지 않는다(응답을 만들어도 분석이 찾지 못함).
        name = paths.safe_name(c["candidate_id"])
        if name != c["candidate_id"] or name.lower() in {n.lower() for n in names.values()}:
            raise run.InputError("후보 ID를 파일 이름으로 그대로 쓸 수 없음(분석 때 응답을 찾지 못함): %r" % c["candidate_id"])
        names[c["candidate_id"]] = name
    made_parent = not os.path.isdir(parent)
    os.makedirs(parent, exist_ok=True)
    # 임시 폴더에 모두 쓴 뒤 이름을 바꾼다. 도중에 실패하면 임시 폴더를 지워 일부만 만든 결과를 남기지 않는다.
    work = tempfile.mkdtemp(prefix=stamp + ".partial-", dir=parent)
    try:
        manifest = _write_export(work, t, inputs, selected, bundles, names)
        os.rename(work, export_dir)
    except BaseException:
        shutil.rmtree(work, ignore_errors=True)
        if made_parent and not os.listdir(parent):
            os.rmdir(parent)
        raise
    manifest_file = os.path.join(export_dir, "manifest.json")
    return {"export_dir": export_dir, "response_dir": os.path.join(export_dir, RESPONSES),
            "manifest_file": manifest_file, "manifest": manifest}
