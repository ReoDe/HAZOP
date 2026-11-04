"""추출 결과의 검증 보고서(Markdown)."""


def _table_rows(items):
    rows = ["| 검사 | 대상 local_id | 원본 객체 ID | 필드 | 사유 |", "| --- | --- | --- | --- | --- |"]
    for it in items:
        rows.append("| %s | %s | %s | %s | %s |" % (
            it["check"], it["target"] or "-", it["source_object_id"] or "-",
            it["field"] or "-", str(it["reason"]).replace("|", "\\|")))
    return rows


def render(result):
    s = result["summary"]
    v = result["validation"]
    d = result["drawing"]
    lines = [
        "# 추출 검증 보고서: %s" % (d["drawing_number"] or result["source_context"]["page_name"]),
        "",
        "| 항목 | 값 |",
        "| --- | --- |",
        "| 원본 파일 | `%s` |" % result["source"]["file"],
        "| SHA-256 | `%s` |" % result["source"]["sha256"],
        "| 압축 저장 | %s |" % ("예" if result["source"]["compressed"] else "아니오"),
        "| 추출 실행 ID | `%s` |" % result["extraction_run_id"],
        "| 스크립트·규칙 버전 | %s %s / %s |" % (result["run"]["script"], result["run"]["script_version"],
                                         result["run"]["rules_version"]),
        "| 도면 제목 | %s |" % (d["title"] or "-"),
        "| 구조 검증 | **%s** |" % v["status"],
        "",
        "## 개수",
        "",
        "| 구분 | 개수 |",
        "| --- | --- |",
        "| 노드(도형) | %d (미분류 %d) |" % (s["nodes"], s["nodes_unclassified"]),
        "| 관계(양 끝 접속 커넥터) | %d |" % s["relations"],
        "| 미해결 커넥터 | %d |" % s["unresolved_connectors"],
        "| 독립 텍스트 | %d |" % s["texts"],
        "| 미분류 요소 | %d |" % s["unclassified_elements"],
        "| 추출 제외(pidIgnore) | %d |" % s["ignored_objects"],
        "",
        "관계 종류별: " + (", ".join("%s %d" % kv for kv in sorted(s["relations_by_kind"].items())) or "없음"),
        "",
        "## 차단 오류 (%d)" % len(v["blockers"]),
        "",
    ]
    lines += _table_rows(v["blockers"]) if v["blockers"] else ["없음"]
    lines += ["", "## 미확인 항목 (%d)" % len(v["unknowns"]), ""]
    lines += _table_rows(v["unknowns"]) if v["unknowns"] else ["없음"]
    al = result["coordinate_system"].get("svg_alignment")
    lines += ["", "## SVG 좌표 대응", ""]
    if al:
        lines += [
            "- SVG: `%s` (viewBox `%s`)" % (al["svg_file"], al["viewBox"]),
            "- offset: %s → %s" % (al["offset"], al["transform"]),
            "- 비교 셀 %d개 중 일치 %d개, 불일치 %s" % (al["compared_cells"], al["consistent_cells"],
                                              al["inconsistent_offsets"] or "없음"),
            "- SVG에 없는 추출 객체: %s" % (al["cells_missing_in_svg"] or "없음"),
        ]
    else:
        lines.append("SVG 미지정")
    lines += ["", "라벨 bbox와 커넥터 bbox는 근사값(`approximate: true`)이다. 미확인 항목은 값을 생성하지 않고 그대로 둔다.", ""]
    return "\n".join(lines)
