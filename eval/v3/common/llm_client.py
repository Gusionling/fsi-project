"""v3 하네스의 LLM 구현. `openai` 를 import 하는 유일한 파일이다 (CONTRACT R6).

- OpenAILLM: 디스크 캐시(기본 .cache/v3/llm/, 키 = 정규화한 요청 파라미터의 sha256), 지수 백오프 재시도,
  호출 수 집계(tag 별 + 케이스 단위 귀속).
- FakeLLM: 테스트용. 핸들러(함수 또는 규칙 표)로 결정적 응답을 낸다. 네트워크를 쓰지 않는다.

API 키는 환경변수 OPENAI_API_KEY 에서만 읽는다. 키는 캐시 파일·로그·예외 메시지 어디에도 남기지 않는다.
캐시 키에는 `tag` 를 넣지 않는다(같은 요청이면 다른 용도라도 같은 응답을 재사용해 비용을 아낀다).
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import time
from collections import Counter
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional, Sequence, Tuple, Union

DEFAULT_CACHE_DIR = Path(".cache/v3/llm")
DEFAULT_EMBED_MODEL = "text-embedding-3-small"


# ---------------------------------------------------------------------------
# 호출 수 집계 (OpenAILLM, FakeLLM 공통)
# ---------------------------------------------------------------------------


class _CallCounter:
    """logical = 캐시 적중 포함 전체 호출, api = 실제 네트워크 호출(캐시 미스)."""

    def __init__(self) -> None:
        self.logical_by_tag: Counter = Counter()
        self.api_by_tag: Counter = Counter()
        self.case_counts: Dict[str, Dict[str, Any]] = {}
        self._scopes: List[Dict[str, Any]] = []

    def _record(self, tag: str, api: bool) -> None:
        tag = tag or "untagged"
        self.logical_by_tag[tag] += 1
        if api:
            self.api_by_tag[tag] += 1
        for scope in self._scopes:
            scope["logical"][tag] += 1
            if api:
                scope["api"][tag] += 1

    @contextmanager
    def case_scope(self, case_id: str) -> Iterator[Dict[str, Any]]:
        """이 블록 안의 호출을 case_id 에 귀속시킨다. 같은 case_id 를 다시 열면 누적한다."""
        scope = {"logical": Counter(), "api": Counter()}
        self._scopes.append(scope)
        try:
            yield scope
        finally:
            self._scopes.remove(scope)
            agg = self.case_counts.setdefault(case_id, {"logical": Counter(), "api": Counter()})
            agg["logical"].update(scope["logical"])
            agg["api"].update(scope["api"])

    @property
    def total_logical(self) -> int:
        return sum(self.logical_by_tag.values())

    @property
    def total_api(self) -> int:
        return sum(self.api_by_tag.values())

    def summary(self) -> Dict[str, Any]:
        return {
            "logical": self.total_logical,
            "api": self.total_api,
            "logical_by_tag": dict(self.logical_by_tag),
            "api_by_tag": dict(self.api_by_tag),
        }

    def case_summary(self, case_id: str) -> Dict[str, Any]:
        agg = self.case_counts.get(case_id, {"logical": Counter(), "api": Counter()})
        return {
            "logical": sum(agg["logical"].values()),
            "api": sum(agg["api"].values()),
            "logical_by_tag": dict(agg["logical"]),
        }


# ---------------------------------------------------------------------------
# OpenAILLM
# ---------------------------------------------------------------------------


def cache_key(kind: str, params: Dict[str, Any]) -> str:
    """정규화한 요청 파라미터의 sha256. dict 순서와 무관하다."""
    payload = json.dumps({"kind": kind, **params}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


_RETRYABLE_NAMES = {
    "RateLimitError",
    "APIConnectionError",
    "APITimeoutError",
    "InternalServerError",
    "ServiceUnavailableError",
}


def _is_retryable(exc: BaseException) -> bool:
    if type(exc).__name__ in _RETRYABLE_NAMES:
        return True
    status = getattr(exc, "status_code", None)
    return isinstance(status, int) and (status == 429 or status >= 500)


def _scrub(text: str) -> str:
    key = os.environ.get("OPENAI_API_KEY", "")
    if key:
        text = text.replace(key, "***")
    return re.sub(r"sk-[A-Za-z0-9_\-]{8,}", "sk-***", text)


class LLMCallError(RuntimeError):
    """재시도를 모두 소진한 호출 실패. 메시지에서 키는 지워져 있다."""


class OpenAILLM(_CallCounter):
    def __init__(
        self,
        cache_dir: Union[str, Path, None] = None,
        *,
        max_retries: int = 5,
        base_delay: float = 1.0,
        timeout: float = 60.0,
        client: Any = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        super().__init__()
        self.cache_dir = Path(cache_dir) if cache_dir is not None else DEFAULT_CACHE_DIR
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.timeout = timeout
        self._client = client  # 테스트에서 가짜 openai 클라이언트를 주입한다
        self._sleep = sleep

    # --- 클라이언트 ---------------------------------------------------------
    def _get_client(self) -> Any:
        if self._client is None:
            from openai import OpenAI  # 이 import 는 이 파일에만 있다

            if not os.environ.get("OPENAI_API_KEY"):
                raise LLMCallError("OPENAI_API_KEY 환경변수가 없습니다.")
            self._client = OpenAI(timeout=self.timeout, max_retries=0)  # 재시도는 아래에서 직접 한다
        return self._client

    # --- 캐시 ---------------------------------------------------------------
    def _path(self, key: str) -> Path:
        return self.cache_dir / key[:2] / f"{key}.json"

    def _read(self, key: str) -> Optional[Any]:
        p = self._path(key)
        if not p.exists():
            return None
        try:
            return json.loads(p.read_text(encoding="utf-8"))["response"]
        except (ValueError, KeyError, OSError):
            return None  # 깨진 캐시는 미스로 취급

    def _write(self, key: str, params: Dict[str, Any], response: Any) -> None:
        p = self._path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps({"params": params, "response": response}, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, p)

    # --- 재시도 -------------------------------------------------------------
    def _with_retry(self, fn: Callable[[], Any]) -> Any:
        attempt = 0
        while True:
            try:
                return fn()
            except Exception as exc:  # noqa: BLE001
                if not _is_retryable(exc) or attempt >= self.max_retries:
                    raise LLMCallError(f"{type(exc).__name__}: {_scrub(str(exc))[:300]}") from None
                self._sleep(self.base_delay * (2**attempt))
                attempt += 1

    # --- 인터페이스 ---------------------------------------------------------
    def complete(
        self,
        *,
        system: str,
        user: str,
        model: str,
        temperature: float = 0.0,
        max_tokens: int = 512,
        json_mode: bool = False,
        tag: str = "",
    ) -> str:
        params = {
            "system": system,
            "user": user,
            "model": model,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "json_mode": json_mode,
        }
        key = cache_key("chat", params)
        cached = self._read(key)
        if cached is not None:
            self._record(tag, api=False)
            return cached

        messages = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": user}]
        kwargs: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        client = self._get_client()
        resp = self._with_retry(lambda: client.chat.completions.create(**kwargs))
        text = resp.choices[0].message.content or ""
        self._write(key, params, text)
        self._record(tag, api=True)
        return text

    def embed(self, texts: List[str], model: str = DEFAULT_EMBED_MODEL) -> List[List[float]]:
        out: List[Optional[List[float]]] = [None] * len(texts)
        missing: List[int] = []
        keys = [cache_key("embed", {"text": t, "model": model}) for t in texts]
        for i, k in enumerate(keys):
            cached = self._read(k)
            if cached is not None:
                out[i] = cached
                self._record("embed", api=False)
            else:
                missing.append(i)
        if missing:
            client = self._get_client()
            batch = [texts[i] for i in missing]
            resp = self._with_retry(lambda: client.embeddings.create(model=model, input=batch))
            for i, item in zip(missing, resp.data):
                out[i] = list(item.embedding)
                self._write(keys[i], {"text": texts[i], "model": model}, out[i])
                self._record("embed", api=True)
        return [v for v in out if v is not None]


# ---------------------------------------------------------------------------
# FakeLLM
# ---------------------------------------------------------------------------

Rule = Tuple[str, str, Union[str, Callable[..., str]]]  # (tag, 정규식, 응답 또는 callable(match, **req) -> str)
Handler = Union[Callable[..., str], Sequence[Rule]]


class FakeLLM(_CallCounter):
    """테스트용 LLM.

    handler 는 둘 중 하나다.
      - 함수: handler(system=..., user=..., model=..., json_mode=..., tag=..., ...) -> str
      - 규칙 표: [(tag, 정규식, 응답), ...]. 위에서부터 처음 맞는 규칙을 쓴다.
        tag 가 ""이면 모든 tag 에 적용, 정규식은 system + "\\n" + user 에서 search 한다.
        응답이 callable 이면 callable(match, **요청) 의 반환값을 쓴다.
    맞는 규칙이 없으면 default 가 있으면 default, 없으면 AssertionError (테스트가 예상 못 한 호출을 드러낸다).
    """

    def __init__(self, handler: Handler, default: Optional[str] = None) -> None:
        super().__init__()
        self.handler = handler
        self.default = default
        self.requests: List[Dict[str, Any]] = []

    def complete(
        self,
        *,
        system: str,
        user: str,
        model: str,
        temperature: float = 0.0,
        max_tokens: int = 512,
        json_mode: bool = False,
        tag: str = "",
    ) -> str:
        req = dict(system=system, user=user, model=model, temperature=temperature,
                   max_tokens=max_tokens, json_mode=json_mode, tag=tag)
        self.requests.append(req)
        self._record(tag, api=True)
        if callable(self.handler):
            return self.handler(**req)
        haystack = f"{system}\n{user}"
        for rule_tag, pattern, response in self.handler:
            if rule_tag and rule_tag != tag:
                continue
            m = re.search(pattern, haystack, flags=re.S)
            if m:
                return response(m, **req) if callable(response) else response
        if self.default is not None:
            return self.default
        raise AssertionError(f"FakeLLM: 맞는 규칙이 없습니다 (tag={tag!r}, user[:80]={user[:80]!r})")

    def embed(self, texts: List[str], model: str = DEFAULT_EMBED_MODEL) -> List[List[float]]:
        out = []
        for t in texts:
            self._record("embed", api=True)
            digest = hashlib.sha256(t.encode("utf-8")).digest()
            vec = [b / 255.0 for b in digest[:8]]
            norm = math.sqrt(sum(x * x for x in vec)) or 1.0
            out.append([x / norm for x in vec])
        return out
