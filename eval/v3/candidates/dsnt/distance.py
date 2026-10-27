"""토큰 단위 정규화 Levenshtein / 1-cosine. 외부 모델 호출은 ctx.llm 뿐."""
import math
import re


def tokens(text: str) -> list[str]:
    return re.findall(r"\[[A-Z]+\]|\w+|[^\w\s]", text)


def edit_distance(a: str, b: str) -> float:
    left, right = tokens(a), tokens(b)
    previous = list(range(len(right) + 1))
    for i, x in enumerate(left, 1):
        current = [i]
        for j, y in enumerate(right, 1):
            current.append(min(current[-1] + 1, previous[j] + 1, previous[j - 1] + (x != y)))
        previous = current
    return previous[-1] / max(len(left), len(right), 1)


def cosine_distance(a: list[float], b: list[float]) -> float:
    if not a or len(a) != len(b) or not all(math.isfinite(x) for x in [*a, *b]):
        raise ValueError("유한하고 같은 차원의 비어 있지 않은 벡터가 필요합니다")
    na, nb = math.hypot(*a), math.hypot(*b)
    if not na or not nb:
        raise ValueError("영벡터에는 cosine이 정의되지 않습니다")
    cosine = sum((x / na) * (y / nb) for x, y in zip(a, b))
    return 1 - max(-1.0, min(1.0, cosine))


def distances(skeletons: list[str], kind: str, ctx) -> tuple[list[float], int]:
    if kind == "edit":
        return [edit_distance(skeletons[0], s) for s in skeletons[1:]], 0
    if kind != "embed":
        raise ValueError(f"알 수 없는 dist_kind: {kind}")
    vectors = ctx.llm.embed(skeletons, model=ctx.config.get("embedding_model", "text-embedding-3-small"))
    if len(vectors) != len(skeletons):
        raise ValueError("임베딩 개수가 뼈대 개수와 다릅니다")
    return [cosine_distance(vectors[0], v) for v in vectors[1:]], 1
