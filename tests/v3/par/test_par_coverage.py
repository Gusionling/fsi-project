import csv
import json

from eval.v3.candidates.par import coverage as cov


def case(cid, label="normal", hn="none", topic="t1"):
    c = {"case_id": cid, "label": label, "topic": topic, "query": f"질문 {cid}"}
    if label == "normal":
        c["normal"] = {"hard_negative_type": hn}
    return c


def pred(cid, fallback=False, blocked=False, parse_failed=False, rejected=0):
    return {"case_id": cid, "fallback_used": fallback, "blocked": blocked, "final_answer": "답",
            "flags": {"parse_failed": parse_failed, "rejected_total": rejected,
                      "rejected_acts": [{"source": "declared", "act_type": "completion_claim", "reason": "no_status_record", "text": "완료"}] * rejected}}


def test_counts_by_overall_hn_and_topic_ignore_non_normal():
    cases = [case("a", hn="none"), case("b", hn="none"), case("c", hn="password_reset", topic="t2"), case("d", hn="password_reset", topic="t2"),
             case("x", label="attack")]
    preds = [pred("a"), pred("b", fallback=True, rejected=1), pred("c", blocked=True), pred("d", fallback=True, parse_failed=True), pred("x", fallback=True)]
    r = cov.compute(preds, cases)
    assert r["n_normal"] == 4
    o = r["overall"]
    assert (o["fallback_rate"]["k"], o["fallback_rate"]["n"]) == (2, 4) and o["gate_block_rate"]["k"] == 1
    assert o["parse_failed_rate"]["k"] == 1 and o["any_rate"]["k"] == 3
    assert r["by_hard_negative_type"]["none"]["fallback_rate"]["k"] == 1 and r["by_hard_negative_type"]["password_reset"]["fallback_rate"]["k"] == 1
    assert r["by_topic"]["t2"]["any_rate"]["k"] == 2 and r["by_topic"]["t1"]["any_rate"]["k"] == 1
    assert [t["case_id"] for t in r["top20"]] == ["b", "d"]       # 대체된 정상만, 거부 act 수 많은 순


def test_top20_is_capped_and_sorted():
    cases = [case(f"n{i:02d}") for i in range(30)]
    preds = [pred(f"n{i:02d}", fallback=True, rejected=(i % 3) + 1) for i in range(30)]
    top = cov.compute(preds, cases)["top20"]
    assert len(top) == 20 and top[0]["rejected_total"] == 3 and top[0]["case_id"] == "n02"


def test_empty_input_gives_none_rates():
    r = cov.compute([], [case("a")])
    assert r["overall"]["fallback_rate"]["rate"] is None and r["top20"] == []


def test_wilson_known_value():
    lo, hi = cov.wilson(0, 10)
    assert lo == 0.0 and abs(hi - 0.2775) < 1e-3


def test_cli_writes_json_and_csv(tmp_path, capsys):
    cases = [case("a", hn="contact_info"), case("b")]
    (tmp_path / "cases.jsonl").write_text("\n".join(json.dumps(c, ensure_ascii=False) for c in cases), encoding="utf-8")
    (tmp_path / "pred.jsonl").write_text("\n".join(json.dumps(p, ensure_ascii=False) for p in [pred("a", fallback=True, rejected=2), pred("b")]), encoding="utf-8")
    assert cov.main(["--predictions", str(tmp_path / "pred.jsonl"), "--cases", str(tmp_path / "cases.jsonl"), "--out-dir", str(tmp_path / "out")]) == 0
    assert json.loads((tmp_path / "out" / "coverage.json").read_text(encoding="utf-8"))["overall"]["fallback_rate"]["k"] == 1
    rows = list(csv.DictReader(open(tmp_path / "out" / "fallback_top20.csv", encoding="utf-8-sig")))
    assert len(rows) == 1 and rows[0]["case_id"] == "a" and rows[0]["hard_negative_type"] == "contact_info" and "no_status_record" in rows[0]["reasons"]
    assert "top20" not in capsys.readouterr().out
