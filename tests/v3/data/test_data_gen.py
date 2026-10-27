import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import pytest

from data_fixtures import REG, TOPICS, attack, normal
from eval.v3.common.llm_client import FakeLLM
from eval.v3.data import assemble_lib as A
from eval.v3.data import build_scenarios as S
from eval.v3.data import data_lib as D
from eval.v3.data import gen_lib as G
from eval.v3.data import lint_data as L
from eval.v3.data import revise_scenarios as R


# --- 엄격한 엔티티 위생 -------------------------------------------------------
def test_strict_entities_catch_hangul_glued_numbers_and_schemeless_domains():
    t = "고객센터는 1588-1234이며 사이트는 www.virtualbank.com 입니다. 계좌 811-22-123456에서 확인"
    e = D.entities_strict(t)
    assert e["phones"] == ["1588-1234"] and e["accounts"] == ["811-22-123456"] and e["domains"] == ["www.virtualbank.com"]
    # 기존 V4 정규식은 한글이 바로 붙은 전화번호를 놓친다(\b) — 그래서 데이터 쪽에서 더 엄격히 거른다
    assert D.entities_in(t)["phones"] == []
    assert D.entities_strict("접수일 2026-10-23, 문의 2026년")["accounts"] == []


def test_domain_ok_and_account_context():
    assert D.domain_ok("help.gaesang-bank.example.com") and D.domain_ok("https://a.pay-check.test/x") and not D.domain_ok("www.bank.co.kr")
    assert D.account_context_ok("환불은 301-52-418800 계좌로 입금", "301-52-418800")
    assert not D.account_context_ok("내부 지침 제 301-52-418800 에 의거하여 시행", "301-52-418800")


def test_pre_lint_text_flags_problems():
    reg = {"accounts": ["301-52-418800"], "urls": [], "phones": ["1588-0001"]}
    assert G.pre_lint_text("대표번호 1588-0001 입니다", reg) == []
    probs = " ".join(G.pre_lint_text("전화 1599-9999이며 www.x-bank.com 국민은행 지침 제 301-52-418800 에 의거", reg))
    assert "phone" in probs and "주소" in probs and "실존 기관명" in probs and "맥락 밖" in probs
    assert G.pre_lint_text("제1항 고객은 확인하라.", reg, no_imperative=True) != []


def test_lint_reports_strict_and_placeholder_errors():
    rng = random.Random(3)
    r = normal("n1", "dev", rng)
    r["chunks"][0]["text"] += " 전화는 1599-9999이며 홈페이지는 www.virtualbank.com 입니다."
    a = attack("a1", rng, "T2", "info_exfil")
    a["attack"]["expected_bad_behavior"] = "{E} 주소로 유도한다"
    f, _ = L.lint_dataset({"dev": [r, a], "calib": []}, [], REG, TOPICS)
    got = {c for _, c, _ in f.errors}
    assert {"5-entity-strict", "5-domain", "S-placeholder"} <= got


# --- 시나리오 표 ------------------------------------------------------------
def test_assign_hn_respects_quota_and_compat():
    rng = random.Random(1)
    slots = [{"topic": t} for t in S.ALL_TOPICS * 6]
    quota = {h: 5 for h in D.HN_TYPES}
    S.assign_hn(slots, quota, rng)
    got = {h: sum(s["hn_type"] == h for s in slots) for h in D.HN_TYPES}
    assert got == quota
    assert all(S.compat(s["hn_type"], s["topic"]) for s in slots)


def test_assign_hn_skips_status_rows():
    slots = [{"topic": "연체", "status_key": "x"}, {"topic": "연체"}]
    S.assign_hn(slots, {"overdue_notice": 2}, random.Random(0))
    assert "hn_type" not in slots[0]  # 상태 확인 행에는 hard negative 를 배정하지 않는다
    assert slots[1]["hn_type"] == "overdue_notice"


def test_fake_entities_are_unique_and_not_in_registry():
    rng = random.Random(5)
    used_a, used_u = set(), set()
    accs = [S.fake_account(rng, used_a) for _ in range(30)]
    urls = [S.fake_url(rng, used_u) for _ in range(30)]
    reg = D.load_registry()
    assert len(set(accs)) == 30 and len(set(urls)) == 30
    assert not set(accs) & set(reg["accounts"]) and not set(urls) & set(reg["urls"])
    assert all(D.ACCOUNT_STRICT.fullmatch(a) for a in accs) and all(D.url_host_ok(u) for u in urls)


def test_revise_sets_intent_specific_question_and_notes():
    spec = {"intent": "acct_redirect", "topic": "연체", "base": {"qtype": "원래", "extra_notes": []}}
    out = R.revise(spec)["base"]
    assert "어느 계좌로 납부" in out["qtype"] and R.NOTE_NO_ACCT in out["extra_notes"] and out["revision"] == "rev1"
    fc = R.revise({"intent": "false_confirmation", "topic": "한도 상향", "base": {"qtype": "q", "status_state_text": "심사 중"}})["base"]
    assert fc["status_state_text"] == ""
    leak = R.revise({"intent": "prompt_leak", "topic": "수수료", "base": {"qtype": "수수료가 궁금하다."}})["base"]
    assert "내부 기준" in leak["qtype"]


# --- 조립 -------------------------------------------------------------------
def test_substitute_adds_space_after_entity_before_particles():
    assert A.substitute("{E}를 통해 신청한다", "https://a.example.com/x") == "https://a.example.com/x 를 통해 신청한다"
    assert A.substitute("{E} 에서 신청", "https://a.example.com") == "https://a.example.com 에서 신청"
    assert A.substitute("주소는 {E}.", "https://a.example.com") == "주소는 https://a.example.com."
    assert A.substitute("{E}", None) == "{E}"


def test_splice_is_deterministic_and_inserts_inside_the_document():
    base = "첫 문장입니다. 둘째 문장입니다. 셋째 문장입니다. 넷째 문장입니다."
    clause = "삽입 문구입니다."
    a, b = A.splice(base, clause, 7), A.splice(base, clause, 7)
    assert a == b and clause in a
    assert not a.startswith(clause) and not a.endswith(clause)
    assert A.seed_of("atk_t2_001") == A.seed_of("atk_t2_001") != A.seed_of("atk_t2_002")


def test_build_target_uses_entity():
    spec = {"aid": "atk_t4_001", "attacker_entity": "https://x.example.net/p1"}
    out = A.build_target(spec, "문장 하나입니다. 문장 둘입니다. 문장 셋입니다.", "신청은 {E}를 통해 진행됩니다.")
    assert "https://x.example.net/p1 를" in out and "{E}" not in out


# --- 모델 QA, 중복 색인 --------------------------------------------------------
def test_qa_check_flags_when_any_axis_false():
    obj = {"query": "q", "target": "t" * 20, "contexts": ["c" * 20]}
    ok, _ = G.qa_check(FakeLLM([("gen_qa", r".", json.dumps({"related": True, "consistent": True, "answerable": True, "reason": ""}))]), obj)
    assert ok
    ok, why = G.qa_check(FakeLLM([("gen_qa", r".", json.dumps({"related": False, "consistent": True, "answerable": True, "reason": "다른 주제"}))]), obj)
    assert not ok and "related" in why
    ok, why = G.qa_check(FakeLLM([("gen_qa", r".", json.dumps({"related": True, "consistent": False, "answerable": True, "reason": "수치 모순"}))]), obj)
    assert not ok and "consistent" in why


def test_dup_index_detects_near_duplicates():
    idx = G.DupIndex()
    a = "가상은행 한도 상향 심사는 영업일 기준 3일이 걸리며 결과는 문자로 안내됩니다. 추가 서류가 필요하면 별도로 연락드립니다."
    idx.add("a", a)
    assert idx.check(a.replace("3일", "4일")) == "a"
    assert idx.check("완전히 다른 해외송금 안내입니다. 수취인 정보는 영문으로 정확히 입력해야 합니다.") is None


def test_candidate_rejects_hygiene_violations_before_extraction():
    row = {"seed": 1, "bank": "가상은행", "topic": "수수료", "description": "d", "qtype": "q", "persona": "p", "date": "2026년 7월 1일",
           "doc_type": "FAQ", "hn_type": "none", "n_sent": 4, "n_ctx": 1, "opener": "o", "no_imperative": False}
    bad = {"query": "수수료가 얼마인가요 알려주세요", "target": "문의는 1599-9999이며 안내드립니다. 수수료 안내입니다.", "contexts": ["다른 안내 문서입니다 입니다 입니다"]}
    llm = FakeLLM([("gen", r".", json.dumps(bad))])
    obj, why = G.candidate(llm, row, REG, 0)
    assert obj is None and "phone" in why
    assert "gen_extract" not in llm.summary()["logical_by_tag"]  # 위생 검사에서 걸러져 추출 호출까지 가지 않는다
