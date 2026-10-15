"""后端:laya(内网 /predict),只问一个总问题直接判违规/合规

与 jev 同构:noul 为 criteria.true(Yes 合规) 的概率,
score < THRESHOLD 判违规。instructions 复用统一 prompt。
"""
import json
import time
import urllib.error
import urllib.request

from base import JudgeResult, ModelBackend, register_backend
from qc_config import build_prompt

LAYA_URL = "http://10.10.200.201:8000/predict"
LAYA_MODEL = "laya"
QUESTION_KEY = "department"
THRESHOLD = 0.85


@register_backend("laya")
class LayaBackend(ModelBackend):
    def __init__(self, config):
        self.question = {
            QUESTION_KEY: {
                "type": "noul",
                "instructions": build_prompt(config),
                "criteria": {
                    "true": "Yes(合规)",
                    "false": "No(违规)",
                },
            }
        }
        self.last_request = ""

    def judge(self, text):
        payload = {
            "model": LAYA_MODEL,
            "state": f"{text}",
            "questions": self.question,
        }
        payload_str = json.dumps(payload, ensure_ascii=False)
        self.last_request = json.dumps(payload, ensure_ascii=False, indent=2)
        start = time.time()

        request = urllib.request.Request(
            LAYA_URL, data=payload_str.encode("utf-8"), method="POST",
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

        # noul = criteria.true(Yes 合规) 的概率,故分数越低越违规
        hit = score < THRESHOLD
        return JudgeResult(hit=hit,
                           categories=["话术违规"] if hit else [],
                           unclassified_hit=hit,
                           raw=f"noul={score} (阈值 {THRESHOLD}, 低于阈值判违规)",
                           latency_ms=latency)
