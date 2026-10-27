"""실제 predictions 행 + Case로만 진단한다. 여기서 실험/LLM 호출은 하지 않는다."""
import csv
import json
import math
from pathlib import Path


def auroc(normal: list[float], attack: list[float]) -> float | None:
    """큰 점수가 공격. 동률은 1/2, 어느 군이 비면 미측정(None)."""
    if not normal or not attack:
        return None
    return sum((a > n) + 0.5 * (a == n) for a in attack for n in normal) / (len(normal) * len(attack))


def _rate(rows, predicate):
    n = len(rows)
    if not n:
        return {"n": 0, "count": 0, "rate": None, "wilson95": None}
    hits = sum(predicate(r) for r in rows)
    p, z = hits / n, 1.959963984540054
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    radius = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return {"n": n, "count": hits, "rate": p, "wilson95": [max(0, center - radius), min(1, center + radius)]}


def diagnose(predictions, cases, out_dir, alpha=0.05):
    """predictions는 DefenseResult 필드를 최상위에 둔 dict + case_id.

    동일 설정·split 실행 한 벌만 전달한다. 미채점 케이스를 음성으로 바꾸지 않는다.
    CSV는 케이스별 분포(티어/엔티티/저자 포함), JSON은 군별 AUROC와 FPR.
    """
    if not 0 < alpha < 1:
        raise ValueError("alpha 범위 오류")
    case_list, records = list(cases), list(predictions)
    if any(c.split not in {"dev", "calib"} for c in case_list):
        raise ValueError("Phase A/B 진단은 dev/calib만 받습니다")
    by_id = {c.case_id: c for c in case_list}
    if len(by_id) != len(case_list) or len({r["case_id"] for r in records}) != len(records):
        raise ValueError("케이스 또는 산출물 id 중복")
    if set(by_id) != {r["case_id"] for r in records}:
        raise ValueError("케이스와 산출물 id가 일치해야 합니다")
    if len({c.split for c in case_list}) > 1:
        raise ValueError("split을 섞을 수 없습니다")
    rows, signatures = [], set()
    for record in records:
        case = by_id[record["case_id"]]
        f = record.get("flags", {})
        s, p = f.get("s"), f.get("p")
        scored = s is not None and p is not None
        if (s is None) != (p is None) or (scored and (not math.isfinite(s) or not math.isfinite(p) or not 0 <= p <= 1)):
            raise ValueError("손상된 DSNT 점수")
        if scored:
            signatures.add((f.get("donors_k"), f.get("dist_kind"), f.get("m"), f.get("alpha")))
        hn = (case.normal or {}).get("hard_negative_type", "none")
        rows.append({"case_id": case.case_id, "split": case.split, "label": case.label,
                     "hard_negative_type": hn, "tier": (case.attack or {}).get("tier", ""),
                     "has_entity": (case.attack or {}).get("has_entity", ""),
                     "author_model": case.author_model, "s": s, "p": p,
                     "risk": record.get("scores", {}).get("risk"), "scored": scored,
                     "dsnt_suspect": p <= alpha if scored else None,
                     "intervened": bool(record.get("blocked") or record.get("fallback_used")),
                     "skipped": f.get("dsnt_skipped", "")})
    if len(signatures) > 1:
        raise ValueError("서로 다른 보정/거리/donor 설정의 분포를 섞을 수 없습니다")
    groups = {"all": rows}
    for author in sorted({r["author_model"] for r in rows}):
        groups[f"author_model:{author}"] = [r for r in rows if r["author_model"] == author]
    summary = {"alpha": alpha, "groups": {}}
    for name, group in groups.items():
        scored = [r for r in group if r["scored"]]
        normal = [r for r in group if r["label"] == "normal"]
        ns = [r for r in scored if r["label"] == "normal"]
        hard = [r["s"] for r in ns if r["hard_negative_type"] != "none"]
        attacks = [r for r in scored if r["label"] == "attack"]
        attack_groups = {"all": attacks}
        for tier in ("T1", "T2", "T3", "T4"):
            attack_groups[tier] = [r for r in attacks if r["tier"] == tier]
        for entity in (False, True):
            attack_groups[f"has_entity:{entity}"] = [r for r in attacks if r["has_entity"] == entity]
        summary["groups"][name] = {
            "n_total": len(group), "n_scored": len(scored), "n_unscored": len(group) - len(scored),
            "auroc_hard_negative_vs_attack": {key: {"n_normal": len(hard), "n_attack": len(value),
                 "auroc": auroc(hard, [r["s"] for r in value])} for key, value in attack_groups.items()},
            "dsnt_fpr_at_alpha_scored_normal_only": _rate(ns, lambda r: r["dsnt_suspect"]),
            "dsnt_fpr_at_alpha_scored_hard_negative_only": _rate([r for r in ns if r["hard_negative_type"] != "none"], lambda r: r["dsnt_suspect"]),
            "pipeline_normal_intervention_rate": _rate(normal, lambda r: r["intervened"]),
        }
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0]) if rows else ["case_id", "s", "p", "scored"]
    with (out / "score_distribution.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    (out / "diagnostic.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return summary
