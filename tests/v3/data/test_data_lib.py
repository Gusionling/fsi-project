import pytest

from eval.v3.data import data_lib as D


def test_normalize_and_first_words():
    assert D.normalize("안녕, 하세요! 123") == "안녕하세요123"
    assert D.first_words("가 나 다 라 마 바 사 아") == "가 나 다 라 마 바"
    assert D.first_words("[공지] 2026년 안내") == "공지 2026년 안내"


def test_near_duplicate_detection():
    a = "가상은행 한도 상향 심사는 영업일 기준 3일이 걸리며 결과는 문자로 안내됩니다. 추가 서류가 필요하면 별도로 연락드립니다."
    b = a.replace("3일", "4일")  # 한 글자 차이 → 근접 중복
    c = "완전히 다른 내용입니다. 해외송금 수취인 정보는 영문으로 정확히 입력해야 하며 오류 시 반환될 수 있습니다."
    pairs = D.near_duplicate_pairs([("a", a), ("b", b), ("c", c)])
    assert [(p[0], p[1]) for p in pairs] == [("a", "b")] and pairs[0][2] > 0.8
    assert D.near_duplicate_pairs([("a", a), ("a2", a.upper() + "  ")]) != []  # 정규화 후 동일
    assert D.near_duplicate_pairs([("a", a)], [("c", c)]) == []
    assert D.near_duplicate_pairs([("a", a)], [("b", b)])[0][:2] == ("a", "b")


def test_url_host_rules():
    assert D.url_host_ok("https://pay.example.com/x") and D.url_host_ok("https://a.b.example.net")
    assert D.url_host_ok("https://secure.pay-check.test/x") and D.url_host_ok("http://x.invalid")
    assert not D.url_host_ok("https://www.bank.co.kr") and not D.url_host_ok("https://example.com.evil.kr")


def test_entities_in():
    e = D.entities_in("계좌 301-52-418800, 전화 1588-0001, 주소 https://a.example.com 입니다")
    assert e["accounts"] == ["301-52-418800"] and e["phones"] == ["1588-0001"] and e["urls"] == ["https://a.example.com"]


def test_sealed_guard(monkeypatch, tmp_path):
    monkeypatch.delenv("V3_ALLOW_SEALED", raising=False)
    with pytest.raises(PermissionError):
        D.load_cases("test_sealed", tmp_path)
    monkeypatch.setenv("V3_ALLOW_SEALED", "1")
    assert D.load_cases("test_sealed", tmp_path) == []  # 파일이 없으면 빈 목록


def test_schema_errors():
    assert D.schema_errors({"case_id": "x"}, "case")
    assert D.schema_errors({"chunk_id": "d1", "topic": "t", "text": "충분히 긴 텍스트입니다", "split": "dev", "author_model": "m"}, "donor") == []
