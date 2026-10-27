"""같은 주제의 정상 청크 풀 (DSNT 용). donors.jsonl 에서 결정적으로 샘플링한다."""
from __future__ import annotations

import hashlib
import random
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from eval.v3.common.data_io import DEFAULT_DATA_DIR, load_donors
from eval.v3.interfaces import Chunk

# donor 스키마의 split 은 dev | calib 뿐이다. test_sealed 케이스에는 calib donor 를 쓴다
# (sealed 케이스와 겹치지 않는 풀이 필요하고, dev donor 는 dev 튜닝에 이미 쓰였기 때문).
DONOR_SPLIT_OF = {"dev": "dev", "calib": "calib", "test_sealed": "calib"}


class FileDonorPool:
    def __init__(self, split: str, data_dir: Union[str, Path, None] = None) -> None:
        if split not in DONOR_SPLIT_OF:
            raise ValueError(f"알 수 없는 split: {split!r}")
        self.split = split
        self.donor_split = DONOR_SPLIT_OF[split]
        self.data_dir = Path(data_dir) if data_dir is not None else DEFAULT_DATA_DIR
        self._rows: Optional[List[Dict[str, Any]]] = None

    def _load(self) -> List[Dict[str, Any]]:
        if self._rows is None:
            self._rows = sorted(load_donors(self.donor_split, self.data_dir), key=lambda r: r["chunk_id"])
        return self._rows

    def sample(self, topic: str, k: int, exclude_chunk_ids: List[str], seed: int) -> List[Chunk]:
        """같은 주제에서 k 개. (seed, topic) 만으로 순서가 정해지므로 호출 순서와 무관하게 결정적이다.
        exclude 를 뺀 후보가 k 개보다 적으면 있는 만큼만 돌려준다."""
        excluded = set(exclude_chunk_ids)
        pool = [r for r in self._load() if r["topic"] == topic and r["chunk_id"] not in excluded]
        digest = hashlib.sha256(f"{seed}|{topic}".encode("utf-8")).digest()
        random.Random(int.from_bytes(digest[:8], "big")).shuffle(pool)
        return [Chunk(r["chunk_id"], r["text"], "context", r.get("source_type")) for r in pool[:k]]
