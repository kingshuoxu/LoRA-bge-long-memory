"""第一人称回忆、近义合并，以及雾港灯塔志的分页检索。"""
import unittest
from pathlib import Path

from memory_core.documents import (
    attribute_in_statement,
    chunk_book,
    covered_fact,
    document_miss,
    extract_document,
    extract_key_points,
    extract_pdf_text_layer,
    fact_from_point,
    pdf_document_title,
    search_documents,
    split_chapters,
)
from memory_core.identity import migrate_user_identity
from memory_core.extract import expand_training_fact, pattern_extract
from memory_core.same_memory import is_same_memory
from memory_core.self_query import self_ask, self_reply

ROOT = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "wugang"


class _Expert:
    def __init__(self, name, facts, display="关于你"):
        self.name = name
        self.display_name = display
        self.fact_memory = {"facts": facts, "self": display == "关于你"}
        self.entities = []
        self.explicit = True


class SelfRecallTests(unittest.TestCase):
    def test_name_patterns_and_acknowledgement(self):
        try:
            from memory_core.grounding import acknowledge_statement, already_remembered
        except ModuleNotFoundError:
            self.skipTest("torch is not installed")

        called = pattern_extract("我叫徐金朔")[0]
        self.assertEqual(acknowledge_statement(called), "好的，记住了，你是徐金朔。")
        again = pattern_extract("我是徐金朔")[0]
        self.assertTrue(is_same_memory(again["statement"], called["statement"]))
        self.assertEqual(already_remembered(called), "已经记住了，你是徐金朔。")
        greeted = pattern_extract("你好，我是徐金朔。")[0]
        self.assertEqual(greeted["entity"], "我")
        self.assertNotIn("你好", greeted["statement"])

    def test_self_questions_do_not_invent_a_name(self):
        self.assertEqual(self_ask("我是谁？"), "identity")
        self.assertEqual(self_ask("我叫什么名字？"), "name")
        self.assertEqual(self_ask("我的名字是什么？"), "name")
        self.assertEqual(self_ask("关于我你知道什么？"), "overview")
        self.assertEqual(self_ask("你是谁？"), "assistant")
        empty = self_reply("我是谁？", [])
        self.assertIn("还不知道你是谁", empty[0])
        self.assertIsNone(empty[1])
        self.assertIsNone(self_reply("你是谁？", []))

    def test_self_questions_use_stored_name(self):
        fact = expand_training_fact(pattern_extract("我叫徐金朔")[0])
        expert = _Expert("expert_self", [fact])
        for question in ("我是谁？", "我叫什么名字？", "我的名字是什么？"):
            answer, owner, used = self_reply(question, [expert])
            self.assertIn("徐金朔", answer, question)
            self.assertIs(owner, expert)
            self.assertTrue(used)
        overview, _owner, rows = self_reply("关于我你知道什么？", [expert])
        self.assertIn("徐金朔", overview)
        self.assertTrue(rows)

    def test_legacy_user_answers_as_self(self):
        fact = {
            "entity": "用户",
            "attr": "名字",
            "value": "徐金朔",
            "statement": "用户叫徐金朔。",
        }
        expert = _Expert("expert_1000", [fact], display="用户/徐金朔")
        for question in ("我是谁？", "我叫什么名字？", "我的名字是什么？"):
            answer, owner, used = self_reply(question, [expert])
            self.assertIn("徐金朔", answer, question)
            self.assertIs(owner, expert)
            self.assertTrue(used)

    def test_migrate_user_expert(self):
        import json
        import tempfile
        from pathlib import Path

        root = Path(tempfile.mkdtemp())
        folder = root / "experts" / "expert_1000"
        folder.mkdir(parents=True)
        (folder / "fact_memory.json").write_text(json.dumps({
            "display_name": "用户/徐金朔",
            "entities": ["用户"],
            "facts": [{"entity": "用户", "attr": "名字", "value": "徐金朔", "statement": "用户叫徐金朔。"}],
        }, ensure_ascii=False), encoding="utf-8")
        (root / "experts" / "router.jsonl").write_text(
            json.dumps({"expert": "expert_1000", "display_name": "用户/徐金朔"}) + "\n",
            encoding="utf-8",
        )
        self.assertEqual(migrate_user_identity(root), 1)
        memory = json.loads((folder / "fact_memory.json").read_text(encoding="utf-8"))
        self.assertEqual(memory["display_name"], "关于你")
        self.assertTrue(memory["self"])
        self.assertEqual(memory["facts"][0]["entity"], "我")
        self.assertIn("徐金朔", memory["facts"][0]["statement"])
        router = (root / "experts" / "router.jsonl").read_text(encoding="utf-8")
        self.assertIn("关于你", router)
        self.assertEqual(migrate_user_identity(root), 0)

    def test_cat_is_its_own_expert(self):
        cat = pattern_extract("我的猫叫咪咪")[0]
        self.assertEqual(cat["entity"], "咪咪")
        self.assertNotEqual(cat["entity"], "我")


class AttributeMatchTests(unittest.TestCase):
    def test_subject_alone_does_not_count(self):
        address = "沈星河的住址是青岚镇。"
        bike = "沈星河的自行车颜色是朱红色。"
        cat = "沈星河的猫的名字是云朵。"
        self.assertFalse(attribute_in_statement("沈星河的狗叫什么？", "沈星河", address))
        self.assertFalse(attribute_in_statement("沈星河的狗的名字是什么？", "沈星河", cat))
        self.assertFalse(attribute_in_statement("沈星河的汽车颜色是什么？", "沈星河", bike))
        self.assertFalse(attribute_in_statement("沈星河多大了？", "沈星河", address))
        self.assertFalse(attribute_in_statement("沈星河喜欢吃什么？", "沈星河", address))
        tower = "柯岚在雾港守护的第一座灯塔名叫白鹭塔，建于1873年，塔高四十二米。"
        self.assertTrue(attribute_in_statement("白鹭塔建于哪一年？", "白鹭塔", tower))


class WugangTests(unittest.TestCase):
    def test_chrome_and_reportlab_keep_pages(self):
        self.assertIn("雾港灯塔志", pdf_document_title((ROOT / "wugang_chrome.pdf").read_bytes()))
        for name in ("wugang_chrome.pdf", "wugang_reportlab.pdf", "wugang_utf16hex.pdf"):
            text = extract_pdf_text_layer((ROOT / name).read_bytes())
            pages = text.split("\f")
            self.assertGreaterEqual(len(pages), 12, name)
            self.assertIn("1873", pages[2])
            self.assertIn("四十二米", pages[2])
            self.assertIn("星砂盐", pages[5])
            self.assertIn("阿哨", pages[8])
            self.assertIn("诺丁", pages[11])
            chunks = chunk_book(text)
            tower = next(chunk for chunk in chunks if "1873" in chunk["text"] and "四十二米" in chunk["text"])
            self.assertIn("第一章", tower["chapter"])
            self.assertEqual(tower["page"], 3)

    def test_heading_does_not_swallow_the_page(self):
        text = "第一章 白鹭塔柯岚在雾港守护的第一座灯塔名叫白鹭塔，建于1873年，塔高四十二米。"
        chapters = split_chapters(text)
        body = next(body for title, body in chapters if "第一章" in title)
        self.assertIn("1873", body)
        self.assertIn("四十二米", body)

    def test_docx_and_epub(self):
        docx = extract_document("wugang.docx", (ROOT / "wugang.docx").read_bytes())
        epub = extract_document("wugang.epub", (ROOT / "wugang.epub").read_bytes())
        self.assertIn("白鹭塔", docx)
        self.assertIn("雾港灯塔志", epub)

    def test_retrieval_cites_the_page_and_misses_the_mayor(self):
        text = extract_pdf_text_layer((ROOT / "wugang_chrome.pdf").read_bytes())
        doc = {"id": "w", "title": "雾港灯塔志", "chunks": chunk_book(text), "vectors": None}
        tower = search_documents("白鹭塔建于哪一年？", [doc], None)["ground"]
        self.assertIsNotNone(tower)
        self.assertIn("1873", tower["answer"])
        self.assertIn("第3页", tower["chips"][0]["label"])
        self.assertIn("第一章", tower["chips"][0]["label"])
        salt = search_documents("星砂盐什么时候晾晒？", [doc], None)["ground"]
        self.assertIn("霜降", salt["answer"])
        self.assertIn("第6页", salt["chips"][0]["label"])
        gull = search_documents("柯小满的海鸥叫什么？", [doc], None)["ground"]
        self.assertIn("阿哨", gull["answer"])
        mayor = search_documents("雾港的市长是谁？", [doc], None)
        self.assertIsNone(mayor["ground"])
        self.assertTrue(mayor["missing_term"])
        self.assertIn("雾港灯塔志", document_miss("雾港灯塔志"))
        height = search_documents("白鹭塔有多高？", [doc], None)["ground"]
        self.assertIsNotNone(height)
        self.assertIn("四十二米", height["answer"])
        lens = search_documents("白鹭塔的透镜是谁打磨的？", [doc], None)["ground"]
        self.assertIsNotNone(lens)
        self.assertIn("诺丁", lens["answer"])
        self.assertIn("第四章", lens["chips"][0]["label"])
        self.assertNotIn("第一章", lens["chips"][0]["label"])
        self.assertNotIn("\u2ee9", text)
        self.assertIn("黄昏", text)

    def test_docx_chip_names_the_chapter(self):
        text = extract_document("wugang.docx", (ROOT / "wugang.docx").read_bytes())
        doc = {"id": "wugang", "title": "雾港灯塔志", "chunks": chunk_book(text), "vectors": None}
        tower = search_documents("白鹭塔建于哪一年？", [doc], None)["ground"]
        label = tower["chips"][0]["label"]
        self.assertIn("第一章", label)
        self.assertNotIn("第1页", label)
        self.assertNotIn("第2页", label)
        books = {
            "docx": extract_document("wugang.docx", (ROOT / "wugang.docx").read_bytes()),
            "epub": extract_document("wugang.epub", (ROOT / "wugang.epub").read_bytes()),
        }
        for name, blob in books.items():
            book = {"id": name, "title": "雾港灯塔志", "chunks": chunk_book(blob), "vectors": None}
            count = search_documents("透镜一共有多少面？", [book], None)
            self.assertFalse(count["missing_term"], name)
            self.assertIsNotNone(count["ground"], name)
            self.assertIn("十六", count["ground"]["answer"])
            self.assertIn("第四章", count["ground"]["chips"][0]["label"])

    def test_gull_recall_without_the_stored_name(self):
        line = "柯岚的女儿柯小满养了一只三条腿的海鸥，名叫阿哨。"
        fact = fact_from_point(line, "雾港灯塔志", "第三章 守塔人的女儿")
        self.assertEqual(fact["entity"], "柯小满")
        self.assertEqual(fact["value"], "阿哨")
        legacy = dict(fact, entity="阿哨", statement=line if line.endswith("。") else line + "。")
        hit = covered_fact("柯小满的海鸥叫什么", [legacy])
        self.assertIsNotNone(hit)
        self.assertIn("阿哨", hit["statement"])
        bike = {"statement": "沈星河的自行车颜色是朱红色。", "entity": "沈星河"}
        self.assertIsNone(covered_fact("沈星河的车是什么颜色？", [bike]))
        self.assertIsNone(covered_fact("沈星河的狗叫什么？", [bike]))

    def test_learning_questions_use_the_stored_sentence(self):
        from memory_core.fact_recall import possessed_name_query, recall_fact

        facts = [
            {"statement": "柯岚在雾港守护的第一座灯塔名叫白鹭塔，建于1873年，塔高四十二米。", "entity": "白鹭塔"},
            {"statement": "雾港的特产是一种蓝色海盐，名叫星砂盐，每年霜降那天开始晾晒。", "entity": "星砂盐"},
            {"statement": "柯岚的女儿柯小满养了一只三条腿的海鸥，名叫阿哨。", "entity": "柯小满"},
            {"statement": "1931年白鹭塔的灯改用电灯，透镜由瑞典工匠诺丁打磨，一共有十六面。", "entity": "雾港灯塔志"},
            {"statement": "我叫徐金朔。", "entity": "我"},
        ]
        expect = {
            "白鹭塔建于哪一年？": "1873",
            "白鹭塔有多高？": "四十二",
            "那只三条腿的海鸥叫什么名字？": "阿哨",
            "柯岚守护的第一座灯塔是哪年建的？": "1873",
            "雾港的蓝色海盐每年哪天开始晒？": "霜降",
            "白鹭塔哪一年改用电灯？": "1931",
            "白鹭塔的透镜是谁打磨的？": "诺丁",
            "透镜一共有多少面？": "十六",
        }
        from memory_core.fact_recall import answer_span, spoken_fact, touches_memory

        for question, gold in expect.items():
            hit = recall_fact(question, facts)
            self.assertIsNotNone(hit, question)
            self.assertIn(gold, hit["statement"], question)
            self.assertIn(gold, spoken_fact(question, hit), question)
        paraphrases = {
            "那座四十二米高的塔是哪年建成的？": "1873",
            "霜降那天雾港人开始晒什么？": "星砂盐",
            "阿哨是谁养的？": "柯小满",
            "四十二米高的灯塔叫什么名字？": "白鹭塔",
            "谁养了名叫阿哨的海鸥？": "柯小满",
            "每年霜降开始晾晒的是什么？": "星砂盐",
            "诺丁打磨过的透镜有多少面？": "十六",
            "改用电灯的那一年是哪年？": "1931",
            "建于1873年的塔有多高？": "四十二",
            "三条腿的海鸥名叫什么？": "阿哨",
            "蓝色海盐是在哪一天开始晒的？": "霜降",
            "瑞典工匠打磨白鹭塔的透镜，他叫什么？": "诺丁",
            "十六面的透镜是谁打磨的？": "诺丁",
            "柯小满养的那只海鸥叫什么？": "阿哨",
            "雾港特产从哪天起晾晒？": "霜降",
            "第一座灯塔的高度是多少米？": "四十二",
        }
        for question, gold in paraphrases.items():
            self.assertTrue(touches_memory(question, facts), question)
            hit = recall_fact(question, facts)
            self.assertIsNotNone(hit, question)
            spoken = spoken_fact(question, hit)
            self.assertIn(gold, spoken, (question, spoken, hit["statement"]))
            self.assertNotEqual(spoken.rstrip("。"), hit["statement"].rstrip("。"), question)
            self.assertLess(len(spoken), len(hit["statement"]), question)
        for question in ("雾港的市长是谁？", "柯岚的妻子叫什么名字？", "白鹭塔的灯光能照多远？", "我的狗叫什么名字？", "水的化学式是什么？"):
            self.assertIsNone(recall_fact(question, facts), question)
        self.assertTrue(touches_memory("阿哨是谁养的？", facts))
        self.assertFalse(touches_memory("水的化学式是什么？", facts))
        self.assertFalse(touches_memory("中国的首都在哪里？", facts))
        self.assertIn("柯小满", answer_span("阿哨是谁养的？", facts[2]["statement"]))
        self.assertEqual(possessed_name_query("我的狗叫什么名字？"), "狗")
        from memory_core.fact_reader import accept_model_span, clashes, slot_from_fact

        bike = {"statement": "沈星河的自行车颜色是朱红色。", "entity": "沈星河", "value": "朱红色", "attr": "自行车颜色"}
        tea = {"statement": "沈星河最喜欢的茶是桂花乌龙。", "entity": "沈星河", "value": "桂花乌龙", "attr": "最喜欢的茶"}
        self.assertTrue(clashes("沈星河的汽车颜色是什么？", bike))
        self.assertEqual(slot_from_fact("沈星河的汽车颜色是什么？", tea), "")
        copied = accept_model_span("阿哨是谁养的？", "柯岚", [facts[2]])
        self.assertIsNotNone(copied)
        self.assertEqual(copied[0], "柯小满")
        bike = {"statement": "沈星河的自行车颜色是朱红色。", "entity": "沈星河"}
        self.assertIsNone(recall_fact("沈星河的汽车颜色是什么？", [bike]))
        self.assertIsNone(recall_fact("沈星河的车是什么颜色？", [bike]))
        self.assertIsNone(recall_fact("沈星河那辆汽车是什么颜色？", [bike]))
        self.assertEqual(possessed_name_query("我的名字是什么？"), "")

    def test_key_points_keep_facts_when_the_model_picks_scenery(self):
        text = extract_pdf_text_layer((ROOT / "wugang_chrome.pdf").read_bytes())
        points = extract_key_points(split_chapters(text), ask=lambda _prompt: "镇上的人习惯在黄昏时分聚到石阶上，看归港的船。")
        blob = "\n".join(point["text"] for point in points)
        self.assertIn("1873", blob)
        self.assertIn("霜降", blob)
        self.assertNotIn("\u2ee9", blob)

    def test_key_points_stay_whole_sentences(self):
        text = extract_pdf_text_layer((ROOT / "wugang_chrome.pdf").read_bytes())
        points = extract_key_points(split_chapters(text), ask=lambda _prompt: "1873年，塔高\n白鹭塔建于1873年，塔高四十二米。")
        tower = next(point["text"] for point in points if "白鹭塔" in point["text"] and "1873" in point["text"])
        self.assertIn("四十二米", tower)
        self.assertNotEqual(tower.strip("。"), "1873年，塔高")
        short = extract_key_points([("第一章 白鹭塔", "太短")], ask=lambda _prompt: "拆开")
        self.assertEqual(short, [])


class ThreadAndImportBoundTests(unittest.TestCase):
    def test_thread_budget_honors_omp_and_defaults_to_two(self):
        import os

        from memory_core.runtime_threads import configure_process_threads, thread_budget

        saved = {key: os.environ.get(key) for key in ("LORA_MEMORY_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS")}
        try:
            for key in saved:
                os.environ.pop(key, None)
            self.assertEqual(thread_budget(), min(2, os.cpu_count() or 1))
            os.environ["OMP_NUM_THREADS"] = "2"
            self.assertEqual(thread_budget(), 2)
            os.environ["MKL_NUM_THREADS"] = "8"
            self.assertEqual(thread_budget(), 2)
            configure_process_threads()
            self.assertEqual(os.environ["OMP_NUM_THREADS"], "2")
            self.assertEqual(os.environ["MKL_NUM_THREADS"], "8")
            self.assertEqual(os.environ["OPENBLAS_NUM_THREADS"], "2")
        finally:
            for key, value in saved.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

    def test_point_extraction_stops_at_the_deadline_and_keeps_sentences(self):
        import time

        from memory_core.documents import DocumentTimeout, extract_key_points

        called = {"n": 0}

        def ask(_prompt: str) -> str:
            called["n"] += 1
            return ""

        with self.assertRaises(DocumentTimeout) as caught:
            extract_key_points(
                [("第一章", "白鹭塔建于1873年。塔高四十二米。")],
                ask=ask,
                deadline=time.monotonic() - 1,
            )
        self.assertEqual(called["n"], 0)
        blob = "\n".join(point["text"] for point in caught.exception.points)
        self.assertIn("1873", blob)
        self.assertEqual(caught.exception.completed, [])

    def test_docx_uses_the_same_bounded_import(self):
        import io
        import tempfile
        import time
        import zipfile

        from memory_core.documents import DocumentTimeout, extract_docx, extract_key_points, import_document

        xml = (
            "<?xml version=\"1.0\"?>"
            "<w:document xmlns:w=\"http://schemas.openxmlformats.org/wordprocessingml/2006/main\">"
            "<w:body><w:p><w:r><w:t>白鹭塔建于1873年。</w:t></w:r></w:p></w:body></w:document>"
        )
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as archive:
            archive.writestr("word/document.xml", xml)
        text = extract_docx(buf.getvalue())
        self.assertIn("1873", text)

        def ask(_prompt: str) -> str:
            raise AssertionError("过了时限不该再问模型")

        with self.assertRaises(DocumentTimeout):
            extract_key_points(split_chapters(text), ask=ask, deadline=time.monotonic() - 1)
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            src = home / "tower.docx"
            src.write_bytes(buf.getvalue())
            result = import_document(home / "data", src, embed=None, ask=None)
            self.assertIn("1873", " ".join(point["text"] for point in result["points"]))


if __name__ == "__main__":
    unittest.main()
