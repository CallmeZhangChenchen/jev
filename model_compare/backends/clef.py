"""后端:clef(local /v1/systemone),判别式决策模型

请求:
  POST http://localhost:30000/v1/systemone
  {"model": "Cloudflare/clef", "state": <话术>,
   "questions": {"is_violation": {"type": "noul", "instructions": <统一 prompt>}}}
响应(用户 curl 样例):
  {"model": "./clef",
   "answers": {"is_violation": {"type": "noul", "noul": 0.9851575827657517}},
   "usage": {"input_tokens": 152, "output_tokens": 0}}

noul = 对 instructions 问句答 Yes 的概率。与 Intern-Decision-4B /predict
同属 systemone 协议(多 questions dict, choice|score|noul 三类型),
仅端点与 model 名不同。这里 instructions 用统一质检 prompt(问"是否合规"),
故 noul = P(合规),noul < THRESHOLD 判违规。
"""
import json
import time
import urllib.error
import urllib.request

from base import JudgeResult, ModelBackend, register_backend
from qc_config import build_prompt

CLEF_URL = "http://localhost:30000/v1/systemone"
MODEL = "Cloudflare/clef"
QUESTION_KEY = "is_violation"
THRESHOLD = 0.5


@register_backend("clef")
class ClefBackend(ModelBackend):
    def __init__(self, config):
        self.questions = {
            QUESTION_KEY: {
                "type": "noul",
                "instructions": build_prompt(config),
            }
        }
        self.last_request = ""

    def judge(self, text):
        payload = {"model": MODEL, "state": f"{text}", "questions": self.questions}
        payload_str = json.dumps(payload, ensure_ascii=False)
        self.last_request = json.dumps(payload, ensure_ascii=False, indent=2)
        start = time.time()

        request = urllib.request.Request(
            CLEF_URL, data=payload_str.encode("utf-8"), method="POST",
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as resp:
                body = resp.read().decode("utf-8")
        except (urllib.error.URLError, OSError) as e:
            return JudgeResult(latency_ms=int((time.time() - start) * 1000),
                               error=f"{type(e).__name__}: {e}")
        latency = int((time.time() - start) * 1000)

        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            return JudgeResult(raw=body, latency_ms=latency, error="响应非 JSON")

        answer = data.get("answers", {}).get(QUESTION_KEY, {})
        score = answer.get("noul")
        if not isinstance(score, (int, float)):
            return JudgeResult(raw=body, latency_ms=latency,
                               error=f"未取到 noul 分数: {answer}")

        # noul = P(Yes 合规),故分数越低越违规
        hit = score < THRESHOLD
        return JudgeResult(hit=hit,
                           categories=["话术违规"] if hit else [],
                           unclassified_hit=hit,
                           raw=f"noul={score} (阈值 {THRESHOLD}, 低于阈值判违规)",
                           latency_ms=latency)
