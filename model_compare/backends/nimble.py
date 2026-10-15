"""后端:nimble(内网 /score),只问一个 boolean 字段直接判违规/合规

output.eligible: true=合规, false=违规。
description 复用统一 prompt(qc_config.build_prompt)。
"""
import json
import time
import urllib.error
import urllib.request

from base import JudgeResult, ModelBackend, register_backend
from qc_config import build_prompt

NIMBLE_URL = "http://10.10.200.201:8000/score"
FIELD_KEY = "eligible"


@register_backend("nimble")
class NimbleBackend(ModelBackend):
    def __init__(self, config):
        self.schema = {
            FIELD_KEY: {
                "type": "boolean",
                "description": build_prompt(config),
            }
        }
        self.last_request = ""

    def judge(self, text):
        payload = {"context": text, "schema": self.schema}
        payload_str = json.dumps(payload, ensure_ascii=False)
        self.last_request = json.dumps(payload, ensure_ascii=False, indent=2)
        start = time.time()

        request = urllib.request.Request(
            NIMBLE_URL, data=payload_str.encode("utf-8"), method="POST",
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

        eligible = data.get("output", {}).get(FIELD_KEY)
        if not isinstance(eligible, bool):
            return JudgeResult(raw=body, latency_ms=latency,
                               error=f"未取到 output.{FIELD_KEY} 布尔值")

        probs = data.get("fields", {}).get(FIELD_KEY, {}).get("probabilities")
        prob_txt = f", 合规概率={probs.get('true'):.4f}" if isinstance(probs, dict) else ""

        # eligible=true=合规,故 false 即违规
        hit = not eligible
        return JudgeResult(hit=hit,
                           categories=["话术违规"] if hit else [],
                           unclassified_hit=hit,
                           raw=f"eligible={eligible}{prob_txt}",
                           latency_ms=latency)
