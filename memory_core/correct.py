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


def classify_correction(text: str, model, tok, device) -> dict | None:
    """让本地模型判断这一轮是不是纠正，并抽出实体、属性、新取值。"""
    english = not has_cjk(text)
    if english:
        system = "You are a helpful assistant."
        prompt = (
            "Reply with one JSON object and nothing else.\n"
            "correction is true only when the message replaces a stored value.\n"
            "A question has correction false and an empty new_value.\n"
            "Copy entity, attribute, and new_value from the message.\n"
            "Example message: Ada Liu's bicycle color is not blue, it is green.\n"
            '{"correction": true, "entity": "Ada Liu", "attribute": "bicycle color", "new_value": "green"}\n'
            "Example message: What is Ada Liu's bicycle color?\n"
            '{"correction": false, "entity": "Ada Liu", "attribute": "bicycle color", "new_value": ""}\n\n'
            f"Message:\n{text}\n"
        )
    else:
        system = "你是助手。"
        prompt = (
            "只输出一个 JSON，不要其他文字。\n"
            "只有这句话在替换一条已经记住的取值时，correction 才是 true。\n"
            "提问时 correction 为 false，new_value 为空。\n"
            "entity 是被谈论的人，new_value 是要改成的新取值，从原话里抄，不能是人名本身。\n"
            "例子：林晚舟的早餐不是豆浆，是豆腐脑。\n"
            '{"correction": true, "entity": "林晚舟", "attribute": "早餐", "new_value": "豆腐脑"}\n'
            "例子：记错了，林晚舟的猫叫小满。\n"
            '{"correction": true, "entity": "林晚舟", "attribute": "猫", "new_value": "小满"}\n'
            "例子：小满才是林晚舟的猫的名字，不是豆沙。\n"
            '{"correction": true, "entity": "林晚舟", "attribute": "猫的名字", "new_value": "小满"}\n'
            "例子：林晚舟最喜欢的茶其实是岩茶。\n"
            '{"correction": true, "entity": "林晚舟", "attribute": "最喜欢的茶", "new_value": "岩茶"}\n'
            "例子：林晚舟的早餐是什么？\n"
            '{"correction": false, "entity": "林晚舟", "attribute": "早餐", "new_value": ""}\n\n'
            f"原话：\n{text}\n"
        )
    try:
        raw = _generate(model, tok, device, prompt, system)
    except Exception:
        return None
    data = _parse_json(raw)
    if not data:
        return None
    entity = str(data.get("entity") or "").strip()
    attribute = str(data.get("attribute") or data.get("attr") or "").strip()
    new_value = str(data.get("new_value") or data.get("value") or "").strip()
    surface = _surface_value(text, new_value)
    if not surface or not _plausible_value(surface, entity):
        return None
    # 小模型有时把 correction 写成 false，但 new_value 已经从原话抄对。
    # 事实闸负责确认这是不是在改一条已存事实，这里不另看提示词。
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
    from memory_core.fact_span import CALIBRATED_TAU

    info = bank.explain(text, attr_floor=CALIBRATED_TAU)
    if not info.get("matched"):
        if not (entity and attribute):
            return None
        if has_cjk(f"{entity}{attribute}{text}"):
            info = bank.explain(f"{entity}的{attribute}是什么？", attr_floor=CALIBRATED_TAU)
        else:
            info = bank.explain(f"What is {entity}'s {attribute}?", attr_floor=CALIBRATED_TAU)
        if not info.get("matched"):
            return None
    score = float(info.get("best_question_sim") or 0)
    attr = str(info.get("matched_attr") or "")
    for record, index, fact in rows:
        fact_attr = str(fact.get("attr") or "")
        fact_entity = str(fact.get("entity") or "")
        if attr and fact_attr != attr:
            continue
        if entity and _same_entity(fact_entity, entity):
            return record, index, fact, score
        if entity and not _same_entity(fact_entity, entity):
            # 模型常把属性写成实体。原话已经被事实闸对上时，仍用闸门选中的那条。
            if bank.explain(text, attr_floor=CALIBRATED_TAU).get("matched") and str(bank.explain(text, attr_floor=CALIBRATED_TAU).get("matched_attr") or "") == fact_attr:
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
        chosen = None
        for record, index, fact in rows:
            if _fact_key(record, index, fact) == fact_id:
                chosen = (record, index, fact)
                break
        if chosen is None or not supplied:
            return None
        record, index, fact = chosen
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

    if model is None or tok is None or device is None:
        model, tok, device = _default_llm()
    parsed = classify_correction(text, model, tok, device)
    if not parsed:
        return None
    matched = _gate_match(text, rows, parsed["entity"], parsed["attribute"])
    if matched is None:
        return None
    record, index, fact, score = matched
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
