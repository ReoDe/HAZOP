"""출력/ 정리 후보를 찾고, --apply일 때만 출력/_보관/<시각>/으로 옮긴다(삭제하지 않음).

  python scripts/clean_outputs.py                 # dry-run: 옮길 후보·보존 사유만 출력
  python scripts/clean_outputs.py --keep 3        # 구간별 최근 3개 실행만 남기는 후보
  python scripts/clean_outputs.py --apply         # 후보를 출력/_보관/<UTC 시각>/<원래 상대 경로>로 이동
  --out-root를 주면 --store-root도 함께 줘야 한다. 검토 기록 폴더(<저장 루트>/reviews)가 없으면 --apply에
  --no-review-records를 명시해야 진행한다. 앱·build_kg가 끝난 뒤 --apply 한다.

대상은 두 곳뿐이다. 그 밖(검토본·출력 기록이 있는 저장 루트, 자료저장소/, 출력의 다른 폴더)은 읽기만 하거나 보지 않는다.
1) 출력/분석/<구간>/<실행>/ (analysis.json이 있는 폴더): analysis_run.created_at(없으면 폴더 이름) 기준 최근 --keep개 보존.
   그 밖의 실행도 다음이 참조하면 보존한다: 검토 기록(<저장 루트>/reviews/<region_id>/<analysis_run_id>/),
   평가 비교 보고서(출력/평가비교/<region_id>/<analysis_run_id>/ 또는 그 아래 JSON의 target.analysis_run_id),
   설정 파일(hazop.paths.settings_path)의 recent_runs. analysis.json을 읽을 수 없는 폴더는 건드리지 않는다.
2) 출력/지식그래프/<kg>/ (current.json이 있는 폴더): 옛 경로 파일(<kg>/knowledge.json·knowledge_graph.json)과
   이전 버전 폴더(<kg>/v-…/, <kg>/screen/v-…/, <kg>/algo/v-…/). 다음 버전은 보존한다:
   current.json이 가리키는 버전, ③ 화면이 blocked 때 보여 줄 직전 passed 버전(hazop.kg.screen.previous_passed),
   보존하는 분석 실행이 참조한 버전(analysis_run.versions.knowledge_graph). current.json을 읽을 수 없으면 그 kg는 건드리지 않는다.
   건너뛴 분석 실행(analysis.json 읽기 실패·링크·정션)이 하나라도 있으면 그 실행의 참조를 알 수 없으므로
   버전 폴더는 옮기지 않는다(옛 경로 파일은 옮김).
링크·정션 폴더(기준 폴더 출력/분석·출력/지식그래프와 screen/·algo/ 포함)는 따라가지 않는다.
이동: os.rename만 쓴다(복사 없음). 이동 직전에 검토 기록·평가 비교 참조와 kg current.json 해시를 다시 확인해 바뀌었으면
그 항목을 건너뛴다. 한계: recent_runs와 계획 이후 새로 생긴 분석 실행의 kg 버전 참조는 다시 확인하지 않는다
(앱·analyze·build_kg를 끝낸 뒤 실행한다는 운영 지침에 의존).
기록: 항목마다 rename 전에 출력/_보관/<시각>/manifest.json의 entries에 status "pending"을 먼저 쓰고, 성공하면 "moved"로 고친다.
사전 기록이 실패하면 옮기지 않고 멈추고, rename이 실패하면 "failed"로 기록한 뒤 멈춘다. 갱신이 실패해도 pending 항목으로 복구할 수 있다.
종료 코드 0 = 정상(후보가 없어도 0), 1 = 이동·기록 중 실패, 2 = 인자 오류·이동 전 검사 실패.
"""

import argparse
import datetime
import hashlib
import json
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from hazop import paths  # noqa: E402
from hazop.console import safe_console  # noqa: E402
from hazop.kg import build as kg_build  # noqa: E402

ARCHIVE_DIR = "_보관"
MANIFEST = "manifest.json"
OLD_KG_FILES = (kg_build.KNOWLEDGE_FILE, kg_build.KG_FILE)


def _read_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _file_sha(path):
    try:
        with open(path, "rb") as fh:
            return hashlib.sha256(fh.read()).hexdigest()
    except OSError:
        return None


def _is_plain_dir(path):
    """링크·정션이 아닌 실제 폴더(풀린 경로가 부모 폴더 바로 아래 같은 이름이어야 함)."""
    if not os.path.isdir(path) or os.path.islink(path):
        return False
    expect = os.path.join(os.path.realpath(os.path.dirname(path)), os.path.basename(path))
    return os.path.normcase(os.path.realpath(path)) == os.path.normcase(expect)


def _reviewed(store_root, regions, names):
    return any(os.path.isdir(os.path.join(store_root, "reviews", str(rg), str(n)))
               for rg in regions for n in names if rg and n)


def compare_refs(out_root):
    """평가 비교 보고서가 참조하는 (region, run_id). 폴더 이름과 보고서 JSON의 target 둘 다 모은다."""
    refs = set()
    base = os.path.join(out_root, "평가비교")
    if not _is_plain_dir(base):
        return refs
    for region in os.listdir(base):
        rdir = os.path.join(base, region)
        for run_id in os.listdir(rdir) if _is_plain_dir(rdir) else []:
            d = os.path.join(rdir, run_id)
            if not _is_plain_dir(d) or not os.listdir(d):
                continue
            refs.add((region, run_id))
            for f in os.listdir(d):
                if f.endswith(".json"):
                    try:
                        t = _read_json(os.path.join(d, f)).get("target") or {}
                        refs.add(((t.get("region_ref") or {}).get("region_id") or region, t.get("analysis_run_id")))
                    except (OSError, ValueError, AttributeError):
                        pass
    return refs


def settings_refs(warnings):
    """settings.json recent_runs의 값(문자열 또는 dict 값). 읽기 실패는 경고만 남기고 빈 집합."""
    path = paths.settings_path()
    try:
        runs = paths.load_settings(path).get("recent_runs") or []
    except (OSError, ValueError) as exc:
        warnings.append("설정 파일을 읽을 수 없어 recent_runs 보존을 적용하지 못함: %s (%s)" % (path, exc))
        return set()
    out = set()
    for r in runs if isinstance(runs, list) else []:
        for v in (r.values() if isinstance(r, dict) else [r]):
            if isinstance(v, str) and v:
                out.add(v)
                out.add(os.path.normcase(os.path.abspath(v)))
    return out


def _referenced(item, store_root, out_root, cmp_refs=None):
    """검토 기록·평가 비교 참조 사유(없으면 None)."""
    if _reviewed(store_root, item["regions"], item["names"]):
        return "검토 기록이 참조함"
    cmp_refs = compare_refs(out_root) if cmp_refs is None else cmp_refs
    if any((rg, n) in cmp_refs for rg in item["regions"] for n in item["names"]):
        return "평가 비교 보고서가 참조함"
    return None


def plan_analysis(out_root, store_root, keep, warnings):
    """(move, keep_list, skipped, kg_refs). move 항목은 dict(rel, reason, kind, ...), 나머지는 (상대 경로, 사유)."""
    move, kept, skipped, kg_refs = [], [], [], set()
    base = os.path.join(out_root, "분석")
    if not os.path.isdir(base):
        return move, kept, skipped, kg_refs
    if not _is_plain_dir(base):
        return move, kept, [("분석", "링크·정션 폴더라 건드리지 않음")], kg_refs
    cmp_refs, recent = compare_refs(out_root), settings_refs(warnings)
    for region in sorted(os.listdir(base)):
        rdir = os.path.join(base, region)
        if not os.path.isdir(rdir):
            continue
        if not _is_plain_dir(rdir):
            skipped.append((paths.rel_or_abs(rdir, out_root), "링크·정션 폴더라 건드리지 않음"))
            continue
        runs = []
        for name in sorted(os.listdir(rdir)):
            d = os.path.join(rdir, name)
            rel = paths.rel_or_abs(d, out_root)
            if not os.path.isfile(os.path.join(d, "analysis.json")):
                continue
            if not _is_plain_dir(d):
                skipped.append((rel, "링크·정션 폴더라 건드리지 않음"))
                continue
            try:
                doc = _read_json(os.path.join(d, "analysis.json"))
                run = doc.get("analysis_run") or {}
                region_id = (doc.get("region_ref") or {}).get("region_id") or region
                run_id = doc.get("analysis_run_id") or run.get("analysis_run_id") or name
                kg = (run.get("versions") or {}).get("knowledge_graph") or {}
            except (OSError, ValueError, AttributeError) as exc:
                skipped.append((rel, "analysis.json을 읽을 수 없어 건드리지 않음: %s" % exc))
                continue
            runs.append({"rel": rel, "kind": "analysis_run", "key": (str(run.get("created_at") or name), name),
                         "names": sorted({name, run_id}), "regions": sorted({region, region_id}), "kg": kg,
                         "abs": os.path.normcase(os.path.abspath(d))})
        runs.sort(key=lambda r: r["key"], reverse=True)
        for i, r in enumerate(runs):
            why = "최근 %d개 안" % keep if i < keep else _referenced(r, store_root, out_root, cmp_refs)
            if not why and (r["abs"] in recent or any(n in recent for n in r["names"])):
                why = "설정 recent_runs가 참조함"
            if why:
                kept.append((r["rel"], why))
                if r["kg"].get("id") and r["kg"].get("version"):
                    kg_refs.add((r["kg"]["id"], r["kg"]["version"]))
            else:
                move.append({"rel": r["rel"], "reason": "구간별 최근 %d개 밖의 실행" % keep, "kind": "analysis_run",
                             "names": r["names"], "regions": r["regions"]})
    return move, kept, skipped, kg_refs


def plan_kg(out_root, kg_refs, hold_versions=None):
    """hold_versions: 사유 문자열이면 보호되지 않는 버전 폴더도 옮기지 않고 그 사유로 보존한다."""
    move, kept, skipped = [], [], []
    base = os.path.join(out_root, "지식그래프")
    if not os.path.isdir(base):
        return move, kept, skipped
    if not _is_plain_dir(base):
        return move, kept, [("지식그래프", "링크·정션 폴더라 건드리지 않음")]
    for name in sorted(os.listdir(base)):
        kg_root = os.path.join(base, name)
        pointer = os.path.join(kg_root, kg_build.POINTER_FILE)
        if not os.path.isfile(pointer):
            continue
        rel_root = paths.rel_or_abs(kg_root, out_root)
        if not _is_plain_dir(kg_root):
            skipped.append((rel_root, "링크·정션 폴더라 건드리지 않음"))
            continue
        try:
            ptr = _read_json(pointer)
            current = ptr["kg_version"]
            kg_build.current_dir(kg_root)  # 형식·위치 검사
        except (OSError, ValueError, KeyError, TypeError) as exc:
            skipped.append((rel_root, "current.json을 읽을 수 없어 건드리지 않음: %s" % exc))
            continue
        from hazop.kg import screen  # 무거운 모듈은 필요할 때만
        prev = screen.previous_passed(kg_root, current)
        protect = {current: "current.json이 가리킴"}
        if prev:
            protect.setdefault(prev[0], "③ 화면의 직전 passed 버전")
        for kg_id, ver in kg_refs:
            if kg_id == ptr.get("kg_id"):
                protect.setdefault(ver, "보존하는 분석 실행이 참조함")
        check = {"kind": "kg", "pointer": paths.rel_or_abs(pointer, out_root), "pointer_sha256": _file_sha(pointer)}
        for f in OLD_KG_FILES:
            if os.path.isfile(os.path.join(kg_root, f)):
                move.append(dict(check, rel=rel_root + "/" + f, reason="옛 경로 파일(current.json 이전 형식)"))
        for sub in ("", "screen", "algo"):
            d = os.path.join(kg_root, sub) if sub else kg_root
            if not os.path.isdir(d):
                continue
            if not _is_plain_dir(d):
                skipped.append((paths.rel_or_abs(d, out_root), "링크·정션 폴더라 건드리지 않음"))
                continue
            for ver in sorted(os.listdir(d)):
                p = os.path.join(d, ver)
                if not kg_build.VERSION_RE.match(ver) or not os.path.isdir(p):
                    continue
                rel = paths.rel_or_abs(p, out_root)
                if not _is_plain_dir(p):
                    skipped.append((rel, "링크·정션 폴더라 건드리지 않음"))
                elif ver in protect:
                    kept.append((rel, protect[ver]))
                elif hold_versions:
                    kept.append((rel, hold_versions))
                else:
                    move.append(dict(check, rel=rel, reason="이전 버전 폴더"))
    return move, kept, skipped


def make_plan(out_root, store_root, keep):
    warnings = []
    a_move, a_kept, a_skip, refs = plan_analysis(out_root, store_root, keep, warnings)
    hold = "참조를 확인할 수 없는 분석 실행 있음" if a_skip else None
    k_move, k_kept, k_skip = plan_kg(out_root, refs, hold)
    return {"move": a_move + k_move, "keep": a_kept + k_kept, "skipped": a_skip + k_skip, "warnings": warnings}


def _write_manifest(path, doc):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    os.replace(tmp, path)


def _changed(item, out_root, store_root):
    """이동 직전 재확인. 바뀌었으면 사유, 아니면 None."""
    if item["kind"] == "analysis_run":
        return _referenced(item, store_root, out_root)
    if _file_sha(os.path.join(out_root, *item["pointer"].split("/"))) != item["pointer_sha256"]:
        return "current.json이 계획 이후 바뀜"
    return None


def apply_plan(plan, out_root, store_root, stamp):
    """후보를 <out_root>/_보관/<stamp>/<상대 경로>로 os.rename한다. manifest.json의 entries에 rename 전 "pending",
    성공 후 "moved", 실패 시 "failed"를 기록한다. 재확인에서 바뀐 항목은 건너뛴다(skipped).
    기록·rename이 실패하면 그 자리에서 OSError를 올린다(그 뒤 항목은 손대지 않음).
    보관 폴더가 이미 있거나 정리 대상 밖 경로면 ValueError(아무것도 옮기지 않음). manifest 경로를 돌려준다."""
    archive = os.path.join(out_root, ARCHIVE_DIR)
    if os.path.exists(archive) and not _is_plain_dir(archive):
        raise ValueError("보관 폴더가 링크·정션임: %s" % archive)
    if paths.safe_name(stamp) != stamp:
        raise ValueError("보관 폴더 이름으로 쓸 수 없음: %r" % stamp)
    dest_root = os.path.join(archive, stamp)
    if os.path.exists(dest_root):
        raise ValueError("보관 폴더가 이미 있음: %s" % dest_root)
    allowed = []
    for d in ("분석", "지식그래프"):
        b = os.path.join(out_root, d)
        if _is_plain_dir(b):
            allowed.append(os.path.realpath(b))
    for item in plan["move"]:
        real = os.path.realpath(os.path.join(out_root, *item["rel"].split("/")))
        if not any(os.path.commonpath([a, real]) == a and real != a for a in allowed):
            raise ValueError("정리 대상 밖 경로: %s" % item["rel"])
    os.makedirs(dest_root)
    manifest_path = os.path.join(dest_root, MANIFEST)
    doc = {"created_at": stamp, "out_root": os.path.abspath(out_root), "entries": [], "skipped": []}
    _write_manifest(manifest_path, doc)
    for item in plan["move"]:
        src = os.path.join(out_root, *item["rel"].split("/"))
        dst = os.path.join(dest_root, *item["rel"].split("/"))
        why = _changed(item, out_root, store_root)
        if why:
            doc["skipped"].append({"original": item["rel"], "reason": why})
            _write_manifest(manifest_path, doc)
            continue
        entry = {"original": item["rel"], "archived": paths.rel_or_abs(dst, out_root), "reason": item["reason"],
                 "status": "pending"}
        doc["entries"].append(entry)
        _write_manifest(manifest_path, doc)  # 실패하면 옮기지 않고 멈춤
        try:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            os.rename(src, dst)
        except OSError as exc:
            entry.update(status="failed", error=str(exc))
            _write_manifest(manifest_path, doc)
            raise
        entry["status"] = "moved"
        _write_manifest(manifest_path, doc)  # 실패해도 디스크에는 pending 항목이 남음
    return manifest_path


def main(argv=None):
    safe_console()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--keep", type=int, default=5, help="구간별로 남길 최근 분석 실행 수 (기본 %(default)s)")
    ap.add_argument("--apply", action="store_true", help="후보를 출력/_보관/<시각>/으로 옮긴다(없으면 dry-run)")
    ap.add_argument("--out-root", help="출력 루트 (기본 %s). 주면 --store-root도 필수" % paths.output_root())
    ap.add_argument("--store-root", help="검토 기록 저장 루트 (기본 %s)" % paths.store_root())
    ap.add_argument("--no-review-records", action="store_true",
                    help="검토 기록 폴더가 없어도 --apply를 진행(검토 기록 참조 보존 없이)")
    args = ap.parse_args(argv)
    if args.keep < 1:
        ap.error("--keep은 1 이상")
    if args.out_root and not args.store_root:
        ap.error("--out-root를 주면 --store-root도 함께 줘야 함")
    out_root = args.out_root or paths.output_root()
    store_root = args.store_root or paths.store_root()
    reviews = os.path.join(store_root, "reviews")
    plan = make_plan(out_root, store_root, args.keep)
    for w in plan["warnings"]:
        print("경고:", w)
    if not os.path.isdir(reviews):
        print("참고: 검토 기록 폴더 없음(%s) - 검토 기록 참조 보존은 적용할 것이 없음" % reviews)
    for label, key in (("보존", "keep"), ("건드리지 않음", "skipped")):
        print("== %s %d건" % (label, len(plan[key])))
        for rel, why in plan[key]:
            print("  %s  (%s)" % (rel, why))
    print("== 옮길 후보 %d건" % len(plan["move"]))
    for item in plan["move"]:
        print("  %s  (%s)" % (item["rel"], item["reason"]))
    if not args.apply:
        print("dry-run: 옮기지 않음. 옮기려면 --apply (앱·build_kg 종료 후)")
        return 0
    if not os.path.isdir(reviews) and not args.no_review_records:
        print("중단: 검토 기록 폴더가 없음. 저장 루트가 맞는지 확인하고, 맞으면 --no-review-records를 함께 지정")
        return 2
    if not plan["move"]:
        print("옮길 후보 없음")
        return 0
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    manifest = os.path.join(out_root, ARCHIVE_DIR, stamp, MANIFEST)
    try:
        apply_plan(plan, out_root, store_root, stamp)
    except ValueError as exc:
        print("중단(옮기지 않음): %s" % exc)
        return 2
    except OSError as exc:
        where = ("그때까지 기록: %s" % manifest) if os.path.isfile(manifest) else "기록 파일 없음"
        print("이동·기록 실패 - 즉시 멈춤: %s (%s)" % (exc, where))
        return 1
    doc = _read_json(manifest)
    moved = sum(e["status"] == "moved" for e in doc["entries"])
    print("옮김 %d건, 건너뜀 %d건 -> %s" % (moved, len(doc["skipped"]), manifest))
    return 0


if __name__ == "__main__":
    sys.exit(main())
