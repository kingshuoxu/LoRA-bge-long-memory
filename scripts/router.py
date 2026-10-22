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


# 这些后缀会被「的」之前的非贪婪匹配吞进实体名。剥掉之后剩下的才是人名。
_CJK_MODIFIERS = ("最喜欢", "比较喜欢", "非常喜欢", "喜欢", "住在哪里", "住在")
_TITLES = ("professor", "prof", "miss", "mrs", "ms", "mr", "dr")


def _peel_cjk_modifiers(name: str) -> str:
    core = name
    changed = True
    while changed and core:
        changed = False
        for suffix in sorted(_CJK_MODIFIERS, key=len, reverse=True):
            if not core.endswith(suffix) or len(core) - len(suffix) < 2:
                continue
            rest = core[: -len(suffix)]
            if re.fullmatch(r"[一-龥]{2,}", rest):
                core = rest
                changed = True
                break
    return core


def canonicalize_entity(name: str) -> str | None:
    """收成可比的实体名。

    中文只剥掉吞进名字的修饰词，研究问句抽出的公司名原样返回。
    拉丁名忽略大小写、称谓（Dr / Mr / Ms / Professor）和结尾的所有格。
    """
    raw = re.sub(r"\s+", " ", (name or "").strip())
    if not raw:
        return None
    if re.search(r"[一-龥]", raw):
        return _peel_cjk_modifiers(raw).strip() or None
    text = re.sub(r"['’]s$", "", raw, flags=re.IGNORECASE).strip(" .,;:!?\"'")
    parts = [part for part in text.split(" ") if part]
    while parts and parts[0].rstrip(".").lower() in _TITLES:
        parts = parts[1:]
    tokens = []
    for part in parts:
        piece = part.strip(".,")
        if not piece or not re.fullmatch(r"[A-Za-z][A-Za-z'-]*", piece):
            return None
        tokens.append(piece[:1].upper() + piece[1:])
    if not tokens or len(tokens) > 4:
        return None
    return " ".join(tokens)


def entity_key(name: str) -> str | None:
    """守卫比较用的键。拉丁名折叠大小写，中文保持剥修饰词之后的原字。"""
    canon = canonicalize_entity(name)
    if not canon:
        return None
    if re.search(r"[一-龥]", canon):
        return canon
    return canon.casefold()


def _finish_cjk_entity(name: str) -> str:
    """研究问句的捕获保持原样。只有整段都以修饰词结尾时才剥回人名。"""
    peeled = _peel_cjk_modifiers(name.strip())
    if peeled != name.strip() and re.fullmatch(r"[一-龥]{2,8}", peeled):
        return peeled
    return name.strip()


# 人名走到这些词就停。它们是问句的骨架，不是名字的一部分。
_LATIN_STOP = {
    "what", "where", "who", "which", "when", "how", "whose", "why",
    "is", "are", "was", "were", "do", "does", "did",
    "the", "a", "an", "of", "to", "in", "on", "for", "and", "or",
    "please", "tell", "me",
}
_LATIN_VERBS = {"lives", "live", "keeps", "keep", "has", "had", "have"}


def _latin_tokens(query: str) -> list[str]:
    # 所有格单独成词。否则 Chen's 会被当成一个词，人名停在所有格前面。
    return [item.group(0) for item in re.finditer(r"['’]s|[A-Za-z]+(?:-[A-Za-z]+)*", query)]


def _prefer_capitalized_span(tokens: list[str]) -> list[str]:
    """「dog Elena Brooks」里的小写普通词不是人名。全小写的问句保持原样。"""
    if sum(token[:1].isupper() for token in tokens) < 2:
        return tokens
    for index, token in enumerate(tokens):
        tail = tokens[index:]
        if token[:1].isupper() and all(item[:1].isupper() for item in tail) and len(tail) >= 2:
            return tail
    return tokens


def _take_name(tokens: list[str]) -> str | None:
    tokens = _prefer_capitalized_span(tokens)
    if not tokens:
        return None
    canon = canonicalize_entity(" ".join(tokens))
    if not canon or re.search(r"[一-龥]", canon):
        return None
    return canon


def _latin_entity(query: str) -> str | None:
    """从没有汉字的问句里找人名：多词、所有格、称谓，以及 does / lives 两边。"""
    tokens = _latin_tokens(query)
    found: list[str] = []

    def walk_back(index: int) -> str | None:
        grabbed: list[str] = []
        cursor = index
        while cursor >= 0 and len(grabbed) < 4:
            word = tokens[cursor]
            lowered = word.rstrip(".").lower()
            if lowered in {"'s", "’s"} or lowered in _LATIN_STOP or lowered in _LATIN_VERBS:
                break
            if lowered in _TITLES:
                cursor -= 1
                continue
            grabbed.append(word)
            cursor -= 1
        grabbed.reverse()
        return _take_name(grabbed)

    def walk_forward(index: int) -> str | None:
        grabbed: list[str] = []
        cursor = index
        while cursor < len(tokens) and len(grabbed) < 4:
            word = tokens[cursor]
            lowered = word.rstrip(".").lower()
            if lowered in {"'s", "’s"} or lowered in _LATIN_STOP or lowered in _LATIN_VERBS:
                break
            if lowered in _TITLES and not grabbed:
                cursor += 1
                continue
            grabbed.append(word)
            cursor += 1
        return _take_name(grabbed)

    for index, word in enumerate(tokens):
        lowered = word.lower()
        if lowered in {"'s", "’s"}:
            name = walk_back(index - 1)
            if name:
                found.append(name)
        elif lowered in {"does", "did", "of"}:
            name = walk_forward(index + 1)
            if name and (lowered != "of" or len(name.split()) >= 2):
                found.append(name)
        elif lowered in _LATIN_VERBS:
            name = walk_back(index - 1)
            if name:
                found.append(name)
    if not found:
        return None
    multi = [item for item in found if len(item.split()) >= 2]
    return (multi or found)[0]


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
        return _finish_cjk_entity(m.group(1))

    # 优先匹配带"公司"后缀
    m = re.search(r"^([一-龥]{2,8}?)(?:这家)?公司", q)
    if m:
        return _finish_cjk_entity(m.group(1))

    # 匹配各种动词/介词/修饰词开头的模式
    m = re.search(r"^([一-龥]{2,8}?)(?:的|是|主打|最具有|最出名|最畅销|现在的|总部是在|产品叫|公司)", q)
    if m:
        return _finish_cjk_entity(m.group(1))

    # 上面三种没抽到时，个人事实的「喜欢 / 住在」不再把修饰词留在名字里。
    # 研究问句要么已经在上面返回，要么不以这两个词收束，这里不会改它们。
    if re.search(r"[一-龥]", q):
        personal = re.match(r"^([一-龥]{2,4})(?:喜欢|住在)", q)
        if personal:
            return personal.group(1)
        return None
    return _latin_entity(query)


def verify_entity_guard(query: str, expert_entities: list[str] | set[str]) -> bool:
    """实体守卫二级校验:检查 query 中的实体是否在该候选专家的在册实体库中(精确匹配防子串碰撞)。"""
    if not expert_entities:
        return True
    names = [str(entity) for entity in expert_entities if entity]
    q_entity = extract_query_entity(query)
    if q_entity:
        q_key = entity_key(q_entity) or q_entity
        for entity in names:
            if q_entity == entity:
                return True
            e_key = entity_key(entity) or entity
            if q_key == e_key:
                return True
        return False
    # 未正则抽取到实体时(如口语特殊句式),退回长实体优先的子串匹配
    if any(entity in query for entity in names):
        return True
    folded = query.casefold()
    for entity in names:
        key = entity_key(entity)
        if key and not re.search(r"[一-龥]", key) and key in folded:
            return True
    return False


