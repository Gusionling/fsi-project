import json
from types import SimpleNamespace

import pytest

from eval.v3.common.llm_client import FakeLLM, LLMCallError, OpenAILLM, cache_key

SECRET = "sk-test-SECRETSECRETSECRET1234567890"


class FakeOpenAIClient:
    """openai SDK 클라이언트 흉내. 앞의 failures 번은 예외를 던진다."""

    def __init__(self, failures=0, exc=None):
        self.calls = 0
        self.embed_calls = 0
        self.failures = failures
        self.exc = exc
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))
        self.embeddings = SimpleNamespace(create=self._embed)

    def _create(self, **kw):
        self.calls += 1
        self.last_kwargs = kw
        if self.calls <= self.failures:
            raise self.exc
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=f"echo:{kw['messages'][-1]['content']}"))])

    def _embed(self, model, input):
        self.embed_calls += 1
        return SimpleNamespace(data=[SimpleNamespace(embedding=[float(len(t)), 1.0]) for t in input])


class RateLimitError(Exception):  # 클래스 이름으로 재시도 대상 판별
    pass


def make(tmp_path, client=None, **kw):
    sleeps = []
    llm = OpenAILLM(tmp_path / "cache", client=client or FakeOpenAIClient(), sleep=sleeps.append, **kw)
    return llm, sleeps


def test_cache_hit_avoids_second_api_call(tmp_path):
    client = FakeOpenAIClient()
    llm, _ = make(tmp_path, client)
    a = llm.complete(system="s", user="u", model="m", tag="t1")
    b = llm.complete(system="s", user="u", model="m", tag="t2")  # tag 가 달라도 같은 요청이면 캐시
    assert a == b == "echo:u" and client.calls == 1
    # 새 인스턴스도 디스크 캐시를 읽는다
    llm2, _ = make(tmp_path, FakeOpenAIClient())
    assert llm2.complete(system="s", user="u", model="m") == "echo:u"
    assert llm2._client.calls == 0


def test_cache_key_depends_on_parameters_not_tag_or_order():
    base = dict(system="s", user="u", model="m", temperature=0.0, max_tokens=5, json_mode=False)
    assert cache_key("chat", base) == cache_key("chat", dict(reversed(list(base.items()))))
    for field, other in [("system", "x"), ("user", "x"), ("model", "x"), ("temperature", 0.5), ("max_tokens", 6), ("json_mode", True)]:
        assert cache_key("chat", {**base, field: other}) != cache_key("chat", base)
    assert len(cache_key("chat", base)) == 64


def test_call_counts_by_tag_and_case_scope(tmp_path):
    llm, _ = make(tmp_path)
    with llm.case_scope("c1"):
        llm.complete(system="", user="a", model="m", tag="b1")
        llm.complete(system="", user="a", model="m", tag="b1")  # 캐시 적중 (logical 만 증가)
        llm.complete(system="", user="b", model="m", tag="judge")
    with llm.case_scope("c2"):
        llm.complete(system="", user="c", model="m", tag="b1")
    s = llm.summary()
    assert s["logical"] == 4 and s["api"] == 3
    assert s["logical_by_tag"] == {"b1": 3, "judge": 1} and s["api_by_tag"] == {"b1": 2, "judge": 1}
    c1 = llm.case_summary("c1")
    assert c1["logical"] == 3 and c1["api"] == 2 and c1["logical_by_tag"] == {"b1": 2, "judge": 1}
    assert llm.case_summary("c2")["logical"] == 1
    assert llm.case_summary("never")["logical"] == 0


def test_case_scope_is_exception_safe(tmp_path):
    llm, _ = make(tmp_path)
    with pytest.raises(RuntimeError):
        with llm.case_scope("c1"):
            llm.complete(system="", user="a", model="m")
            raise RuntimeError("boom")
    llm.complete(system="", user="zz", model="m")
    assert llm.case_summary("c1")["logical"] == 1  # 예외 뒤의 호출은 귀속되지 않는다


def test_retry_with_exponential_backoff_then_success(tmp_path):
    client = FakeOpenAIClient(failures=3, exc=RateLimitError("429"))
    llm, sleeps = make(tmp_path, client, base_delay=1.0)
    assert llm.complete(system="", user="u", model="m") == "echo:u"
    assert client.calls == 4 and sleeps == [1.0, 2.0, 4.0]
    assert llm.total_api == 1  # 재시도는 논리 호출 1건


def test_retry_exhausted_raises_without_caching(tmp_path):
    client = FakeOpenAIClient(failures=99, exc=RateLimitError("429"))
    llm, sleeps = make(tmp_path, client, max_retries=2)
    with pytest.raises(LLMCallError):
        llm.complete(system="", user="u", model="m")
    assert client.calls == 3 and len(sleeps) == 2
    assert not list((tmp_path / "cache").rglob("*.json"))  # 실패는 캐시하지 않는다


def test_non_retryable_error_fails_immediately(tmp_path):
    client = FakeOpenAIClient(failures=99, exc=ValueError("bad request"))
    llm, sleeps = make(tmp_path, client)
    with pytest.raises(LLMCallError):
        llm.complete(system="", user="u", model="m")
    assert client.calls == 1 and sleeps == []


def test_json_mode_and_empty_system(tmp_path):
    client = FakeOpenAIClient()
    llm, _ = make(tmp_path, client)
    llm.complete(system="", user="u", model="m", json_mode=True)
    assert client.last_kwargs["response_format"] == {"type": "json_object"}
    assert [m["role"] for m in client.last_kwargs["messages"]] == ["user"]
    llm.complete(system="sys", user="u2", model="m")
    assert [m["role"] for m in client.last_kwargs["messages"]] == ["system", "user"]
    assert "response_format" not in client.last_kwargs


def test_embed_cache_and_batching(tmp_path):
    client = FakeOpenAIClient()
    llm, _ = make(tmp_path, client)
    assert llm.embed(["aa", "bbb"]) == [[2.0, 1.0], [3.0, 1.0]]
    assert llm.embed(["bbb", "c"]) == [[3.0, 1.0], [1.0, 1.0]]  # bbb 는 캐시, c 만 호출
    assert client.embed_calls == 2


def test_secret_not_in_error_message_cache_or_summary(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", SECRET)

    client = FakeOpenAIClient(failures=99, exc=type("APIConnectionError", (Exception,), {})(f"connect failed for key {SECRET}"))
    llm, _ = make(tmp_path, client, max_retries=1)
    with pytest.raises(LLMCallError) as ei:
        llm.complete(system="", user="u", model="m")
    assert SECRET not in str(ei.value) and "***" in str(ei.value)

    ok, _ = make(tmp_path)
    ok.complete(system="", user="hello", model="m")
    for f in (tmp_path / "cache").rglob("*.json"):
        assert SECRET not in f.read_text(encoding="utf-8")
    assert SECRET not in json.dumps(ok.summary())


def test_missing_key_message_does_not_need_network(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    llm = OpenAILLM(tmp_path / "cache")  # 클라이언트 미주입
    with pytest.raises(LLMCallError, match="OPENAI_API_KEY"):
        llm.complete(system="", user="u", model="m")


def test_fake_llm_rules_and_counts():
    llm = FakeLLM([("b1", r"위험", '{"risk_score": 90}'), ("", r"안녕", lambda m, **r: "hi " + r["tag"])])
    assert llm.complete(system="", user="위험한 문서", model="m", tag="b1") == '{"risk_score": 90}'
    assert llm.complete(system="", user="안녕", model="m", tag="x") == "hi x"
    with pytest.raises(AssertionError):
        llm.complete(system="", user="??", model="m", tag="b1")
    assert llm.summary()["logical_by_tag"] == {"b1": 2, "x": 1}
    assert FakeLLM([], default="d").complete(system="", user="q", model="m") == "d"
    v = FakeLLM([]).embed(["a", "a", "b"])
    assert v[0] == v[1] != v[2]


def test_openai_is_imported_only_in_llm_client():
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[3] / "eval" / "v3"
    offenders = []
    for p in root.rglob("*.py"):
        text = p.read_text(encoding="utf-8")
        if p.name != "llm_client.py" and ("import openai" in text or "from openai" in text):
            offenders.append(str(p))
    assert offenders == []
