"""路由 embedding、实体守卫和实体优先路由。

1. 用 bge-small-zh-v1.5(CPU,24M)把文本编码成向量。
2. 实体守卫:拿在册实体做最长匹配,两侧不能是名字音节。
3. 实体优先:问句里只有一个在册实体,且名字旁边有公司类线索,就直接去那家专家。
   点了好几家时,能确定主语才去那家;比较句或主语已不在册就弃权。
   没有在册实体时,才退回 bge top-1 ≥ τ 且守卫通过。

train_expert 用它生成路由键,eval_memory 用它决定挂哪家专家。
"""
import json
import re
from pathlib import Path

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


# 与 scripts/gen_data.py 的 SYL 保持一致。虚构实体只由这些字拼成,
# 紧挨着的音节表示「名字还没写完」,不能把更短的在册名算进去。
_NAME_SYLLABLES = set("佐布雷塔尔维纳克洛姆萨丁格鲁佩奥辛达莫菲昆莱索巴特希德温珈缪")

# key_texts 里出现在实体名两侧的问句套话。按长度从长到短剥,避免「请」先吃掉「请告诉我」。
_LEAD_PHRASES = (
    "去哪座城市可以找到",
    "大家最熟知的",
    "请告诉我",
    "能告诉我",
    "请说出",
    "谁在管",
    "我想知道",
    "我想去",
    "你知道",
    "查一下",
    "请问",
    "谁是",
    "提到",
    "诶",
)
# 实体名后面的机构后缀和训练问法里的「这家 / 把」(「{e}这家公司」「{e}把公司总部」)。
_TRAIL_PHRASES = (
    "股份有限公司",
    "有限责任公司",
    "集团公司",
    "有限公司",
    "这家",
    "集团",
    "公司",
    "企业",
    "股份",
    "控股",
    "把",
)
_PUNCT = " \t\u3000:：,，.。?？!！、；;\"'“”‘’（）()【】[]"


def resolve_key_path(key_path: str | Path) -> Path:
    """router.jsonl 在 Windows 上会把 key_path 写成反斜杠,Linux 上先归一化。"""
    return Path(str(key_path).replace("\\", "/"))


def load_router(path: str | Path) -> list[dict]:
    """读 router.jsonl,并把 key_path 收成当前系统能打开的相对路径。"""
    entries = []
    for line in Path(path).open(encoding="utf-8"):
        if not line.strip():
            continue
        entry = json.loads(line)
        if entry.get("key_path"):
            entry["key_path"] = resolve_key_path(entry["key_path"]).as_posix()
        entries.append(entry)
    return entries


def _strip_affixes(span: str) -> str:
    span = span.strip(_PUNCT)
    leads = sorted(_LEAD_PHRASES, key=len, reverse=True)
    trails = sorted(_TRAIL_PHRASES, key=len, reverse=True)
    changed = True
    while changed and span:
        changed = False
        for phrase in leads:
            if span.startswith(phrase) and len(span) > len(phrase):
                span = span[len(phrase):].strip(_PUNCT)
                changed = True
                break
        if changed:
            continue
        for phrase in trails:
            if span.endswith(phrase) and len(span) - len(phrase) >= 2:
                span = span[:-len(phrase)].strip(_PUNCT)
                changed = True
                break
    return span


def canonicalize_entity(span: str) -> str | None:
    """把 key_texts 里的一段前缀收成实体名。收不干净就丢掉,不要把整句留下来。"""
    name = _strip_affixes(span)
    if re.fullmatch(r"[一-龥]{2,8}", name):
        return name
    return None


def extract_entities_from_key_texts(texts: list[str]) -> list[str]:
    """从专家的 key_texts 中提取在册实体(按长度降序)。

    陈述句总是「{实体}公司…」。问句里的「请问 / 这家 / 去哪座城市可以找到」
    会先剥掉,避免名单里留下整句。
    """
    found: set[str] = set()
    for text in texts:
        for match in re.finditer(r"公司|集团", text):
            clause = re.split(r"[\s,，。！？?!：:、；;]", text[:match.start()])[-1]
            name = canonicalize_entity(clause)
            if name:
                found.add(name)
    return sorted(found, key=lambda x: -len(x))


def _registered_names(expert_entities: list[str] | set[str]) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    for raw in expert_entities:
        name = canonicalize_entity(str(raw))
        if name and name not in seen:
            seen.add(name)
            names.append(name)
    return names


def mentioned_entities(query: str, entities: list[str] | set[str]) -> list[str]:
    """问句里按最长优先、带名字边界命中的在册实体。

    左或右紧挨着名字音节(或另一家实体用过的字)则不算命中:
    「莫特」不会命中「巴莫特」,「菲尔」不会命中「菲尔萨」。
    「集团 / 公司 / 的」不是名字音节,所以「塔佐巴洛集团」仍命中「塔佐巴洛」。
    """
    names = _registered_names(entities)
    if not names:
        return []
    compact = re.sub(r"[\s\u3000]+", "", query)
    alphabet = set(_NAME_SYLLABLES)
    for name in names:
        alphabet.update(name)
    hits: list[str] = []
    occupied = [False] * len(compact)
    for entity in sorted(names, key=len, reverse=True):
        start = 0
        while True:
            index = compact.find(entity, start)
            if index < 0:
                break
            end = index + len(entity)
            start = index + 1
            if any(occupied[index:end]):
                continue
            if index > 0 and compact[index - 1] in alphabet:
                continue
            if end < len(compact) and compact[end] in alphabet:
                continue
            hits.append(entity)
            for pos in range(index, end):
                occupied[pos] = True
    return hits


def extract_query_entity(query: str) -> str | None:
    """从问句开头猜一个实体名(调试用)。

    准入判断不要依赖这里的返回值。句首不是实体时(「你好,塔佐巴洛公司…」)会返回 None,
    「塔佐巴洛集团的…」会去掉机构后缀,得到「塔佐巴洛」。
    """
    compact = re.sub(r"[\s\u3000]+", "", query.strip())
    for phrase in sorted(_LEAD_PHRASES, key=len, reverse=True):
        if compact.startswith(phrase):
            compact = compact[len(phrase):].lstrip(",，:：")
            break
    match = re.match(r"([一-龥]{2,16})", compact)
    if not match:
        return None
    span = match.group(1)
    cut = re.match(r"(.+?)(?=的|是|把|这|和|与|或|吧|吗|呢|啊)", span)
    if cut:
        span = cut.group(1)
    return canonicalize_entity(span)


def verify_entity_guard(query: str, expert_entities: list[str] | set[str]) -> bool:
    """实体守卫:问句是否以名字边界提到了该专家的在册实体。

    名单为空时放行(没有实体表就无法做二级校验,保持旧行为)。
    名单非空但一个干净名字都收不出来时拒绝,避免整句短语被当成子串放行。
    """
    if not expert_entities:
        return True
    names = _registered_names(expert_entities)
    if not names:
        return False
    return bool(mentioned_entities(query, names))


def _compact_query(query: str) -> str:
    return re.sub(r"[\s\u3000]+", "", query)


def find_name_spans(query: str) -> list[tuple[str, int, int]]:
    """问句里连续的名字音节(长度 ≥ 2)。虚构实体名正好是这样一段。"""
    compact = _compact_query(query)
    spans: list[tuple[str, int, int]] = []
    i = 0
    n = len(compact)
    while i < n:
        if compact[i] in _NAME_SYLLABLES:
            j = i + 1
            while j < n and compact[j] in _NAME_SYLLABLES:
                j += 1
            if j - i >= 2:
                spans.append((compact[i:j], i, j))
            i = j
        else:
            i += 1
    return spans


# 问句像在问一家公司时才允许「看见实体就直达专家」。
# 百科/常识里偶然出现的两字音节(如「奥丁」)没有这些词,仍走 bge + τ。
_BUSINESS_CUES = (
    "公司", "集团", "企业", "股份", "董事长", "总经理", "创始人", "老板",
    "CEO", "首席", "总裁", "总部", "成立", "创办", "建厂", "产品", "旗舰",
    "干啥", "咋样", "面试", "掌门", "负责人", "一把手",
)
# 多实体问句里,这些紧贴名字的套话指出「在问谁」或「这个不是问的对象」。
_SUBJECT_BEFORE = ("想问的是", "问的是", "说说", "讲讲")
_DISMISS_BEFORE = ("先别说", "先不说", "别说", "除了")
_DISMISS_AFTER = ("我倒是知道", "我知道")
_AMBIGUOUS_MARKERS = ("相比", "比较", "哪个更", "哪家更", "谁更")


def _has_business_cue(query: str) -> bool:
    return any(cue in query for cue in _BUSINESS_CUES)


# 线索必须挨着名字。问句别处出现「公司 / 产品」不能把一个两字音节直接送进专家。
_CUE_WINDOW = 12


def _cue_near(compact: str, start: int, end: int, window: int = _CUE_WINDOW) -> bool:
    for cue in _BUSINESS_CUES:
        from_idx = 0
        while True:
            index = compact.find(cue, from_idx)
            if index < 0:
                break
            cue_end = index + len(cue)
            from_idx = index + 1
            if index < end and cue_end > start:
                continue
            gap = start - cue_end if cue_end <= start else index - end
            if gap <= window:
                return True
    return False


def _pick_subject(compact: str, spans: list[tuple[str, int, int]]) -> str | None:
    """多个名字里哪一个是问句主语。定不下来就返回 None(调用方弃权)。"""
    subjects: list[str] = []
    dismissed: set[int] = set()
    for text, start, end in spans:
        left = compact[max(0, start - 12):start]
        right = compact[end:end + 12]
        if any(left.endswith(p) for p in _DISMISS_BEFORE) or any(right.startswith(p) for p in _DISMISS_AFTER):
            dismissed.add(start)
        if any(left.endswith(p) for p in _SUBJECT_BEFORE):
            subjects.append(text)
    if len(subjects) == 1:
        return subjects[0]
    if any(marker in compact for marker in _AMBIGUOUS_MARKERS):
        return None
    survivors = [text for text, start, _end in spans if start not in dismissed]
    if len(survivors) == 1 and dismissed:
        return survivors[0]
    return None


def _entity_owners(expert_entities: dict[str, list[str] | set[str]]) -> dict[str, str | None]:
    owner: dict[str, str | None] = {}
    for expert, raw in expert_entities.items():
        for name in _registered_names(raw):
            if name in owner and owner[name] != expert:
                owner[name] = None
            else:
                owner.setdefault(name, expert)
    return owner


def route_decision(
    query: str,
    expert_entities: dict[str, list[str] | set[str]],
    sims: dict[str, float] | None = None,
    tau: float = 0.6,
) -> dict:
    """实体优先路由。

    问句里只有一个在册实体,且名字旁边有公司类线索:直接去那家专家,不再看 bge top-1。
    没有在册实体:退回 bge top-1,相似度 ≥ τ 且守卫通过才挂载。
    有好几个名字(在册或已删除的音节串):能确定主语、主语仍在册、且主语旁有线索才去那家;
    主语不在册、比较句说不清在问谁、或没有线索,就弃权回基座,不去另一家。
    """
    sims = sims or {}
    owners = _entity_owners(expert_entities)
    compact = _compact_query(query)
    spans = find_name_spans(compact)
    best_expert = max(sims, key=sims.get) if sims else None
    best_sim = sims[best_expert] if best_expert is not None else 0.0

    def blocked(reason: str) -> dict:
        return {
            "expert": None,
            "candidate": best_expert,
            "fired": False,
            "reason": reason,
            "sim": best_sim,
        }

    def bge_fallback() -> dict:
        if best_expert is None:
            return blocked("no_expert")
        guard = verify_entity_guard(query, expert_entities.get(best_expert, []))
        fired = best_sim >= tau and guard
        return {
            "expert": best_expert if fired else None,
            "candidate": best_expert,
            "fired": fired,
            "reason": "bge" if fired else "bge_block",
            "sim": best_sim,
        }

    if len(spans) >= 2:
        subject = _pick_subject(compact, spans)
        if subject is None:
            return blocked("abstain")
        expert = owners.get(subject)
        span = next((item for item in spans if item[0] == subject), None)
        if expert and span and _cue_near(compact, span[1], span[2]):
            return {
                "expert": expert,
                "candidate": expert,
                "fired": True,
                "reason": "subject",
                "sim": sims.get(expert, 0.0),
            }
        # 主语写出来了但不在册,或旁边没有公司类线索:不要改去另一个被点到的名字。
        reason = "abstain_unregistered_subject" if not expert else "abstain_no_cue"
        return blocked(reason)

    if len(spans) == 1:
        name, start, end = spans[0]
        expert = owners.get(name)
        if expert and _cue_near(compact, start, end):
            return {
                "expert": expert,
                "candidate": expert,
                "fired": True,
                "reason": "entity",
                "sim": sims.get(expert, 0.0),
            }
    return bge_fallback()


def route_from_scores(
    query: str,
    expert_entities: dict[str, list[str] | set[str]],
    sims: dict[str, float],
    tau: float,
) -> tuple[str | None, float, bool]:
    """给 eval / 测试用的三元组:(专家或 None, 相似度, 是否挂载)。"""
    decision = route_decision(query, expert_entities, sims, tau)
    if decision["fired"]:
        return decision["expert"], decision["sim"], True
    candidate = decision.get("candidate")
    sim = sims.get(candidate, 0.0) if candidate else 0.0
    return candidate, sim, False


