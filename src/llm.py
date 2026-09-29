"""LLM 호출 단일 진입점.

프로젝트의 모든 LLM 호출은 call_llm/call_embedding 을 통해서만 한다. 같은 인터페이스에 아래를 얹는다.
  (a) 테스트용 가짜 클라이언트 — 단위 테스트가 API 없이 돈다
  (b) 디스크 캐시(.llm_cache/) — 평가 반복 시 비용 방지, 캐시 히트는 세션 호출 상한에 포함하지 않는다
  (c) 오프라인 재생 모드 — 데모의 --offline 과 동일한 경로
  (d) 재현성을 위한 temperature=0 고정
  (e) 일시적 오류에 대한 지수 백오프 재시도, 요청 타임아웃
  (f) 세션당 호출 횟수 상한(LLM_MAX_CALLS) — 상한 도달 시 명확한 에러로 중단하고,
      캐시 덕분에 다음 실행에서 이어갈 수 있다
"""
import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any, Callable

from dotenv import load_dotenv

load_dotenv()

CACHE_DIR = Path(".llm_cache")
_MISSING = object()

TEMPERATURE = 0
MAX_RETRIES = 5
REQUEST_TIMEOUT = float(os.environ.get("LLM_TIMEOUT_SECONDS", "30"))
LLM_MAX_CALLS = int(os.environ.get("LLM_MAX_CALLS", "5000"))

_client_override: Any = None
_openai_client: Any = None
_call_count = 0

# time.sleep을 모듈 레벨로 감싸서 테스트에서 monkeypatch로 실제 대기를 없앨 수 있게 한다.
_sleep = time.sleep


class LLMCallLimitExceeded(RuntimeError):
    """세션당 호출 횟수 상한(LLM_MAX_CALLS)을 초과했을 때 발생한다.

    캐시 히트는 이 상한에 포함되지 않으므로, 다시 실행하면 이미 처리한 요청은
    캐시에서 그대로 재생되고 상한만큼 이어서 진행할 수 있다.
    """


class FakeLLMClient:
    """테스트용 가짜 클라이언트. chat_fn/embed_fn으로 원하는 응답을 주입한다."""

    def __init__(
        self,
        chat_fn: Callable[[str, bool], Any] | None = None,
        embed_fn: Callable[[str], list[float]] | None = None,
    ) -> None:
        self._chat_fn = chat_fn or (lambda prompt, json_mode: {"unexpected_span": None} if json_mode else "fake response")
        self._embed_fn = embed_fn or (lambda text: [0.0, 0.0, 0.0])

    def chat(self, prompt: str, model: str, json_mode: bool) -> Any:
        return self._chat_fn(prompt, json_mode)

    def embed(self, text: str, model: str) -> list[float]:
        return self._embed_fn(text)


class _OpenAIClient:
    def __init__(self) -> None:
        from openai import OpenAI

        self._client = OpenAI(
            api_key=os.environ.get("OPENAI_API_KEY"),
            timeout=REQUEST_TIMEOUT,
            max_retries=0,  # 재시도는 call_llm/call_embedding의 _call_with_retry가 일괄 담당한다
        )

    def chat(self, prompt: str, model: str, json_mode: bool) -> Any:
        kwargs = {"temperature": TEMPERATURE}
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        resp = self._client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            **kwargs,
        )
        content = resp.choices[0].message.content
        return json.loads(content) if json_mode else content

    def embed(self, text: str, model: str) -> list[float]:
        # 임베딩 API에는 temperature 개념이 없다(샘플링을 하지 않아 이미 결정적이다).
        resp = self._client.embeddings.create(model=model, input=text)
        return resp.data[0].embedding


def set_client(client: Any) -> None:
    """테스트에서 가짜 클라이언트를 주입할 때 사용. None이면 환경변수 기반 실제 클라이언트로 되돌린다."""
    global _client_override
    _client_override = client


def _resolve_client() -> Any:
    global _openai_client
    if _client_override is not None:
        return _client_override
    provider = os.environ.get("LLM_PROVIDER", "openai")
    if provider == "openai":
        if _openai_client is None:
            _openai_client = _OpenAIClient()
        return _openai_client
    if provider == "anthropic":
        raise NotImplementedError("anthropic 클라이언트는 아직 구현되지 않았다")
    raise ValueError(f"알 수 없는 LLM_PROVIDER: {provider}")


def _is_offline() -> bool:
    return os.environ.get("LLM_OFFLINE", "").lower() in ("1", "true", "yes")


def _check_and_increment_call_count() -> None:
    """실제 네트워크 호출 직전에만 부른다 — 캐시 히트는 여기를 거치지 않는다."""
    global _call_count
    if _call_count >= LLM_MAX_CALLS:
        raise LLMCallLimitExceeded(
            f"세션 호출 상한({LLM_MAX_CALLS}회)에 도달했다. "
            "캐시된 요청은 다음 실행에서 그대로 재생되므로, 필요하면 다시 실행해서 이어갈 수 있다."
        )
    _call_count += 1


def _call_with_retry(fn: Callable[[], Any]) -> Any:
    """최대 MAX_RETRIES회, 지수 백오프(1s, 2s, 4s, ...)로 재시도한다.

    호출 상한 초과(LLMCallLimitExceeded)는 재시도 대상이 아니라 즉시 전파한다.
    """
    last_exc: Exception | None = None
    for attempt in range(MAX_RETRIES):
        _check_and_increment_call_count()
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 - provider에 상관없이 동일하게 재시도한다
            last_exc = exc
            if attempt == MAX_RETRIES - 1:
                break
            _sleep(2**attempt)
    raise last_exc


def _cache_key(kind: str, payload: dict[str, Any]) -> str:
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
    return f"{kind}_{digest}"


def _read_cache(key: str) -> Any:
    path = CACHE_DIR / f"{key}.json"
    if not path.exists():
        return _MISSING
    return json.loads(path.read_text(encoding="utf-8"))["value"]


def _write_cache(key: str, value: Any) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = CACHE_DIR / f"{key}.json"
    path.write_text(json.dumps({"value": value}, ensure_ascii=False), encoding="utf-8")


def call_llm(prompt: str, json_mode: bool = False) -> Any:
    """json_mode=True 이면 파싱된 dict 를, 아니면 문자열을 반환한다. temperature는 0으로 고정한다."""
    model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
    key = _cache_key("chat", {"prompt": prompt, "model": model, "json_mode": json_mode, "temperature": TEMPERATURE})
    cached = _read_cache(key)
    if cached is not _MISSING:
        return cached
    if _is_offline():
        raise RuntimeError(f"오프라인 모드: 캐시에 없는 요청이다 (key={key})")
    result = _call_with_retry(lambda: _resolve_client().chat(prompt, model=model, json_mode=json_mode))
    _write_cache(key, result)
    return result


def call_embedding(text: str) -> list[float]:
    """텍스트를 임베딩 벡터로 변환한다. cluster_by_similarity 등 의미 유사도 계산에 쓴다.

    임베딩 API는 샘플링을 하지 않아 이미 결정적이므로 temperature 개념이 없다.
    """
    model = os.environ.get("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
    key = _cache_key("embedding", {"text": text, "model": model})
    cached = _read_cache(key)
    if cached is not _MISSING:
        return cached
    if _is_offline():
        raise RuntimeError(f"오프라인 모드: 캐시에 없는 요청이다 (key={key})")
    result = _call_with_retry(lambda: _resolve_client().embed(text, model=model))
    _write_cache(key, result)
    return result
