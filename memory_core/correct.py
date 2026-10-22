"""把一句用户的话对上已存事实，并抽出要改成的取值。

不看「不是 / 应该 / 不对」这类词表。先用 bge 对上某条事实的陈述或问句，
再把原句里已经被这条事实覆盖掉的字去掉，剩下的片段才可能是新取值。
片段若更像这条事实自己的问句里多出来的部分（什么、哪里），就当它是提问，不改。
新陈述必须比旧陈述更贴近把旧取值遮掉之后的原话。
"""
from __future__ import annotations

import re
from typing import Any

from memory_core.fact_span import CALIBRATED_TAU, mask_fact

MATCH_TAU = 0.70
MATCH_MARGIN = 0.03
VALUE_GAIN = 0.04
WH_TAU = CALIBRATED_TAU
# 改写后的陈述必须比这条事实已经存下的问句更贴近原话。提问会更靠近那些问句。
QUESTION_MARGIN = 0.06
# 原话要靠近这条事实自己的属性。只是提到了同一个人、却在问别的事，不改这条。
ATTR_SIM = 0.46


def _norm_space(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


def _questions(fact: dict) -> list[str]:
    found: list[str] = []
    for qa in fact.get("qa") or []:
        question = str(qa.get("q") or "").strip()
        if question and question not in found:
            found.append(question)
    primary = str(fact.get("question") or "").strip()
    if primary and primary not in found:
        found.append(primary)
    return found


def _known_phrases(fact: dict) -> list[str]:
    phrases = [
        str(fact.get("statement") or ""),
        str(fact.get("entity") or ""),
        str(fact.get("attr") or ""),
        str(fact.get("value") or ""),
        str(fact.get("answer") or ""),
    ]
    phrases.extend(_questions(fact))
    return [phrase for phrase in phrases if len(phrase) >= 2]


def _leftover(text: str, known: list[str]) -> list[str]:
    """去掉已知短语之后还剩下的连续片段。"""
    masked = text
    for phrase in sorted({item for item in known if len(item) >= 2}, key=len, reverse=True):
        masked = masked.replace(phrase, "\n")
    return [piece for piece in re.findall(r"[0-9A-Za-z\u4e00-\u9fff]{2,}", masked)]


def _glue(fact: dict) -> str:
    statement = str(fact.get("statement") or "")
    value = str(fact.get("value") or fact.get("answer") or "")
    if value and value in statement:
        left = statement.split(value, 1)[0]
        return left[-1:] if left else ""
    return ""


def _echoes_known(tail: str, known: list[str]) -> bool:
    """和实体、属性几乎重合、只多一个字的片段不是新取值。"""
    for phrase in known:
        if len(phrase) < 2:
            continue
        common = 0
        for left, right in zip(tail, phrase):
            if left != right:
                break
            common += 1
        if common >= 2 and common >= len(tail) - 1:
            return True
    return False


def _fragment_hits(fragment: str, tail: str) -> bool:
    """问句残片落在候选取值里。英文长词里碰巧出现的两字母不算。"""
    if fragment not in tail:
        return False
    if tail.isascii() and fragment.isascii() and len(fragment) < len(tail):
        return False
    return True


def _same_token(tail: str, fragment: str) -> bool:
    """两个片段是否在说同一个词。单字重合不算，避免英文向量挤在一起时误伤。"""
    if len(tail) < 2 or len(fragment) < 2:
        return False
    return tail in fragment or fragment in tail


def _peel(run: str, known_blob: str) -> str:
    """只剥掉粘在片段开头的非拉丁字符。拉丁词的首字母经常也出现在实体里，剥掉会变成残词。"""
    peeled = run
    while len(peeled) > 2 and peeled[0] in known_blob and not peeled[0].isascii():
        peeled = peeled[1:]
    return peeled


def _candidate_tails(text: str, fact: dict) -> list[tuple[str, str]]:
    """每个候选取值配上它所在的那一小句，后面用这一小句而不是整段话来打分。"""
    known = _known_phrases(fact)
    value = str(fact.get("value") or fact.get("answer") or "")
    glue = _glue(fact)
    blob = "".join(known)
    tails: list[tuple[str, str]] = []
    seen: set[str] = set()
    clauses = [piece.strip() for piece in re.split(r"[，,。！？；;\n]+", text) if piece.strip()]
    for clause in clauses or [text]:
        for run in _leftover(clause, known):
            if value and value in run:
                run = run.replace(value, "")
            tail = run
            options: list[str] = []
            if glue and glue in run:
                tail = run.rsplit(glue, 1)[-1].strip()
                if len(tail) >= 2:
                    options.append(tail)
                else:
                    # 「暮雪才是名字」这类说法里，新取值在「是」前面。
                    head = run.split(glue, 1)[0].strip()
                    for length in range(2, len(head) + 1):
                        options.append(head[:length])
            else:
                options.append(_peel(run, blob).strip())
            for tail in options:
                if len(tail) < 2 or len(tail) > 16:
                    continue
                if value and (tail == value or value in tail):
                    continue
                if _echoes_known(tail, known):
                    continue
                if tail not in clause or tail in seen:
                    continue
                seen.add(tail)
                tails.append((tail, clause))
    return tails


def _wh_fragments(fact: dict) -> list[str]:
    """问句里比陈述多出来的字。候选取值若还带着这些字，它仍是在提问。"""
    fragments: list[str] = []
    for piece in _wh_texts(fact):
        for length in range(2, len(piece) + 1):
            for start in range(len(piece) - length + 1):
                frag = piece[start : start + length]
                if frag not in fragments:
                    fragments.append(frag)
    return fragments


def _wh_texts(fact: dict) -> list[str]:
    known = [
        str(fact.get("statement") or ""),
        str(fact.get("entity") or ""),
        str(fact.get("attr") or ""),
        str(fact.get("value") or ""),
        str(fact.get("answer") or ""),
    ]
    texts: list[str] = []
    for question in _questions(fact):
        for piece in _leftover(question, known):
            if piece not in texts:
                texts.append(piece)
    return texts


def _shorter_prefix(passing: list[tuple[float, int, str]]) -> tuple[float, int, str]:
    """「暮雪才是」和「暮雪」都说得通时，留更短、仍然贴着原句的那一个。"""
    kept = list(passing)
    for score, position, tail in passing:
        for other_score, _other_pos, other in passing:
            if other != tail and tail.startswith(other) and len(other) < len(tail) and other_score >= score - 0.04:
                kept = [item for item in kept if item[2] != tail]
                break
    return max(kept, key=lambda item: (item[0], item[1]))


def _rewrite(fact: dict, new_value: str) -> str:
    statement = str(fact.get("statement") or "").strip()
    old = str(fact.get("value") or fact.get("answer") or "")
    if old and old in statement:
        rewritten = statement.replace(old, new_value)
    else:
        entity = str(fact.get("entity") or "")
        attr = str(fact.get("attr") or "")
        rewritten = f"{entity}的{attr}是{new_value}。" if attr else f"{entity}是{new_value}。"
    if rewritten and rewritten[-1] not in "。！？.!?":
        rewritten += "。" if re.search(r"[\u4e00-\u9fff]", rewritten) else "."
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


def propose_from_records(
    text: str,
    records: list[Any],
    fact_id: str | None = None,
    new_value: str | None = None,
) -> dict[str, Any] | None:
    """对上一条可改的事实。对不上、或只是在提问，就返回 None。"""
    text = (text or "").strip()
    supplied = (new_value or "").strip()
    if not text and not (fact_id and supplied):
        return None
    rows = _active_rows(records)
    if not rows:
        return None
    from memory_core.paths import ensure_scripts_path

    ensure_scripts_path()
    from router import embed

    chosen: tuple[Any, int, dict] | None = None
    score = 1.0
    if fact_id:
        for record, index, fact in rows:
            if _fact_key(record, index, fact) == fact_id:
                chosen = (record, index, fact)
                break
        if chosen is None:
            return None
    else:
        if not text:
            return None
        bank_texts: list[str] = []
        owners: list[int] = []
        for row_index, (_record, _index, fact) in enumerate(rows):
            surfaces = [str(fact.get("statement") or "")]
            surfaces.extend(_questions(fact))
            surfaces = [item for item in surfaces if item]
            owners.extend([row_index] * len(surfaces))
            bank_texts.extend(surfaces)
        if not bank_texts:
            return None
        vectors = embed([text, *bank_texts])
        user_vec = vectors[0]
        best_score = -1.0
        second = -1.0
        best_row = 0
        cursor = 1
        for row_index in range(len(rows)):
            count = owners.count(row_index)
            if count == 0:
                continue
            block = vectors[cursor : cursor + count]
            cursor += count
            row_score = float((block @ user_vec).max())
            if row_score > best_score:
                second = best_score
                best_score = row_score
                best_row = row_index
            elif row_score > second:
                second = row_score
        if best_score < MATCH_TAU:
            return None
        if second >= 0 and best_score < second + MATCH_MARGIN:
            return None
        chosen = rows[best_row]
        score = best_score

    record, index, fact = chosen
    old_value = str(fact.get("value") or fact.get("answer") or "")
    if supplied:
        if supplied == old_value:
            return None
        picked = supplied
        score = score if fact_id is None else 1.0
    else:
        attr_name = str(fact.get("attr") or "").strip()
        # 整句已经很像这条事实的陈述时，属性名本身不一定出现在原话里（lives in / address）。
        if attr_name and score < 0.85:
            attr_vecs = embed([text, attr_name])
            if float(attr_vecs[0] @ attr_vecs[1]) < ATTR_SIM:
                return None
        tails = _candidate_tails(text, fact)
        if not tails:
            return None
        # 还在复述旧取值的那一小句是在否定旧事实，新取值在另一小句里。
        if old_value and any(old_value not in clause for _tail, clause in tails):
            narrowed = [(tail, clause) for tail, clause in tails if old_value not in clause]
            if narrowed:
                tails = narrowed
        wh = _wh_texts(fact)
        questions = _questions(fact)
        entity = str(fact.get("entity") or "")
        statements = [_rewrite(fact, tail) for tail, _clause in tails]
        masked_clauses = [mask_fact(clause, entity, old_value) for _tail, clause in tails]
        tail_texts = [tail for tail, _clause in tails]
        payload = [text, str(fact.get("statement") or ""), *questions, *masked_clauses, *statements, *tail_texts, *wh]
        vectors = embed(payload)
        user_vec = vectors[0]
        old_statement_vec = vectors[1]
        q_count = len(questions)
        question_vecs = vectors[2 : 2 + q_count]
        base = 2 + q_count
        clause_vecs = vectors[base : base + len(tails)]
        statement_vecs = vectors[base + len(tails) : base + 2 * len(tails)]
        tail_vecs = vectors[base + 2 * len(tails) : base + 3 * len(tails)]
        wh_vecs = vectors[base + 3 * len(tails) :]
        best_question = float((question_vecs @ user_vec).max()) if q_count else -1.0
        statement_text = str(fact.get("statement") or "")
        # 先看每个候选取值。bge-small-zh 把没见过的英文词嵌成同一个向量时，
        # 新旧陈述的相似度会一样，增益看不出来。这种小句里留下最长的那个新片段。
        scored: list[tuple[int, str, str, float, bool]] = []
        degenerate_clauses: set[str] = set()
        for tail_index, (tail, clause) in enumerate(tails):
            if any(_fragment_hits(fragment, tail) for fragment in _wh_fragments(fact)):
                continue
            if wh_vecs.numel():
                scores = wh_vecs @ tail_vecs[tail_index]
                wh_score = float(scores.max())
                closest = wh[int(scores.argmax())] if wh else ""
                if wh_score >= WH_TAU and _same_token(tail, closest):
                    continue
            new_score = float(clause_vecs[tail_index] @ statement_vecs[tail_index])
            old_score = float(clause_vecs[tail_index] @ old_statement_vec)
            fresh = tail not in statement_text
            degenerate = fresh and abs(new_score - old_score) < 1e-3
            if degenerate:
                degenerate_clauses.add(clause)
            scored.append((tail_index, tail, clause, new_score, degenerate))
        longest: dict[str, str] = {}
        for _index, tail, clause, _score, _degenerate in scored:
            if clause in degenerate_clauses and tail not in statement_text:
                if clause not in longest or len(tail) > len(longest[clause]):
                    longest[clause] = tail
        margin = QUESTION_MARGIN if re.search(r"[\u4e00-\u9fff]", text) else 0.0
        passing: list[tuple[float, int, str]] = []
        for tail_index, tail, clause, new_score, degenerate in scored:
            if clause in degenerate_clauses and longest.get(clause) != tail:
                continue
            if not degenerate and new_score < float(clause_vecs[tail_index] @ old_statement_vec) + VALUE_GAIN:
                continue
            if best_question >= 0 and float(user_vec @ statement_vecs[tail_index]) < best_question + margin:
                continue
            passing.append((new_score, text.rfind(tail), tail))
        if not passing:
            return None
        _best_score, _position, picked = _shorter_prefix(passing)
        compact = _norm_space(text)
        if _norm_space(picked) not in compact:
            return None
    if _norm_space(picked) == _norm_space(old_value):
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
