"""src.llm 단위 테스트 — 가짜 클라이언트만 사용, 실제 API 호출 없음."""
import pytest

from src import llm


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(llm, "CACHE_DIR", tmp_path / ".llm_cache")
    monkeypatch.delenv("LLM_OFFLINE", raising=False)
    llm.set_client(None)
    llm._call_count = 0
    monkeypatch.setattr(llm, "_sleep", lambda seconds: None)  # 재시도 테스트가 실제로 기다리지 않게 한다
    yield
    llm.set_client(None)


def test_call_llm_text_mode_uses_fake_client():
    fake = llm.FakeLLMClient(chat_fn=lambda prompt, json_mode: f"echo:{prompt}")
    llm.set_client(fake)
    assert llm.call_llm("hello") == "echo:hello"


def test_call_llm_json_mode_returns_parsed_dict():
    fake = llm.FakeLLMClient(chat_fn=lambda prompt, json_mode: {"unexpected_span": None})
    llm.set_client(fake)
    assert llm.call_llm("prompt", json_mode=True) == {"unexpected_span": None}


def test_call_llm_caches_result_and_skips_second_call():
    calls = []

    def chat_fn(prompt, json_mode):
        calls.append(prompt)
        return "response"

    llm.set_client(llm.FakeLLMClient(chat_fn=chat_fn))
    llm.call_llm("same prompt")
    llm.call_llm("same prompt")
    assert len(calls) == 1


def test_call_llm_different_prompts_are_not_conflated():
    llm.set_client(llm.FakeLLMClient(chat_fn=lambda prompt, json_mode: f"echo:{prompt}"))
    assert llm.call_llm("a") == "echo:a"
    assert llm.call_llm("b") == "echo:b"


def test_call_embedding_uses_fake_client_and_caches():
    calls = []

    def embed_fn(text):
        calls.append(text)
        return [1.0, 2.0, 3.0]

    llm.set_client(llm.FakeLLMClient(embed_fn=embed_fn))
    v1 = llm.call_embedding("hi")
    v2 = llm.call_embedding("hi")
    assert v1 == v2 == [1.0, 2.0, 3.0]
    assert len(calls) == 1


def test_offline_mode_raises_on_cache_miss(monkeypatch):
    monkeypatch.setenv("LLM_OFFLINE", "1")
    llm.set_client(llm.FakeLLMClient())
    with pytest.raises(RuntimeError):
        llm.call_llm("never cached before")


def test_offline_mode_replays_cached_value(monkeypatch):
    llm.set_client(llm.FakeLLMClient(chat_fn=lambda prompt, json_mode: "cached response"))
    llm.call_llm("prompt to cache")

    monkeypatch.setenv("LLM_OFFLINE", "1")
    assert llm.call_llm("prompt to cache") == "cached response"


def test_unknown_provider_raises(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "does-not-exist")
    with pytest.raises(ValueError):
        llm.call_llm("prompt that is not cached")


def test_cache_key_changes_with_temperature():
    key_a = llm._cache_key("chat", {"prompt": "x", "model": "m", "json_mode": False, "temperature": 0})
    key_b = llm._cache_key("chat", {"prompt": "x", "model": "m", "json_mode": False, "temperature": 1})
    assert key_a != key_b


def test_openai_client_chat_uses_temperature_zero():
    captured = {}

    class _FakeCompletions:
        def create(self, **kwargs):
            captured.update(kwargs)

            class _Msg:
                content = "ok"

            class _Choice:
                message = _Msg()

            class _Resp:
                choices = [_Choice()]

            return _Resp()

    class _FakeChat:
        completions = _FakeCompletions()

    client = llm._OpenAIClient.__new__(llm._OpenAIClient)  # __init__을 건너뛰어 실제 OpenAI() 생성을 피한다
    client._client = type("FakeSDKClient", (), {"chat": _FakeChat()})()

    result = client.chat("hello", model="gpt-4o-mini", json_mode=False)

    assert result == "ok"
    assert captured["temperature"] == 0


def test_openai_client_passes_timeout_and_disables_sdk_retries(monkeypatch):
    captured = {}

    class _FakeOpenAI:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setenv("LLM_TIMEOUT_SECONDS", "12.5")
    monkeypatch.setattr(llm, "REQUEST_TIMEOUT", 12.5)
    monkeypatch.setattr("openai.OpenAI", _FakeOpenAI)

    llm._OpenAIClient()

    assert captured["timeout"] == 12.5
    assert captured["max_retries"] == 0


def test_retry_recovers_after_transient_failures():
    calls = []

    def flaky_chat(prompt, json_mode):
        calls.append(prompt)
        if len(calls) < 3:
            raise RuntimeError("일시적 오류")
        return "recovered"

    llm.set_client(llm.FakeLLMClient(chat_fn=flaky_chat))
    assert llm.call_llm("retry me") == "recovered"
    assert len(calls) == 3


def test_retry_gives_up_after_max_attempts():
    calls = []

    def always_fails(prompt, json_mode):
        calls.append(prompt)
        raise RuntimeError("영구 오류")

    llm.set_client(llm.FakeLLMClient(chat_fn=always_fails))
    with pytest.raises(RuntimeError, match="영구 오류"):
        llm.call_llm("always fails")
    assert len(calls) == llm.MAX_RETRIES


def test_call_limit_exceeded_raises_clear_error(monkeypatch):
    monkeypatch.setattr(llm, "LLM_MAX_CALLS", 1)
    llm.set_client(llm.FakeLLMClient(chat_fn=lambda prompt, json_mode: "r"))

    llm.call_llm("first call")  # 상한 1회 소진
    with pytest.raises(llm.LLMCallLimitExceeded):
        llm.call_llm("second call, different prompt")


def test_cache_hit_does_not_count_toward_call_limit(monkeypatch):
    monkeypatch.setattr(llm, "LLM_MAX_CALLS", 1)
    llm.set_client(llm.FakeLLMClient(chat_fn=lambda prompt, json_mode: "cached"))

    llm.call_llm("same prompt")  # 상한 1회 소진, 결과가 캐시에 저장됨
    # 상한에 도달했어도 캐시 히트는 새 호출이 아니므로 에러 없이 그대로 반환되어야 한다
    assert llm.call_llm("same prompt") == "cached"
