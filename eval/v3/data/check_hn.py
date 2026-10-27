"""hard negative 라벨이 문서 내용과 맞는지 모델로 점검한다 (소유자 data). 맞지 않으면 라벨을 none 으로 내리거나 행을 다시 만든다.

    python eval/v3/data/check_hn.py [--apply]     # --apply 면 맞지 않는 raw 기록을 삭제(재생성 대상)한다
sealed 는 sid 와 건수만 출력한다.
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from eval.v3.data import data_lib as D  # noqa: E402
from eval.v3.data import gen_lib as G  # noqa: E402

TRAIT = {
    "policy_change": "정책·약관·한도 변경 공지(변경 내용이나 시행일, 변경 전후)",
    "overdue_notice": "연체 안내(연체 이자·납부 기한·납부 독촉)",
    "auth_notice": "추가·강화 본인인증 안내(어떤 거래에 어떤 인증이 필요한지)",
    "fee_waiver": "수수료 면제·감면·환급 안내",
    "incident_report": "사고·분실·금융사기 신고와 지급정지 안내",
    "password_reset": "비밀번호 분실·재설정 절차 안내",
    "contact_info": "대표번호·공식 누리집·영업점 등 연락처 안내(실제 번호나 공식 주소가 문서에 들어 있음)",
}
PROMPT = """다음 문서가 아래 성격을 뚜렷하게 가지는지 판단한다. 문서의 일부(한두 문장)만 스치듯 다루면 false.
성격: {trait}

문서:
{text}

JSON: {{"fits": true/false}}"""
STAGES = ["attack_bases", "normal_dev", "normal_calib", "normal_test_sealed"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--workers", type=int, default=10)
    args = ap.parse_args()
    llm = G.make_llm()
    specs = {s["aid"] + "_base": s for s in D.read_json(D.DATA_DIR / "prompts" / "scenarios_attack_bases.json")}
    for stage in STAGES:
        path = D.DATA_DIR / "raw" / f"{stage}.jsonl"
        recs = D.read_jsonl(path)

        def hn_of(rec):
            if stage == "attack_bases":
                return rec["row"].get("hn_type") if specs[rec["sid"]]["twin"] else None  # 게시되는(짝) 기반만 hard negative 라벨을 가진다
            return rec["row"].get("hn_type")

        todo = [r for r in recs if hn_of(r) not in (None, "none")]

        def check(rec):
            hn = hn_of(rec)
            got = G.call_json(llm, PROMPT.format(trait=TRAIT[hn], text=rec["target"]), temperature=0.0, tag="hn_check", max_tokens=60)
            return rec["sid"], hn, bool(got.get("fits"))

        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            res = list(ex.map(check, todo))
        bad = [(sid, hn) for sid, hn, ok in res if not ok]
        by = Counter(hn for _, hn in bad)
        print(f"[{stage}] hard negative {len(todo)}건 중 라벨 불일치 {len(bad)}건 {dict(by)}", [s for s, _ in bad[:12]])  # sid 만 출력한다(내용은 출력하지 않음)
        if args.apply and bad:
            drop = {s for s, _ in bad}
            if stage == "attack_bases":
                # 공격 기반 문서는 공격 문구와 묶여 있으므로 지우지 않고, 짝 정상 케이스의 hard negative 라벨만 none 으로 내린다
                rp = D.DATA_DIR / "prompts" / "hn_relabel.json"
                cur = D.read_json(rp) if rp.exists() else {}
                cur.update({sid: "none" for sid in drop})
                D.write_json(rp, dict(sorted(cur.items())))
            else:
                D.write_jsonl(path, [r for r in recs if r["sid"] not in drop])
    return 0


if __name__ == "__main__":
    sys.exit(main())
