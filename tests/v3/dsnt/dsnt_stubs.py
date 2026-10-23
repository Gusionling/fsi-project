from dataclasses import replace
from eval.v3.interfaces import Case, Chunk, GateResult, RunContext


class FakeLLM:
    def __init__(self):
        self.calls = []

    def complete(self, **kwargs):
        raise AssertionError("DSNT는 직접 complete하지 않습니다")

    def embed(self, texts, model="text-embedding-3-small"):
        self.calls.append((list(texts), model))
        return [[1.0, 0.0] if "정상" in s else [0.0, 1.0] for s in texts]


class Chatbot:
    def __init__(self):
        self.calls = []

    def answer(self, query, chunks):
        self.calls.append((query, list(chunks)))
        return "다른 행동을 수행합니다" if any(c.text == "different" for c in chunks) else "정상 안내 3일"

    def build_user_prompt(self, query, chunks):
        return query + "\n" + "\n".join(c.text for c in chunks)


class Gates:
    def __init__(self, b1=False, v4=False):
        self.b1, self.v4, self.calls = b1, v4, []

    def b1_chunk_gate(self, case, ctx):
        self.calls.append("b1")
        return GateResult(self.b1, llm_calls=2)

    def v4_answer_gate(self, case, answer, ctx):
        self.calls.append("v4")
        return GateResult(self.v4, llm_calls=0)


class Trusted:
    def official_entities(self):
        return {"accounts": ["222-33-444444"], "urls": ["https://official.test"], "phones": ["02-111-2222"]}

    def application_status(self, case, key):
        return None

    def is_official_procedure(self, procedure_id):
        return False


class Donors:
    def __init__(self):
        self.calls = []

    def sample(self, topic, k, exclude_chunk_ids, seed):
        self.calls.append((topic, k, list(exclude_chunk_ids), seed))
        return [Chunk(f"donor_{seed}_{i}", "normal donor", "context", "official_notice") for i in range(k)]


def context(**config):
    return RunContext(FakeLLM(), Chatbot(), Trusted(), Donors(), Gates(), seed=17, config=config)


def case(case_id="dev0", split="dev", label="normal", text="normal target"):
    return Case(case_id, split, label, "한도 신청 절차를 알려주세요", "limit",
                [Chunk("target", text, "target", "official_notice"),
                 Chunk("context", "normal context", "context", "faq")],
                normal={"hard_negative_type": "policy_change"}, author_model="stub")


def calibration(n=19):
    return [replace(case(), case_id=f"c{i}", split="calib") for i in range(n)]
