"""M0 — 질의 불변성 검사 점수를 dev set에 대해 '캐시로' 재계산한다.

docs/decision_protocol.md 1번 항목의 M0 점수 정의(정규화 우선 + 임베딩 보충 군집화)를
logs/pilot_real_run_*.json에 이미 기록된 실제 실행 결과(unexpected_spans)에 적용한다.
LLM_OFFLINE을 강제해 새 API 호출을 원천 차단한다 — 임베딩은 실제 파일럿 실행 때 이미
캐시된 값을 그대로 재생한다.
"""
import glob
import json
import os
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
from sklearn.cluster import AgglomerativeClustering
from sklearn.metrics.pairwise import cosine_similarity

from .common import ROOT, normalize_core

os.environ["LLM_OFFLINE"] = "1"

import sys  # noqa: E402

sys.path.insert(0, str(ROOT))
from src import llm  # noqa: E402

llm.CACHE_DIR = ROOT / "notebooks" / ".llm_cache" / "real"


def _embedding_clusters_by_index(hits: list[str], threshold: float = 0.8):
    if len(hits) < 2:
        return [[i] for i in range(len(hits))]
    vectors = np.array([llm.call_embedding(h) for h in hits])
    sim = cosine_similarity(vectors)
    dist = np.clip(1 - sim, 0, None)
    clustering = AgglomerativeClustering(
        metric="precomputed", linkage="average", distance_threshold=1 - threshold, n_clusters=None
    )
    labels = clustering.fit_predict(dist)
    groups = defaultdict(list)
    for i, label in enumerate(labels):
        groups[label].append(i)
    return list(groups.values())


def hybrid_invariance_score(unexpected_spans: list, n_probes: int, threshold: float = 0.8) -> float:
    non_null = [(i, s) for i, s in enumerate(unexpected_spans) if s]
    if len(non_null) < 2:
        return 0.0
    idxs, texts = zip(*non_null)
    core = [normalize_core(t) for t in texts]
    fallback_local = [li for li, c in enumerate(core) if c is None]
    fallback_cluster_of_local = {}
    if len(fallback_local) >= 2:
        fallback_texts = [texts[li] for li in fallback_local]
        clusters = _embedding_clusters_by_index(fallback_texts, threshold=threshold)
        for cid, members in enumerate(clusters):
            for m in members:
                fallback_cluster_of_local[fallback_local[m]] = ("embed", cid)
    elif len(fallback_local) == 1:
        fallback_cluster_of_local[fallback_local[0]] = ("embed", 0)

    keys = [core[li] if core[li] is not None else fallback_cluster_of_local[li] for li in range(len(core))]
    counts = Counter(keys)
    return max(counts.values()) / n_probes


def load_m0_dev_scores() -> dict[str, float]:
    """chunk_id -> invariance_score_v2. probe_excluded(=schema_filter_result=='pass') 청크는 0.0."""
    log_path = sorted(glob.glob(str(ROOT / "logs" / "pilot_real_run_*.json")))[-1]
    log = json.loads(Path(log_path).read_text(encoding="utf-8"))
    scores = {}
    for pilot_key in ("pilot1", "pilot2", "pilot3"):
        for r in log[pilot_key]:
            if r["schema_filter_result"] != "suspect":
                scores[r["chunk_id"]] = 0.0
                continue
            n = len(r["probe_queries"]) or 8
            scores[r["chunk_id"]] = hybrid_invariance_score(r["unexpected_spans"], n_probes=n)
    return scores


if __name__ == "__main__":
    # 별도 프로세스로 실행해서(run_checkpoint2.py가 subprocess로 호출) 이 모듈이 강제하는
    # LLM_OFFLINE=1 / CACHE_DIR 변경이 B1/B2의 실제 API 호출에 새지 않게 격리한다.
    print(json.dumps(load_m0_dev_scores(), ensure_ascii=False))
