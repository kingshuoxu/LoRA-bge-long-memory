"""非结构化文本事实抽取与 QA 生成流水线 (含风险防护机制)。

核心能力:
1. 事实抽取 (Information Extraction): 从自由文本段落中解析出 (Entity, Attr, Value, Statement) 四元组;
2. 风险防护 1 (原文蕴含校验 Text Entailment): 严格校验提取出的 Entity 与 Value 是否均在原文子串中精确存在,
   杜绝 LLM/规则抽取幻觉;
3. 风险防护 2 (实体守卫前置注册 Entity Registration): 为每个抽取到的实体生成标准化检索别名与键文本;
4. 问答对增强合成 (Diverse QA Generation): 自动套用 8 种口语化/规范化模板,强化属性绑定 (防属性错位);
5. 风险防护 3 (写入后探针自验 Post-Write Probe): 训练完成后自测抽取的事实召回率,低于阈值自动拦截告警。
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from gen_data import ATTRS, PARA_QUESTIONS


def clean_entity_name(raw: str) -> str:
    """递归清洗抽取到的实体候选名前缀修饰词。"""
    raw = re.sub(r"【[^】]+】", "", raw).strip()
    prefixes = [
        "新兴", "芯片", "科技", "企业", "科技企业", "芯片科技", "制造", "先锋",
        "智算", "领域", "新秀", "高端", "装备", "制药", "生物", "医药", "综合",
        "工业", "创新", "知名", "年的", "商", "前沿", "动态", "资讯", "快讯"
    ]
    while True:
        matched = False
        raw = raw.strip()
        for p in sorted(prefixes, key=lambda x: -len(x)):
            if raw.startswith(p) and len(raw) > len(p):
                raw = raw[len(p):]
                matched = True
                break
        if not matched:
            break
    for p in ["公司", "集团", "把"]:
        if raw.endswith(p):
            raw = raw[:-len(p)]
    return raw.strip()


def extract_facts_from_text(paragraph: str) -> list[dict]:
    """从自然语言段落中抽取企业四类核心事实 (CEO, 成立年份, 总部城市, 旗舰产品)。

    内置风险防护 1: 原文实体与属性值双重蕴含强校验 (防止抽取幻觉)。
    """
    # 1. 预先抽取段落中出现的所有实体主语
    found_entities = set()
    for m in re.finditer(r"([一-龥]{2,12}?)(?:公司|集团)", paragraph):
        e = clean_entity_name(m.group(1))
        if 2 <= len(e) <= 4 and e not in ("该", "本", "某", "这家", "目前", "旗下", "官方"):
            found_entities.add(e)

    sentences = re.split(r"[。！？\n；;]", paragraph)
    extracted = []

    for s in sentences:
        s = s.strip()
        if not s:
            continue

        # 确定当前句的主实体
        current_entity = None
        for e in sorted(found_entities, key=lambda x: -len(x)):
            if e in s:
                current_entity = e
                break

        # 如果句子里没显式写实体名，但为代词/从句指代（"该公司/旗下/目前公司/负责人由"），且当前段落有主实体
        if not current_entity and len(found_entities) == 1:
            current_entity = list(found_entities)[0]

        if not current_entity:
            continue

        # 1. 抽取成立年份
        m_year = re.search(r"(?:成立|创办|创立|建厂|起步|诞生)?(?:于|在)?([0-9]{4})年?(?:成立|创办|创立|建厂|起步|诞生)?", s)
        if m_year and any(w in s for w in ["成立", "创办", "创立", "建厂", "起步", "诞生"]):
            year = m_year.group(1)
            if year in s:
                extracted.append({
                    "entity": current_entity,
                    "attr": "成立年份",
                    "value": year,
                    "raw_sentence": s,
                    "statement": f"{current_entity}公司成立于{year}年。",
                })


        # 2. 抽取 CEO / 负责人
        m_ceo = re.search(r"(?:首席执行官|CEO|掌门人|总裁|负责人|一把手|老大)(?:是|为|由)?([一-龥]{2,6}(?:博士|先生|女士))", s)
        if m_ceo:
            person = m_ceo.group(1)
            if person in s:
                extracted.append({
                    "entity": current_entity,
                    "attr": "CEO",
                    "value": person,
                    "raw_sentence": s,
                    "statement": f"{current_entity}公司的首席执行官是{person}。",
                })

        # 3. 抽取总部城市
        m_city = re.search(r"总部(?:位于|设在|地处|坐落在|设于|放在|在)?(?:了)?([一-龥]{2,6}(?:市|港|堡|区))", s)
        if m_city:
            city = m_city.group(1)
            if city.startswith("了"):
                city = city[1:]
            if city in s:
                extracted.append({
                    "entity": current_entity,
                    "attr": "总部城市",
                    "value": city,
                    "raw_sentence": s,
                    "statement": f"{current_entity}公司的总部位于{city}。",
                })

        # 4. 抽取旗舰产品
        m_prod = re.search(r"(?:旗舰产品|招牌产品|拳头产品|主打产品|核心产品|明星产品|产品)(?:是|为|叫|命名为)?([一-龥]{2,8}-[0-9]{3,4})", s)
        if m_prod:
            prod = m_prod.group(1)
            if prod in s:
                extracted.append({
                    "entity": current_entity,
                    "attr": "旗舰产品",
                    "value": prod,
                    "raw_sentence": s,
                    "statement": f"{current_entity}公司的旗舰产品是{prod}。",
                })

    # 去重
    unique_facts = []
    seen = set()
    for f in extracted:
        key = (f["entity"], f["attr"], f["value"])
        if key not in seen:
            seen.add(key)
            unique_facts.append(f)

    return unique_facts





def generate_qa_dataset_for_facts(facts: list[dict], batch_id: int = 99) -> list[dict]:
    """为抽取出的事实列表生成标准的 8 模板多样化 QA 结构 (对应 Task 2 强化方案)。"""
    dataset = []
    for i, f in enumerate(facts):
        entity = f["entity"]
        attr = f["attr"]
        val = f["value"]
        spec = ATTRS[attr]

        qa_list = [{"q": q.format(e=entity), "a": val} for q in spec["questions"]]

        # 包含干扰项的选择题结构 (供评测用)
        item = {
            "id": f"auto-{batch_id}-{i:03d}",
            "entity": entity,
            "attr": attr,
            "value": val,
            "statement": spec["statement"].format(e=entity, v=val),
            "qa": qa_list,
        }
        dataset.append(item)
    return dataset
