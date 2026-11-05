"""후보 추출(PDF 등) 좌표 → 정답(drawio) 좌표 변환 추정과 잔차 보고 (T3 W3, 평가 전용).

어댑터는 정답 좌표를 모르므로(블라인드) 변환을 추정하지 않는다. 평가할 때만 이 모듈이
양쪽에 한 번씩만 나오는 같은 보이는 글자(evaluation.normalize_text)를 가진 노드를 기준점으로 삼아
축별 최소제곱(정답 = 후보 × scale + offset, 결정 D3 형식)으로 변환을 구하고 잔차를 남긴다.
기준점 중심은 노드 bbox 중심이다. 영향력이 큰 이상치에 끌리지 않도록 초기 변환은 기준점 두 개씩의 조합
(글자 순 정렬 후 전수, 쌍이 상한보다 많으면 전체 쌍 순번에서 고정 보폭으로 고른 층화 표본)마다 변환을 구해 허용 잔차 안에 드는 기준점이 가장 많은 것을 고른다(결정적 합의).
그 기준점으로 최소제곱을 다시 하고, 잔차가 큰 기준점을 빼고 한 번 더 맞춘다(뺀 목록을 결과에 남김).
기준점이 모자라거나, 최종 변환이 유한하지 않거나 scale이 0이거나, 잔차 RMS가 상한을 넘으면
status=blocked(조용히 평가하지 않는다).
"""

import math
from collections import Counter

from . import evaluation as ev

ALIGN_VERSION = "0.2.0"
DEFAULTS = {
    "min_anchors": 3,
    "outlier_factor": 3.0,   # 잔차 > max(중앙값 × 배수, 하한)이면 기준점에서 뺀다
    "outlier_floor": 2.0,    # 정답 좌표 단위
    "max_rms": 5.0,          # 잔차 RMS 상한(정답 좌표 단위), 넘으면 blocked
    "consensus_tol": 2.0,    # 합의 초기 추정: 이 잔차 안이면 같은 변환을 따르는 기준점(정답 좌표 단위)
    "consensus_max_pairs": 500,  # 합의 초기 추정에서 볼 기준점 쌍 상한(넘으면 전체 쌍에서 고정 보폭 표본)
}


def _center(b):
    return (b[0] + b[2] / 2.0, b[1] + b[3] / 2.0)


def anchors(truth, candidate):
    """[(글자, 후보 중심, 정답 중심)] — 양쪽에서 한 번씩만 나오는 보이는 글자, 글자 순."""
    def unique(view):
        count = Counter(v["text"] for v in view if v["text"] and v["bbox"])
        return {v["text"]: v for v in view if v["text"] and v["bbox"] and count[v["text"]] == 1}
    t, c = unique(ev.node_view(truth)), unique(ev.node_view(candidate))
    return [(text, _center(c[text]["bbox"]), _center(t[text]["bbox"])) for text in sorted(set(t) & set(c))]


def _fit(xs, ys):
    """ys = s × xs + o 최소제곱. 분산이 0이면 None."""
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx == 0:
        return None
    s = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    return s, my - s * mx


def _solve(pairs):
    fx = _fit([p[1][0] for p in pairs], [p[2][0] for p in pairs])
    fy = _fit([p[1][1] for p in pairs], [p[2][1] for p in pairs])
    if fx is None or fy is None:
        return None, []
    res = [math.hypot(p[1][0] * fx[0] + fx[1] - p[2][0], p[1][1] * fy[0] + fy[1] - p[2][1]) for p in pairs]
    return (fx[0], fy[0], fx[1], fy[1]), res


def _pair_model(a, b):
    """기준점 두 개로 정한 변환(sx, sy, ox, oy). 어느 축이든 후보 좌표가 같으면 None."""
    out = []
    for k in (0, 1):
        dx = b[1][k] - a[1][k]
        if dx == 0:
            return None
        s = (b[2][k] - a[2][k]) / dx
        out.append((s, a[2][k] - s * a[1][k]))
    return (out[0][0], out[1][0], out[0][1], out[1][1])


def _residuals(tf, pairs):
    return [math.hypot(p[1][0] * tf[0] + tf[2] - p[2][0], p[1][1] * tf[1] + tf[3] - p[2][1]) for p in pairs]


def _candidate_pairs(n, cap):
    """기준점 n개의 쌍 (i, j) 후보. 전체 쌍 수가 cap 이하면 전수, 넘으면 전체 쌍 순번 0..T-1에서
    고정 보폭(T/cap)으로 cap개를 고른다(결정적, 앞쪽 쌍에 치우치지 않음)."""
    total = n * (n - 1) // 2
    picks = set(range(total)) if total <= cap else {k * total // cap for k in range(cap)}
    out, k = [], 0
    for i in range(n):
        for j in range(i + 1, n):
            if k in picks:
                out.append((i, j))
            k += 1
    return out


def _consensus(pairs, prm):
    """후보 쌍마다 구한 변환 중 허용 잔차 안 기준점이 가장 많은 것. 동점은 잔차 합, 그다음 후보 순서."""
    best = None
    for i, j in _candidate_pairs(len(pairs), prm["consensus_max_pairs"]):
        tf = _pair_model(pairs[i], pairs[j])
        if tf is None or not all(math.isfinite(v) for v in tf):
            continue
        res = _residuals(tf, pairs)
        inl = [r for r in res if r <= prm["consensus_tol"]]
        key = (-len(inl), round(sum(inl), 9))
        if best is None or key < best[0]:
            best = (key, tf)
    return best[1] if best else None


def _r(x):
    return None if x is None else round(x, 6)


def estimate_transform(truth, candidate, params=None):
    prm = dict(DEFAULTS)
    prm.update(params or {})
    pairs = anchors(truth, candidate)
    out = {"align_version": ALIGN_VERSION, "params": prm, "status": "blocked", "reason": None, "transform": None,
           "anchors_total": len(pairs), "anchors_used": 0, "outliers": [], "residual_rms": None,
           "residual_max": None, "residual_rms_all": None, "unit": (truth.get("coordinate_system") or {}).get("unit"),
           "page_ratio": None}
    td, cd = truth.get("drawing") or {}, candidate.get("drawing") or {}
    if all(isinstance(v, (int, float)) and v for v in (td.get("page_width"), td.get("page_height"),
                                                         cd.get("page_width"), cd.get("page_height"))):
        out["page_ratio"] = [_r(td["page_width"] / cd["page_width"]), _r(td["page_height"] / cd["page_height"])]
    if len(pairs) < prm["min_anchors"]:
        out["reason"] = "기준점 부족: %d < %d" % (len(pairs), prm["min_anchors"])
        return out
    tf_all, res_all = _solve(pairs)
    if tf_all is None:
        out["reason"] = "기준점이 한 축에서 모두 같은 좌표(변환을 정할 수 없음)"
        return out
    out["residual_rms_all"] = _r(math.sqrt(sum(r * r for r in res_all) / len(res_all)))
    init = _consensus(pairs, prm) or tf_all
    inliers = [p for p, r in zip(pairs, _residuals(init, pairs)) if r <= prm["consensus_tol"]]
    tf = (_solve(inliers)[0] if len(inliers) >= 2 else None) or init
    res = _residuals(tf, pairs)
    ref = sorted(r for r in res if r <= prm["consensus_tol"]) or sorted(res)
    limit = max(prm["outlier_factor"] * ref[len(ref) // 2], prm["outlier_floor"])
    keep = [p for p, r in zip(pairs, res) if r <= limit]
    if len(keep) < prm["min_anchors"]:
        out["reason"] = "합의한 기준점 부족: %d < %d" % (len(keep), prm["min_anchors"])
        return out
    refit = _solve(keep)[0]
    if refit is not None:
        tf = refit
    out["outliers"] = [p[0] for p in pairs if p not in keep]
    res = _residuals(tf, keep)
    rms = math.sqrt(sum(r * r for r in res) / len(res))
    final = {"scale": [_r(tf[0]), _r(tf[1])], "offset": [_r(tf[2]), _r(tf[3])]}
    out.update({"anchors_used": len(keep)})
    vals = final["scale"] + final["offset"]
    if not all(isinstance(v, float) and math.isfinite(v) for v in vals) or 0.0 in final["scale"]:
        out["reason"] = "쓸 수 없는 변환(유한하지 않거나 scale 0): %r" % (final,)
        return out
    out.update({"transform": final, "residual_rms": _r(rms), "residual_max": _r(max(res))})
    if rms > prm["max_rms"]:
        out["reason"] = "잔차 RMS %.3f > 상한 %.3f" % (rms, prm["max_rms"])
        return out
    out["status"] = "ok"
    return out
