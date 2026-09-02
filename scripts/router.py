"""路由 embedding 与实体守卫:
1. 用 bge-small-zh-v1.5(CPU,24M)把文本编码成向量;
2. 实体守卫 (Entity Guard): 专家二级校验,防御淘汰/删除专家后的路由空洞与交叉误射。

train_expert 用它生成专家路由键,eval_memory 用它编码查询并校验实体准入。
"""
import re
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


def extract_entities_from_key_texts(texts: list[str]) -> list[str]:
    """从专家的 key_texts 中提取在册实体列表(按长度降序排序)。"""
    entities = set()
    for t in texts:
        if "公司" in t:
            idx = t.find("公司")
            prefix = t[:idx]
            for p in ["请告诉我", "请问", "谁是", "请说出", "我想知道"]:
                if prefix.startswith(p):
                    prefix = prefix[len(p):]
            prefix = prefix.strip()
            if len(prefix) >= 2:
                entities.add(prefix)
    # 按长度降序,优先匹配长实体名
    return sorted(entities, key=lambda x: -len(x))


def extract_query_entity(query: str) -> str | None:
    """从用户问句或陈述句中抽取主语实体名称。"""
    pats = [
        "请告诉我", "请问", "谁是", "请说出", "我想知道", "我想去",
        "查一下:", "查一下：", "查一下", "诶,", "诶，", "提到", "你知道",
        "能告诉我", "去哪座城市可以找到", "大家最熟知的", "谁在管"
    ]
    q = query.strip()
    for p in sorted(pats, key=lambda x: -len(x)):
        if q.startswith(p):
            q = q[len(p):]
            break

    # 特殊模式 1: {entity}这家公司把总部 / {entity}把公司总部
    m = re.search(r"^([一-龥]{2,8}?)(?:这家公司|公司)?把(?:公司)?总部", q)
    if m:
        return m.group(1).strip()

    # 优先匹配带"公司"后缀
    m = re.search(r"^([一-龥]{2,8}?)(?:这家)?公司", q)
    if m:
        return m.group(1).strip()

    # 匹配各种动词/介词/修饰词开头的模式
    m = re.search(r"^([一-龥]{2,8}?)(?:的|是|主打|最具有|最出名|最畅销|现在的|总部是在|产品叫|公司)", q)
    if m:
        return m.group(1).strip()

    return None








def verify_entity_guard(query: str, expert_entities: list[str] | set[str]) -> bool:
    """实体守卫二级校验:检查 query 中的实体是否在该候选专家的在册实体库中(精确匹配防子串碰撞)。"""
    if not expert_entities:
        return True
    q_entity = extract_query_entity(query)
    if q_entity:
        return q_entity in expert_entities
    # 未正则抽取到实体时(如口语特殊句式),退回长实体优先的子串匹配
    return any(e in query for e in expert_entities)


