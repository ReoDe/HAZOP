"""빌드된 뷰어 HTML 자동 검사 (브라우저 없이 정적으로)."""

import json
import re

from hazop.viewer import sanitize

# 네트워크 요청을 일으킬 수 있는 참조. xmlns·requiredFeatures 같은 식별자 URI는 요청이 아니므로 제외.
_EXTERNAL_PATTERNS = [
    re.compile(r'\b(?:src|href|xlink:href|action|poster|data)\s*=\s*["\']\s*(?:https?:)?//', re.I),
    re.compile(r"url\(\s*['\"]?\s*(?:https?:)?//", re.I),
    re.compile(r"@import", re.I),
    re.compile(r"\bfetch\s*\("),
    re.compile(r"XMLHttpRequest|WebSocket|EventSource|navigator\.sendBeacon"),
    re.compile(r"<(?:iframe|embed|object)\b", re.I),
]


def external_refs(text):
    found = []
    for pat in _EXTERNAL_PATTERNS:
        for m in pat.finditer(text):
            found.append(text[max(0, m.start() - 20):m.end() + 40])
    return found


TEMPLATE_SCRIPT_COUNT = 3  # 템플릿 자체의 <script>: 내장 JSON 2(그래프·추출) + 뷰어 코드 1


_STAGE = re.compile(r'<div id="stage">(.*?)<svg id="overlay"', re.S)
_JSON_BLOCK = re.compile(r'(<script type="application/json" id="\w+">)(.*?)(</script>)', re.S)


def stage_markup(html_text):
    """배경 SVG가 들어가는 영역(#stage 시작 ~ 오버레이 SVG 직전)."""
    m = _STAGE.search(html_text)
    return m.group(1) if m else None


def active_content(html_text):
    """실행 가능 요소 검사.
    - 배경 SVG 영역: 정화기와 같은 XML 파서·허용 목록(sanitize.violations)으로 검사
    - 나머지(템플릿): <script> 개수, on* 이벤트 속성, javascript:/vbscript: (내장 JSON 내용은 제외하고 검사)
    """
    found = []
    stage = stage_markup(html_text)
    if stage is None:
        found.append("배경 SVG 영역(#stage)을 찾을 수 없음")
    else:
        try:
            root = sanitize.parse('<root xmlns:xlink="%s">%s</root>' % (sanitize.XLINK_NS, stage))
            found += ["배경 SVG: %s" % v for v in sanitize.violations(root) if v != "허용되지 않은 요소 <root>"]
        except ValueError as exc:
            found.append("배경 SVG 영역 XML 파싱 실패: %s" % exc)
    n = len(re.findall(r"<script\b", html_text, re.I))
    if n != TEMPLATE_SCRIPT_COUNT:
        found.append("<script> 개수 %d (기대 %d)" % (n, TEMPLATE_SCRIPT_COUNT))
    for m in _JSON_BLOCK.finditer(html_text):
        if "<" in m.group(2):
            found.append("내장 JSON에 이스케이프되지 않은 '<' 있음: %s" % m.group(1))
    # 스크립트 본문(템플릿 JS·내장 JSON)은 개수로만 검사하고, 마크업 속성 검사에서는 제외한다.
    rest = re.sub(r"(<script\b[^>]*>)(.*?)(</script\s*>)", r"\1\3", html_text, flags=re.S | re.I)
    if stage is not None:
        rest = rest.replace(stage, "")
    for m in re.finditer(r"""[\s"'/]on[a-z]+\s*=""", rest, re.I):
        found.append("이벤트 속성: %r" % rest[max(0, m.start() - 10):m.end() + 30])
    if re.search(r"(?:javascript|vbscript)\s*:", rest, re.I):
        found.append("javascript:/vbscript: URL 있음")
    return found


def id_conflicts(html_text):
    """배경 SVG의 id가 템플릿 id를 가로챌 수 있는지 검사.
    - SVG 영역의 id는 모두 sanitize.ID_PREFIX로 시작하고 템플릿 id(build.TEMPLATE_IDS)와 겹치지 않아야 함
    - 정적 마크업(스크립트 본문 제외)에서 템플릿 id가 두 번 이상 나오면 안 됨"""
    from hazop.viewer.build import TEMPLATE_IDS  # 순환 import 방지
    found = []
    stage = stage_markup(html_text) or ""
    for sid in re.findall(r'\sid\s*=\s*["\']([^"\']*)["\']', stage):
        if not sid.startswith(sanitize.ID_PREFIX) or sid in TEMPLATE_IDS:
            found.append("배경 SVG id 충돌 위험: %r" % sid)
    markup = re.sub(r"(<script\b[^>]*>)(.*?)(</script\s*>)", r"\1\3", html_text, flags=re.S | re.I)
    counts = {}
    for i in re.findall(r'\sid\s*=\s*["\']([^"\']*)["\']', markup):
        counts[i] = counts.get(i, 0) + 1
    for i in sorted(TEMPLATE_IDS):
        if counts.get(i, 0) > 1:
            found.append("템플릿 id 중복: %r (%d회)" % (i, counts[i]))
    return found


def embedded_data(html_text, name="extraction"):
    m = re.search(r'<script type="application/json" id="%s">(.*?)</script>' % name, html_text, re.S)
    if m is None:
        raise ValueError("내장 데이터 없음: %s" % name)
    return json.loads(m.group(1))


def _inside(x, y, vb):
    return vb[0] <= x <= vb[0] + vb[2] and vb[1] <= y <= vb[1] + vb[3]


def check_drawing_html(html_text, extraction, graph=None):
    """문제 목록을 돌려준다. 빈 목록이면 통과. graph를 주면 내장 그래프도 대조한다."""
    problems = []
    data = embedded_data(html_text)
    for key in ("nodes", "relations", "unresolved_connectors"):
        want = {x["local_id"] for x in extraction[key]}
        have = {x["local_id"] for x in data.get(key, [])}
        if want - have:
            problems.append("%s 누락: %s" % (key, sorted(want - have)))
    svg_ids = set(re.findall(r'data-cell-id="([^"]+)"', html_text))
    for x in data["nodes"] + data["relations"] + data["unresolved_connectors"]:
        if x["source_object_id"] not in svg_ids:
            problems.append("SVG에 data-cell-id 없음: %s" % x["source_object_id"])

    m = re.search(r'<svg\b[^>]*\bviewBox="([^"]+)"', html_text)
    if m is None:
        problems.append("배경 SVG viewBox 없음")
        return problems
    vb = [float(v) for v in re.split(r"[ ,]+", m.group(1).strip())]
    al = data["coordinate_system"].get("svg_alignment") or {}
    if al.get("offset") is None:
        problems.append("svg_alignment.offset 없음")
        return problems
    ox, oy = al["offset"]

    def check_box(owner, box):
        x, y, w, h = box
        for px, py in ((x, y), (x + w, y + h)):
            if not _inside(px - ox, py - oy, vb):
                problems.append("viewBox 밖 좌표: %s %s" % (owner, box))
                return

    for loc in data["source_locations"]:
        check_box(loc["local_id"], loc["bbox"])
    for n in data["nodes"]:
        if n.get("label_location"):
            check_box(n["local_id"] + " label", n["label_location"]["bbox"])
    for r in data["relations"] + data["unresolved_connectors"]:
        for p in [ep["point"] for ep in r["endpoints"] if ep["point"]] + r["waypoints"]:
            if not _inside(p[0] - ox, p[1] - oy, vb):
                problems.append("viewBox 밖 좌표: %s %s" % (r["local_id"], p))

    for ref in external_refs(html_text):
        problems.append("외부 참조: %r" % ref)
    problems += active_content(html_text)
    problems += id_conflicts(html_text)
    if al.get("status") != "verified":
        problems.append("SVG 좌표 정렬 미검증: %s" % al.get("reasons"))
        if "SVG 좌표 정렬 미검증" not in html_text.split('<script type="application/json"')[0]:
            problems.append("정렬 미검증 경고가 화면에 없음")
    if graph is not None:
        problems += _check_graph_data(html_text, data, graph, vb, ox, oy, _inside)
    return problems


def _check_graph_data(html_text, data, graph, vb, ox, oy, inside):
    problems = []
    g = embedded_data(html_text, "graph")
    if g is None:
        return ["내장 그래프 없음"]
    for key in ("nodes", "edges"):
        want = {x["entity_id"] for x in graph[key]}
        have = {x["entity_id"] for x in g.get(key, [])}
        if want != have:
            problems.append("그래프 %s 불일치: 누락 %s, 추가 %s" % (key, sorted(want - have), sorted(have - want)))
    if data["extraction_run_id"] not in g.get("input_runs", []):
        problems.append("그래프 input_runs에 추출 실행 없음")
    if g.get("graph_version") != graph.get("graph_version"):
        problems.append("그래프 버전 불일치: 내장 %s / 파일 %s" % (g.get("graph_version"), graph.get("graph_version")))
    if g["validation"]["status"] != "passed":
        problems.append("그래프 구조 검증 %s" % g["validation"]["status"])
        if "그래프 구조 검증" not in html_text.split('<script type="application/json"')[0]:
            problems.append("그래프 검증 경고가 화면에 없음")
    local_ids = {x["local_id"] for x in data["nodes"] + data["relations"]}
    for n in g["nodes"]:
        if n["local_id"] not in local_ids:
            problems.append("그래프 노드의 local_id가 추출 데이터에 없음: %s" % n["entity_id"])
        if n.get("position") and not inside(n["position"][0] - ox, n["position"][1] - oy, vb):
            problems.append("그래프 노드 위치가 viewBox 밖: %s %s" % (n["entity_id"], n["position"]))
    return problems
