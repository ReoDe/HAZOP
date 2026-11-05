"""④⑤가 함께 쓰는 '열린 실행' 상태. 실행은 읽기 전용으로 연다(hazop.review.open_run)."""

import os

from hazop import paths
from hazop import review as rv
from hazop.app import data


class RunContext:
    def __init__(self, run_dir, store_root=None):
        self.run_dir = os.path.abspath(run_dir)
        self.store_root = store_root or paths.store_root()
        self.run = rv.open_run(self.run_dir)
        self.doc = self.run["doc"]
        self.run_graph = self.run["graph"]
        self.region_id = self.doc["region_ref"]["region_id"]
        self.tags = {n["entity_id"]: n.get("tag") for n in (self.run_graph or {}).get("nodes", [])}
        p = paths.work_path("데이터", "구간", "%s.json" % paths.safe_name(self.region_id))
        self.region_path = p if os.path.isfile(p) else None
        run_region = os.path.join(self.run_dir, "inputs", "region.json")
        region = data.read_json(run_region) if os.path.isfile(run_region) else (
            data.read_json(self.region_path) if self.region_path else {})
        self.drawing_name = data.extraction_name_for_graph_file((region.get("graph_ref") or {}).get("graph_file"))
        self.viewer = None
        self.viewer_error = None
        if self.drawing_name and os.path.isfile(os.path.join(paths.output_root("추출"), self.drawing_name,
                                                             "extraction.json")):
            try:
                self.viewer = data.viewer_html_for(self.drawing_name)
                self.viewer_error = self.viewer["error"]
            except (OSError, ValueError, KeyError) as exc:
                self.viewer_error = "뷰어를 만들 수 없음: %s" % exc
        else:
            self.viewer_error = "현재 도면의 추출 결과가 없음(%s) — ①에서 추출·그래프를 만들어야 도면에 강조할 수 있음" % self.drawing_name
        vg = (self.viewer or {}).get("graph")
        run_v = (self.run_graph or {}).get("graph_version")
        # 분석 당시 그래프와 현재 도면 그래프 버전이 다르면 강조를 끈다(§3.3 그래프 버전 불일치)
        self.version_mismatch = bool(vg) and run_v != vg.get("graph_version")
        self.current_graph_version = (vg or {}).get("graph_version")
        self.local_map = {} if self.version_mismatch or not (self.viewer or {}).get("html") else \
            data.entity_local_map(self.run_graph)
        self.missing_local = set()
        self.records = {}
        self.reload_reviews()

    def reload_reviews(self):
        self.records = rv.load_run_reviews(self.store_root, self.region_id, self.doc["analysis_run_id"])
        self.summary = rv.review_summary(self.doc, self.records)
        return self.records

    def html(self):
        return (self.viewer or {}).get("html")

    def candidate(self, cid):
        return next(c for c in self.doc["candidates"] if c["candidate_id"] == cid)

    def scenarios_of(self, cid):
        return [s for s in self.doc["scenarios"] if s["candidate_id"] == cid]

    def dics_of(self, cid):
        return [d for d in self.doc["design_improvement_candidates"] if d["candidate_id"] == cid]

    def holds_of(self, cid):
        sids = {s["scenario_id"] for s in self.scenarios_of(cid)}
        return [h for h in self.doc["holds"] if h.get("candidate_id") == cid or h.get("scope") in sids]

    def scenario(self, sid):
        return next(s for s in self.doc["scenarios"] if s["scenario_id"] == sid)

    def evidence(self, scenario):
        return data.evidence_summary(self.doc, scenario, self.run_graph, self.local_map,
                                     self.version_mismatch or not self.html(), self.missing_local)

    def highlight_spec(self, scenario):
        if self.version_mismatch or not self.local_map:
            return None
        return data.highlight_spec(scenario, self.local_map, self.run_graph)

    def editable(self, cid):
        return rv.check_editable(self.run, self.records.get(cid))
