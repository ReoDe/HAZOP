"""단계 ② 원본 대조 뷰어 빌드: 추출 결과 JSON + draw.io SVG -> 자체 완결 HTML.

근거: 기획서/정보추출.md #viewer. file://로 열 수 있도록 데이터와 SVG를 HTML에 인라인으로 넣고
외부 요청(fetch·CDN·네트워크)을 쓰지 않는다.
"""

import html
import json
import os
import re

from hazop import paths
from hazop.app import tokens
from hazop.viewer import sanitize

TEMPLATE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "template.html")

# 뷰어 템플릿(HTML·JS)이 쓰는 id 전체. 배경 SVG의 id는 sanitize.ID_PREFIX("svg-")가 붙어 이 목록과 겹치지 않아야 한다.
# 템플릿에 id를 추가하면 여기에도 추가한다(tests/test_viewer.py가 대조).
TEMPLATE_IDS = frozenset("""
alignwarn dwg dwgtitle extraction g-all g-layout g-none glegend graph graphsvg layer-pipe layer-symbol
layer-tag layers legend-btn legend-drop n-pipe n-symbol n-tag overlay panel pathq pct pq-a pq-a-sel pq-b pq-b-sel
pq-body pq-chip pq-clear pq-close pq-go pq-list pq-mode pq-res q results search seglegend stage status taglabels tab-drawing
tab-graph tooltip viewport zfit zin zoom zout
""".split())


def prepare_svg(svg_text):
    """draw.io SVG를 HTML 인라인용으로 정화한다(hazop.viewer.sanitize: XML 파싱 + 허용 목록).

    - 허용 목록 밖의 요소(script·style·animate·set·iframe 등)와 속성(on*, 외부·javascript: URL 등)을 버린다.
    - <a>는 링크를 버리고 내용만 남긴다(draw.io 'Text is not SVG' 안내 링크 포함).
    - 루트는 width·height·viewBox·version만 남기고(내장 drawio 모델 content 속성 제거) 흰 배경을 지정한다.
    - XML로 읽을 수 없는 SVG는 거부한다(ValueError).
    """
    return sanitize.sanitize_svg(svg_text, {"style": "background: %s;" % tokens.c("card")})


def _json_for_script(data):
    # '<'를 모두 \\u003c 이스케이프로 바꿔 </script>·<!-- 로 스크립트 블록이 끊기거나 바뀌지 않게 한다.
    return json.dumps(data, ensure_ascii=False).replace("<", "\\u003c")


_PLACEHOLDER = re.compile(r"__(TITLE|ALIGN_WARNING|SVG|GRAPH|DATA)__")


def build_drawing_html(extraction, svg_text, graph=None):
    """graph가 있으면 그래프 탭·경로 질의를 켠다. graph는 같은 추출 실행에서 만든 것이어야 한다."""
    al = extraction["coordinate_system"].get("svg_alignment")
    if not al or al.get("offset") is None:
        raise ValueError("coordinate_system.svg_alignment.offset 없음: 추출 시 SVG 대응을 먼저 측정해야 함")
    if graph is not None and extraction["extraction_run_id"] not in graph.get("input_runs", []):
        raise ValueError("그래프의 input_runs에 추출 실행 %r 가 없음(그래프가 오래됨)" % extraction["extraction_run_id"])
    with open(TEMPLATE, encoding="utf-8") as fh:
        tpl = fh.read()
    title = "%s · %s" % (extraction["drawing"].get("drawing_number") or "",
                         extraction["drawing"].get("title") or "")
    warns = []
    if al.get("status") != "verified":
        warns.append("SVG 좌표 정렬 미검증: %s" % "; ".join(al.get("reasons") or ["판정 정보 없음"]))
    if graph is not None and graph["validation"]["status"] != "passed":
        warns.append("그래프 구조 검증 %s: %s" % (graph["validation"]["status"], "; ".join(
            "%s %s" % (b["check"], b.get("target") or "") for b in graph["validation"]["blockers"]) or "사유 없음"))
    warn = " / ".join(warns)
    values = {"TITLE": html.escape(title), "ALIGN_WARNING": html.escape(warn), "SVG": prepare_svg(svg_text),
              "GRAPH": _json_for_script(graph), "DATA": _json_for_script(extraction)}
    # 템플릿의 자리표시자만 한 번에 치환한다(SVG·데이터 안의 같은 문자열은 다시 치환되지 않음).
    return _PLACEHOLDER.sub(lambda m: values[m.group(1)], tpl)


def build_index(entries):
    rows = []
    for e in entries:
        s = e["summary"]
        rows.append(
            "<tr><td><a href=\"%s\">%s</a></td><td>%s</td><td>%d</td><td>%d</td><td>%d</td><td>%d</td><td>%s</td><td>%s</td><td>%s</td></tr>"
            % (html.escape(e["file"]), html.escape(e["drawing_number"]), html.escape(e["title"] or ""),
               s["nodes"], s["relations"], s["unresolved_connectors"], s["unknowns"],
               html.escape(e["status"]), html.escape(str(e.get("align_status"))),
               "%d / %d" % (e["graph"]["node_count"], e["graph"]["edge_count"]) if e.get("graph") else "없음"))
    return """<!DOCTYPE html>
<html lang="ko"><head><meta charset="utf-8"><title>HAZOP 추출 뷰어 - 도면 목록</title>
<style>
body { margin: 0; padding: 32px; font-family: "Pretendard", "Malgun Gothic", sans-serif; background: %(bg)s; color: %(ink)s; }
h1 { font-size: 22px; } p { color: %(muted)s; font-size: 13px; }
table { border-collapse: collapse; background: %(card)s; border-radius: 16px; overflow: hidden; box-shadow: %(shadow)s; }
th, td { padding: 10px 16px; text-align: left; font-size: 14px; border-bottom: 1px solid %(line)s; }
th { color: %(muted)s; font-weight: 600; font-size: 12px; } a { color: %(ui)s; font-weight: 700; text-decoration: none; }
</style></head><body>
<h1>HAZOP 추출 뷰어 · 도면 목록</h1>
<p>로컬 정적 파일입니다. 외부로 자료를 보내지 않습니다.</p>
<table><tr><th>도면 번호</th><th>제목</th><th>노드</th><th>관계</th><th>미해결 커넥터</th><th>미확인</th><th>구조 검증</th><th>SVG 정렬</th><th>그래프 노드 / 엣지</th></tr>
%(rows)s
</table></body></html>
""" % dict(tokens.COLORS, shadow=tokens.CARD_SHADOW, rows="\n".join(rows))


def load_graph(graph_root, name):
    """graph_root/<name>/graph.json. 없으면 None."""
    if not graph_root:
        return None
    path = os.path.join(paths.safe_join(graph_root, paths.safe_name(name)), "graph.json")
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _svg_path(svg_rel, roots):
    """svg_file(첫 루트 기준 상대 경로 또는 절대 경로)이 허용 루트 중 하나의 안에 있을 때만 경로를 돌려준다.
    어느 루트 안에도 없으면 ValueError(기존 safe_join 오류)."""
    target = os.path.join(roots[0], svg_rel)
    for root in roots[1:]:
        try:
            return paths.safe_join(root, target)
        except ValueError:
            continue
    return paths.safe_join(roots[0], svg_rel)


def build_all(extract_root, out_root, repo_root, graph_root=None, svg_roots=()):
    """extract_root/<도면번호>/extraction.json 마다 out_root/<도면번호>.html, 그리고 index.html.
    graph_root/<도면번호>/graph.json이 있으면 함께 넣는다.
    SVG는 repo_root(작업 루트) 안 또는 svg_roots(예: 등록 저장 루트, 파생 SVG 보관 위치) 안에 있어야 한다."""
    os.makedirs(out_root, exist_ok=True)
    entries = []
    for name in sorted(os.listdir(extract_root)):
        path = os.path.join(extract_root, name, "extraction.json")
        if not os.path.isfile(path):
            continue
        with open(path, encoding="utf-8") as fh:
            extraction = json.load(fh)
        svg_rel = (extraction["coordinate_system"].get("svg_alignment") or {}).get("svg_file")
        if not svg_rel:
            raise ValueError("%s: SVG 파일 정보 없음" % name)
        with open(_svg_path(svg_rel, [repo_root] + list(svg_roots)), encoding="utf-8") as fh:
            svg_text = fh.read()
        al = extraction["coordinate_system"].get("svg_alignment") or {}
        fname = "%s.html" % paths.safe_name(name)
        graph = load_graph(graph_root, name)
        with open(paths.safe_join(out_root, fname), "w", encoding="utf-8", newline="\n") as fh:
            fh.write(build_drawing_html(extraction, svg_text, graph))
        entries.append({"file": fname, "drawing_number": extraction["drawing"].get("drawing_number") or name,
                        "title": extraction["drawing"].get("title"), "summary": extraction["summary"],
                        "status": extraction["validation"]["status"], "align_status": al.get("status"),
                        "graph": graph["structure"] if graph else None})
    with open(paths.safe_join(out_root, "index.html"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write(build_index(entries))
    return entries
