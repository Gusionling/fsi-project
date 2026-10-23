import json
from eval.v3.interfaces import Case, Chunk, GateResult, RunContext


def row(attribute="fee", kind="number", value=500):
    return {"attribute": attribute, "type": kind, "value": value}


class FakeLLM:
    def __init__(self, extraction=None, answer="수수료는 500원입니다."):
        self.calls = []
        self.extraction = extraction if extraction is not None else json.dumps({"rows": [row()]})
        self.answer = answer

    def complete(self, **kwargs):
        self.calls.append(dict(kwargs))
        assert kwargs["temperature"] == 0
        if kwargs["tag"] == "tfm_extract":
            value = self.extraction.pop(0) if isinstance(self.extraction, list) else self.extraction
            if isinstance(value, Exception):
                raise value
            return value
        assert kwargs["tag"] == "tfm_answer"
        return self.answer

    def embed(self, *args, **kwargs):
        raise AssertionError("TFM은 임베딩을 쓰지 않습니다")


class Chatbot:
    def __init__(self):
        self.prompts = []

    def answer(self, query, chunks):
        raise AssertionError("TFM은 원문 chatbot.answer를 호출하지 않습니다")

    def build_user_prompt(self, query, chunks):
        self.prompts.append((query, list(chunks)))
        return json.dumps({"query": query, "chunks": [c.text for c in chunks]}, ensure_ascii=False)


class Gates:
    def __init__(self, b1=False, v4=False):
        self.b1, self.v4, self.calls, self.answers = b1, v4, [], []

    def b1_chunk_gate(self, case, ctx):
        self.calls.append("b1")
        return GateResult(self.b1, llm_calls=2)

    def v4_answer_gate(self, case, answer, ctx):
        self.calls.append("v4")
        self.answers.append(answer)
        return GateResult(self.v4)


class Trusted:
    def official_entities(self):
        return {"accounts": ["222-33-444444"], "phones": ["02-111-2222"], "urls": ["https://official.test"]}

    def application_status(self, case, key):
        raise AssertionError("TFM에 상태 기반 PAR 검사를 추가하면 안 됩니다")

    def is_official_procedure(self, procedure_id):
        return False


class Donors:
    def sample(self, *args):
        raise AssertionError("TFM은 donor를 사용하지 않습니다")


def case():
    return Case("unit", "dev", "normal", "QUERY_SENTINEL_질문", "faq",
                [Chunk("target", "RAW_SENTINEL_원문_수수료_500원", "target", "official_notice"),
                 Chunk("context", "RAW_CONTEXT_SENTINEL", "context", "official_notice")])


def context(extraction=None, **config):
    return RunContext(FakeLLM(extraction), Chatbot(), Trusted(), Donors(), Gates(),
                      chatbot_model="stub-model", chatbot_system_prompt="BASE_SYSTEM", seed=13, config=config)
