"""真实问法下的路由评测。

同一套题报三列:旧正则守卫 + bge top-1、边界守卫 + bge top-1、实体优先。
τ 默认 0.6。`--generate` 再用 Qwen 抽样看记忆准确率;`--cmmlu-dir` 只统计题干激活。

用法:
  python scripts/eval_entity_guard_realistic.py --logic-only
  python scripts/eval_entity_guard_realistic.py --json-out /tmp/guard_eval.json --cmmlu-dir data_bench/test
  python scripts/eval_entity_guard_realistic.py --generate-only --n-per-cat 50
"""
import argparse
import json
import os
import random
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).parent))

from gen_data import PARA_QUESTIONS, SYL  # noqa: E402
from router import (  # noqa: E402
    classify_attribute,
    extract_entities_from_key_texts,
    find_name_spans,
    load_entity_attrs,
    mentioned_entities,
    route_decision,
    verify_entity_guard,
)

DATA_PATH = ROOT / "data_guard" / "realistic_queries.jsonl"
TAU_DEFAULT = 0.6

# 单实体、问法完整、守卫应当放行的新类别
ADMIT_CATS = ("org_suffix", "title", "colloquial", "long_context")
# 脚本内从 data/ 拼出来、同样应当放行的回归集
REGRESS_CATS = ("canonical", "para")
# 不该命中任何在册专家
REJECT_CATS = ("typo", "partial", "near_miss", "general")

ORG_TEMPLATES = [
    "{e}集团的旗舰产品是什么?",
    "{e}企业的总部位于哪座城市?",
    "{e}股份有限公司是哪一年成立的?",
    "介绍一下{e}集团公司,它的旗舰产品是什么?",
]
TITLE_TEMPLATES = [
    "{e}的董事长是谁?",
    "请问{e}公司的总经理怎么称呼?",
    "{e}集团的创始人是哪一位?",
    "{e}的老板头衔是董事长还是总裁?",
]
COLLOQUIAL_TEMPLATES = [
    "你好,{e}公司的CEO是谁?",
    "关于{e},它的首席执行官是谁?",
    "{e}的老板叫什么名字?",
    "说说{e}吧,它哪年成立的?",
    "{e} 公司 CEO",
    "诶，{e}是干啥的来着?",
    "{e}咋样,主打产品是哪个型号?",
]
LONG_TEMPLATES = [
    "我在新闻里看到{e},它总部在哪个城市?",
    "朋友推荐我去了解一下{e}这家企业,他们是哪年成立的?",
    "最近行业报告里多次提到{e}集团,它的旗舰产品到底是什么?",
    "如果要去{e}公司总部面试,我该飞往哪座城市?",
]
TWO_TEMPLATES = [
    "{d}我倒是知道,但我想问的是{e}的老板是谁?",
    "{e}和{d}相比,哪家成立得更早?",
    "先别说{d}了,说说{e}集团的旗舰产品。",
]
# 错字 / 残名 / 近名:用「你好,」迫使旧守卫抽不出实体、退回子串匹配
STRESS_TEMPLATES = [
    "你好,{s}公司的CEO是谁?",
    "{s}集团的旗舰产品是什么?",
]
EXTRA_GENERAL = [
    "今天天气怎么样?",
    "红烧肉怎么做比较入味?",
    "世界杯几年举办一次?",
    "Python是什么编程语言?",
    "长江的长度大约是多少公里?",
    "《红楼梦》的作者是谁?",
    "月球离地球有多远?",
    "如何煮一碗清汤面条?",
    "银行定期存款利率是什么意思?",
    "光合作用的主要产物是什么?",
    "为什么海水是咸的?",
    "钢琴有多少个键?",
    "奥运会首次举办是在哪一年?",
    "蓝牙技术是用来做什么的?",
    "赤道附近的气候有什么特点?",
]

SYL_SET = set(SYL)


def load_facts(data_dir: Path) -> list[dict]:
    facts = []
    for b in range(5):
        path = data_dir / f"batch_{b}.jsonl"
        for line in path.open(encoding="utf-8"):
            if not line.strip():
                continue
            fact = json.loads(line)
            fact["batch"] = b
            fact["expert"] = f"expert_{b}"
            facts.append(fact)
    return facts


def _check_boundaries(question: str, *names: str) -> None:
    """模板把实体嵌进非名字字里,避免评测题本身就贴着音节。"""
    compact = question.replace(" ", "").replace("\u3000", "")
    for name in names:
        i = compact.find(name)
        if i < 0:
            raise SystemExit(f"模板没有留下实体 {name!r}: {question}")
        if i > 0 and compact[i - 1] in SYL_SET:
            raise SystemExit(f"实体左侧贴着名字音节: {question}")
        j = i + len(name)
        if j < len(compact) and compact[j] in SYL_SET:
            raise SystemExit(f"实体右侧贴着名字音节: {question}")


def _row(category: str, question: str, fact: dict, expect: str, **extra) -> dict:
    row = {
        "id": extra.pop("id"),
        "category": category,
        "q": question,
        "expect": expect,
        "entity": fact["entity"] if fact else None,
        "expert": fact["expert"] if fact else None,
        "batch": fact["batch"] if fact else None,
    }
    row.update(extra)
    return row


def _mutate_sub(name: str, rng: random.Random, real: set[str]) -> str:
    for _ in range(40):
        chars = list(name)
        i = rng.randrange(len(chars))
        chars[i] = rng.choice([s for s in SYL if s != chars[i]])
        surface = "".join(chars)
        if surface not in real:
            return surface
    raise RuntimeError(f"无法为 {name} 生成错字")


def _mutate_ext(name: str, rng: random.Random, real: set[str]) -> str:
    for _ in range(40):
        surface = name + rng.choice(SYL)
        if surface not in real:
            return surface
    raise RuntimeError(f"无法为 {name} 生成近名")


def _mutate_partial(name: str, real: set[str]) -> str | None:
    if len(name) < 3:
        return None
    for surface in (name[:-1], name[1:]):
        if len(surface) >= 2 and surface not in real:
            return surface
    return None


def build_realistic_rows(facts: list[dict], generic_path: Path) -> list[dict]:
    """确定性生成更难的问法。不写入向量,只产 jsonl。"""
    real = {f["entity"] for f in facts}
    rows: list[dict] = []
    grouped = {
        "org_suffix": ORG_TEMPLATES,
        "title": TITLE_TEMPLATES,
        "colloquial": COLLOQUIAL_TEMPLATES,
        "long_context": LONG_TEMPLATES,
    }
    for i, fact in enumerate(facts):
        e = fact["entity"]
        for cat, templates in grouped.items():
            for ti, tmpl in enumerate(templates):
                q = tmpl.format(e=e)
                _check_boundaries(q, e)
                rows.append(_row(cat, q, fact, "admit", id=f"{cat}-{fact['id']}-{ti}"))
        for ti, tmpl in enumerate(TWO_TEMPLATES):
            # 下一批次的同序号事实,保证干扰项属于别的专家
            j = (i + len(facts) // 5) % len(facts)
            other = facts[j]
            if other["expert"] == fact["expert"]:
                other = facts[(j + 1) % len(facts)]
            q = tmpl.format(e=e, d=other["entity"])
            _check_boundaries(q, e, other["entity"])
            rows.append(_row(
                "two_entity", q, fact, "admit",
                id=f"two-{fact['id']}-{ti}",
                distractor=other["entity"],
                distractor_expert=other["expert"],
            ))

    rng = random.Random(20261022)
    for fact in facts:
        surfaces = {
            "typo": _mutate_sub(fact["entity"], rng, real),
            "near_miss": _mutate_ext(fact["entity"], rng, real),
        }
        partial = _mutate_partial(fact["entity"], real)
        if partial:
            surfaces["partial"] = partial
        for cat, surface in surfaces.items():
            for ti, tmpl in enumerate(STRESS_TEMPLATES):
                q = tmpl.format(s=surface)
                rows.append({
                    "id": f"{cat}-{fact['id']}-{ti}",
                    "category": cat,
                    "q": q,
                    "expect": "reject",
                    "entity": None,
                    "expert": None,
                    "batch": None,
                    "source_entity": fact["entity"],
                    "source_expert": fact["expert"],
                    "surface": surface,
                })

    generic = []
    for line in generic_path.open(encoding="utf-8"):
        if line.strip():
            item = json.loads(line)
            generic.append(item["q"] if isinstance(item, dict) else item)
    generic.extend(EXTRA_GENERAL)
    for i, q in enumerate(generic):
        hit = [e for e in real if e in q]
        if hit:
            raise SystemExit(f"常识题意外含在册实体 {hit}: {q}")
        rows.append({
            "id": f"general-{i:03d}",
            "category": "general",
            "q": q,
            "expect": "reject",
            "entity": None,
            "expert": None,
            "batch": None,
        })
    return rows


def write_data(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"写入 {path}: {len(rows)} 条", flush=True)


def load_rows(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.open(encoding="utf-8") if l.strip()]


def regression_rows(facts: list[dict]) -> list[dict]:
    """原模板 + 未见口语模板,不单独落盘(由 data/ 与 PARA_QUESTIONS 决定)。"""
    rows = []
    for fact in facts:
        for i, qa in enumerate(fact["qa"]):
            rows.append(_row("canonical", qa["q"], fact, "admit", id=f"canon-{fact['id']}-{i}"))
        for i, tmpl in enumerate(PARA_QUESTIONS[fact["attr"]]):
            q = tmpl.format(e=fact["entity"])
            rows.append(_row("para", q, fact, "admit", id=f"para-{fact['id']}-{i}"))
    return rows


def load_expert_entities(experts_dir: Path) -> tuple[list[dict], dict[str, list[str]]]:
    router_path = experts_dir / "router.jsonl"
    entries = []
    entities = {}
    for line in router_path.open(encoding="utf-8"):
        if not line.strip():
            continue
        entry = json.loads(line)
        # Windows 反斜杠在 Linux 上不是分隔符
        entry["key_path"] = str(entry["key_path"]).replace("\\", "/")
        entries.append(entry)
        kt = Path(entry["key_path"]).parent / "key_texts.json"
        texts = json.loads(kt.read_text(encoding="utf-8")) if kt.exists() else []
        entities[entry["expert"]] = extract_entities_from_key_texts(texts)
    return entries, entities


def logic_check(facts: list[dict], entities: dict[str, list[str]], rows: list[dict]) -> None:
    """不加载 bge:名单是否干净,边界是否挡住子串碰撞,在册问法是否误拦。"""
    gold = defaultdict(set)
    for fact in facts:
        gold[fact["expert"]].add(fact["entity"])
    for name, got in entities.items():
        if set(got) != gold[name]:
            missing = gold[name] - set(got)
            extra = set(got) - gold[name]
            raise SystemExit(f"{name} 实体名单与数据不一致 missing={list(missing)[:5]} extra={list(extra)[:5]}")
        for ent in got:
            if any(p in ent for p in ("公司", "去哪", "请", "这家")):
                raise SystemExit(f"{name} 名单仍含短语: {ent}")

    by_name = {fact["entity"]: fact["expert"] for fact in facts}
    # 短名是长名子串时,问长名不得命中短名那一家
    names = list(by_name)
    traps = 0
    for short in names:
        for long in names:
            if short != long and short in long and by_name[short] != by_name[long]:
                q = f"{long}公司的CEO是谁?"
                if verify_entity_guard(q, entities[by_name[short]]):
                    raise SystemExit(f"子串碰撞未挡住: {short} 命中了 {q}")
                if not verify_entity_guard(q, entities[by_name[long]]):
                    raise SystemExit(f"长名自身被误拦: {q}")
                traps += 1
    print(f"逻辑检查: 5 个专家名单与数据一致,子串碰撞 {traps} 对已挡住", flush=True)

    admit_rows = [r for r in rows if r["expect"] == "admit"]
    blocked = [r for r in admit_rows if not verify_entity_guard(r["q"], entities[r["expert"]])]
    if blocked:
        eg = blocked[0]
        raise SystemExit(f"在册问法被误拦 {len(blocked)}/{len(admit_rows)} 例: {eg['q']}")
    print(f"逻辑检查: 在册问法守卫放行 {len(admit_rows)}/{len(admit_rows)}", flush=True)

    reject_rows = [r for r in rows if r["expect"] == "reject"]
    leaked = []
    for r in reject_rows:
        if any(verify_entity_guard(r["q"], ents) for ents in entities.values()):
            leaked.append(r)
    if leaked:
        eg = leaked[0]
        raise SystemExit(f"未注册/常识问法被守卫放行 {len(leaked)} 例: {eg['q']}")
    print(f"逻辑检查: 错字/残名/近名/常识均未放行 {len(reject_rows)}/{len(reject_rows)}", flush=True)
    _logic_check_routing(entities, rows, facts)


def _asked_attr(row: dict) -> str | None:
    """这条问法模板在问的属性。原模板和未见口语就是该事实自己的属性,由调用方另判。"""
    matched = re.fullmatch(r"(.+)-(b\d+-\d+)-(\d+)", row["id"])
    if not matched or row["category"] in ("canonical", "para"):
        return None
    return _ASKS.get((row["category"], int(matched.group(3))))


def _logic_check_routing(entities: dict[str, list[str]], rows: list[dict], facts: list[dict]) -> None:
    """不看向量:存过的属性直达专家;没存过的属性弃权;删掉之后和比较句也弃权。"""
    experts = list(entities)
    zero = {name: 0.0 for name in experts}
    by_entity = {fact["entity"]: fact for fact in facts}
    attrs = {fact["entity"]: fact["attr"] for fact in facts}
    on_disk = load_entity_attrs(ROOT / "experts")
    if on_disk != attrs:
        missing = set(attrs) - set(on_disk)
        raise SystemExit(f"entity_attrs.json 与数据不一致,缺 {len(missing)} 个实体")

    def spans_of(q: str) -> list[str]:
        return [text for text, _s, _e in find_name_spans(q)]

    bad_span = []
    miss = []
    leaked_attr = []
    deleted_fire = []
    stored_n = unstored_n = 0
    for row in rows:
        if row["expect"] != "admit" or row["category"] == "two_entity":
            continue
        names = spans_of(row["q"])
        if names != [row["entity"]]:
            bad_span.append((names, row["q"]))
            continue
        fact = by_entity[row["entity"]]
        asked = fact["attr"] if row["category"] in ("canonical", "para") else _asked_attr(row)
        classified = classify_attribute(row["q"])
        if asked is not None and classified not in (asked, None):
            raise SystemExit(f"属性分类错了: 期望 {asked} 得到 {classified} | {row['q']}")
        if asked is not None and row["category"] not in ("canonical", "para") and classified != asked:
            raise SystemExit(f"真实问法没分出属性 {asked}: {row['q']}")
        if row["category"] in ("canonical", "para"):
            stored = classified is None or classified == fact["attr"]
        else:
            stored = classified == fact["attr"]
        got = route_decision(row["q"], entities, zero, 0.6, attrs)
        if stored:
            stored_n += 1
            if not (got["fired"] and got["expert"] == row["expert"]):
                miss.append((got["reason"], row["q"]))
        else:
            unstored_n += 1
            if got["fired"]:
                leaked_attr.append((got["reason"], row["q"]))
        kept = {n: ents for n, ents in entities.items() if n != row["expert"]}
        removed = {item["entity"] for item in facts if item["expert"] == row["expert"]}
        kept_attrs = {name: attr for name, attr in attrs.items() if name not in removed}
        after = route_decision(row["q"], kept, {n: 0.99 for n in kept}, 0.6, kept_attrs)
        if after["fired"]:
            deleted_fire.append((after["expert"], after["reason"], row["q"]))
    if bad_span:
        names, q = bad_span[0]
        raise SystemExit(f"单实体问法音节段不是该实体 {len(bad_span)} 例: {names} | {q}")
    if miss:
        reason, q = miss[0]
        raise SystemExit(f"已存属性未直达 {len(miss)} 例 reason={reason}: {q}")
    if leaked_attr:
        reason, q = leaked_attr[0]
        raise SystemExit(f"未存属性仍挂载 {len(leaked_attr)} 例 reason={reason}: {q}")
    if deleted_fire:
        expert, reason, q = deleted_fire[0]
        raise SystemExit(f"删掉被问专家后仍挂载 {len(deleted_fire)} 例 {expert}/{reason}: {q}")
    print(
        f"逻辑检查: 已存属性直达 {stored_n}/{stored_n},未存属性弃权 {unstored_n}/{unstored_n},删除后挂载 0",
        flush=True,
    )

    subject_ok = subject_miss = compare_fire = deleted_two = unstored_two = unstored_two_fire = 0
    for row in rows:
        if row["category"] != "two_entity":
            continue
        fact = by_entity[row["entity"]]
        asked = _asked_attr(row)
        classified = classify_attribute(row["q"])
        if asked is not None and classified != asked:
            raise SystemExit(f"双实体属性分类错了: 期望 {asked} 得到 {classified} | {row['q']}")
        got = route_decision(row["q"], entities, zero, 0.6, attrs)
        comparing = "相比" in row["q"] or "比较" in row["q"]
        if comparing:
            if got["fired"]:
                compare_fire += 1
            continue
        stored = asked is not None and asked == fact["attr"]
        if not stored:
            unstored_two += 1
            if got["fired"]:
                unstored_two_fire += 1
            continue
        if got["fired"] and got["expert"] == row["expert"]:
            subject_ok += 1
        else:
            subject_miss += 1
            if subject_miss <= 3:
                print(f"  双实体未直达 reason={got['reason']} spans={spans_of(row['q'])} | {row['q']}", flush=True)
        removed = {item["entity"] for item in facts if item["expert"] == row["expert"]}
        kept = {n: ents for n, ents in entities.items() if n != row["expert"]}
        kept_attrs = {name: attr for name, attr in attrs.items() if name not in removed}
        after = route_decision(row["q"], kept, {n: 0.99 for n in kept}, 0.6, kept_attrs)
        if after["fired"]:
            deleted_two += 1
    if compare_fire or subject_miss or deleted_two or unstored_two_fire:
        raise SystemExit(
            f"双实体路由不符合预期: 比较句误挂载 {compare_fire}, "
            f"已存主语未直达 {subject_miss}, 未存属性仍挂载 {unstored_two_fire}, 删除后仍挂载 {deleted_two}"
        )
    print(
        f"逻辑检查: 双实体已存主语直达 {subject_ok},未存属性弃权 {unstored_two},比较句弃权,删除后挂载 0",
        flush=True,
    )

    for probe in ("著名的埃菲尔铁塔位于", "福克纳写过《喧哗与骚动》", "下列著名建筑物哪个不属于法国埃菲尔铁塔"):
        if any(mentioned_entities(probe, ents) for ents in entities.values()):
            raise SystemExit(f"两字名从真实词里切了出来: {probe}")
        got = route_decision(probe, entities, {name: 0.99 for name in experts}, 0.6, attrs)
        if got["fired"]:
            raise SystemExit(f"两字名真实词仍挂载 {got['expert']}/{got['reason']}: {probe}")
    print("逻辑检查: 「埃菲尔 / 福克纳」不挂载", flush=True)

    reject_fire = []
    for row in rows:
        if row["expect"] != "reject":
            continue
        got = route_decision(row["q"], entities, {name: 0.99 for name in experts}, 0.6, attrs)
        if got["fired"]:
            reject_fire.append((got["expert"], got["reason"], row["q"]))
    if reject_fire:
        expert, reason, q = reject_fire[0]
        raise SystemExit(f"未注册/常识在相似度 0.99 时仍挂载 {len(reject_fire)} 例 {expert}/{reason}: {q}")
    print(f"逻辑检查: 错字/残名/近名/常识在相似度 0.99 时挂载 0/{len([r for r in rows if r['expect']=='reject'])}", flush=True)


def _norm_key(path: str) -> str:
    return str(path).replace("\\", "/")


# 改守卫之前的自由抽取。只在这份评测里复现「前」列,线上路由不再走这里。
_LEGACY_LEAD = (
    "请告诉我", "请问", "谁是", "请说出", "我想知道", "我想去",
    "查一下:", "查一下：", "查一下", "诶,", "诶，", "提到", "你知道",
    "能告诉我", "去哪座城市可以找到", "大家最熟知的", "谁在管",
)


def legacy_entities(texts: list[str]) -> list[str]:
    found: set[str] = set()
    for text in texts:
        if "公司" not in text:
            continue
        prefix = text[:text.find("公司")]
        for lead in ("请告诉我", "请问", "谁是", "请说出", "我想知道"):
            if prefix.startswith(lead):
                prefix = prefix[len(lead):]
        prefix = prefix.strip()
        if len(prefix) >= 2:
            found.add(prefix)
    return sorted(found, key=len, reverse=True)


def legacy_extract(query: str) -> str | None:
    text = query.strip()
    for lead in sorted(_LEGACY_LEAD, key=len, reverse=True):
        if text.startswith(lead):
            text = text[len(lead):]
            break
    matched = re.search(r"^([一-龥]{2,8}?)(?:这家公司|公司)?把(?:公司)?总部", text)
    if matched:
        return matched.group(1).strip()
    matched = re.search(r"^([一-龥]{2,8}?)(?:这家)?公司", text)
    if matched:
        return matched.group(1).strip()
    matched = re.search(
        r"^([一-龥]{2,8}?)(?:的|是|主打|最具有|最出名|最畅销|现在的|总部是在|产品叫|公司)",
        text,
    )
    if matched:
        return matched.group(1).strip()
    return None


def legacy_verify(query: str, expert_entities: list[str] | set[str]) -> bool:
    if not expert_entities:
        return True
    extracted = legacy_extract(query)
    if extracted:
        return extracted in expert_entities
    return any(entity in query for entity in expert_entities)


def load_dirty_entities(entries: list[dict]) -> dict[str, list[str]]:
    dirty = {}
    for entry in entries:
        path = Path(_norm_key(entry["key_path"])).parent / "key_texts.json"
        texts = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
        dirty[entry["expert"]] = legacy_entities(texts)
    return dirty


def run_routing(entries, entities, rows, tau: float, entity_attrs: dict[str, str] | None = None) -> list[dict]:
    import torch
    from router import embed

    keys = {}
    for entry in entries:
        keys[entry["expert"]] = torch.load(_norm_key(entry["key_path"]), weights_only=True)
    dirty = load_dirty_entities(entries)
    questions = [r["q"] for r in rows]
    print(f"编码 {len(questions)} 条问句…", flush=True)
    vecs = embed(questions)
    scored = []
    for row, vec in zip(rows, vecs):
        sims = {name: (key @ vec).max().item() for name, key in keys.items()}
        best, best_s = max(sims.items(), key=lambda kv: kv[1])
        guard_best = verify_entity_guard(row["q"], entities.get(best, []))
        legacy_best = legacy_verify(row["q"], dirty.get(best, []))
        decision = route_decision(row["q"], entities, sims, tau, entity_attrs)
        rec = {
            "id": row["id"],
            "category": row["category"],
            "expect": row["expect"],
            "q": row["q"],
            "best": best,
            "sim": best_s,
            "guard_best": guard_best,
            "fired": best_s >= tau and guard_best,
            "legacy_fired": best_s >= tau and legacy_best,
            "ent_fired": decision["fired"],
            "ent_expert": decision["expert"],
            "ent_reason": decision["reason"],
        }
        if row["expect"] == "admit":
            gold = row["expert"]
            rec["gold"] = gold
            rec["guard_gold"] = verify_entity_guard(row["q"], entities.get(gold, []))
            rec["legacy_guard_gold"] = legacy_verify(row["q"], dirty.get(gold, []))
            rec["top1_ok"] = best == gold
            rec["ent_routed_gold"] = bool(decision["fired"] and decision["expert"] == gold)
            others = {n: s for n, s in sims.items() if n != gold}
            b2, s2 = max(others.items(), key=lambda kv: kv[1])
            g2 = verify_entity_guard(row["q"], entities.get(b2, []))
            rec["cross"] = s2 >= tau and g2
            rec["legacy_cross"] = s2 >= tau and legacy_verify(row["q"], dirty.get(b2, []))
            rec["vector_cross"] = s2 >= tau
            rec["cross_expert"] = b2
            pruned_entities = {n: ents for n, ents in entities.items() if n != gold}
            pruned_sims = {n: s for n, s in sims.items() if n != gold}
            after = route_decision(row["q"], pruned_entities, pruned_sims, tau, entity_attrs)
            rec["ent_cross"] = after["fired"]
            rec["ent_cross_expert"] = after["expert"]
            rec["ent_cross_reason"] = after["reason"]
            distractor = row.get("distractor_expert")
            rec["cross_is_distractor"] = bool(distractor) and b2 == distractor
            rec["cross_unmentioned"] = rec["cross"] and not rec["cross_is_distractor"]
            rec["legacy_cross_unmentioned"] = rec["legacy_cross"] and not rec["cross_is_distractor"]
            rec["ent_cross_distractor"] = bool(after["fired"] and distractor and after["expert"] == distractor)
        else:
            rec["guard_any"] = any(
                verify_entity_guard(row["q"], ents) for ents in entities.values()
            )
            rec["legacy_guard_any"] = any(
                legacy_verify(row["q"], ents) for ents in dirty.values()
            )
        scored.append(rec)
    return scored


def _pct(n: int, d: int) -> str:
    if d == 0:
        return "—"
    return f"{n}/{d}"


def summarize_with_tau(scored: list[dict], tau: float) -> dict:
    """`cross` / `fired` 已按本次 τ 算好,这里只聚合。"""
    by = defaultdict(list)
    for rec in scored:
        by[rec["category"]].append(rec)
    summary = {}
    for cat, recs in by.items():
        if recs[0]["expect"] == "admit":
            summary[cat] = {
                "n": len(recs),
                "expect": "admit",
                "false_block": sum(not r["guard_gold"] for r in recs),
                "false_block_legacy": sum(not r["legacy_guard_gold"] for r in recs),
                "correct_route": sum(r["top1_ok"] and r["fired"] for r in recs),
                "correct_legacy": sum(r["top1_ok"] and r["legacy_fired"] for r in recs),
                "correct_entity": sum(r["ent_routed_gold"] for r in recs),
                "top1": sum(r["top1_ok"] for r in recs),
                "top1_tau": sum(r["top1_ok"] and r["sim"] >= tau for r in recs),
                "crossfire": sum(r["cross"] for r in recs),
                "crossfire_legacy": sum(r["legacy_cross"] for r in recs),
                "crossfire_entity": sum(r["ent_cross"] for r in recs),
                "vector_crossfire": sum(r["vector_cross"] for r in recs),
                "crossfire_unmentioned": sum(r["cross_unmentioned"] for r in recs),
                "crossfire_unmentioned_legacy": sum(r["legacy_cross_unmentioned"] for r in recs),
                "crossfire_distractor_entity": sum(r["ent_cross_distractor"] for r in recs),
                "entity_abstain": sum(not r["ent_fired"] for r in recs),
            }
        else:
            summary[cat] = {
                "n": len(recs),
                "expect": "reject",
                "guard_any": sum(r["guard_any"] for r in recs),
                "guard_any_legacy": sum(r["legacy_guard_any"] for r in recs),
                "false_activation": sum(r["fired"] for r in recs),
                "false_activation_legacy": sum(r["legacy_fired"] for r in recs),
                "false_activation_entity": sum(r["ent_fired"] for r in recs),
            }
    return summary


def _triple(stats: dict, key_a: str, key_b: str, key_c: str) -> str:
    return f"{stats[key_a]}/{stats[key_b]}/{stats[key_c]}"


def print_report(summary: dict, tau: float) -> None:
    admit_order = list(REGRESS_CATS) + list(ADMIT_CATS) + ["two_entity"]
    print(f"\nτ={tau}  正确路由与删除后误射: 正则守卫 / 边界守卫+bge / 实体优先")
    print(f"{'类别':<16}{'题数':>8}{'正确路由(正/边/实)':>24}{'删除后误射(正/边/实)':>24}{'向量top1≥τ':>12}")
    for cat in admit_order:
        stats = summary.get(cat)
        if not stats:
            continue
        print(
            f"{cat:<16}{stats['n']:>8}"
            f"{_triple(stats, 'correct_legacy', 'correct_route', 'correct_entity'):>24}"
            f"{_triple(stats, 'crossfire_legacy', 'crossfire', 'crossfire_entity'):>24}"
            f"{_pct(stats['top1_tau'], stats['n']):>12}"
        )
    print("\n未注册 / 常识  误激活: 正则 / 边界+bge / 实体优先")
    print(f"{'类别':<16}{'题数':>8}{'误激活(正/边/实)':>24}")
    for cat in REJECT_CATS:
        stats = summary.get(cat)
        if not stats:
            continue
        print(
            f"{cat:<16}{stats['n']:>8}"
            f"{_triple(stats, 'false_activation_legacy', 'false_activation', 'false_activation_entity'):>24}"
        )


def pooled_admit(scored: list[dict], cats: tuple[str, ...], tau: float) -> dict:
    recs = [r for r in scored if r["category"] in cats]
    if not recs:
        return {}
    n = len(recs)
    return {
        "n": n,
        "false_block": sum(not r["guard_gold"] for r in recs),
        "false_block_legacy": sum(not r["legacy_guard_gold"] for r in recs),
        "correct_route": sum(r["top1_ok"] and r["fired"] for r in recs),
        "correct_legacy": sum(r["top1_ok"] and r["legacy_fired"] for r in recs),
        "correct_entity": sum(r["ent_routed_gold"] for r in recs),
        "top1_tau": sum(r["top1_ok"] and r["sim"] >= tau for r in recs),
        "crossfire": sum(r["cross"] for r in recs),
        "crossfire_legacy": sum(r["legacy_cross"] for r in recs),
        "crossfire_entity": sum(r["ent_cross"] for r in recs),
        "vector_crossfire": sum(r["vector_cross"] for r in recs),
        "crossfire_unmentioned": sum(r["cross_unmentioned"] for r in recs),
        "entity_abstain": sum(not r["ent_fired"] for r in recs),
    }


def print_examples(scored: list[dict], limit: int = 3) -> None:
    print("\n样例(每类最多若干条失败):")
    shown = defaultdict(int)
    for rec in scored:
        cat = rec["category"]
        if shown[cat] >= limit:
            continue
        if rec["expect"] == "admit" and (not rec["guard_gold"] or rec["cross"]):
            why = "误拦" if not rec["guard_gold"] else "误射"
            print(f"  [{cat}/{why}] {rec['q']}  top1={rec['best']} sim={rec['sim']:.3f} cross={rec['cross_expert']}")
            shown[cat] += 1
        elif rec["expect"] == "reject" and (rec["guard_any"] or rec["fired"]):
            print(f"  [{cat}/误放行] {rec['q']}  top1={rec['best']} sim={rec['sim']:.3f}")
            shown[cat] += 1


# 真实问法模板在问哪一种事实。职务题按 CEO 记(训练里没有「董事长」这个属性)。
# None 的模板没有唯一答案,不进记忆准确率。
_ASKS = {
    ("org_suffix", 0): "旗舰产品",
    ("org_suffix", 1): "总部城市",
    ("org_suffix", 2): "成立年份",
    ("org_suffix", 3): "旗舰产品",
    ("title", 0): "CEO",
    ("title", 1): "CEO",
    ("title", 2): "CEO",
    ("colloquial", 0): "CEO",
    ("colloquial", 1): "CEO",
    ("colloquial", 2): "CEO",
    ("colloquial", 3): "成立年份",
    ("colloquial", 4): "CEO",
    ("colloquial", 6): "旗舰产品",
    ("long_context", 0): "总部城市",
    ("long_context", 1): "成立年份",
    ("long_context", 2): "旗舰产品",
    ("long_context", 3): "总部城市",
    ("two_entity", 0): "CEO",
    ("two_entity", 2): "旗舰产品",
}


def _row_fact(row: dict, facts_by_id: dict[str, dict]) -> tuple[dict | None, int | None]:
    matched = re.fullmatch(r"(.+)-(b\d+-\d+)-(\d+)", row["id"])
    if not matched:
        return None, None
    return facts_by_id.get(matched.group(2)), int(matched.group(3))


def memory_gold(row: dict, facts_by_id: dict[str, dict]) -> str | None:
    """问句如果正好在问这条事实训练过的属性,返回答案;否则没有可对的标准答案。"""
    fact, index = _row_fact(row, facts_by_id)
    if fact is None or index is None:
        return None
    if row["category"] == "canonical":
        return fact["qa"][index]["a"]
    attr = _ASKS.get((row["category"], index))
    if attr and fact["attr"] == attr:
        return fact["value"]
    return None


def _contains_value(answer: str, value: str | None) -> bool:
    if not value:
        return False
    return value.rstrip("年") in answer


def scan_cmmlu(entries, entities, tau: float, cmmlu_dir: Path, entity_attrs: dict[str, str] | None = None) -> dict:
    """CMMLU 题干的路由激活。只编码题干,和 eval_general 的路由文本一致。"""
    import csv

    import torch
    from router import embed

    keys = {e["expert"]: torch.load(_norm_key(e["key_path"]), weights_only=True) for e in entries}
    stems = []
    for path in sorted(cmmlu_dir.glob("*.csv")):
        with path.open(encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                if row.get("Answer") in "ABCD" and row.get("Question"):
                    stems.append(row["Question"])
    print(f"CMMLU 编码题干 {len(stems)} 条…", flush=True)
    vecs = embed(stems)
    boundary = entity = 0
    max_sim = 0.0
    samples = []
    for text, vec in zip(stems, vecs):
        sims = {name: (key @ vec).max().item() for name, key in keys.items()}
        best, best_s = max(sims.items(), key=lambda kv: kv[1])
        max_sim = max(max_sim, best_s)
        if best_s >= tau and verify_entity_guard(text, entities.get(best, [])):
            boundary += 1
        decision = route_decision(text, entities, sims, tau, entity_attrs)
        if decision["fired"]:
            entity += 1
            if len(samples) < 8:
                samples.append({"q": text[:80], "reason": decision["reason"], "expert": decision["expert"], "sim": round(best_s, 3)})
    report = {
        "n": len(stems),
        "max_sim": round(max_sim, 4),
        "boundary_activations": boundary,
        "entity_activations": entity,
        "samples": samples,
    }
    print(
        f"CMMLU 全题干 n={report['n']} 最高相似度 {report['max_sim']:.3f}  "
        f"边界+bge 激活 {boundary}  实体优先激活 {entity}",
        flush=True,
    )
    return report


def _is_unstored(row: dict, facts_by_id: dict[str, dict]) -> bool:
    fact, index = _row_fact(row, facts_by_id)
    if fact is None or index is None or row["category"] in ("canonical", "para"):
        return False
    if "相比" in row["q"] or "比较" in row["q"]:
        return False
    asked = _ASKS.get((row["category"], index))
    return bool(asked) and fact["attr"] != asked


def _memory_leak(answer: str, values: list[str]) -> bool:
    return any(value and value in answer for value in values)


def run_generation(
    entries, entities, rows, facts, tau: float, out_path: Path, n_per_cat: int, seed: int,
    entity_attrs: dict[str, str] | None = None,
) -> dict:
    """抽样生成。已存属性看召回;没存过的属性看弃权率和记忆泄漏。"""
    import time

    import torch
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer

    from eval_memory import answer
    from router import embed

    torch.set_num_threads(os.cpu_count() or 4)
    facts_by_id = {fact["id"]: fact for fact in facts}
    by_entity = {fact["entity"]: fact for fact in facts}
    generic_gold = {}
    generic_path = ROOT / "data" / "generic_questions.jsonl"
    for line in generic_path.open(encoding="utf-8"):
        if not line.strip():
            continue
        item = json.loads(line)
        if isinstance(item, dict) and item.get("a"):
            generic_gold[item["q"]] = item["a"]

    memory_values = [fact["value"].rstrip("年") for fact in facts]
    rng = random.Random(seed)
    chosen = []
    for cat in ("canonical",) + ADMIT_CATS + ("two_entity",):
        pool = [row for row in rows if row["category"] == cat and memory_gold(row, facts_by_id)]
        picked = rng.sample(pool, min(n_per_cat, len(pool)))
        chosen.extend(picked)
        print(f"生成抽样 {cat}: {len(picked)}/{len(pool)} 条有标准答案", flush=True)
    for cat in ADMIT_CATS + ("two_entity",):
        pool = [row for row in rows if row["category"] == cat and _is_unstored(row, facts_by_id)]
        picked = rng.sample(pool, min(n_per_cat, len(pool)))
        for row in picked:
            tagged = dict(row)
            tagged["unstored"] = True
            chosen.append(tagged)
        print(f"生成抽样 {cat} 未存属性: {len(picked)}/{len(pool)}", flush=True)
    compare_pool = [row for row in rows if row["category"] == "two_entity" and "相比" in row["q"]]
    compare_picked = rng.sample(compare_pool, min(n_per_cat, len(compare_pool)))
    chosen.extend(compare_picked)
    print(f"生成抽样 two_entity 比较句: {len(compare_picked)}", flush=True)
    general_rows = [row for row in rows if row["category"] == "general"]
    chosen.extend(general_rows)
    print(f"生成抽样 general: {len(general_rows)}", flush=True)

    keys = {e["expert"]: torch.load(_norm_key(e["key_path"]), weights_only=True) for e in entries}
    print(f"编码抽样 {len(chosen)} 条…", flush=True)
    vecs = embed([row["q"] for row in chosen])
    plans = []
    for row, vec in zip(chosen, vecs):
        sims = {name: (key @ vec).max().item() for name, key in keys.items()}
        best, best_s = max(sims.items(), key=lambda kv: kv[1])
        boundary_fire = best_s >= tau and verify_entity_guard(row["q"], entities.get(best, []))
        before = route_decision(row["q"], entities, sims, tau)
        after = route_decision(row["q"], entities, sims, tau, entity_attrs)
        plans.append({
            "row": row,
            "boundary_expert": best if boundary_fire else None,
            "before_expert": before["expert"] if before["fired"] else None,
            "before_reason": before["reason"],
            "entity_expert": after["expert"] if after["fired"] else None,
            "entity_reason": after["reason"],
            "sim": best_s,
        })

    device = torch.device("cpu")
    model_path = ROOT / "models" / "Qwen2.5-0.5B-Instruct"
    tok = AutoTokenizer.from_pretrained(model_path)
    base = AutoModelForCausalLM.from_pretrained(model_path, torch_dtype=torch.float32).to(device)
    first = entries[0]
    model = PeftModel.from_pretrained(base, ROOT / "experts" / first["expert"], adapter_name=first["expert"])
    for entry in entries[1:]:
        model.load_adapter(ROOT / "experts" / entry["expert"], adapter_name=entry["expert"])
    model.eval()

    cache: dict[tuple[str, str], str] = {}

    def generate(question: str, expert: str | None) -> str:
        key = (expert or "", question)
        if key in cache:
            return cache[key]
        if expert:
            model.set_adapter(expert)
            text = answer(model, tok, device, question, max_new_tokens=40)
        else:
            with model.disable_adapter():
                text = answer(model, tok, device, question, max_new_tokens=40)
        cache[key] = text
        return text

    records = []
    started = time.time()
    for i, plan in enumerate(plans, start=1):
        row = plan["row"]
        question = row["q"]
        base_ans = generate(question, None)
        boundary_ans = generate(question, plan["boundary_expert"])
        before_ans = generate(question, plan["before_expert"])
        entity_ans = generate(question, plan["entity_expert"])
        fact, _index = _row_fact(row, facts_by_id)
        gold = memory_gold(row, facts_by_id)
        if row["category"] == "general":
            gold = generic_gold.get(question)
        other = by_entity.get(row.get("distractor")) if row.get("distractor") else None
        records.append({
            "id": row["id"],
            "category": row["category"],
            "unstored": bool(row.get("unstored")),
            "q": question,
            "gold": gold,
            "attr": fact["attr"] if fact else None,
            "compare": "相比" in question and row["category"] == "two_entity" and not row.get("unstored"),
            "boundary_expert": plan["boundary_expert"],
            "before_expert": plan["before_expert"],
            "before_reason": plan["before_reason"],
            "entity_expert": plan["entity_expert"],
            "entity_reason": plan["entity_reason"],
            "base": base_ans,
            "boundary": boundary_ans,
            "before": before_ans,
            "entity": entity_ans,
            "base_hit": _contains_value(base_ans, gold),
            "boundary_hit": _contains_value(boundary_ans, gold),
            "before_hit": _contains_value(before_ans, gold),
            "entity_hit": _contains_value(entity_ans, gold),
            "base_either": _contains_value(base_ans, fact["value"] if fact else None) or _contains_value(base_ans, other["value"] if other else None),
            "boundary_either": _contains_value(boundary_ans, fact["value"] if fact else None) or _contains_value(boundary_ans, other["value"] if other else None),
            "entity_either": _contains_value(entity_ans, fact["value"] if fact else None) or _contains_value(entity_ans, other["value"] if other else None),
            "base_leak": _memory_leak(base_ans, memory_values),
            "before_leak": _memory_leak(before_ans, memory_values),
            "entity_leak": _memory_leak(entity_ans, memory_values),
        })
        if i % 10 == 0 or i == len(plans):
            elapsed = time.time() - started
            print(f"  生成 {i}/{len(plans)}  用时 {elapsed:.0f}s  缓存 {len(cache)}", flush=True)

    def pack(cat: str, subset: list[dict]) -> dict:
        scored = [rec for rec in subset if rec["gold"]]
        return {
            "n": len(subset),
            "scored": len(scored),
            "base_hit": sum(rec["base_hit"] for rec in scored),
            "boundary_hit": sum(rec["boundary_hit"] for rec in scored),
            "before_hit": sum(rec["before_hit"] for rec in scored),
            "entity_hit": sum(rec["entity_hit"] for rec in scored),
            "boundary_fired": sum(rec["boundary_expert"] is not None for rec in subset),
            "before_fired": sum(rec["before_expert"] is not None for rec in subset),
            "entity_fired": sum(rec["entity_expert"] is not None for rec in subset),
            "before_leak": sum(rec["before_leak"] for rec in subset),
            "entity_leak": sum(rec["entity_leak"] for rec in subset),
            "base_leak": sum(rec["base_leak"] for rec in subset),
            "abstain": sum(rec["entity_expert"] is None for rec in subset),
        }

    by_cat = defaultdict(list)
    for rec in records:
        if rec["unstored"]:
            key = rec["category"] + "_unstored"
        elif rec["compare"]:
            key = "two_compare"
        else:
            key = rec["category"]
        by_cat[key].append(rec)
    summary = {cat: pack(cat, subset) for cat, subset in by_cat.items()}
    compare = by_cat.get("two_compare", [])
    summary["two_compare_emit"] = {
        "n": len(compare),
        "base": sum(rec["base_either"] for rec in compare),
        "boundary": sum(rec["boundary_either"] for rec in compare),
        "entity": sum(rec["entity_either"] for rec in compare),
        "boundary_fired": sum(rec["boundary_expert"] is not None for rec in compare),
        "entity_fired": sum(rec["entity_expert"] is not None for rec in compare),
    }
    general = by_cat.get("general", [])
    general_scored = [rec for rec in general if rec["gold"]]
    summary["general_damage"] = {
        "n": len(general),
        "with_gold": len(general_scored),
        "boundary_fired": sum(rec["boundary_expert"] is not None for rec in general),
        "entity_fired": sum(rec["entity_expert"] is not None for rec in general),
        "base_hit": sum(rec["base_hit"] for rec in general_scored),
        "boundary_hit": sum(rec["boundary_hit"] for rec in general_scored),
        "entity_hit": sum(rec["entity_hit"] for rec in general_scored),
        "boundary_wrong": sum(rec["boundary_expert"] is not None and not rec["boundary_hit"] for rec in general_scored),
        "entity_wrong": sum(rec["entity_expert"] is not None and not rec["entity_hit"] for rec in general_scored),
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps({"summary": summary, "records": records}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"生成结果写入 {out_path}", flush=True)
    for cat, stats in summary.items():
        print(f"  {cat}: {stats}", flush=True)
    return summary


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write-data", action="store_true", help="重写 data_guard/realistic_queries.jsonl")
    ap.add_argument("--data", type=Path, default=DATA_PATH)
    ap.add_argument("--facts", type=Path, default=ROOT / "data")
    ap.add_argument("--experts", type=Path, default=ROOT / "experts")
    ap.add_argument("--tau", type=float, default=TAU_DEFAULT)
    ap.add_argument("--logic-only", action="store_true", help="只检查名单与守卫,不跑 bge")
    ap.add_argument("--json-out", type=Path, default=None)
    ap.add_argument("--no-regression", action="store_true", help="不把原模板/未见口语算进本次(调试用)")
    ap.add_argument("--cmmlu-dir", type=Path, default=None, help="CMMLU test 目录,只做路由激活统计")
    ap.add_argument("--generate", action="store_true", help="抽样跑 Qwen 生成(基座 / 边界守卫 / 实体优先)")
    ap.add_argument("--generate-only", action="store_true", help="只跑生成,不再做全量路由统计")
    ap.add_argument("--generate-out", type=Path, default=Path("/tmp/guard_generate.json"))
    ap.add_argument("--n-per-cat", type=int, default=50)
    ap.add_argument("--seed", type=int, default=20261022)
    args = ap.parse_args()

    facts = load_facts(args.facts)
    if args.write_data or not args.data.exists():
        rows = build_realistic_rows(facts, args.facts / "generic_questions.jsonl")
        write_data(args.data, rows)
        if args.write_data and args.logic_only is False and args.json_out is None:
            # 只写数据时若没有其它任务也可以继续评;写完数据后默认接着评。
            pass
    rows = load_rows(args.data)
    if not args.no_regression:
        rows = regression_rows(facts) + rows

    entries, entities = load_expert_entities(args.experts)
    if args.logic_only:
        logic_check(facts, entities, rows)
        return
    entity_attrs = load_entity_attrs(args.experts)
    if args.generate_only:
        run_generation(
            entries, entities, rows, facts, args.tau,
            args.generate_out, args.n_per_cat, args.seed, entity_attrs,
        )
        return

    # logic_check 在守卫改完之后应当通过;改之前会失败,所以完整评测不强制它。
    scored = run_routing(entries, entities, rows, args.tau, entity_attrs)
    summary = summarize_with_tau(scored, args.tau)
    print_report(summary, args.tau)
    pool = pooled_admit(scored, ADMIT_CATS, args.tau)
    if pool:
        print(
            f"\n真实单实体合计 n={pool['n']}  "
            f"正确路由 正则/边界/实体优先="
            f"{pool['correct_legacy']}/{pool['correct_route']}/{pool['correct_entity']}  "
            f"删除后误射 {pool['crossfire_legacy']}/{pool['crossfire']}/{pool['crossfire_entity']}  "
            f"向量top1≥τ={pool['top1_tau']}  纯向量会误射={pool['vector_crossfire']}"
        )
    general = [r for r in scored if r["category"] == "general"]
    if general:
        print(
            f"常识题最高相似度 {max(r['sim'] for r in general):.3f}, "
            f"误激活 正则/边界/实体优先 "
            f"{sum(r['legacy_fired'] for r in general)}/"
            f"{sum(r['fired'] for r in general)}/"
            f"{sum(r['ent_fired'] for r in general)}"
        )

    print("\n按被删专家(真实单实体, 边界误射 / 实体优先误射):")
    for expert in sorted({r["gold"] for r in scored if r.get("gold") and r["category"] in ADMIT_CATS}):
        subset = [r for r in scored if r.get("gold") == expert and r["category"] in ADMIT_CATS]
        cross = sum(r["cross"] for r in subset)
        ent = sum(r["ent_cross"] for r in subset)
        print(f"  删除 {expert}: 题数 {len(subset)}  边界误射 {cross}  实体优先误射 {ent}")

    two_rows = [r for r in scored if r["category"] == "two_entity"]
    if two_rows:
        reasons = defaultdict(int)
        for rec in two_rows:
            reasons[rec["ent_reason"]] += 1
        print(
            f"双实体实体优先: 直达主语 {sum(r['ent_routed_gold'] for r in two_rows)}/{len(two_rows)}  "
            f"弃权 {sum(not r['ent_fired'] for r in two_rows)}  "
            f"删除后误射 {sum(r['ent_cross'] for r in two_rows)}  "
            f"其中打到另一家 {sum(r['ent_cross_distractor'] for r in two_rows)}  "
            f"原因 {dict(reasons)}"
        )
    print_examples(scored)
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        payload = {"tau": args.tau, "summary": summary, "pooled_realistic": pool}
        if args.cmmlu_dir:
            payload["cmmlu"] = scan_cmmlu(entries, entities, args.tau, args.cmmlu_dir, entity_attrs)
        args.json_out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nJSON 已写入 {args.json_out}", flush=True)
    elif args.cmmlu_dir:
        scan_cmmlu(entries, entities, args.tau, args.cmmlu_dir, entity_attrs)
    if args.generate:
        run_generation(
            entries, entities, rows, facts, args.tau,
            args.generate_out, args.n_per_cat, args.seed, entity_attrs,
        )


if __name__ == "__main__":
    main()
