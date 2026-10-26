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
        if entity.endswith(suffix) and len(entity) > len(suffix):
            return entity[: -len(suffix)], suffix + "的" + attr
    return entity, attr


def _normalize_value(value: str) -> str:
    """英文取值去掉开头的冠词。中文取值不动。"""
    value = value.strip("。．. ")
    if has_cjk(value):
        return value
    stripped = re.sub(r"^(?:the|a|an)\s+", "", value, count=1, flags=re.IGNORECASE).strip()
    return stripped or value


_EN_COLOR_WORD = (
    "red|blue|green|yellow|black|white|grey|gray|orange|purple|pink|brown|gold|silver|"
    "beige|navy|teal|cyan|magenta|maroon|ivory|cream|vermilion|scarlet|crimson|azure|"
    "indigo|violet|khaki|tan|olive|coral|turquoise|charcoal|burgundy|amber|lilac|"
    "copper|sage|slate|pewter|rust|bronze|mauve|ochre|plum"
)
_EN_COLOR = re.compile(
    rf"^(?:(?:dark|light|deep|pale|navy|royal|sky|hot)\s+)?(?:{_EN_COLOR_WORD})$",
    re.IGNORECASE,
)


def looks_like_en_color(value: str) -> bool:
    """取值是颜色短语：blue、sage green，或颜色词不在末尾的 amber mist。"""
    text = re.sub(r"\s+", " ", (value or "").strip())
    if not text or has_cjk(text):
        return False
    if _EN_COLOR.match(text):
        return True
    parts = text.split(" ")
    if not 1 <= len(parts) <= 3:
        return False
    if not all(re.fullmatch(r"[A-Za-z]+", part) for part in parts):
        return False
    return any(re.fullmatch(_EN_COLOR_WORD, part, flags=re.IGNORECASE) for part in parts)


def _color_head(attr: str) -> str | None:
    """属性里颜色性质前面的事物。没有颜色性质时返回 None。"""
    text = (attr or "").strip()
    if not text:
        return None
    if has_cjk(text):
        if text.endswith("颜色") and len(text) > len("颜色"):
            return text[: -len("颜色")]
        return None
    lowered = text.casefold()
    for suffix in (" color", " colour"):
        if lowered.endswith(suffix) and len(text) > len(suffix):
            return text[: -len(suffix)]
    return None


def _retain_color_attr(old_attr: str, new_attr: str) -> str:
    """纠正后的新取值未必还像颜色词。同一事物上已经记下的颜色性质要留下来。"""
    old_head = _color_head(old_attr)
    if old_head is None or _color_head(new_attr) is not None:
        return new_attr
    new = (new_attr or "").strip()
    if has_cjk(old_attr):
        if new == old_head:
            return f"{new}颜色"
        return new_attr
    if new.casefold() == old_head.casefold():
        return f"{new} color"
    return new_attr
_ZH_COLOR = re.compile(r"^[\u4e00-\u9fff]{0,4}(?:白|红|绿|蓝|黑|黄|紫|灰|棕|粉|青|橙|金|银)色?的?$")
_POSS = r"(?:'s|’s|'|’)"


def _refine_attr(attr: str, value: str, how: str, raw: str) -> str:
    """属性要带上颜色、名字、品牌这类性质。只看取值和原句里的性质，不给事物配同义词。"""
    if has_cjk(f"{attr}{value}{raw}"):
        if attr in {"猫猫", "狗狗"}:
            attr = attr[0]
        if how == "叫" and "名" not in attr:
            attr = f"{attr}的名字"
        if "名" not in attr and how != "叫" and "色" not in attr and ("色" in value or _ZH_COLOR.match(value)):
            attr = f"{attr}颜色"
        if any(mark in raw for mark in ("品牌", "牌子")) and "牌" not in attr:
            attr = f"{attr}品牌"
        return attr
    lowered = attr.casefold()
    if how in {"named", "called"} and not lowered.endswith("name"):
        attr = f"{attr}'s name"
        lowered = attr.casefold()
    if looks_like_en_color(value) and "color" not in lowered and "colour" not in lowered:
        attr = f"{attr} color"
    if re.search(r"\bbrand\b", raw, re.IGNORECASE) and "brand" not in attr.casefold():
        attr = f"{attr} brand"
    return attr


def _make_fact(entity: str, attr: str, value: str, how: str, raw: str) -> dict[str, Any] | None:
    entity = entity.strip()
    attr = attr.strip("的").strip()
    value = _normalize_value(value)
    value = re.split(r"\s+by\s+", value, maxsplit=1, flags=re.IGNORECASE)[0].strip(" ,")
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
    elif how == "在":
        question = f"{entity}的{attr}在哪里？"
    elif how == "于":
        if re.search(r"\d|年", value):
            question = f"{entity}{attr}于哪一年？"
        else:
            question = f"{entity}{attr}于哪里？"
    elif how == "lives":
        question = f"Where does {entity} live?"
        # bge-small-zh 把单词 address 嵌得很远，过不了 0.622。
        # “where they live” 对「Where does 某 live?」约 0.676。
        attr = attr or "where they live"
    elif how == "plays":
        question = f"What instrument does {entity} play?"
        attr = attr or "instrument"
    elif how == "works":
        question = f"What does {entity} do for a living?"
        attr = attr or "job"
    elif how == "has":
        question = f"How many {attr} does {entity} have?"
    elif how == "rel":
        if re.search(r"\d", value):
            question = f"When was {entity} {attr}?"
        else:
            question = f"Where is {entity} {attr}?"
    elif how in {"named", "called", "is_en"}:
        if entity.casefold() in {"i", "me"}:
            question = f"What is my {attr}?"
        else:
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


_REL_IN = r"founded|established|based|headquartered|born|located|started|incorporated"
_PRONOUN_ZH = re.compile(r"^(?:它|她|他|其|该公司|这家公司|这个人)")


def _bind_subject(sentence: str, current: str | None) -> str:
    """它 / It / Its 接着上一句的主语，不把代词当成新实体。"""
    if not current:
        return sentence
    if has_cjk(sentence):
        matched = _PRONOUN_ZH.match(sentence)
        if matched:
            return current + sentence[matched.end():]
        return sentence
    if re.match(r"^Its\b", sentence, re.IGNORECASE):
        return f"{current}'s{sentence[3:]}"
    if re.match(r"^It(?:'s)?\b", sentence, re.IGNORECASE):
        rest = re.sub(r"^It(?:'s)?\b", "", sentence, count=1, flags=re.IGNORECASE).strip()
        if re.match(r"^(?:is|was|has|have)\b", rest, re.IGNORECASE):
            return f"{current} {rest}"
    return sentence


def _split_yu(sentence: str) -> tuple[str, str, str] | None:
    """「主语 + 一两字的动词 + 于 + 取值」。动词取紧挨着「于」的最短可用长度。"""
    matched = re.match(r"^(.+)于([^，。]{1,24})$", sentence)
    if not matched or "的" in matched.group(1):
        return None
    left, value = matched.group(1), matched.group(2)
    for size in (2, 1, 3, 4):
        if len(left) <= size + 1:
            continue
        verb = left[-size:]
        entity = left[:-size]
        if re.fullmatch(r"[\u4e00-\u9fff]{1,4}", verb) and len(entity) >= 2:
            return entity, verb, value
    return None


def _match_sentence(sentence: str, current: str | None) -> dict[str, Any] | None:
    sentence = _bind_subject(sentence, current)
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
            r"^(?P<entity>[^，。,的]{1,16})的(?P<attr>[^，。]{1,12}?)(?:位于|在)(?P<value>[^，。]{1,24})$",
            sentence,
        )
        if matched:
            found = _make_fact(matched.group("entity"), matched.group("attr"), matched.group("value"), "在", sentence)
    if found is None:
        matched = re.match(
            r"^(?P<entity>[\u4e00-\u9fffA-Za-z0-9]{1,16})(?:养了|有)(?:一[只条个位名匹头])?(?P<attr>[\u4e00-\u9fff]{1,8})[，,]\s*(?:它的|他的|她的)?(?:名字|名)?叫(?P<value>[^，。]{1,16})$",
            sentence,
        )
        if matched:
            found = _make_fact(matched.group("entity"), matched.group("attr"), matched.group("value"), "叫", sentence)
    if found is None:
        matched = re.match(
            r"^(?P<entity>[\u4e00-\u9fffA-Za-z0-9]{1,16})(?:养了|有)(?:一[只条个位名匹头])?(?P<attr>[\u4e00-\u9fff]{1,8})叫(?P<value>[^，。]{1,16})$",
            sentence,
        )
        if matched:
            found = _make_fact(matched.group("entity"), matched.group("attr"), matched.group("value"), "叫", sentence)
    if found is None:
        parts = _split_yu(sentence)
        if parts:
            found = _make_fact(parts[0], parts[1], parts[2], "于", sentence)
    if found is None:
        matched = re.match(
            rf"^(?P<entity>[A-Za-z][A-Za-z .'-]{{0,60}}?){_POSS} (?P<attr>[A-Za-z][A-Za-z' -]{{0,48}}?) is named (?P<value>.+)$",
            sentence,
        )
        if matched:
            found = _make_fact(matched.group("entity"), matched.group("attr"), matched.group("value"), "named", sentence)
    if found is None:
        matched = re.match(
            rf"^(?P<entity>[A-Za-z][A-Za-z .'-]{{0,60}}?){_POSS} (?P<attr>[A-Za-z][A-Za-z' -]{{0,48}}?) is called (?P<value>.+)$",
            sentence,
        )
        if matched:
            found = _make_fact(matched.group("entity"), matched.group("attr"), matched.group("value"), "called", sentence)
    if found is None:
        matched = re.match(
            rf"^(?P<entity>[A-Za-z][A-Za-z .'-]{{0,60}}?){_POSS} (?P<attr>[A-Za-z][A-Za-z' -]{{0,48}}?) is (?P<value>.+)$",
            sentence,
        )
        if matched:
            found = _make_fact(matched.group("entity"), matched.group("attr"), matched.group("value"), "is_en", sentence)
    if found is None:
        matched = re.match(
            r"^(?P<entity>[A-Za-z][A-Za-z .'-]{0,60}?) lives in (?P<value>.+)$",
            sentence,
        )
        if matched:
            found = _make_fact(matched.group("entity"), "where they live", matched.group("value"), "lives", sentence)
    if found is None:
        matched = re.match(
            rf"^(?P<entity>[A-Z][A-Za-z0-9 .'-]{{1,60}}?) (?:was|is|were|are) (?P<rel>{_REL_IN}) (?:in|at) (?P<value>.+)$",
            sentence,
        )
        if matched:
            found = _make_fact(matched.group("entity"), matched.group("rel").lower(), matched.group("value"), "rel", sentence)
    if found is None:
        matched = re.match(
            r"^(?P<entity>[A-Z][A-Za-z0-9 .'-]{1,60}?) was founded by (?P<value>.+)$",
            sentence,
            re.IGNORECASE,
        )
        if matched:
            found = _make_fact(matched.group("entity"), "founder", matched.group("value"), "is_en", sentence)
    if found is None:
        matched = re.match(
            r"^(?P<entity>[A-Z][\w.'’ -]{1,60}?) works as (?:an? )?(?P<value>.+)$",
            sentence,
            re.IGNORECASE,
        )
        if matched:
            found = _make_fact(matched.group("entity"), "job", matched.group("value"), "works", sentence)
    if found is None:
        matched = re.match(
            r"^(?P<entity>[A-Z][\w.'’ -]{1,60}?) plays (?:the )?(?P<value>[A-Za-z][\w' -]{0,32})$",
            sentence,
            re.IGNORECASE,
        )
        if matched:
            found = _make_fact(matched.group("entity"), "instrument", matched.group("value"), "plays", sentence)
    if found is None:
        matched = re.match(
            r"^(?P<entity>[A-Z][\w.'’ -]{1,60}?) is (?:an? )(?P<value>[a-z].+)$",
            sentence,
        )
        if matched:
            found = _make_fact(matched.group("entity"), "job", matched.group("value"), "works", sentence)
    if found is None:
        matched = re.match(
            r"^(?P<entity>[A-Z][\w.'’ -]{1,60}?) has (?:an?|the) (?P<attr>[A-Za-z][\w' -]{0,40}?) (?:named|called) (?P<value>[A-Za-z][\w' -]{0,32})$",
            sentence,
            re.IGNORECASE,
        )
        if matched:
            found = _make_fact(matched.group("entity"), matched.group("attr"), matched.group("value"), "named", sentence)
    if found is None:
        matched = re.match(
            r"^(?P<entity>[A-Z][\w.'’ -]{1,60}?) has (?P<value>\d[\d,]*) (?P<attr>[A-Za-z][\w ]{0,32})$",
            sentence,
            re.IGNORECASE,
        )
        if matched:
            found = _make_fact(matched.group("entity"), matched.group("attr"), matched.group("value"), "has", sentence)
    if found is None:
        matched = re.match(r"^My (?P<attr>.+?) is (?:called|named) (?P<value>.+)$", sentence, re.IGNORECASE)
        if matched:
            found = _make_fact("I", matched.group("attr"), matched.group("value"), "called", sentence)
    if found is None:
        matched = re.match(r"^My (?P<attr>.+?) is (?P<value>.+)$", sentence, re.IGNORECASE)
        if matched:
            found = _make_fact("I", matched.group("attr"), matched.group("value"), "is_en", sentence)
    if found is None:
        matched = re.match(r"^I live in (?P<value>.+)$", sentence, re.IGNORECASE)
        if matched:
            found = _make_fact("I", "where they live", matched.group("value"), "lives", sentence)
    if found is None:
        matched = re.match(r"^(?P<value>.+?) is my (?P<attr>.+)$", sentence, re.IGNORECASE)
        if matched:
            found = _make_fact("I", matched.group("attr"), matched.group("value"), "is_en", sentence)
    if found is None and current and re.match(r"^The [a-z]", sentence):
        matched = re.match(r"^The (?P<attr>.+?) is (?:called|named) (?P<value>.+)$", sentence, re.IGNORECASE)
        if matched:
            found = _make_fact(current, matched.group("attr"), matched.group("value"), "called", sentence)
        if found is None:
            matched = re.match(r"^The (?P<attr>.+?) is (?P<value>.+)$", sentence, re.IGNORECASE)
            if matched:
                found = _make_fact(current, matched.group("attr"), matched.group("value"), "is_en", sentence)
    return found


def _leading_name(sentence: str) -> str | None:
    if _looks_like_question(sentence):
        return None
    if re.match(r"^(?:It|Its|The|They|Their|My|I)\b", sentence):
        return None
    matched = re.match(r"^([A-Z][A-Za-z0-9'’.-]+(?:\s+[A-Z][A-Za-z0-9'’.-]+){0,5})\b", sentence)
    if matched:
        return matched.group(1).strip()
    matched = re.match(r"^([\u4e00-\u9fff]{2,12})", sentence)
    if matched:
        return matched.group(1)
    return None


def pattern_extract(text: str) -> list[dict[str, Any]]:
    """按句式抽事实，不查属性词表。一段话里的 It / 它 沿用上一句的主语。"""
    facts: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    current: str | None = None
    for sentence in _split_sentences(text):
        found = _match_sentence(sentence, current)
        if found is None:
            named = _leading_name(sentence)
            if named:
                current = named
            continue
        found["raw"] = sentence
        current = str(found["entity"])
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


def _looks_like_claim(sentence: str) -> bool:
    if _looks_like_question(sentence):
        return False
    if has_cjk(sentence):
        return any(mark in sentence for mark in ("是", "叫", "在", "于", "有", "养")) or bool(re.search(r"\d", sentence))
    return bool(re.search(r"\b(is|was|are|were|has|have|named|called|lives|works|plays)\b", sentence, re.IGNORECASE)) or bool(
        re.search(r"\d", sentence)
    )


def _named_values(sentence: str) -> list[str]:
    """句子里点名的取值。只抽到种类、没抽到这个名字，这句仍算没覆盖。"""
    found = []
    for pattern in (
        r"(?:名字|名)叫([\u4e00-\u9fffA-Za-z0-9]{1,16})",
        r"(?:名叫|叫做)([\u4e00-\u9fffA-Za-z0-9]{1,16})",
        r"叫([\u4e00-\u9fffA-Za-z0-9]{1,16})",
        r"\bnamed\s+([A-Za-z][\w'-]{0,32})",
        r"\bcalled\s+([A-Za-z][\w'-]{0,32})",
    ):
        for match in re.finditer(pattern, sentence, re.IGNORECASE):
            value = match.group(1).strip()
            if value and value not in found:
                found.append(value)
    return found


def _covers(sentence: str, fact: dict[str, Any]) -> bool:
    compact = re.sub(r"\s+", "", sentence)
    value = re.sub(r"\s+", "", str(fact.get("value") or ""))
    entity = re.sub(r"\s+", "", str(fact.get("entity") or ""))
    raw = re.sub(r"\s+", "", str(fact.get("raw") or fact.get("statement") or ""))
    named = _named_values(sentence)
    if named and not any(item and item in str(fact.get("value") or "") for item in named):
        return False
    if value and entity and value in compact and entity in compact:
        return True
    if value and value in compact and raw and (compact in raw or raw in compact):
        return True
    return False


def _values_overlap(left: str, right: str) -> bool:
    a = re.sub(r"[\s的。\.年]", "", left or "").casefold()
    b = re.sub(r"[\s的。\.年]", "", right or "").casefold()
    if not a or not b:
        return False
    if a == b:
        return True
    short, long = (a, b) if len(a) <= len(b) else (b, a)
    return len(short) >= 2 and short in long


def refresh_stored_fact(fact: dict[str, Any]) -> dict[str, Any]:
    """旧专家只存了事物名时，按现在的句式补上颜色、名字这类性质。

    实体名保持文件里的写法。对不上原句的取值就不改。
    """
    statement = str(fact.get("statement") or "").strip()
    if not statement:
        return fact
    parsed = pattern_extract(statement)
    if not parsed:
        return fact
    new = parsed[0]
    old_value = str(fact.get("value") or fact.get("answer") or "")
    if not _values_overlap(old_value, str(new.get("value") or "")):
        return fact
    old_entity = str(fact.get("entity") or "").strip()
    new_entity = str(new.get("entity") or "").strip()
    if old_entity and new_entity and old_entity not in new_entity and new_entity not in old_entity:
        if old_entity.casefold() != new_entity.casefold():
            return fact
    updated = dict(fact)
    if new.get("attr"):
        updated["attr"] = _retain_color_attr(str(fact.get("attr") or ""), str(new["attr"]))
    if old_entity:
        updated["entity"] = old_entity
    return updated


def uncovered_claims(text: str, facts: list[dict[str, Any]]) -> list[str]:
    """像陈述、但实体和取值都没有落进任何一条事实的句子。"""
    missing = []
    for sentence in _split_sentences(text):
        if not _looks_like_claim(sentence):
            continue
        if any(_covers(sentence, fact) for fact in facts):
            continue
        missing.append(sentence)
    return missing


def subject_names(text: str) -> list[str]:
    """非问句里出现的主语。提问不算，避免「中国的首都」把中国记成已提及实体。"""
    names: list[str] = []

    def add(name: str) -> None:
        name = (name or "").strip()
        if len(name) < 2 or name.casefold() in {"i", "me", "我"}:
            return
        if name not in names:
            names.append(name)

    for fact in pattern_extract(text):
        add(str(fact.get("entity") or ""))
    for sentence in _split_sentences(text):
        if _looks_like_question(sentence):
            continue
        if not _looks_like_claim(sentence):
            continue
        named = _leading_name(sentence)
        if named:
            add(named)
    return names


def _relation_questions(entity: str, attr: str, statement: str, english: bool) -> list[str]:
    from memory_core.relations import fact_relations

    rels = fact_relations(attr, statement)
    extra: list[str] = []
    if english:
        if "residence" in rels:
            extra.extend([f"Where does {entity} live?", f"Which town is {entity} living in?"])
        if "origin" in rels:
            extra.extend([f"Where is {entity} originally from?", f"Where did {entity} grow up?"])
        if "occupation" in rels:
            extra.extend([f"What does {entity} do for a living?", f"What is {entity}'s profession?"])
        if "founding" in rels:
            extra.extend([f"When was {entity} founded?", f"What year did {entity} start?"])
        if "headquarters" in rels:
            extra.extend([f"Where is {entity} based?", f"Where are {entity}'s headquarters?"])
        if "founder" in rels:
            extra.extend([f"Who founded {entity}?", f"Who is the founder of {entity}?"])
        if "instrument" in rels:
            extra.append(f"What instrument does {entity} play?")
        if "headcount" in rels:
            extra.append(f"How many employees does {entity} have?")
        if "product" in rels:
            extra.append(f"What is {entity}'s main product?")
        return extra
    if "residence" in rels:
        extra.extend([f"{entity}现居哪座城市？", f"{entity}目前住在哪儿？"])
    if "origin" in rels:
        extra.extend([f"{entity}老家是哪里？", f"{entity}是在哪里长大的？"])
    if "occupation" in rels:
        extra.extend([f"{entity}是做什么工作的？", f"{entity}靠什么手艺谋生？"])
    if "founding" in rels:
        extra.extend([f"{entity}是哪一年创立的？", f"{entity}什么时候成立的？"])
    if "headquarters" in rels:
        extra.extend([f"{entity}总部设在哪个城市？", f"{entity}的总部位于哪里？"])
    if "founder" in rels:
        extra.extend([f"{entity}是谁创办的？", f"{entity}的创始人是谁？"])
    if "instrument" in rels:
        extra.append(f"{entity}会弹什么乐器？")
    if "headcount" in rels:
        extra.append(f"{entity}有多少员工？")
    if "product" in rels:
        extra.append(f"{entity}的主打产品是什么？")
    return extra


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
        if attr.casefold().endswith((" color", " colour")):
            head = attr.rsplit(" ", 1)[0]
            questions.extend([
                f"What color is {entity}'s {head}?",
                f"What colour is {entity}'s {head}?",
                f"What color does {entity}'s {head} have?",
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
        questions.extend(_relation_questions(entity, attr, statement, True))
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
    questions.extend(_relation_questions(entity, attr, statement, False))
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


# 关于使用者的事实并进同一个专家。问句仍用「我 / I」，显示名是「关于你」。
# 别的主体各用自己的专家。取值留在事实节点上，不按句子另开专家。
SELF_ROUTE = "self"
SELF_DISPLAY = "关于你"
_SPEAKER = frozenset({"我", "我们", "咱们", "咱", "i", "me", "my", "mine", "we", "our", "ours", "us"})


def speaker_pronoun(entity: str) -> bool:
    return str(entity or "").strip().casefold() in _SPEAKER


def _label_parts(display: str) -> list[str]:
    text = str(display or "").strip()
    if text.endswith("等"):
        text = text[:-1]
    return [part.strip() for part in re.split(r"[、,]", text) if part.strip()]


def pronoun_only_label(display: str) -> bool:
    parts = _label_parts(display)
    return bool(parts) and all(speaker_pronoun(part) for part in parts)


def fact_route(fact: dict) -> str:
    """说话人归到稳定的 self。其他主体用实体名本身，同一实体永远同一路由。

    没有实体名的旧事实不算使用者本人，避免把研究专家并进「关于你」。
    """
    entity = str((fact or {}).get("entity") or "").strip()
    if speaker_pronoun(entity):
        return SELF_ROUTE
    return entity


def group_facts(facts: list[dict]) -> list[tuple[str, list[dict]]]:
    """self 在前，其余按第一次出现的实体。一组一个专家。"""
    buckets: dict[str, list[dict]] = {}
    order: list[str] = []
    for fact in facts or []:
        if not isinstance(fact, dict):
            continue
        key = fact_route(fact)
        if not key:
            continue
        if key not in buckets:
            buckets[key] = []
            order.append(key)
        buckets[key].append(fact)
    keys = ([SELF_ROUTE] if SELF_ROUTE in buckets else []) + [key for key in order if key != SELF_ROUTE]
    return [(key, buckets[key]) for key in keys]


def sole_route(facts: list[dict] | None) -> str | None:
    keys: list[str] = []
    for fact in facts or []:
        if not isinstance(fact, dict) or fact.get("superseded"):
            continue
        key = fact_route(fact)
        if not key or key in keys:
            continue
        keys.append(key)
    if len(keys) == 1:
        return keys[0]
    return None


def facts_are_self(facts: list[dict] | None) -> bool:
    return sole_route(facts) == SELF_ROUTE


def merge_route_facts(existing: list[dict] | None, incoming: list[dict] | None) -> list[dict]:
    """同一专家上的旧事实留下。新事实按实体、属性和取值并进去，不另开一条重复的。"""
    merged: list[dict] = []
    seen: set[tuple[str, str, str]] = set()
    for fact in list(existing or []) + list(incoming or []):
        if not isinstance(fact, dict):
            continue
        if fact.get("superseded"):
            merged.append(dict(fact))
            continue
        key = (
            str(fact.get("entity") or "").strip(),
            str(fact.get("attr") or "").strip(),
            str(fact.get("value") or fact.get("answer") or "").strip(),
        )
        if key in seen:
            continue
        seen.add(key)
        merged.append(dict(fact))
    return merged


def _join_labels(labels: list[str]) -> str:
    shown = "、".join(labels[:2])
    if len(labels) > 2:
        shown += "等"
    return shown


def expert_display_name(facts: list[dict]) -> str:
    """关于使用者的事实显示「关于你」。有名字的主体仍用主体，不把取值当成专家名。"""
    labels: list[str] = []
    for key, _items in group_facts(facts):
        label = SELF_DISPLAY if key == SELF_ROUTE else key
        if label not in labels:
            labels.append(label)
    return _join_labels(labels)


def visible_display_name(display: str, facts: list[dict] | None) -> str:
    """已存的「我」改显示成「关于你」。事实里的实体不动，回忆仍认「我」。"""
    text = str(display or "").strip()
    rows = [fact for fact in (facts or []) if isinstance(fact, dict)]
    if facts_are_self(rows):
        return SELF_DISPLAY
    if text == SELF_DISPLAY:
        return text
    if text and not pronoun_only_label(text):
        return text
    return expert_display_name(rows) or text
