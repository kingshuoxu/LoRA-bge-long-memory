"""真实问法下的实体守卫评测(只跑 bge 路由 + 守卫,不加载因果 LM)。

仓库原验收(`test_task1_entity_guard.py`)只用训练问法,删专家后交叉误射是 0/400。
本脚本补一套更接近真实用户的问法,并同时回归原模板与未见口语模板。

指标(τ 默认 0.6,与读取路由一致):
- 守卫误拦:问句的在册专家名单过不了守卫(与向量 top-1 无关);
- 正确路由召回:向量 top-1 是该专家,且相似度 ≥ τ,且守卫放行;
- 删除后交叉误射:去掉该专家后,剩余专家的 top-1 仍 ≥ τ 且守卫放行。

数据:
- `data_guard/realistic_queries.jsonl`  集团/职务/口语/长上下文/错字/残名/双实体/近名/常识
- `data/batch_*.jsonl` 的原模板,以及 `gen_data.PARA_QUESTIONS` 的未见口语模板

用法:
  python scripts/eval_entity_guard_realistic.py --write-data
  python scripts/eval_entity_guard_realistic.py
  python scripts/eval_entity_guard_realistic.py --logic-only
  python scripts/eval_entity_guard_realistic.py --json-out /tmp/guard_eval.json
"""
import argparse
import json
import random
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).parent))

from gen_data import PARA_QUESTIONS, SYL  # noqa: E402
from router import (  # noqa: E402
    extract_entities_from_key_texts,
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


def _norm_key(path: str) -> str:
    return str(path).replace("\\", "/")


def run_routing(entries, entities, rows, tau: float) -> list[dict]:
    import torch
    from router import embed

    keys = {}
    for entry in entries:
        keys[entry["expert"]] = torch.load(_norm_key(entry["key_path"]), weights_only=True)
    questions = [r["q"] for r in rows]
    print(f"编码 {len(questions)} 条问句…", flush=True)
    vecs = embed(questions)
    scored = []
    for row, vec in zip(rows, vecs):
        sims = {name: (key @ vec).max().item() for name, key in keys.items()}
        best, best_s = max(sims.items(), key=lambda kv: kv[1])
        guard_best = verify_entity_guard(row["q"], entities.get(best, []))
        rec = {
            "id": row["id"],
            "category": row["category"],
            "expect": row["expect"],
            "q": row["q"],
            "best": best,
            "sim": best_s,
            "guard_best": guard_best,
            "fired": best_s >= tau and guard_best,
        }
        if row["expect"] == "admit":
            gold = row["expert"]
            rec["gold"] = gold
            rec["guard_gold"] = verify_entity_guard(row["q"], entities.get(gold, []))
            rec["top1_ok"] = best == gold
            others = {n: s for n, s in sims.items() if n != gold}
            b2, s2 = max(others.items(), key=lambda kv: kv[1])
            g2 = verify_entity_guard(row["q"], entities.get(b2, []))
            rec["cross"] = s2 >= tau and g2
            rec["vector_cross"] = s2 >= tau
            rec["cross_expert"] = b2
            distractor = row.get("distractor_expert")
            rec["cross_is_distractor"] = bool(distractor) and b2 == distractor
            rec["cross_unmentioned"] = rec["cross"] and not rec["cross_is_distractor"]
        else:
            rec["guard_any"] = any(
                verify_entity_guard(row["q"], ents) for ents in entities.values()
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
                "correct_route": sum(r["top1_ok"] and r["fired"] for r in recs),
                "top1": sum(r["top1_ok"] for r in recs),
                "top1_tau": sum(r["top1_ok"] and r["sim"] >= tau for r in recs),
                "crossfire": sum(r["cross"] for r in recs),
                "vector_crossfire": sum(r["vector_cross"] for r in recs),
                "crossfire_unmentioned": sum(r["cross_unmentioned"] for r in recs),
            }
        else:
            summary[cat] = {
                "n": len(recs),
                "expect": "reject",
                "guard_any": sum(r["guard_any"] for r in recs),
                "false_activation": sum(r["fired"] for r in recs),
            }
    return summary


def print_report(summary: dict, tau: float) -> None:
    admit_order = list(REGRESS_CATS) + list(ADMIT_CATS) + ["two_entity"]
    print(f"\nτ={tau}  在册问法(误拦=守卫拒绝了该专家的名单;误射=删掉该专家后 top-1 仍放行)")
    print(f"{'类别':<16}{'题数':>8}{'守卫误拦':>14}{'正确路由召回':>16}{'向量top1≥τ':>14}{'删除后误射':>14}{'纯向量会误射':>14}")
    for cat in admit_order:
        stats = summary.get(cat)
        if not stats:
            continue
        print(
            f"{cat:<16}{stats['n']:>8}"
            f"{_pct(stats['false_block'], stats['n']):>14}"
            f"{_pct(stats['correct_route'], stats['n']):>16}"
            f"{_pct(stats['top1_tau'], stats['n']):>14}"
            f"{_pct(stats['crossfire'], stats['n']):>14}"
            f"{_pct(stats['vector_crossfire'], stats['n']):>14}"
        )
    print(f"\n未注册 / 常识(守卫命中=任一在册名单被放行;误激活=top-1 ≥τ 且守卫放行)")
    print(f"{'类别':<16}{'题数':>8}{'守卫命中':>14}{'路由误激活':>14}")
    for cat in REJECT_CATS:
        stats = summary.get(cat)
        if not stats:
            continue
        print(
            f"{cat:<16}{stats['n']:>8}"
            f"{_pct(stats['guard_any'], stats['n']):>14}"
            f"{_pct(stats['false_activation'], stats['n']):>14}"
        )


def pooled_admit(scored: list[dict], cats: tuple[str, ...], tau: float) -> dict:
    recs = [r for r in scored if r["category"] in cats]
    if not recs:
        return {}
    n = len(recs)
    return {
        "n": n,
        "false_block": sum(not r["guard_gold"] for r in recs),
        "correct_route": sum(r["top1_ok"] and r["fired"] for r in recs),
        "top1_tau": sum(r["top1_ok"] and r["sim"] >= tau for r in recs),
        "crossfire": sum(r["cross"] for r in recs),
        "vector_crossfire": sum(r["vector_cross"] for r in recs),
        "crossfire_unmentioned": sum(r["cross_unmentioned"] for r in recs),
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

    # logic_check 在守卫改完之后应当通过;改之前会失败,所以完整评测不强制它。
    scored = run_routing(entries, entities, rows, args.tau)
    summary = summarize_with_tau(scored, args.tau)
    print_report(summary, args.tau)
    pool = pooled_admit(scored, ADMIT_CATS, args.tau)
    if pool:
        print(
            f"\n真实单实体合计  n={pool['n']}  误拦={pool['false_block']}  "
            f"正确路由召回={pool['correct_route']}  向量top1≥τ={pool['top1_tau']}  "
            f"删除后误射={pool['crossfire']}  纯向量会误射={pool['vector_crossfire']}"
        )
    general = [r for r in scored if r["category"] == "general"]
    if general:
        print(
            f"常识题最高相似度 {max(r['sim'] for r in general):.3f},"
            f" 路由误激活 {sum(r['fired'] for r in general)}/{len(general)}"
        )

    print("\n按被删专家(真实单实体问法):")
    for expert in sorted({r["gold"] for r in scored if r.get("gold") and r["category"] in ADMIT_CATS}):
        subset = [r for r in scored if r.get("gold") == expert and r["category"] in ADMIT_CATS]
        blocked = sum(not r["guard_gold"] for r in subset)
        cross = sum(r["cross"] for r in subset)
        print(f"  删除 {expert}: 题数 {len(subset)}  误拦 {blocked}  交叉误射 {cross}")

    two = summary.get("two_entity")
    if two:
        print(
            f"双实体:误拦={two['false_block']}/{two['n']}  "
            f"正确路由召回={two['correct_route']}/{two['n']}  "
            f"删除后误射={two['crossfire']}/{two['n']}  "
            f"其中打到未提及专家={two['crossfire_unmentioned']}/{two['n']}"
        )
    print_examples(scored)
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        payload = {"tau": args.tau, "summary": summary, "pooled_realistic": pool}
        args.json_out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nJSON 已写入 {args.json_out}", flush=True)


if __name__ == "__main__":
    main()
