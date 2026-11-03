"""第一人称回忆、近义合并，以及雾港灯塔志的分页检索。"""
import unittest
from pathlib import Path

from memory_core.documents import (
    attribute_in_statement,
    chunk_book,
    document_miss,
    extract_document,
    extract_key_points,
    extract_pdf_text_layer,
    pdf_document_title,
    search_documents,
    split_chapters,
)
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

    def test_key_points_stay_whole_sentences(self):
        text = extract_pdf_text_layer((ROOT / "wugang_chrome.pdf").read_bytes())
        points = extract_key_points(split_chapters(text), ask=lambda _prompt: "1873年，塔高\n白鹭塔建于1873年，塔高四十二米。")
        tower = next(point["text"] for point in points if "白鹭塔" in point["text"] and "1873" in point["text"])
        self.assertIn("四十二米", tower)
        self.assertNotEqual(tower.strip("。"), "1873年，塔高")
        short = extract_key_points([("第一章 白鹭塔", "太短")], ask=lambda _prompt: "拆开")
        self.assertEqual(short, [])


if __name__ == "__main__":
    unittest.main()
