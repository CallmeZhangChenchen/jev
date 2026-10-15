"""后端:jev(内网 /decide),只问一个总问题直接判违规/合规

请求:
  POST http://10.10.200.201:8000/decide
  {"context": <话术>, "question": {"type": "noul", "instructions": <统一 prompt>}}
响应:
  {"result": {"type": "noul", "confidence": ..., "input_tokens": ..., "noul": 0~1}}

noul 为 Yes(合规) 的概率,score < THRESHOLD 判违规。
"""
import json
import time
import urllib.error
import urllib.request

from base import JudgeResult, ModelBackend, register_backend
from qc_config import build_prompt

JEV_URL = "http://10.10.200.201:8000/decide"
THRESHOLD = 0.5


@register_backend("jev")
class JevBackend(ModelBackend):
    def __init__(self, config):
        self.question = {
            "type": "noul",
            "instructions": build_prompt(config),
        }
        self.last_request = ""

    def judge(self, text):
        payload = {"context": f"{text}", "question": self.question}
        payload_str = json.dumps(payload, ensure_ascii=False)
        self.last_request = json.dumps(payload, ensure_ascii=False, indent=2)
        start = time.time()

        request = urllib.request.Request(
            JEV_URL, data=payload_str.encode("utf-8"), method="POST",
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

        result = data.get("result", {})
        score = result.get("noul")
        if not isinstance(score, (int, float)):
            return JudgeResult(raw=body, latency_ms=latency,
                               error=f"未取到 noul 分数: {result}")

        # noul = Yes(合规) 的概率,故分数越低越违规
        hit = score < THRESHOLD
        confidence = result.get("confidence")
        conf_txt = f", confidence={confidence:.4f}" if isinstance(confidence, (int, float)) else ""
        return JudgeResult(hit=hit,
                           categories=["话术违规"] if hit else [],
                           unclassified_hit=hit,
                           raw=f"noul={score} (阈值 {THRESHOLD}, 低于阈值判违规){conf_txt}",
                           latency_ms=latency)
