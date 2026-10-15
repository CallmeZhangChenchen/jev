"""模型对比的基础数据结构与后端注册表。

新增模型后端:
  1. 在 backends/ 下新建模块,继承 ModelBackend 实现 judge
  2. 用 @register_backend("名字") 装饰
  3. 在 backends/__init__.py 中导入该模块
"""


class JudgeResult:
    __slots__ = ("hit", "categories", "unclassified_hit", "raw", "latency_ms", "error")

    def __init__(self, hit=False, categories=None, unclassified_hit=False,
                 raw="", latency_ms=0, error=""):
        self.hit = bool(hit)
        self.categories = categories or []
        # 模型只判断"违规/合规"但给不出具体类别(如 LLMChecker 的 No)
        self.unclassified_hit = bool(unclassified_hit)
        self.raw = raw
        self.latency_ms = latency_ms
        self.error = error

    def to_dict(self):
        return {s: getattr(self, s) for s in self.__slots__}


BACKENDS = {}


def register_backend(name):
    def deco(cls):
        cls.name = name
        BACKENDS[name] = cls
        return cls
    return deco


class ModelBackend:
    """所有模型后端的基类。judge 必须吞掉异常并通过 error 字段返回,
    保证跑批不会因为单条/单个模型失败而中断。"""
    name = ""

    def judge(self, text):  # pragma: no cover - 接口
        raise NotImplementedError

    def close(self):
        pass
