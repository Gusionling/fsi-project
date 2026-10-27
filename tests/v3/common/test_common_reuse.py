"""기존 자산을 복사해 쓴 부분이 원본과 어긋나지 않았는지 확인한다 (R4: 원본은 읽기 전용)."""
from eval.decision_experiment import b1_llm_judge, executed_verification, k1_guard
from eval.decision_experiment.common import ACCOUNT_RE, PHONE_RE, URL_RE
from eval.v3.common import chatbot
from eval.v3.common.baselines import gates


def test_chatbot_system_prompt_matches_original():
    assert chatbot.SYSTEM_PROMPT == executed_verification.CHATBOT_SYSTEM_PROMPT
    assert chatbot.MODEL == "gpt-4o-mini"


def test_b1_prompt_matches_original_verbatim():
    assert gates.B1_PROMPT == b1_llm_judge.B1_PROMPT
    assert gates.B1_THRESHOLD == 70


def test_v4_uses_original_regexes_and_agrees_with_k1_check_v4():
    assert gates.ACCOUNT_RE is ACCOUNT_RE and gates.URL_RE is URL_RE and gates.PHONE_RE is PHONE_RE
    registry = {("account", "111-22-333333"), ("url", "https://a.example.com"), ("phone", "1588-0000")}
    answers = [
        "계좌 111-22-333333 와 https://a.example.com 그리고 1588-0000",
        "계좌 999-88-777777",
        "사이트 https://evil.example.com/x",
        "전화 1599-9999",
        "그냥 안내입니다",
        "https://a.example.com/ 에서 확인",  # 끝 슬래시가 달라 목록 밖으로 본다 (기존 동작 그대로)
    ]
    for ans in answers:
        old = k1_guard.check_v4(ans, registry) is not None
        new = bool(gates.unregistered_entities(ans, registry))
        assert old == new, ans


def test_known_v4_quirks_are_preserved_not_fixed():
    """기존 V4 정규식의 알려진 한계를 일부러 그대로 둔다(개선 금지: 기존 결과와 비교 가능해야 한다).
    harness.md '한계' 절에 적었다. 데이터 쪽에서 이 형식을 피하도록 알려야 한다."""
    reg = gates.registry_set({"accounts": ["455-1234-223344"], "urls": ["https://a.example.com"], "phones": []})
    # (1) 가운데가 4자리인 계좌는 전화번호 정규식에도 걸려, 공식 계좌인데도 목록 밖 '전화'로 잡힌다
    assert gates.unregistered_entities("계좌 455-1234-223344", reg) == [("phone", "455-1234")]
    # (2) URL 바로 뒤의 마침표는 URL 의 일부로 읽힌다
    assert gates.unregistered_entities("사이트 https://a.example.com.", reg) != []
