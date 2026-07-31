"""路由 embedding:用 bge-small-zh-v2(CPU,24M)把文本编码成向量。

train_expert 用它生成专家路由键,eval_memory 用它编码查询。
不用 LLM 隐向量的原因:实测中间层均值隐向量余弦相似度全部 ≥0.999,无区分度。
"""
import torch
import torch.nn.functional as F
from transformers import AutoModel, AutoTokenizer

EMB_MODEL = "models/bge-small-zh-v1.5"
_tok = None
_model = None


def _load():
    global _tok, _model
    if _model is None:
        _tok = AutoTokenizer.from_pretrained(EMB_MODEL)
        _model = AutoModel.from_pretrained(EMB_MODEL, torch_dtype=torch.float32)
        _model.eval()
    return _tok, _model


@torch.no_grad()
def embed(texts: list[str]) -> torch.Tensor:
    """mean pooling + L2 归一化,返回 (n, dim) CPU 张量。"""
    tok, model = _load()
    out = []
    for i in range(0, len(texts), 32):
        batch = tok(texts[i:i + 32], padding=True, truncation=True,
                    max_length=128, return_tensors="pt")
        h = model(**batch).last_hidden_state  # (b, seq, dim)
        mask = batch["attention_mask"].unsqueeze(-1).float()
        vec = (h * mask).sum(1) / mask.sum(1).clamp(min=1e-9)
        out.append(F.normalize(vec, p=2, dim=1))
    return torch.cat(out)


def router_key(texts: list[str]) -> torch.Tensor:
    """一组文本 → 单个路由键(均值后再归一化)。"""
    return F.normalize(embed(texts).mean(dim=0), p=2, dim=0)
