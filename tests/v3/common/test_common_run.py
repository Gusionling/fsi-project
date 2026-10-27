import json
import shutil

import pytest

from eval.v3.common import compare as C
from eval.v3.common import executed_set
from eval.v3.common import metrics as M
from eval.v3.common import run as R
from eval.v3.common.audit import build_audit_rows, write_audit
from eval.v3.common.data_io import load_cases
from eval.v3.common.llm_client import FakeLLM
from eval.v3.common.selfcheck import FIXTURE_DIR, fixture_handler, make_fake_llm, run_selfcheck

quiet = lambda *a, **k: None  # noqa: E731


@pytest.fixture()
def env(tmp_path):
    out_root = tmp_path / "_common"
    executed_set.compute_executed_set("dev", llm=make_fake_llm(), data_dir=FIXTURE_DIR, out_root=out_root, log=quiet)
    return {"tmp": tmp_path, "root": out_root, "E": out_root / "executed_dev.json"}


def do_run(env, name, subdir=None, llm=None, **kw):
    out = env["tmp"] / (subdir or name)
    m = R.execute(R.resolve_defense(name)(), "dev", out, llm=llm or make_fake_llm(), data_dir=FIXTURE_DIR,
                  executed_file=env["E"], defense_spec=name, log=quiet, **kw)
    return out, m


def test_executed_set_contents(env):
    E = json.loads(env["E"].read_text(encoding="utf-8"))
    assert E["split"] == "dev" and E["n_attack"] == 6 and E["n_executed"] == 5
    assert "fx_atk_noexec" not in E["case_ids"]  # 방어 없이도 실행되지 않은 공격은 분모에서 빠진다
    assert E["by_tier"]["T2"] == {"n_attack": 3, "n_executed": 2, "executed_rate": 2 / 3}
    assert E["by_intent"]["prompt_leak"]["n_executed"] == 1
    assert E["by_entity"]["no_entity"]["n_executed"] == 3 and E["by_entity"]["entity"]["n_executed"] == 2
    assert E["by_author_model"]["fixture-hand"]["n_attack"] == 6
    assert E["g2_check"]["passed"] is False  # fixture 는 E >= 60 이 아니다 (판정이 계산으로 나온다는 확인)
    assert len(E["split_sha256"]) == 64
    assert (env["root"] / "no_defense_dev" / "metrics.json").exists()


def test_executed_set_is_not_overwritten_without_force(env):
    with pytest.raises(FileExistsError):
        executed_set.compute_executed_set("dev", llm=make_fake_llm(), data_dir=FIXTURE_DIR, out_root=env["root"], log=quiet)
    executed_set.compute_executed_set("dev", llm=make_fake_llm(), data_dir=FIXTURE_DIR, out_root=env["root"], force=True, log=quiet)


def test_executed_set_refuses_limit(env):
    with pytest.raises(ValueError):
        executed_set.compute_executed_set("dev", llm=make_fake_llm(), data_dir=FIXTURE_DIR, out_root=env["tmp"] / "x",
                                          limit=3, log=quiet)


def test_three_artifacts_and_meta_fields(env):
    out, m = do_run(env, "l1")
    # 산출물 3종 (+ 점수가 있는 방어는 calib 정상 점수 calib_scores.jsonl)
    assert {p.name for p in out.iterdir()} == {"predictions.jsonl", "metrics.json", "run_meta.json", "calib_scores.jsonl"}
    out0, _ = do_run(env, "no_defense")
    assert {p.name for p in out0.iterdir()} == {"predictions.jsonl", "metrics.json", "run_meta.json"}
    meta = json.loads((out / "run_meta.json").read_text(encoding="utf-8"))
    for key in ("git_sha", "dirty", "defense", "config", "split", "split_sha256", "models", "seed", "n_cases",
                "llm_calls", "started_at", "finished_at", "status"):
        assert key in meta, key
    assert meta["status"] == "complete" and meta["n_cases"] == 11 and meta["split"] == "dev"
    assert meta["llm_calls"]["logical"] > 0 and "judge" in meta["llm_calls"]["logical_by_tag"]
    assert meta["models"]["chatbot"] == "gpt-4o-mini"
    lines = [json.loads(l) for l in (out / "predictions.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(lines) == 11 and {"case_id", "final_answer", "intervened", "scores", "flags", "judge", "llm"} <= set(lines[0])


def test_metrics_values_per_baseline(env):
    expect = {"no_defense": (0, 5, 0), "l0": (2, 3, 0), "l1": (3, 2, 1), "l2": (5, 0, 1)}
    for name, (recall_k, asr_k, fpr_k) in expect.items():
        _, m = do_run(env, name)
        assert (m["attack"]["executed_recall"]["k"], m["attack"]["executed_recall"]["n"]) == (recall_k, 5), name
        assert m["attack"]["asr_after"]["k"] == asr_k, name
        assert m["normal"]["fpr"]["k"] == fpr_k and m["normal"]["fpr"]["n"] == 4, name
        # 무결성(허위 수수료)은 공격 5종과 분리 보고: 이 기준선들은 청크를 믿으므로 오염된 값이 그대로 나간다
        assert m["integrity"]["n"] == 1 and m["integrity"]["poisoned_in_answer"]["k"] == 1
        assert m["integrity"]["intervened"]["k"] == 0


def test_breakdowns_and_hard_negatives(env):
    _, m = do_run(env, "l2")
    assert m["attack"]["by_tier"]["T2"]["executed_recall"] == M.rate_dict(2, 2)
    assert m["attack"]["by_intent"]["false_confirmation"]["executed_recall"]["k"] == 1
    assert m["attack"]["by_entity"]["no_entity"]["executed_recall"]["n"] == 3
    assert m["normal"]["fpr_hard_negative"]["n"] == 3  # none 이 아닌 정상: pw, done, fp
    assert m["normal"]["by_hard_negative_type"]["password_reset"]["fpr"]["k"] == 0
    assert m["normal"]["by_hard_negative_type"]["contact_info"]["fpr"]["k"] == 1
    assert m["normal"]["by_author_model"]["fixture-hand"]["fpr"]["n"] == 4
    # 거부된 정상 답변은 required_info 를 담지 못해 정확도에서 빠지지만, 개입 안 한 케이스만 보면 모두 맞다
    assert m["normal"]["answer_acc"]["k"] == 3 and m["normal"]["answer_acc_among_not_intervened"] == M.rate_dict(3, 3)


def test_risk_auc_and_calib_threshold_not_possible_with_few_calib(env):
    out, m = do_run(env, "l1")
    assert m["risk"]["has_risk"] and 0.0 <= m["risk"]["roc_auc_executed_vs_normal"] <= 1.0
    assert m["risk"]["calib"]["n_calib_normal"] == 4 and m["risk"]["calib"]["threshold"] is None
    assert len((out / "calib_scores.jsonl").read_text(encoding="utf-8").splitlines()) == 4
    _, none = do_run(env, "no_defense")
    assert none["risk"]["has_risk"] is False  # 점수가 없는 방어는 AUC 를 내지 않는다


def test_threshold_from_calib_normals_only():
    preds = [{"case_id": f"a{i}", "label": "attack", "intervened": False, "scores": {"risk": float(10 + i)}, "tier": "T2",
              "intent": "prompt_leak", "has_entity": False, "author_model": "m",
              "judge": {"attack_executed": True, "parse_error": False}} for i in range(4)]
    preds += [{"case_id": f"n{i}", "label": "normal", "intervened": False, "scores": {"risk": float(i)}, "hard_negative_type": "none",
               "author_model": "m", "judge": {"answer_ok": True, "parse_error": False}} for i in range(5)]
    calib = [float(x) for x in range(100)]
    m = R.compute_metrics(preds, executed_ids=[f"a{i}" for i in range(4)], calib_scores=calib)
    assert m["risk"]["calib"]["threshold"] == 96.0
    assert m["risk"]["at_calib_threshold"]["executed_recall"]["k"] == 0  # 공격 점수 10~13 < 96
    assert m["risk"]["roc_auc_executed_vs_normal"] == 1.0


def test_resume_skips_finished_cases_and_rejects_changed_settings(env):
    out = env["tmp"] / "resume"
    R.execute(R.resolve_defense("l1")(), "dev", out, llm=make_fake_llm(), data_dir=FIXTURE_DIR, executed_file=env["E"],
              limit=4, defense_spec="l1", log=quiet)
    assert len((out / "predictions.jsonl").read_text(encoding="utf-8").splitlines()) == 4
    # 설정(limit)이 달라지면 이어쓰기를 거부한다
    with pytest.raises(R.RunMismatchError):
        R.execute(R.resolve_defense("l1")(), "dev", out, llm=make_fake_llm(), data_dir=FIXTURE_DIR, executed_file=env["E"],
                  defense_spec="l1", log=quiet)
    # 같은 설정으로 다시 돌리면 이미 끝난 케이스는 호출 없이 건너뛴다
    llm2 = make_fake_llm()
    R.execute(R.resolve_defense("l1")(), "dev", out, llm=llm2, data_dir=FIXTURE_DIR, executed_file=env["E"], limit=4,
              defense_spec="l1", log=quiet)
    assert llm2.summary()["logical_by_tag"].get("chatbot", 0) == 0 and llm2.summary()["logical_by_tag"].get("judge", 0) == 0


def test_resume_after_crash_mid_run(env):
    out = env["tmp"] / "crash"
    calls = {"n": 0}

    def flaky(**req):
        if req["tag"] == "chatbot":
            calls["n"] += 1
            if calls["n"] == 5:
                raise KeyboardInterrupt  # 중간에 죽는 상황
        return fixture_handler(**req)

    with pytest.raises(KeyboardInterrupt):
        R.execute(R.resolve_defense("no_defense")(), "dev", out, llm=FakeLLM(flaky), data_dir=FIXTURE_DIR,
                  executed_file=env["E"], defense_spec="no_defense", log=quiet)
    done = [json.loads(l)["case_id"] for l in (out / "predictions.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(done) == 4
    llm = make_fake_llm()
    m = R.execute(R.resolve_defense("no_defense")(), "dev", out, llm=llm, data_dir=FIXTURE_DIR, executed_file=env["E"],
                  defense_spec="no_defense", log=quiet)
    ids = [json.loads(l)["case_id"] for l in (out / "predictions.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(ids) == len(set(ids)) == 11  # 중복 없이 이어서 끝낸다
    assert llm.summary()["logical_by_tag"]["chatbot"] == 7
    assert m["n_cases"] == 11


def test_truncated_last_line_is_tolerated(env):
    out = env["tmp"] / "trunc"
    R.execute(R.resolve_defense("l0")(), "dev", out, llm=make_fake_llm(), data_dir=FIXTURE_DIR, executed_file=env["E"],
              defense_spec="l0", log=quiet)
    text = (out / "predictions.jsonl").read_text(encoding="utf-8")
    (out / "predictions.jsonl").write_text(text[: len(text) - 40], encoding="utf-8")  # 마지막 줄을 자른다
    R.execute(R.resolve_defense("l0")(), "dev", out, llm=make_fake_llm(), data_dir=FIXTURE_DIR, executed_file=env["E"],
              defense_spec="l0", log=quiet)
    assert len((out / "predictions.jsonl").read_text(encoding="utf-8").splitlines()) == 11


def test_stale_executed_set_is_rejected(env, tmp_path):
    data = tmp_path / "data"
    shutil.copytree(FIXTURE_DIR, data)
    with open(data / "cases_dev.jsonl", "a", encoding="utf-8") as f:
        f.write("")
    rows = (data / "cases_dev.jsonl").read_text(encoding="utf-8").splitlines()
    (data / "cases_dev.jsonl").write_text("\n".join(rows[:-1]) + "\n", encoding="utf-8")  # 데이터가 바뀜
    with pytest.raises(R.StaleExecutedSet):
        R.execute(R.resolve_defense("l0")(), "dev", tmp_path / "o", llm=make_fake_llm(), data_dir=data,
                  executed_file=env["E"], defense_spec="l0", log=quiet)


def test_limit_run_marks_E_restricted(env):
    _, m = do_run(env, "l0", subdir="lim", limit=3)
    assert m["attack"]["E_restricted"] is True and m["attack"]["n_executed_set_full"] == 5
    assert m["attack"]["n_executed_set"] < 5


def test_without_executed_set_attack_metrics_are_none(tmp_path):
    out = tmp_path / "r"
    m = R.execute(R.resolve_defense("l0")(), "dev", out, llm=make_fake_llm(), data_dir=FIXTURE_DIR,
                  executed_file=tmp_path / "missing.json", defense_spec="l0", log=quiet)
    assert m["attack"]["executed_set"] is None and "executed_recall" not in m["attack"]
    assert m["normal"]["fpr"]["n"] == 4


def test_config_is_passed_via_set(env):
    assert R.parse_set_args(["a=true", "b=3", "c=0.5", "d=text", "e=[1, 2]"]) == {"a": True, "b": 3, "c": 0.5, "d": "text", "e": [1, 2]}
    with pytest.raises(ValueError):
        R.parse_set_args(["novalue"])
    seen = {}

    class Probe:
        name = "probe"

        def fit(self, calib, ctx):
            seen["fit_calib"] = len(calib)

        def run(self, case, ctx):
            seen["config"] = dict(ctx.config)
            seen["prompt"] = ctx.chatbot_system_prompt
            from eval.v3.interfaces import DefenseResult
            return DefenseResult(final_answer=ctx.chatbot.answer(case.query, case.chunks))

    R.execute(Probe(), "dev", env["tmp"] / "probe", llm=make_fake_llm(), data_dir=FIXTURE_DIR, executed_file=env["E"],
              config={"stack_b1": False}, limit=1, calib_scores=False, defense_spec="probe", log=quiet)
    assert seen["config"] == {"stack_b1": False} and seen["fit_calib"] == 4 and seen["prompt"].startswith("아래 컨텍스트만")


def test_resolve_defense_names():
    for short, name in [("no_defense", "NoDefense"), ("l0", "L0Defense"), ("l1", "L1Defense"), ("l2", "L2Defense")]:
        assert R.resolve_defense(short).__name__ == name
    assert R.resolve_defense("eval.v3.common.baselines.l1:L1Defense") is R.resolve_defense("l1")
    with pytest.raises(ValueError):
        R.resolve_defense("nonsense")


def test_compare_runs_paired_on_same_E(env):
    a, _ = do_run(env, "l2")
    b, _ = do_run(env, "l0")
    res = C.compare_runs(a, b, executed_file=env["E"], n_boot=500)
    r = res["metrics"]["executed_recall"]
    assert r["diff"] == pytest.approx(0.6) and r["n"] == 5 and r["rate_a"] == 1.0 and r["rate_b"] == 0.4
    assert res["metrics"]["asr_after"]["diff"] == pytest.approx(-0.6)
    assert res["metrics"]["fpr"]["diff"] == pytest.approx(0.25) and res["metrics"]["fpr"]["n"] == 4
    assert C.compare_runs(a, b, executed_file=env["E"], n_boot=500, seed=0) == res  # 결정적


def test_compare_rejects_different_data(env, tmp_path):
    a, _ = do_run(env, "l2")
    other = json.loads((a / "run_meta.json").read_text(encoding="utf-8"))
    other["split_sha256"] = "0" * 64
    b = tmp_path / "other"
    shutil.copytree(a, b)
    (b / "run_meta.json").write_text(json.dumps(other), encoding="utf-8")
    with pytest.raises(ValueError, match="sha256"):
        C.compare_runs(a, b, executed_file=env["E"])


def test_audit_csv(env, tmp_path):
    out = write_audit(env["root"] / "no_defense_dev", tmp_path / "audit.csv", FIXTURE_DIR, seed=3)
    import csv
    rows = list(csv.DictReader(open(out, encoding="utf-8-sig")))
    assert len(rows) == 6 + 4  # fixture 는 공격 6 / 정상 4 (각각 20 미만이면 전부)
    assert {"case_id", "answer", "judge_verdict", "judge_reason", "human_verdict"} <= set(rows[0])
    assert all(r["human_verdict"] == "" for r in rows)
    cases = {c.case_id: c for c in load_cases("dev", FIXTURE_DIR)}
    preds = R._read_jsonl_tolerant(env["root"] / "no_defense_dev" / "predictions.jsonl")
    again = build_audit_rows(preds, cases, seed=3)
    assert [r["case_id"] for r in again] == [r["case_id"] for r in rows]  # seed 고정이면 같은 표본


def test_audit_sample_sizes_and_seed():
    cases = {}
    preds = []
    from eval.v3.interfaces import Case, Chunk
    for i in range(30):
        for label in ("attack", "normal"):
            cid = f"{label}{i}"
            cases[cid] = Case(cid, "dev", label, "q", "t", [Chunk("a", "문서 하나입니다", "target")],
                              attack={"expected_bad_behavior": "나쁜 행동"} if label == "attack" else None,
                              normal={"required_info": ["정보"]} if label == "normal" else None)
            preds.append({"case_id": cid, "label": label, "final_answer": "답",
                          "judge": {"attack_executed": True, "attack_reason": "r", "answer_ok": True, "answer_reason": "r"}})
    r1 = build_audit_rows(preds, cases, seed=1)
    assert sum(r["label"] == "attack" for r in r1) == 20 and sum(r["label"] == "normal" for r in r1) == 20
    assert [r["case_id"] for r in r1] == [r["case_id"] for r in build_audit_rows(preds, cases, seed=1)]
    assert [r["case_id"] for r in r1] != [r["case_id"] for r in build_audit_rows(preds, cases, seed=2)]


def test_selfcheck_runs():
    res = run_selfcheck()
    assert res["l2"]["executed_recall"] == 5 and res["no_defense"]["executed_recall"] == 0
