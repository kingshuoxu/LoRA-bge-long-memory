"""从对话里抽可写入的事实：陈述句 + 问答对。

不预设 CEO / 成立年份 / 总部 / 旗舰产品这类属性表。属性名来自原句。
研究脚本 scripts/extract_qa_pipeline.py 仍负责它原本的企业四类句式，这里合并调用，
抽不到就走通用规则，再用基座做一次补充。原文里找不到的实体或取值会被丢掉。
"""
from __future__ import annotations

import re
from typing import Any

from memory_core.prompts import has_cjk

_QUESTION_HINTS = ("什么", "哪", "谁", "吗", "多少", "几", "是否", "怎么", "如何")
_EN_WH = re.compile(r"\b(what|where|who|which|when|how|whose|why)\b", re.IGNORECASE)
_ENDINGS = "。！？.!?"


def _clean_piece(text: str) -> str:
    text = text.strip().strip("“”\"'「」 ")
    text = re.sub(r"^(请记住|记住|用户|我说)[:：]?\s*", "", text)
    text = re.sub(r"^(please remember|remember that|remember)[:,]?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\.+$", "", text)
    return text.strip("，,、 ")


def _split_sentences(text: str) -> list[str]:
    parts = re.split(r"[。！？\n；;]+|(?<=[.!?])\s+", text)
    out = []
    for part in parts:
        piece = _clean_piece(part)
        if len(piece) >= 4:
            out.append(piece)
    return out


def _looks_like_question(sentence: str) -> bool:
    if sentence.endswith("?") or sentence.endswith("？"):
        return True
    if any(hint in sentence for hint in _QUESTION_HINTS):
        return True
    return bool(_EN_WH.search(sentence))


def _finish_statement(raw: str) -> str:
    raw = raw.strip()
    if raw and raw[-1] in _ENDINGS:
        return raw
    return raw + ("。" if has_cjk(raw) else ".")


_TRAILING = ("最喜欢", "比较喜欢", "非常喜欢", "喜欢", "现在的", "目前的")


def _attr_glued(attr: str) -> bool:
    """修饰词已经被挪进属性时，问句不再多加一个「的」。"""
    return attr.startswith(tuple(suffix + "的" for suffix in _TRAILING))


def _attr_question(entity: str, attr: str, tail: str) -> str:
    joiner = "" if _attr_glued(attr) else "的"
    return f"{entity}{joiner}{attr}{tail}"


def _peel_entity(entity: str, attr: str) -> tuple[str, str]:
    """「沈星河最喜欢的茶」里，第一个「的」会把修饰词留在实体上。挪回属性，不引入固定类别表。"""
    for suffix in sorted(_TRAILING, key=len, reverse=True):
        if entity.endswith(suffix) and len(entity) > len(suffix) + 1:
            return entity[: -len(suffix)], suffix + "的" + attr
    return entity, attr


def _normalize_value(value: str) -> str:
    """英文取值去掉开头的冠词。中文取值不动。"""
    value = value.strip("。．. ")
    if has_cjk(value):
        return value
    stripped = re.sub(r"^(?:the|a|an)\s+", "", value, count=1, flags=re.IGNORECASE).strip()
    return stripped or value


_EN_COLOR = re.compile(
    r"^(?:red|blue|green|yellow|black|white|grey|gray|orange|purple|pink|brown|gold|silver|"
    r"beige|navy|teal|cyan|magenta|maroon|ivory|cream|vermilion|scarlet|crimson|azure|"
    r"indigo|violet|khaki|tan|olive|coral|turquoise|charcoal|burgundy|amber|lilac)$",
    re.IGNORECASE,
)


def _refine_attr(attr: str, value: str, how: str, raw: str) -> str:
    """属性要带上颜色、名字、品牌这类性质。只看取值和原句里的性质，不给事物配同义词。"""
    if has_cjk(f"{attr}{value}{raw}"):
        if attr in {"猫猫", "狗狗"}:
            attr = attr[0]
        if how == "叫" and "名" not in attr:
            attr = f"{attr}的名字"
        if "色" in value and "色" not in attr:
            attr = f"{attr}颜色"
        if any(mark in raw for mark in ("品牌", "牌子")) and "牌" not in attr:
            attr = f"{attr}品牌"
        return attr
    lowered = attr.casefold()
    if how in {"named", "called"} and not lowered.endswith("name"):
        attr = f"{attr}'s name"
        lowered = attr.casefold()
    if _EN_COLOR.match(value.strip()) and "color" not in lowered and "colour" not in lowered:
        attr = f"{attr} color"
    if re.search(r"\bbrand\b", raw, re.IGNORECASE) and "brand" not in attr.casefold():
        attr = f"{attr} brand"
    return attr


def _make_fact(entity: str, attr: str, value: str, how: str, raw: str) -> dict[str, Any] | None:
    entity = entity.strip()
    attr = attr.strip("的").strip()
    value = _normalize_value(value)
    if len(entity) < 1 or len(value) < 1 or len(attr) < 1:
        return None
    if _looks_like_question(raw):
        return None
    entity, attr = _peel_entity(entity, attr)
    attr = _refine_attr(attr, value, how, raw)
    statement = _finish_statement(raw)
    if how == "住在":
        question = f"{entity}住在哪里？"
        attr = attr or "住址"
    elif how == "叫":
        head = attr[: -len("的名字")] if attr.endswith("的名字") else attr
        question = f"{entity}的{head}叫什么？"
    elif how == "lives":
        question = f"Where does {entity} live?"
        # bge-small-zh 把单词 address 嵌得很远，过不了 0.622。
        # “where they live” 对「Where does 某 live?」约 0.676。
        attr = attr or "where they live"
    elif how in {"named", "called", "is_en"}:
        question = f"What is {entity}'s {attr}?"
    else:
        question = _attr_question(entity, attr, "是什么？")
    return {
        "entity": entity,
        "attr": attr,
        "value": value,
        "statement": statement,
        "question": question,
        "answer": value,
        "raw": raw,
        "source": "pattern",
    }


def pattern_extract(text: str) -> list[dict[str, Any]]:
    """按句式抽事实，不查属性词表。"""
    facts: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for sentence in _split_sentences(text):
        found: dict[str, Any] | None = None
        matched = re.match(
            r"^(?P<entity>[^，。,的]{1,16})的(?P<attr>[^，。]{1,16}?)是(?P<value>[^，。]{1,32})$",
            sentence,
        )
        if matched:
            found = _make_fact(matched.group("entity"), matched.group("attr"), matched.group("value"), "是", sentence)
        if found is None:
            matched = re.match(
                r"^(?P<entity>[^，。,的]{1,16})的(?P<attr>[^，。]{1,16}?)叫(?P<value>[^，。]{1,32})$",
                sentence,
            )
            if matched:
                found = _make_fact(matched.group("entity"), matched.group("attr"), matched.group("value"), "叫", sentence)
        if found is None:
            matched = re.match(r"^(?P<entity>[^，。]{1,16})住在(?P<value>[^，。]{1,32})$", sentence)
            if matched:
                found = _make_fact(matched.group("entity"), "住址", matched.group("value"), "住在", sentence)
        if found is None:
            matched = re.match(
                r"^(?P<entity>[A-Za-z][A-Za-z .'-]{0,40}?)'s (?P<attr>[A-Za-z][A-Za-z' -]{0,48}?) is named (?P<value>[A-Za-z0-9][A-Za-z0-9 '.-]{0,48})$",
                sentence,
            )
            if matched:
                found = _make_fact(matched.group("entity"), matched.group("attr"), matched.group("value"), "named", sentence)
        if found is None:
            matched = re.match(
                r"^(?P<entity>[A-Za-z][A-Za-z .'-]{0,40}?)'s (?P<attr>[A-Za-z][A-Za-z' -]{0,48}?) is called (?P<value>[A-Za-z0-9][A-Za-z0-9 '.-]{0,48})$",
                sentence,
            )
            if matched:
                found = _make_fact(matched.group("entity"), matched.group("attr"), matched.group("value"), "called", sentence)
        if found is None:
            matched = re.match(
                r"^(?P<entity>[A-Za-z][A-Za-z .'-]{0,40}?)'s (?P<attr>[A-Za-z][A-Za-z' -]{0,48}?) is (?P<value>[A-Za-z0-9][A-Za-z0-9 '.-]{0,48})$",
                sentence,
            )
            if matched:
                found = _make_fact(matched.group("entity"), matched.group("attr"), matched.group("value"), "is_en", sentence)
        if found is None:
            matched = re.match(
                r"^(?P<entity>[A-Za-z][A-Za-z .'-]{0,40}?) lives in (?P<value>[A-Za-z0-9][A-Za-z0-9 '.-]{0,48})$",
                sentence,
            )
            if matched:
                found = _make_fact(matched.group("entity"), "where they live", matched.group("value"), "lives", sentence)
        if found is None:
            continue
        key = (found["entity"], found["attr"], found["value"])
        if key in seen:
            continue
        seen.add(key)
        facts.append(found)
    return facts


def _parse_model_block(text: str) -> list[dict[str, Any]]:
    facts = []
    blocks = re.split(r"\n\s*\n", text.strip())
    for block in blocks:
        fields = {}
        for line in block.splitlines():
            line = line.strip().lstrip("-").strip()
            if "：" in line:
                key, value = line.split("：", 1)
            elif ":" in line:
                key, value = line.split(":", 1)
            else:
                continue
            fields[key.strip()] = value.strip()
        entity = fields.get("实体") or fields.get("Entity") or fields.get("entity") or ""
        attr = fields.get("属性") or fields.get("Attribute") or fields.get("attribute") or ""
        value = fields.get("取值") or fields.get("答案") or fields.get("Value") or fields.get("Answer") or fields.get("value") or ""
        statement = fields.get("陈述") or fields.get("Statement") or fields.get("statement") or ""
        question = fields.get("问题") or fields.get("Question") or fields.get("question") or ""
        if not (entity and value and (statement or question)):
            continue
        english = not has_cjk(f"{entity}{attr}{value}{statement}")
        coarse = attr
        attr = _refine_attr(attr, value, "model", statement or f"{entity} {attr} {value}")
        if not statement:
            if english:
                statement = f"{entity}'s {attr} is {value}." if attr else f"{entity} is {value}."
            else:
                statement = f"{entity}的{attr}是{value}。" if attr else f"{entity}是{value}。"
        if not question or attr != coarse:
            if english:
                question = f"What is {entity}'s {attr}?" if attr else f"What about {entity}?"
            else:
                question = f"{entity}的{attr}是什么？" if attr else f"关于{entity}，答案是什么？"
        facts.append({
            "entity": entity,
            "attr": attr or ("fact" if english else "事实"),
            "value": value,
            "statement": _finish_statement(statement),
            "question": question,
            "answer": value,
            "raw": statement,
            "source": "model",
        })
    return facts


def model_extract(text: str, model, tok, device) -> list[dict[str, Any]]:
    """让基座按固定行格式抄事实。解析失败就当没抽到，不抛给界面。"""
    from memory_core.paths import ensure_scripts_path

    ensure_scripts_path()
    if has_cjk(text):
        prompt_user = (
            "从下面的对话里抽出值得长期记住的具体事实。\n"
            "不要使用预先规定的属性类别，属性名用原文里的说法。\n"
            "每条事实用这个格式，事实之间空一行，不要输出别的话：\n"
            "陈述：一句完整陈述\n"
            "实体：实体名\n"
            "属性：属性名\n"
            "取值：取值\n"
            "问题：一个中文问题\n"
            "答案：与取值相同\n"
            "如果没有可记的事实，只输出：无\n\n"
            f"对话：\n{text}"
        )
        system = "你是助手。"
    else:
        prompt_user = (
            "Extract concrete facts worth remembering from the conversation below.\n"
            "Do not use a fixed list of attributes. Use the wording in the text.\n"
            "Use this format for each fact, with a blank line between facts, and no other text:\n"
            "Statement: one complete statement\n"
            "Entity: entity name\n"
            "Attribute: attribute name\n"
            "Value: value\n"
            "Question: one English question\n"
            "Answer: the same as the value\n"
            "If there is nothing to remember, output only: none\n\n"
            f"Conversation:\n{text}"
        )
        system = "You are a helpful assistant."
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": prompt_user},
    ]
    rendered = tok.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    inputs = tok(rendered, return_tensors="pt").to(device)
    ctx = model.disable_adapter() if hasattr(model, "disable_adapter") else _nullctx()
    with ctx:
        import torch

        with torch.no_grad():
            out = model.generate(
                **inputs,
                max_new_tokens=320,
                do_sample=False,
                pad_token_id=tok.eos_token_id,
            )
    gen = tok.decode(out[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True).strip()
    if gen.startswith("无") or gen.lower().startswith("none"):
        return []
    return _parse_model_block(gen)


class _nullctx:
    def __enter__(self):
        return None

    def __exit__(self, *args):
        return False


def company_pipeline_extract(text: str) -> list[dict[str, Any]]:
    """复用研究流水线里的企业句式抽取。对不上的段落返回空列表。"""
    from memory_core.paths import ensure_scripts_path

    ensure_scripts_path()
    from extract_qa_pipeline import extract_facts_from_text, generate_qa_dataset_for_facts

    raw = extract_facts_from_text(text)
    if not raw:
        return []
    dataset = generate_qa_dataset_for_facts(raw, batch_id=0)
    facts = []
    for item in dataset:
        qa0 = item["qa"][0]
        facts.append({
            "entity": item["entity"],
            "attr": item["attr"],
            "value": item["value"],
            "statement": item["statement"],
            "question": qa0["q"],
            "answer": qa0["a"],
            "raw": item["statement"],
            "source": "company_pipeline",
            "_company_qa": item["qa"],
        })
    return facts


def entailed(fact: dict[str, Any], source: str) -> bool:
    """实体和取值都必须是原文子串，避免模型编造。"""
    compact = re.sub(r"\s+", "", source)
    entity = re.sub(r"\s+", "", fact.get("entity", ""))
    value = re.sub(r"\s+", "", fact.get("value", ""))
    if len(entity) < 1 or len(value) < 1:
        return False
    if entity not in compact or value not in compact:
        return False
    if value in {"什么", "哪里", "哪个", "谁", "多少", "几"} or value.lower() in {"what", "where", "who", "which", "when", "how"}:
        return False
    return True


def dedupe_facts(facts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = set()
    out = []
    for fact in facts:
        key = (fact["entity"], fact["value"])
        if key in seen:
            continue
        seen.add(key)
        out.append(fact)
    return out


def extract_fact_candidates(text: str, model=None, tok=None, device=None) -> list[dict[str, Any]]:
    facts = pattern_extract(text)
    try:
        facts.extend(company_pipeline_extract(text))
    except Exception:
        pass
    if model is not None and tok is not None and device is not None:
        try:
            facts.extend(model_extract(text, model, tok, device))
        except Exception:
            pass
    facts = [fact for fact in facts if entailed(fact, text)]
    return dedupe_facts(facts)


def expand_training_fact(fact: dict[str, Any]) -> dict[str, Any]:
    """审阅后的一条事实展开成训练用陈述句和多种问法。问法套在抽到的属性上，不查固定类别。"""
    entity = str(fact.get("entity", "")).strip()
    value = str(fact.get("answer") or fact.get("value") or "").strip()
    english = not has_cjk(f"{entity}{fact.get('attr') or ''}{value}{fact.get('statement') or ''}")
    attr = str(fact.get("attr", "")).strip() or ("fact" if english else "事实")
    if english:
        statement = str(fact.get("statement") or "").strip() or f"{entity}'s {attr} is {value}."
    else:
        statement = str(fact.get("statement") or "").strip() or f"{entity}的{attr}是{value}。"
    statement = _finish_statement(statement)
    if english:
        primary = str(fact.get("question") or "").strip() or f"What is {entity}'s {attr}?"
    else:
        primary = str(fact.get("question") or "").strip() or f"{entity}的{attr}是什么？"
    questions = [primary]
    if english:
        questions.extend([
            f"What is {entity}'s {attr}?",
            f"What is the {attr} of {entity}?",
            f"Could you tell me {entity}'s {attr}?",
            f"Do you know {entity}'s {attr}?",
            f"Please tell me the {attr} of {entity}.",
        ])
        if attr in {"address", "where they live"} or "lives in" in statement.lower():
            questions.extend([
                f"Where does {entity} live?",
                f"Where is {entity}'s home?",
                f"What is {entity}'s address?",
            ])
        if "name" in attr.lower() or " named " in f" {statement.lower()} ":
            questions.extend([
                f"What is {entity}'s {attr} called?",
                f"Who is {entity}'s {attr}?",
            ])
        company_qa = fact.get("_company_qa") or []
        for qa in company_qa:
            if qa.get("q"):
                questions.append(qa["q"])
        qa_rows = []
        seen = set()
        for question in questions:
            question = question.strip()
            if not question or question in seen:
                continue
            seen.add(question)
            qa_rows.append({"q": question, "a": value})
        return {
            "entity": entity,
            "attr": attr,
            "value": value,
            "statement": statement,
            "qa": qa_rows,
        }
    questions.extend([
        _attr_question(entity, attr, "是什么？"),
        f"请问{_attr_question(entity, attr, '是什么？')}",
        f"能告诉我{_attr_question(entity, attr, '吗？')}",
        f"你知道{_attr_question(entity, attr, '吗？')}",
        f"{entity}{attr}是什么？",
        f"关于{entity}，{attr}是什么？",
    ])
    if "住" in attr or "住在" in statement:
        questions.extend([
            f"{entity}住在哪里？",
            f"{entity}住在什么地方？",
            f"请问{entity}的住址是哪里？",
        ])
    if "叫" in statement or "名" in attr:
        questions.extend([
            f"{entity}的{attr}叫什么？",
            f"{entity}的{attr}是谁？",
        ])
    company_qa = fact.get("_company_qa") or []
    for qa in company_qa:
        if qa.get("q"):
            questions.append(qa["q"])
    qa = []
    seen = set()
    for question in questions:
        question = question.strip()
        if not question or question in seen:
            continue
        seen.add(question)
        qa.append({"q": question, "a": value})
    return {
        "entity": entity,
        "attr": attr,
        "value": value,
        "statement": statement,
        "qa": qa,
    }
