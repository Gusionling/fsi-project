"""v3 하네스 실행기 (CONTRACT §6.2).

    python -m eval.v3.common.run --defense l1 --split dev [--limit N] [--set key=value ...] --out <run_dir>

산출물(--out): predictions.jsonl, metrics.json, run_meta.json  (+ 점수가 있는 방어면 calib_scores.jsonl)
케이스 단위로 predictions.jsonl 에 바로 기록하므로 중간에 죽어도 같은 명령을 다시 돌리면 이어서 한다
(설정이 달라졌으면 run_meta 의 signature 가 달라 이어쓰기를 거부한다).
모든 지표 정의는 metrics.py / CONTRACT §2 를 따른다. 분모 E 는 executed_<split>.json 에서 읽는다.
"""
from __future__ import annotations

import argparse
import importlib
import json
import math
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Type

from eval.v3.common import metrics as M
from eval.v3.common import judge as J
from eval.v3.common.baselines import act_detector
from eval.v3.common.baselines.gates import B1_MODEL, DefaultGates
from eval.v3.common.chatbot import MODEL as CHATBOT_MODEL
from eval.v3.common.chatbot import SYSTEM_PROMPT, ReferenceChatbot
from eval.v3.common.data_io import DEFAULT_DATA_DIR, ROOT, file_sha256, load_cases, split_path
from eval.v3.common.donors import FileDonorPool
from eval.v3.common.llm_client import OpenAILLM
from eval.v3.common.trusted import FileTrustedStores
from eval.v3.interfaces import Case, Defense, RunContext

COMMON_RESULTS_DIR = ROOT / "eval" / "v3" / "results" / "_common"

SHORT_NAMES = {
    "no_defense": "eval.v3.common.baselines.no_defense:NoDefense",
    "l0": "eval.v3.common.baselines.l0:L0Defense",
    "l1": "eval.v3.common.baselines.l1:L1Defense",
    "l2": "eval.v3.common.baselines.l2:L2Defense",
}


class RunMismatchError(RuntimeError):
    """이어쓰기하려는 출력 디렉터리의 설정이 지금 실행과 다르다."""


class StaleExecutedSet(RuntimeError):
    """executed set 이 지금의 split 파일과 맞지 않는다 (split 파일이 바뀐 뒤 E 를 다시 계산하지 않음)."""


# ---------------------------------------------------------------------------
# 준비
# ---------------------------------------------------------------------------


def resolve_defense(spec: str) -> Type[Defense]:
    target = SHORT_NAMES.get(spec, spec)
    if ":" not in target:
        raise ValueError(f"--defense 는 짧은 이름({', '.join(SHORT_NAMES)}) 또는 module:Class 형식입니다: {spec!r}")
    module_name, cls_name = target.split(":", 1)
    return getattr(importlib.import_module(module_name), cls_name)


def parse_set_args(items: Optional[Sequence[str]]) -> Dict[str, Any]:
    """--set key=value 를 dict 로. 값은 JSON 으로 해석되면 그 타입(true/12/0.5/[1,2]), 아니면 문자열."""
    out: Dict[str, Any] = {}
    for item in items or []:
        if "=" not in item:
            raise ValueError(f"--set 은 key=value 형식입니다: {item!r}")
        key, raw = item.split("=", 1)
        try:
            out[key] = json.loads(raw)
        except ValueError:
            out[key] = raw
    return out


def build_context(llm: Any, split: str, data_dir: Optional[Path], seed: int, config: Dict[str, Any]) -> RunContext:
    return RunContext(
        llm=llm,
        chatbot=ReferenceChatbot(llm),
        trusted=FileTrustedStores(data_dir),
        donors=FileDonorPool(split, data_dir),
        gates=DefaultGates(),
        chatbot_model=CHATBOT_MODEL,
        chatbot_system_prompt=SYSTEM_PROMPT,
        seed=seed,
        config=dict(config),
    )


def git_info() -> Dict[str, Any]:
    def git(*args: str) -> str:
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout

    try:
        sha = git("rev-parse", "HEAD").strip()
        dirty_paths = []
        for line in git("status", "--porcelain").splitlines():
            path = line[3:].strip().strip('"')
            if path.startswith(("eval/v3/results/", ".cache/")) or "__pycache__" in path:
                continue  # 산출물 자체는 dirty 로 보지 않는다
            dirty_paths.append(path)
        return {"git_sha": sha, "dirty": bool(dirty_paths), "dirty_paths": dirty_paths[:20]}
    except (subprocess.CalledProcessError, FileNotFoundError):
        return {"git_sha": None, "dirty": None, "dirty_paths": []}


def load_executed_ids(path: Path, split: str, split_sha: str) -> Optional[Dict[str, Any]]:
    """executed set 파일을 읽는다. 없으면 None. split 파일이 바뀌었으면 StaleExecutedSet."""
    if not path.exists():
        return None
    obj = json.loads(path.read_text(encoding="utf-8"))
    if obj.get("split") != split:
        raise StaleExecutedSet(f"{path}: split={obj.get('split')!r} (요청: {split!r})")
    if obj.get("split_sha256") != split_sha:
        raise StaleExecutedSet(f"{path}: split 파일 sha256 이 달라졌습니다. executed_set 을 --force 로 다시 계산하세요.")
    return obj


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _json_default(o: Any) -> Any:
    return str(o)


def _atomic_write_json(path: Path, obj: Any) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(_clean(obj), ensure_ascii=False, indent=2, default=_json_default), encoding="utf-8")
    os.replace(tmp, path)


def _clean(o: Any) -> Any:
    """nan/inf 를 None 으로 (표준 JSON 으로 저장)."""
    if isinstance(o, float) and (math.isnan(o) or math.isinf(o)):
        return None
    if isinstance(o, dict):
        return {k: _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    return o


def _read_jsonl_tolerant(path: Path) -> List[Dict[str, Any]]:
    """마지막 줄이 쓰다 만 상태여도 앞의 완전한 줄은 살린다 (그 경우 파일을 완전한 줄만으로 다시 쓴다)."""
    if not path.exists():
        return []
    rows, bad = [], False
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except ValueError:
            bad = True
    if bad:
        path.write_text("".join(json.dumps(r, ensure_ascii=False, default=_json_default) + "\n" for r in rows),
                        encoding="utf-8")
    return rows


def _append_jsonl(path: Path, row: Dict[str, Any]) -> None:
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False, default=_json_default) + "\n")
        f.flush()


# ---------------------------------------------------------------------------
# 케이스 하나
# ---------------------------------------------------------------------------


def evaluate_case(defense: Defense, case: Case, ctx: RunContext) -> Dict[str, Any]:
    """방어를 돌리고 judge 로 판정해 predictions.jsonl 한 줄(dict)을 만든다."""
    llm = ctx.llm
    with llm.case_scope(case.case_id):
        res = defense.run(case, ctx)
        rec: Dict[str, Any] = {
            "case_id": case.case_id, "split": case.split, "label": case.label, "topic": case.topic,
            "author_model": case.author_model, "final_answer": res.final_answer,
            "blocked": bool(res.blocked), "fallback_used": bool(res.fallback_used), "intervened": res.intervened,
            "scores": res.scores, "flags": res.flags, "defense_llm_calls": res.llm_calls,
        }
        judge: Dict[str, Any] = {}
        if case.label == "attack":
            rec.update(tier=case.attack["tier"], intent=case.attack["intent"], has_entity=case.attack["has_entity"])
            ok, why = J.attack_executed(case, res.final_answer, llm)
            judge.update(attack_executed=ok, attack_reason=why)
        elif case.label == "normal":
            rec["hard_negative_type"] = case.normal["hard_negative_type"]
            ok, why = J.answer_ok(case, res.final_answer, llm)
            judge.update(answer_ok=ok, answer_reason=why)
        else:
            rec["integrity_field"] = case.integrity["field"]
            checks, why = J.integrity_check(case, res.final_answer)
            judge.update(integrity=checks, integrity_reason=why)
        reason = judge.get("attack_reason") or judge.get("answer_reason") or ""
        judge["parse_error"] = reason.startswith(J.PARSE_ERROR)
        rec["judge"] = judge
    rec["llm"] = llm.case_summary(case.case_id)
    return rec


# ---------------------------------------------------------------------------
# 지표
# ---------------------------------------------------------------------------


def _group(preds: List[Dict[str, Any]], key: str) -> Dict[str, List[Dict[str, Any]]]:
    out: Dict[str, List[Dict[str, Any]]] = {}
    for p in preds:
        out.setdefault(str(p.get(key)), []).append(p)
    return out


def _attack_block(E_preds: List[Dict[str, Any]]) -> Dict[str, Any]:
    ids = [p["case_id"] for p in E_preds]
    interv = {p["case_id"]: p["intervened"] for p in E_preds}
    after = {p["case_id"]: bool(p["judge"]["attack_executed"]) for p in E_preds}
    return {"executed_recall": M.executed_recall(interv, ids), "asr_after": M.asr_after(after, ids)}


def compute_metrics(
    preds: List[Dict[str, Any]],
    *,
    executed_ids: Optional[Sequence[str]],
    calib_scores: Optional[Sequence[float]] = None,
    allow_partial_E: bool = False,
    alpha: float = 0.05,
) -> Dict[str, Any]:
    """predictions → metrics. 분모 E 는 executed_ids 로 고정한다(없으면 E 의존 지표는 None)."""
    by_id = {p["case_id"]: p for p in preds}
    attacks = [p for p in preds if p["label"] == "attack"]
    normals = [p for p in preds if p["label"] == "normal"]
    integ = [p for p in preds if p["label"] == "integrity"]
    out: Dict[str, Any] = {
        "n_cases": len(preds), "n_attack": len(attacks), "n_normal": len(normals), "n_integrity": len(integ),
        "judge_parse_errors": sum(1 for p in preds if p["judge"].get("parse_error")),
    }

    # --- 공격 (분모 = E) ---
    E_preds: List[Dict[str, Any]] = []
    if executed_ids is None:
        out["attack"] = {"executed_set": None, "note": "executed set 이 없어 executed recall / ASR_after 를 계산하지 않았다."}
    else:
        ids = list(executed_ids)
        present = [c for c in ids if c in by_id]
        if len(present) != len(ids) and not allow_partial_E:
            raise ValueError(f"executed set {len(ids)}건 중 {len(ids) - len(present)}건이 결과에 없습니다.")
        E_preds = [by_id[c] for c in present]
        attack_out: Dict[str, Any] = {
            "n_executed_set": len(present), "n_executed_set_full": len(ids), "E_restricted": len(present) != len(ids),
            **_attack_block(E_preds),
            "by_tier": {}, "by_intent": {}, "by_entity": {}, "by_author_model": {},
        }
        for key, name in (("tier", "by_tier"), ("intent", "by_intent"), ("author_model", "by_author_model")):
            for g, rows in sorted(_group(E_preds, key).items()):
                attack_out[name][g] = _attack_block(rows)
        for g, rows in sorted(_group([dict(p, entity="entity" if p["has_entity"] else "no_entity") for p in E_preds],
                                     "entity").items()):
            attack_out["by_entity"][g] = _attack_block(rows)
        out["attack"] = attack_out

    # --- 정상 ---
    fpr_all = M.fpr(p["intervened"] for p in normals)
    hard = [p for p in normals if p.get("hard_negative_type") != "none"]
    ok_all = [bool(p["judge"]["answer_ok"]) for p in normals]
    ok_kept = [bool(p["judge"]["answer_ok"]) for p in normals if not p["intervened"]]
    normal_out: Dict[str, Any] = {
        "fpr": fpr_all,
        "fpr_hard_negative": M.fpr(p["intervened"] for p in hard),
        "answer_acc": M.rate_dict(sum(ok_all), len(ok_all)),
        # 개입하지 않은 정상 케이스만 본 정확도: 거부로 정확도가 깎인 부분과 모델 자체의 오답을 분리해서 본다
        "answer_acc_among_not_intervened": M.rate_dict(sum(ok_kept), len(ok_kept)),
        "by_hard_negative_type": {}, "by_author_model": {},
    }
    for g, rows in sorted(_group(normals, "hard_negative_type").items()):
        normal_out["by_hard_negative_type"][g] = {
            "fpr": M.fpr(p["intervened"] for p in rows),
            "answer_acc": M.rate_dict(sum(bool(p["judge"]["answer_ok"]) for p in rows), len(rows)),
        }
    for g, rows in sorted(_group(normals, "author_model").items()):
        normal_out["by_author_model"][g] = {
            "fpr": M.fpr(p["intervened"] for p in rows),
            "answer_acc": M.rate_dict(sum(bool(p["judge"]["answer_ok"]) for p in rows), len(rows)),
        }
    out["normal"] = normal_out

    # --- 무결성 (공격 5종과 분리 보고) ---
    integ_out: Dict[str, Any] = {
        "n": len(integ),
        "poisoned_in_answer": M.rate_dict(sum(p["judge"]["integrity"]["poisoned_in_answer"] for p in integ), len(integ)),
        "true_in_answer": M.rate_dict(sum(p["judge"]["integrity"]["true_in_answer"] for p in integ), len(integ)),
        "intervened": M.rate_dict(sum(p["intervened"] for p in integ), len(integ)),
        "by_field": {},
    }
    for g, rows in sorted(_group(integ, "integrity_field").items()):
        integ_out["by_field"][g] = {
            "n": len(rows),
            "poisoned_in_answer": M.rate_dict(sum(p["judge"]["integrity"]["poisoned_in_answer"] for p in rows), len(rows)),
        }
    out["integrity"] = integ_out

    # --- risk 점수: ROC-AUC, calib 정상으로 정한 임계값 ---
    risk = {p["case_id"]: p["scores"].get("risk") for p in preds if p["scores"].get("risk") is not None}
    has_risk = len(risk) == len(preds) and len(preds) > 0
    score_out: Dict[str, Any] = {"has_risk": has_risk}
    if has_risk and executed_ids is not None:
        pos = [risk[p["case_id"]] for p in E_preds]
        neg = [risk[p["case_id"]] for p in normals]
        score_out["roc_auc_executed_vs_normal"] = M.roc_auc(pos, neg)
        if calib_scores is not None:
            thr = M.calibrated_threshold(calib_scores, alpha)
            score_out["calib"] = {"n_calib_normal": len(calib_scores), "alpha": alpha,
                                  "min_p_value": M.min_p_value(len(calib_scores)), "threshold": thr}
            if thr is None:
                score_out["calib"]["note"] = "calib 정상이 너무 적어 이 alpha 로는 임계값을 정할 수 없다 (min_p_value > alpha)."
            else:
                score_out["at_calib_threshold"] = {
                    "executed_recall": M.rate_dict(sum(risk[p["case_id"]] >= thr for p in E_preds), len(E_preds)),
                    "fpr": M.fpr(risk[p["case_id"]] >= thr for p in normals),
                }
    out["risk"] = score_out
    return out


# ---------------------------------------------------------------------------
# 실행
# ---------------------------------------------------------------------------


def _models(config: Dict[str, Any]) -> Dict[str, str]:
    return {"chatbot": CHATBOT_MODEL, "b1": B1_MODEL, "act_detector": act_detector.MODEL, "judge": J.JUDGE_MODEL,
            "act_detector_version": config.get("act_detector_version", act_detector.DEFAULT_VERSION)}


def _aggregate_llm(preds: List[Dict[str, Any]], calib_rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    by_tag: Dict[str, int] = {}
    logical = api = 0
    for p in list(preds) + list(calib_rows):
        s = p.get("llm", {})
        logical += s.get("logical", 0)
        api += s.get("api", 0)
        for t, n in s.get("logical_by_tag", {}).items():
            by_tag[t] = by_tag.get(t, 0) + n
    return {"logical": logical, "api": api, "logical_by_tag": by_tag}


def execute(
    defense: Defense,
    split: str,
    out_dir: Path,
    *,
    llm: Any,
    data_dir: Optional[Path] = None,
    seed: int = 0,
    config: Optional[Dict[str, Any]] = None,
    limit: Optional[int] = None,
    executed_file: Optional[Path] = None,
    calib_scores: bool = True,
    defense_spec: str = "",
    log: Any = print,
) -> Dict[str, Any]:
    """한 방어를 한 split 에 돌리고 산출물 3종을 out_dir 에 쓴다. 반환값 = metrics."""
    config = dict(config or {})
    data_dir = Path(data_dir) if data_dir else DEFAULT_DATA_DIR
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    cases = load_cases(split, data_dir)
    if limit is not None:
        cases = cases[:limit]
    split_sha = file_sha256(split_path(split, data_dir))
    executed_file = Path(executed_file) if executed_file else COMMON_RESULTS_DIR / f"executed_{split}.json"
    executed_obj = load_executed_ids(executed_file, split, split_sha)

    signature = {"defense": defense_spec or getattr(defense, "name", type(defense).__name__), "config": config,
                 "split": split, "split_sha256": split_sha, "seed": seed, "limit": limit,
                 "models": _models(config)}
    meta_path = out_dir / "run_meta.json"
    if meta_path.exists():
        old = json.loads(meta_path.read_text(encoding="utf-8"))
        if old.get("signature") != json.loads(json.dumps(_clean(signature), default=_json_default)):
            raise RunMismatchError(f"{out_dir} 는 다른 설정으로 만들어졌습니다. 새 --out 을 쓰세요.")
        started_at = old.get("started_at", _utcnow())
    else:
        started_at = _utcnow()
    meta: Dict[str, Any] = {"signature": signature, "defense": signature["defense"], "config": config, "split": split,
                            "split_sha256": split_sha, "seed": seed, "limit": limit, "models": signature["models"],
                            "n_cases": len(cases), "started_at": started_at, "finished_at": None, "status": "running",
                            "executed_set_file": str(executed_file) if executed_obj else None,
                            "executed_set_sha256": file_sha256(executed_file) if executed_obj else None,
                            **git_info()}
    _atomic_write_json(meta_path, meta)

    ctx = build_context(llm, split, data_dir, seed, config)
    try:
        calib_cases = load_cases("calib", data_dir)
    except FileNotFoundError:
        calib_cases = []
    with llm.case_scope("__fit__"):
        defense.fit(calib_cases, ctx)
    meta["fit_cases"] = len(calib_cases)
    meta["fit_llm"] = llm.case_summary("__fit__")

    pred_path = out_dir / "predictions.jsonl"
    preds = _read_jsonl_tolerant(pred_path)
    done = {p["case_id"] for p in preds}
    todo = [c for c in cases if c.case_id not in done]
    log(f"[run] {meta['defense']} on {split}: {len(cases)} cases ({len(done)} 이미 완료, {len(todo)} 남음)")
    t0 = time.time()
    for i, case in enumerate(todo, 1):
        rec = evaluate_case(defense, case, ctx)
        _append_jsonl(pred_path, rec)
        preds.append(rec)
        if i % 10 == 0 or i == len(todo):
            log(f"  {i}/{len(todo)} ({time.time() - t0:.0f}s)")
    run_ids = {c.case_id for c in cases}
    preds = [p for p in preds if p["case_id"] in run_ids]

    # calib 정상 케이스의 risk 점수 → 임계값 (점수가 있는 방어만, calib 자체를 평가할 때는 생략)
    calib_rows: List[Dict[str, Any]] = []
    calib_list: Optional[List[float]] = None
    if calib_scores and split != "calib" and preds and all(p["scores"].get("risk") is not None for p in preds):
        calib_normals = [c for c in calib_cases if c.label == "normal"]
        if limit is not None:
            calib_normals = calib_normals[:limit]
        if calib_normals:
            cpath = out_dir / "calib_scores.jsonl"
            calib_rows = _read_jsonl_tolerant(cpath)
            cdone = {r["case_id"] for r in calib_rows}
            cctx = build_context(llm, "calib", data_dir, seed, config)
            for case in [c for c in calib_normals if c.case_id not in cdone]:
                with llm.case_scope(case.case_id):
                    res = defense.run(case, cctx)
                row = {"case_id": case.case_id, "risk": res.scores.get("risk"), "intervened": res.intervened,
                       "llm": llm.case_summary(case.case_id)}
                _append_jsonl(cpath, row)
                calib_rows.append(row)
            calib_list = [r["risk"] for r in calib_rows if r["risk"] is not None]

    metrics = compute_metrics(
        preds, executed_ids=executed_obj["case_ids"] if executed_obj else None, calib_scores=calib_list,
        allow_partial_E=limit is not None,
    )
    metrics["defense_llm_calls"] = {"total": sum(p["defense_llm_calls"] for p in preds),
                                    "per_case_mean": (sum(p["defense_llm_calls"] for p in preds) / len(preds)) if preds else None}
    _atomic_write_json(out_dir / "metrics.json", metrics)

    meta.update(finished_at=_utcnow(), status="complete", llm_calls=_aggregate_llm(preds, calib_rows),
                n_cases_done=len(preds), n_predictions=len(preds))
    _atomic_write_json(meta_path, meta)
    return metrics


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--defense", required=True, help="no_defense | l0 | l1 | l2 | module:Class")
    ap.add_argument("--split", required=True, choices=["dev", "calib", "test_sealed"])
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--limit", type=int, default=None, help="앞에서 N개 케이스만 (스모크 테스트용)")
    ap.add_argument("--set", dest="sets", action="append", default=[], metavar="key=value", help="ctx.config 로 전달")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--data-dir", type=Path, default=None)
    ap.add_argument("--executed-file", type=Path, default=None)
    ap.add_argument("--cache-dir", type=Path, default=None)
    ap.add_argument("--no-calib-scores", action="store_true", help="calib 정상 점수 계산(임계값)을 생략")
    args = ap.parse_args(argv)

    config = parse_set_args(args.sets)
    cls = resolve_defense(args.defense)
    metrics = execute(cls(), args.split, args.out, llm=OpenAILLM(args.cache_dir), data_dir=args.data_dir,
                      seed=args.seed, config=config, limit=args.limit, executed_file=args.executed_file,
                      calib_scores=not args.no_calib_scores, defense_spec=args.defense)
    print(json.dumps(_clean(metrics), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
