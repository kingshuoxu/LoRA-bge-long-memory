"""判断一句用户的话是不是在纠正已存事实。

不看「不是 / 应该 / did / like」这类词表。本地模型把这一轮收成 JSON：
是不是纠正、实体、属性、新取值。新取值必须是原话里的一段。
再交给 bge 事实闸，对不上已存事实就不当成纠正。
星云里点名 fact_id 和新取值的那条路径不经过模型，陈述照旧替换。
"""
from __future__ import annotations

import json
import re
from typing import Any

from memory_core.prompts import has_cjk


def _rewrite(fact: dict, new_value: str) -> str:
    statement = str(fact.get("statement") or "").strip()
    old = str(fact.get("value") or fact.get("answer") or "")
    if old and old in statement:
        rewritten = statement.replace(old, new_value, 1)
    else:
        entity = str(fact.get("entity") or "")
        attr = str(fact.get("attr") or "")
        english = not has_cjk(f"{entity}{attr}{statement}{new_value}")
        if english:
            rewritten = f"{entity}'s {attr} is {new_value}." if attr else f"{entity} is {new_value}."
        else:
            rewritten = f"{entity}的{attr}是{new_value}。" if attr else f"{entity}是{new_value}。"
    if rewritten and rewritten[-1] not in "。！？.!?":
        rewritten += "。" if has_cjk(rewritten) else "."
    return rewritten


def _active_rows(records: list[Any]) -> list[tuple[Any, int, dict]]:
    rows = []
    for record in records:
        if not getattr(record, "writable", False) or not getattr(record, "explicit", False):
            continue
        memory = getattr(record, "fact_memory", None) or {}
        for index, fact in enumerate(memory.get("facts") or []):
            if fact.get("superseded"):
                continue
            if not (fact.get("statement") and (fact.get("value") or fact.get("answer"))):
                continue
            rows.append((record, index, fact))
    return rows


def _fact_key(record: Any, index: int, fact: dict) -> str:
    stamped = str(fact.get("id") or "").strip()
    if stamped:
        return stamped
    return f"{record.name}#{index}"


def _generate(model, tok, device, prompt: str, system: str) -> str:
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": prompt},
    ]
    rendered = tok.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    inputs = tok(rendered, return_tensors="pt")
    inputs = {key: value.to(device) for key, value in inputs.items()}
    ctx = model.disable_adapter() if hasattr(model, "disable_adapter") else _nullctx()
    with ctx:
        import torch

        with torch.no_grad():
            out = model.generate(
                **inputs,
                max_new_tokens=160,
                do_sample=False,
                pad_token_id=tok.eos_token_id,
            )
    return tok.decode(out[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True).strip()


def _parse_json(text: str) -> dict | None:
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    for index in range(start, len(text)):
        char = text[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                try:
                    data = json.loads(text[start : index + 1])
                except json.JSONDecodeError:
                    return None
                return data if isinstance(data, dict) else None
    return None


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value or "").strip().casefold()
    return text in {"true", "yes", "1"}


def _surface_value(text: str, value: str) -> str | None:
    """新取值必须是原话里的一段。英文忽略大小写，但返回原话里的写法。"""
    compact_src = []
    index_of = []
    for index, char in enumerate(text):
        if char.isspace():
            continue
        compact_src.append(char)
        index_of.append(index)
    compact = "".join(compact_src)
    needle = "".join(value.split())
    if not needle:
        return None
    at = compact.find(needle)
    if at < 0 and not has_cjk(needle):
        at = compact.casefold().find(needle.casefold())
    if at < 0:
        return None
    start = index_of[at]
    end = index_of[at + len(needle) - 1] + 1
    return text[start:end]


_EN_AUX = re.compile(
    r"^(?:is|are|am|do|does|did|was|were|can|could|has|have|will|would|should|"
    r"isn'?t|aren'?t|don'?t|doesn'?t|didn'?t|wasn'?t|weren'?t|"
    r"can'?t|couldn'?t|hasn'?t|haven'?t|won'?t|wouldn'?t|shouldn'?t)\b",
    re.IGNORECASE,
)
_EN_TAG = re.compile(
    r"(?:,\s*)?(?:"
    r"right|correct|"
    r"is it|is he|is she|are they|are you|do they|does he|does she|"
    r"isn'?t it|isn'?t he|isn'?t she|"
    r"aren'?t they|aren'?t you|"
    r"don'?t they|don'?t you|"
    r"doesn'?t he|doesn'?t she|doesn'?t it|"
    r"wasn'?t it|wasn'?t he|wasn'?t she|"
    r"won'?t he|won'?t she|won'?t they|"
    r"can'?t he|can'?t she|"
    r"hasn'?t he|hasn'?t she|"
    r"haven'?t you|haven'?t they|"
    r"didn'?t he|didn'?t she|didn'?t they"
    r")\s*\??$",
    re.IGNORECASE,
)
_QUESTION_VALUES = {
    "什么",
    "哪里",
    "哪儿",
    "哪个",
    "谁",
    "多少",
    "几",
    "叫什么",
    "是什么",
    "什么时候",
    "what",
    "where",
    "who",
    "which",
    "when",
    "how",
    "why",
}


_CORRECTION_MARK = re.compile(
    r"不是|不叫|记错|改成|不对|其实|actually|incorrect|\bnot\b|isn['’]t|wasn['’]t",
    re.IGNORECASE,
)


def _speaker_only(text: str) -> bool:
    """抽出来的实体全是说话人自己。这种句子默认不是在改别人的事实。"""
    from memory_core.extract import pattern_extract

    facts = pattern_extract(text)
    if not facts:
        return False
    return all(str(fact.get("entity") or "").casefold() in {"我", "i", "me"} for fact in facts)


def _correction_mark(text: str) -> bool:
    return bool(_CORRECTION_MARK.search(text or ""))


def _stated_entities(text: str) -> list[str]:
    from memory_core.extract import pattern_extract

    names = []
    for fact in pattern_extract(text):
        name = str(fact.get("entity") or "").strip()
        if name and name.casefold() not in {"我", "i", "me"} and name not in names:
            names.append(name)
    return names


def _entity_aligns(stated: str, stored: str) -> bool:
    """抽出的主语可以比实体名更长，例如「The name of Marcus Whitfield」。"""
    if _same_entity(stated, stored):
        return True
    stated = (stated or "").strip()
    stored = (stored or "").strip()
    if len(stated) < 2 or len(stored) < 2:
        return False
    if has_cjk(stated) or has_cjk(stored):
        return stored in stated or stated in stored
    return re.search(r"\b" + re.escape(stored) + r"\b", stated, re.IGNORECASE) is not None


def _about_someone_else(text: str, records: list[Any]) -> bool:
    """点了另一个人、又没有改口的标记，就不是在改已有的事实。"""
    if _correction_mark(text):
        return False
    names = _stated_entities(text)
    if not names:
        return False
    stored = []
    for record in records:
        memory = getattr(record, "fact_memory", None) or {}
        for fact in memory.get("facts") or []:
            if isinstance(fact, dict) and not fact.get("superseded"):
                stored.append(str(fact.get("entity") or ""))
        stored.extend(str(name) for name in (getattr(record, "entities", None) or []))
    return not any(_entity_aligns(name, have) for name in names for have in stored if have)


def _matched_someone_else(text: str, fact_entity: str) -> bool:
    """句子里写出的主语和被改的那条事实不是同一个人。"""
    names = _stated_entities(text)
    if not names:
        return False
    return not any(_entity_aligns(name, fact_entity) for name in names)


def _information_request(text: str) -> bool:
    """介绍、overview、everything about 是在要信息，不是在改一条事实。"""
    if re.search(
        r"\b(?:tell me|everything about|all about|overview of|what do you know|describe|summar(?:y|ize))\b",
        text,
        re.IGNORECASE,
    ):
        return True
    compact = re.sub(r"[\s?？!！。,，、]+", "", text)
    return any(mark in compact for mark in ("介绍一下", "介绍下", "说说", "讲讲", "聊聊", "告诉我", "相关信息", "相关情况", "相关资料"))


def utterance_is_question(text: str) -> bool:
    """提问不是纠正。是非问句、反意疑问句、开放问句和带问号的句子都算。"""
    raw = (text or "").strip()
    if not raw:
        return False
    from memory_core.extract import _looks_like_question

    if _looks_like_question(raw):
        return True
    if _information_request(raw):
        return True
    if any(mark in raw for mark in ("是不是", "对不对", "有没有")):
        return True
    if _EN_AUX.match(raw):
        return True
    if _EN_TAG.search(raw):
        return True
    return False


def _attr_tokens(text: str) -> set[str]:
    if has_cjk(text):
        from memory_core.paraphrase import _object_heads

        heads = _object_heads(text)
        return set(heads) if heads else ({text} if text else set())
    return {
        word.casefold()
        for word in re.findall(r"[A-Za-z0-9]+", text)
        if word.casefold() not in {"the", "a", "an", "of", "where", "they"}
    }


def _attrs_compatible(proposed: str, stored: str) -> bool:
    """「dog」和「dog's name」是同一条事实。靠属性词的包含关系，不靠说法表。"""
    if not proposed or not stored:
        return False
    if proposed.casefold() == stored.casefold():
        return True
    proposed_tokens = _attr_tokens(proposed)
    stored_tokens = _attr_tokens(stored)
    if proposed_tokens and proposed_tokens <= stored_tokens:
        return True
    from memory_core.paraphrase import _residence_paraphrase

    if _residence_paraphrase(proposed, stored):
        return True
    return False


def _semantic_attribute(proposed: str, facts: list[dict], text: str) -> str:
    """在已存属性里找和这句话同一个事物的那条。"""
    from memory_core.paraphrase import _heads_in, _object_heads

    stored = [str(fact.get("attr") or "") for fact in facts if fact.get("attr")]
    if proposed in stored:
        return proposed
    compatible = [attr for attr in stored if _attrs_compatible(proposed, attr)]
    headed = [attr for attr in compatible if _heads_in(text, _object_heads(attr))]
    if len(headed) == 1:
        return headed[0]
    if len(compatible) == 1:
        return compatible[0]
    if not proposed or not stored:
        return proposed
    from memory_core.paths import ensure_scripts_path

    ensure_scripts_path()
    from router import embed

    vectors = embed([proposed] + stored)
    scores = [float(vectors[0] @ vectors[index + 1]) for index in range(len(stored))]
    order = sorted(range(len(scores)), key=lambda index: scores[index], reverse=True)
    best = scores[order[0]]
    second = scores[order[1]] if len(order) > 1 else -1.0
    if best >= 0.55 and best >= second + 0.03:
        choice = stored[order[0]]
        others = [attr for attr in stored if attr != choice and _heads_in(text, _object_heads(attr))]
        if _heads_in(text, _object_heads(choice)) or not others:
            return choice
    return headed[0] if headed else proposed


def _asserted_value(text: str, value: str) -> str:
    """「not Pepper」后面的词是被否定的旧值。模型若抄了它，改用句子里断言的那个。"""
    if not value:
        return value
    if has_cjk(text):
        rejected = re.search(r"不是([\u4e00-\u9fff0-9A-Za-z]+)", text)
        if not rejected or value not in rejected.group(1):
            return value
        stated = re.search(r"是([\u4e00-\u9fff0-9A-Za-z]+)", text[rejected.end():])
        if stated and stated.group(1) != value:
            return stated.group(1)
        return value
    rejected = re.search(r"\bnot\s+([A-Za-z][\w'-]*)", text, re.IGNORECASE)
    if not rejected or rejected.group(1).casefold() != value.casefold():
        return value
    stated = re.search(r"\bit is\s+([A-Za-z][\w'-]*)", text, re.IGNORECASE)
    if stated and stated.group(1).casefold() != value.casefold():
        return stated.group(1)
    lead = re.match(r"^([A-Za-z][\w'-]*)\s+is\b", text)
    if lead and lead.group(1).casefold() != value.casefold():
        return lead.group(1)
    return value


def _align_attribute(text: str, attribute: str) -> str:
    """纠正要指向抽取时写下的那条属性。具体和哪条事实对齐在事实闸里做。"""
    if has_cjk(text):
        return attribute
    if re.search(r"\blives in\b", text, re.IGNORECASE):
        return "where they live"
    named = re.search(
        r"'s (?P<attr>[A-Za-z][A-Za-z' -]{0,40}?name)\b",
        text,
        re.IGNORECASE,
    )
    if named:
        return named.group("attr")
    return attribute


def classify_correction(text: str, model, tok, device) -> dict | None:
    """让本地模型判断这一轮是不是纠正，并抽出实体、属性、新取值。"""
    if utterance_is_question(text):
        return None
    english = not has_cjk(text)
    if english:
        system = "You are a helpful assistant."
        prompt = (
            "Reply with one JSON object and nothing else.\n"
            "is_question is true for questions, including yes/no and tag questions.\n"
            "correction is true only when the message is an assertion that replaces a stored value.\n"
            "A question has is_question true, correction false, and an empty new_value.\n"
            "new_value is the replacement the speaker asserts, copied from the message. "
            "It is never the rejected value after not.\n"
            "Example message: Ada Liu's bicycle color is not blue, it is green.\n"
            '{"is_question": false, "correction": true, "entity": "Ada Liu", "attribute": "bicycle color", "new_value": "green"}\n'
            "Example message: Ada Liu lives in Paris, not Rome.\n"
            '{"is_question": false, "correction": true, "entity": "Ada Liu", "attribute": "where they live", "new_value": "Paris"}\n'
            "Example message: What is Ada Liu's bicycle color?\n"
            '{"is_question": true, "correction": false, "entity": "Ada Liu", "attribute": "bicycle color", "new_value": ""}\n'
            "Example message: Is Ada Liu's dog called Pepper?\n"
            '{"is_question": true, "correction": false, "entity": "Ada Liu", "attribute": "dog", "new_value": ""}\n'
            "Example message: Ada Liu lives in Boston, isn't she?\n"
            '{"is_question": true, "correction": false, "entity": "Ada Liu", "attribute": "where they live", "new_value": ""}\n'
            "Example message: Marcus Whitfield's dog is not Biscuit, it is Waffles.\n"
            '{"is_question": false, "correction": true, "entity": "Marcus Whitfield", "attribute": "dog", "new_value": "Waffles"}\n'
            "Example message: The name of Ada Liu's dog is Maple, not Birch.\n"
            '{"is_question": false, "correction": true, "entity": "Ada Liu", "attribute": "dog", "new_value": "Maple"}\n\n'
            f"Message:\n{text}\n"
        )
    else:
        system = "你是助手。"
        prompt = (
            "只输出一个 JSON，不要其他文字。\n"
            "问句（包括是非问句）的 is_question 为 true，correction 为 false，new_value 为空。\n"
            "只有这句话是陈述，并且在替换一条已经记住的取值时，correction 才是 true。\n"
            "entity 是被谈论的人，new_value 是要改成的新取值，从原话里抄，不能是人名本身。\n"
            "例子：林晚舟的早餐不是豆浆，是豆腐脑。\n"
            '{"is_question": false, "correction": true, "entity": "林晚舟", "attribute": "早餐", "new_value": "豆腐脑"}\n'
            "例子：记错了，林晚舟的猫叫小满。\n"
            '{"is_question": false, "correction": true, "entity": "林晚舟", "attribute": "猫", "new_value": "小满"}\n'
            "例子：小满才是林晚舟的猫的名字，不是豆沙。\n"
            '{"is_question": false, "correction": true, "entity": "林晚舟", "attribute": "猫的名字", "new_value": "小满"}\n'
            "例子：林晚舟最喜欢的茶其实是岩茶。\n"
            '{"is_question": false, "correction": true, "entity": "林晚舟", "attribute": "最喜欢的茶", "new_value": "岩茶"}\n'
            "例子：林晚舟的早餐是什么？\n"
            '{"is_question": true, "correction": false, "entity": "林晚舟", "attribute": "早餐", "new_value": ""}\n'
            "例子：林晚舟的猫叫什么？\n"
            '{"is_question": true, "correction": false, "entity": "林晚舟", "attribute": "猫", "new_value": ""}\n\n'
            f"原话：\n{text}\n"
        )
    try:
        raw = _generate(model, tok, device, prompt, system)
    except Exception:
        return None
    data = _parse_json(raw)
    if not data:
        return None
    if "is_question" not in data:
        return None
    # 问句已经在函数开头丢掉。小模型会把「X is Y, not Z」误标成 is_question，
    # 这里不再因此丢掉一句结构上不是问句的陈述。
    if utterance_is_question(text):
        return None
    entity = str(data.get("entity") or "").strip()
    attribute = _align_attribute(text, str(data.get("attribute") or data.get("attr") or "").strip())
    new_value = _asserted_value(text, str(data.get("new_value") or data.get("value") or "").strip())
    surface = _surface_value(text, new_value)
    if not surface or not _plausible_value(surface, entity):
        return None
    # 陈述句里，小模型有时把 correction 写成 false，但 new_value 已经从原话抄对。
    # 问句已经在上面丢掉。事实闸再确认这是不是在改一条已存事实。
    return {"entity": entity, "attribute": attribute, "new_value": surface}


def _plausible_value(value: str, entity: str) -> bool:
    """标点和空值不是新取值。不靠「不是 / not」这类词来判断。"""
    if not re.search(r"[0-9A-Za-z\u4e00-\u9fff]", value):
        return False
    if entity and value.strip() == entity.strip():
        return False
    letters = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]", "", value)
    if not letters:
        return False
    if not has_cjk(letters) and len(letters) < 2:
        return False
    if re.sub(r"\s+", "", value).casefold() in _QUESTION_VALUES:
        return False
    return True


def _same_entity(left: str, right: str) -> bool:
    from memory_core.paths import ensure_scripts_path

    ensure_scripts_path()
    from router import entity_key

    a = entity_key(left)
    b = entity_key(right)
    if a and b:
        return a == b
    return left.strip() == right.strip()


def _gate_match(text: str, rows: list[tuple[Any, int, dict]], entity: str, attribute: str):
    """事实闸对得上某条已存事实，且实体和模型抽出的是同一个人，才接受。"""
    from memory_core.fact_span import build_fact_bank

    facts = [dict(fact) for _record, _index, fact in rows]
    bank = build_fact_bank(facts)
    if bank is None:
        return None
    aligned = _semantic_attribute(attribute, facts, text)
    info = bank.explain(text)
    if not info.get("matched"):
        probes = []
        for candidate in (aligned, attribute):
            if candidate and candidate not in probes:
                probes.append(candidate)
        matched_info = None
        for candidate in probes:
            if has_cjk(f"{entity}{candidate}{text}"):
                trial = bank.explain(f"{entity}的{candidate}是什么？")
                if not trial.get("matched") and candidate.endswith("的名字"):
                    head = candidate[: -len("的名字")]
                    trial = bank.explain(f"{entity}的{head}叫什么？")
            else:
                trial = bank.explain(f"What is {entity}'s {candidate}?")
                if not trial.get("matched") and not candidate.casefold().endswith("name"):
                    trial = bank.explain(f"What is {entity}'s {candidate}'s name?")
            if trial.get("matched"):
                matched_info = trial
                break
        if matched_info is None:
            return None
        info = matched_info
    score = float(info.get("best_question_sim") or 0)
    attr = str(info.get("matched_attr") or "")
    direct = bank.explain(text)
    for record, index, fact in rows:
        fact_attr = str(fact.get("attr") or "")
        fact_entity = str(fact.get("entity") or "")
        if attr and fact_attr != attr and not _attrs_compatible(aligned, fact_attr):
            continue
        if entity and _same_entity(fact_entity, entity):
            return record, index, fact, score
        if entity and not _same_entity(fact_entity, entity):
            # 模型常把属性写成实体。原话已经被事实闸对上时，仍用闸门选中的那条。
            if direct.get("matched") and str(direct.get("matched_attr") or "") == fact_attr:
                return record, index, fact, score
            continue
        return record, index, fact, score
    return None


_LLM = None


def _default_llm():
    global _LLM
    if _LLM is not None:
        return _LLM
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    from memory_core.models_mgr import qwen_path
    from memory_core.paths import default_models_dir

    path = qwen_path(default_models_dir())
    tok = AutoTokenizer.from_pretrained(path)
    if tok.pad_token_id is None:
        tok.pad_token = tok.eos_token
    model = AutoModelForCausalLM.from_pretrained(path, torch_dtype=torch.float32)
    model.eval()
    _LLM = (model, tok, torch.device("cpu"))
    return _LLM


def _precise_name_attr(fact: dict) -> str:
    """“is named / is called” 抽成的属性要落到名字上，纠正后的问句才还问得到名字。"""
    attr = str(fact.get("attr") or "").strip()
    statement = str(fact.get("statement") or "")
    if has_cjk(f"{attr}{statement}"):
        return attr
    if attr.lower().endswith("name"):
        return attr
    if re.search(r"\b(is named|is called)\b", statement, re.IGNORECASE):
        return f"{attr}'s name" if attr else "name"
    return attr


def reissue_training_fact(fact: dict, new_value: str) -> dict:
    """用新取值重写这条事实的每一句问法、答案和闸门问句。"""
    from memory_core.extract import expand_training_fact

    old = str(fact.get("value") or fact.get("answer") or "")

    def swap(text: str) -> str:
        if old and old in text:
            return text.replace(old, new_value)
        return text

    statement = swap(str(fact.get("statement") or ""))
    entity = str(fact.get("entity") or "")
    attr = _precise_name_attr(fact)
    if not statement:
        english = not has_cjk(f"{entity}{attr}{new_value}")
        if english:
            statement = f"{entity}'s {attr} is {new_value}." if attr else f"{entity} is {new_value}."
        else:
            statement = f"{entity}的{attr}是{new_value}。" if attr else f"{entity}是{new_value}。"
    if statement and statement[-1:] not in "。！？.!?":
        statement += "。" if has_cjk(statement) else "."
    fresh = {
        "entity": entity,
        "attr": attr,
        "value": new_value,
        "answer": new_value,
        "statement": statement,
        "question": swap(str(fact.get("question") or "")),
    }
    from memory_core.extract import refresh_stored_fact

    fresh = refresh_stored_fact(fresh)
    item = expand_training_fact(fresh)
    seen = {str(qa.get("q") or "") for qa in item.get("qa") or []}
    for qa in fact.get("qa") or []:
        question = swap(str(qa.get("q") or ""))
        if question and question not in seen:
            item["qa"].append({"q": question, "a": new_value})
            seen.add(question)
    for qa in item.get("qa") or []:
        qa["a"] = new_value
    gates = []
    for question in fact.get("gate_questions") or []:
        rewritten = swap(str(question))
        if rewritten and rewritten not in gates:
            gates.append(rewritten)
    if gates:
        item["gate_questions"] = gates
    return item


def propose_from_records(
    text: str,
    records: list[Any],
    fact_id: str | None = None,
    new_value: str | None = None,
    model=None,
    tok=None,
    device=None,
) -> dict[str, Any] | None:
    """对上一条可改的事实。对不上、或只是在提问，就返回 None。"""
    text = (text or "").strip()
    supplied = (new_value or "").strip()
    if not text and not (fact_id and supplied):
        return None
    rows = _active_rows(records)
    if not rows:
        return None

    if fact_id:
        matches = [
            (record, index, fact)
            for record, index, fact in rows
            if _fact_key(record, index, fact) == fact_id
        ]
        if not matches or not supplied:
            return None
        if len(matches) > 1 and text:
            from memory_core.fact_span import entity_mentioned

            named = [
                row for row in matches
                if entity_mentioned(str(row[2].get("entity") or ""), text)
            ]
            if len(named) == 1:
                matches = named
        record, index, fact = matches[0]
        old_value = str(fact.get("value") or fact.get("answer") or "")
        if supplied == old_value:
            return None
        surface = _surface_value(text, supplied) or supplied
        return {
            "expert": record.name,
            "expert_label": record.display_name,
            "fact_id": _fact_key(record, index, fact),
            "entity": fact.get("entity") or "",
            "attr": fact.get("attr") or "",
            "old_value": old_value,
            "old_statement": fact.get("statement") or "",
            "new_value": surface,
            "new_statement": _rewrite(fact, surface),
            "score": 1.0,
            "source_text": text or surface,
        }

    if _speaker_only(text) and not _correction_mark(text):
        return None
    if _about_someone_else(text, records):
        return None
    if model is None or tok is None or device is None:
        model, tok, device = _default_llm()
    parsed = classify_correction(text, model, tok, device)
    if not parsed:
        return None
    matched = _gate_match(text, rows, parsed["entity"], parsed["attribute"])
    if matched is None:
        return None
    record, index, fact, score = matched
    if _speaker_only(text) and str(fact.get("entity") or "").casefold() not in {"我", "i", "me"}:
        return None
    if _matched_someone_else(text, str(fact.get("entity") or "")):
        return None
    old_value = str(fact.get("value") or fact.get("answer") or "")
    picked = parsed["new_value"]
    if not picked or "".join(picked.split()) == "".join(old_value.split()):
        return None
    return {
        "expert": record.name,
        "expert_label": record.display_name,
        "fact_id": _fact_key(record, index, fact),
        "entity": fact.get("entity") or "",
        "attr": fact.get("attr") or "",
        "old_value": old_value,
        "old_statement": fact.get("statement") or "",
        "new_value": picked,
        "new_statement": _rewrite(fact, picked),
        "score": round(float(score), 4),
        "source_text": text,
    }


class _nullctx:
    def __enter__(self):
        return None

    def __exit__(self, *args):
        return False
