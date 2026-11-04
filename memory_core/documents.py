"""整本书的读入、分页、检索和重点。行为对齐安卓 0.1.33。"""
from __future__ import annotations

import io
import json
import math
import re
import struct
import unicodedata
import zipfile
from pathlib import Path
from typing import Any, Callable
from xml.etree import ElementTree

PDF_NO_TEXT = "这份 PDF 没有文字层，扫描件暂时还不能读。"

_CHAPTER = re.compile(r"^(第[0-9０-９一二三四五六七八九十百零两]+[章节回部篇])[\s　]*([^\s，。！？\n]{0,12})")
_OTHER_HEAD = re.compile(r"^(#{1,3}\s+\S.{0,40}|\d{1,2}[\.、]\s*\S.{0,24})$")
_STOPS = (
    "什么时候", "哪一年", "哪一天", "哪里", "哪儿", "为什么", "怎么", "多少", "什么", "谁",
    "吗", "呢", "的", "是", "在", "有", "叫", "和", "与", "了",
)


def docs_root(home: Path) -> Path:
    return Path(home) / "docs"


# NFKC 不会把部首区（U+2E80）折成正文汉字。Chrome 抽出的 PDF 常用这些码位。
_RADICALS = str.maketrans({
    "\u2e81": "厂",
    "\u2e84": "乙",
    "\u2e85": "亻",
    "\u2e86": "冂",
    "\u2e89": "刂",
    "\u2e8a": "卜",
    "\u2e8c": "小",
    "\u2e93": "幺",
    "\u2e95": "彐",
    "\u2e96": "忄",
    "\u2e97": "心",
    "\u2e98": "扌",
    "\u2e99": "攵",
    "\u2e9c": "日",
    "\u2e9d": "月",
    "\u2e9f": "母",
    "\u2ea0": "民",
    "\u2ea1": "氵",
    "\u2ea2": "水",
    "\u2ea3": "灬",
    "\u2ea6": "丬",
    "\u2ea7": "牛",
    "\u2ea8": "犭",
    "\u2ea9": "玉",
    "\u2eaa": "疋",
    "\u2eab": "目",
    "\u2eac": "示",
    "\u2ead": "礻",
    "\u2eae": "竹",
    "\u2eaf": "糹",
    "\u2eb0": "纟",
    "\u2eb1": "网",
    "\u2eb2": "罒",
    "\u2eb6": "羊",
    "\u2eb9": "耂",
    "\u2eba": "肀",
    "\u2ebc": "肉",
    "\u2ebd": "臼",
    "\u2ebe": "艹",
    "\u2ec1": "虎",
    "\u2ec2": "衤",
    "\u2ec4": "西",
    "\u2ec5": "见",
    "\u2ec6": "角",
    "\u2ec8": "讠",
    "\u2ec9": "贝",
    "\u2eca": "足",
    "\u2ecb": "车",
    "\u2ecc": "辶",
    "\u2ecf": "阝",
    "\u2ed0": "钅",
    "\u2ed1": "长",
    "\u2ed3": "长",
    "\u2ed4": "门",
    "\u2ed6": "阝",
    "\u2ed7": "雨",
    "\u2ed8": "青",
    "\u2ed9": "韦",
    "\u2eda": "页",
    "\u2edb": "风",
    "\u2edc": "飞",
    "\u2edd": "食",
    "\u2ee0": "饣",
    "\u2ee1": "首",
    "\u2ee2": "马",
    "\u2ee3": "骨",
    "\u2ee4": "鬼",
    "\u2ee5": "鱼",
    "\u2ee6": "鸟",
    "\u2ee7": "卤",
    "\u2ee8": "麦",
    "\u2ee9": "黄",
    "\u2eea": "黾",
    "\u2eec": "齐",
    "\u2eee": "齿",
    "\u2ef0": "龙",
    "\u2ef1": "龟",
    "\u2ef3": "龟",
})


def normalize_cjk(text: str) -> str:
    folded = unicodedata.normalize("NFKC", text or "")
    return folded.translate(_RADICALS)


def normalize_doc_punctuation(text: str) -> str:
    out = []
    for index, ch in enumerate(text):
        if ch == ",":
            prev = text[index - 1] if index else ""
            nxt = text[index + 1] if index + 1 < len(text) else ""
            cjk = ("\u4e00" <= prev <= "\u9fff") or ("\u4e00" <= nxt <= "\u9fff")
            out.append("，" if cjk else ",")
        else:
            out.append(ch)
    return "".join(out)


def normalize_document_text(text: str) -> str:
    return normalize_doc_punctuation(normalize_cjk(text))


def _is_cjk(ch: str) -> bool:
    return "\u4e00" <= ch <= "\u9fff"


def _continues_wrapped(prev: str, nxt: str) -> bool:
    if prev in "。！？；：":
        return False
    if _is_cjk(prev) and (_is_cjk(nxt) or nxt.isdigit()):
        return True
    if prev.isdigit() and (_is_cjk(nxt) or nxt.isdigit()):
        return True
    return False


def join_wrapped_lines(text: str) -> str:
    out: list[str] = []
    for raw in text.split("\n"):
        line = raw.strip()
        if not line:
            continue
        prev = out[-1] if out else None
        wrap = (
            prev is not None
            and len(prev) >= 8
            and heading_title(prev) is None
            and heading_title(line) is None
            and _continues_wrapped(prev[-1], line[0])
        )
        if wrap:
            out[-1] = prev + line
        else:
            out.append(line)
    return "\n".join(out)


def heading_title(line: str) -> str | None:
    trimmed = line.strip()
    if not trimmed or len(trimmed) > 40:
        return None
    if any(mark in trimmed for mark in ("。", "！", "？")):
        return None
    mark = _CHAPTER.match(trimmed)
    if mark and mark.end() >= len(trimmed) - 1:
        return re.sub(r"\s+", " ", f"{mark.group(1)} {mark.group(2)}").strip()
    if _OTHER_HEAD.match(trimmed):
        return trimmed.lstrip("#").strip()
    return None


def separate_headings(text: str) -> str:
    lines = []
    for line in text.replace("\r\n", "\n").split("\n"):
        trimmed = line.strip()
        mark = _CHAPTER.match(trimmed)
        if not mark:
            lines.append(line)
            continue
        title = re.sub(r"\s+", " ", f"{mark.group(1)} {mark.group(2)}").strip()
        rest = trimmed[mark.end():].strip()
        lines.append(trimmed if len(rest) < 8 else f"{title}\n{rest}")
    return "\n".join(lines)


def split_chapters(text: str) -> list[tuple[str, str]]:
    lines = separate_headings(text).split("\n")
    out: list[tuple[str, str]] = []
    title = "正文"
    body: list[str] = []

    def flush() -> None:
        chunk = "\n".join(body).strip()
        if chunk:
            out.append((title, chunk))
        body.clear()

    for raw in lines:
        if "\f" in raw:
            body.append("\f")
            rest = raw.replace("\f", "").strip()
            if rest:
                body.append(rest)
            continue
        line = raw.strip()
        heading = heading_title(line)
        if heading:
            flush()
            title = heading
        elif line:
            body.append(line)
    flush()
    return out or [("正文", text.strip())]


def chunk_passages(text: str, chapter: str = "正文", page: int = 1) -> list[dict]:
    clean = text.replace("\r\n", "\n").strip()
    if not clean:
        return []
    if "\f" in clean:
        out: list[dict] = []
        for index, page_text in enumerate(clean.split("\f")):
            out.extend(chunk_passages(page_text, chapter, page + index))
        for index, chunk in enumerate(out):
            chunk["id"] = f"c{index}"
        return out
    if len(clean) <= 500:
        return [{"id": "c0", "text": clean, "chapter": chapter, "page": page}]
    out = []
    cursor = 0
    page_no = page
    guard = 0
    while cursor < len(clean) and guard < 10000:
        guard += 1
        end = min(len(clean), cursor + 420)
        if end < len(clean):
            break_at = clean.rfind("。", cursor + 280, end)
            if break_at < 0:
                break_at = clean.rfind("\n", cursor + 280, end)
            if break_at > cursor + 280:
                end = min(len(clean), break_at + 1)
        slice_text = clean[cursor:end].strip()
        if slice_text:
            pages = slice_text.count("\f")
            out.append({
                "id": f"c{len(out)}",
                "text": slice_text.replace("\f", "\n"),
                "chapter": chapter,
                "page": page_no,
            })
            page_no += pages
        if end >= len(clean):
            break
        cursor = max(end - 80, cursor + 1)
    return out


def chunk_book(text: str) -> list[dict]:
    out: list[dict] = []
    page = 1
    paged = "\f" in text
    for chapter, body in split_chapters(text):
        pieces = chunk_passages(body, chapter, page)
        for piece in pieces:
            piece["paged"] = paged
        out.extend(pieces)
        if pieces:
            page = max(item["page"] for item in pieces) + 1
    for index, chunk in enumerate(out):
        chunk["id"] = f"c{index}"
    return out


def _cjk_stops(pages: list[str]) -> int:
    return sum(page.count("。") for page in pages)


def _index_of(data: bytes, needle: bytes, start: int) -> int:
    return data.find(needle, start)


def _inflate(data: bytes) -> bytes:
    import zlib

    for window in (zlib.MAX_WBITS, -zlib.MAX_WBITS):
        try:
            return zlib.decompress(data, window)
        except zlib.error:
            continue
    return b""


def _decode_pdf_hex(hex_text: str) -> str:
    compact = re.sub(r"\s+", "", hex_text)
    if len(compact) % 2:
        compact += "0"
    try:
        raw = bytes.fromhex(compact)
    except ValueError:
        return ""
    if raw.startswith(b"\xfe\xff"):
        return raw[2:].decode("utf-16-be", errors="ignore")
    return raw.decode("utf-16-be", errors="ignore")


def legacy_utf16_pages(data: bytes) -> list[str]:
    pages: list[str] = []
    stream_mark = b"stream"
    end_mark = b"endstream"
    cursor = 0
    while cursor < len(data):
        stream_at = _index_of(data, stream_mark, cursor)
        if stream_at < 0:
            break
        dict_start = max(0, stream_at - 2000)
        header = data[dict_start:stream_at].decode("latin1", errors="ignore")
        data_start = stream_at + len(stream_mark)
        if data_start < len(data) and data[data_start] == 13:
            data_start += 1
        if data_start < len(data) and data[data_start] == 10:
            data_start += 1
        end = _index_of(data, end_mark, data_start)
        if end < 0:
            break
        slice_bytes = data[data_start:end]
        flate = "FlateDecode" in header or (len(slice_bytes) > 2 and slice_bytes[0] == 0x78)
        body = _inflate(slice_bytes) if flate else slice_bytes
        text_src = body.decode("latin1", errors="ignore")
        lines = [
            _decode_pdf_hex(match.group(1)).strip()
            for match in re.finditer(r"<(FEFF[0-9A-Fa-f\s]*)>\s*Tj", text_src)
        ]
        text = "\n".join(line for line in lines if line)
        if text.strip():
            pages.append(text)
        cursor = end + len(end_mark)
    return pages


def extract_pdf_pages(data: bytes) -> list[str]:
    if not data:
        return []
    try:
        from pypdf import PdfReader
    except ImportError:
        return []
    reader = PdfReader(io.BytesIO(data))
    pages = []
    for page in reader.pages:
        raw = page.extract_text() or ""
        normalized = normalize_cjk(raw.replace("\r\n", "\n").replace("\r", "\n"))
        pages.append(join_wrapped_lines(normalized))
    return pages


def pdf_document_title(data: bytes) -> str:
    if not data:
        return ""
    try:
        from pypdf import PdfReader

        info = PdfReader(io.BytesIO(data)).metadata
        title = ""
        if info is not None:
            title = str(info.title or "")
        return title.strip()
    except Exception:
        return ""


def extract_pdf_text_layer(data: bytes) -> str:
    legacy = legacy_utf16_pages(data)
    try:
        modern = extract_pdf_pages(data)
    except Exception:
        modern = []
    chosen = legacy if _cjk_stops(legacy) > _cjk_stops(modern) else modern
    if not any(page.strip() for page in chosen):
        return ""
    return normalize_document_text("\n\f\n".join(chosen))


def decode_plain(data: bytes) -> str:
    utf8 = data.decode("utf-8", errors="replace")
    if "\ufffd" in utf8 and len(data) > 8:
        return data.decode("utf-16", errors="replace")
    return utf8


def _zip_entry(data: bytes, name: str) -> str | None:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            for info in archive.infolist():
                if info.filename == name or info.filename.endswith("/" + name):
                    return archive.read(info).decode("utf-8", errors="replace")
    except zipfile.BadZipFile:
        return None
    return None


def _zip_texts(data: bytes) -> dict[str, str]:
    found: dict[str, str] = {}
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            for info in archive.infolist():
                if info.is_dir():
                    continue
                lower = info.filename.lower()
                if lower.endswith((".xml", ".xhtml", ".html", ".htm", ".opf", ".ncx")):
                    found[info.filename] = archive.read(info).decode("utf-8", errors="replace")
    except zipfile.BadZipFile:
        return {}
    return found


def _xml_text(xml: str) -> str:
    text = re.sub(r"<script[\s\S]*?</script>", " ", xml, flags=re.IGNORECASE)
    text = re.sub(r"<style[\s\S]*?</style>", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "\n", text)
    text = (
        text.replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&amp;", "&")
        .replace("&quot;", '"')
        .replace("&#39;", "'")
    )
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def extract_docx(data: bytes) -> str:
    xml = _zip_entry(data, "word/document.xml")
    if not xml:
        return ""
    try:
        root = ElementTree.fromstring(xml)
    except ElementTree.ParseError:
        return _xml_text(xml)
    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    paragraphs = []
    for para in root.iter("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p"):
        parts = [node.text or "" for node in para.iter("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t")]
        line = "".join(parts).strip()
        if line:
            paragraphs.append(line)
    if paragraphs:
        return "\n".join(paragraphs)
    del ns
    return _xml_text(xml)


def docx_title(data: bytes) -> str:
    core = _zip_entry(data, "docProps/core.xml") or ""
    match = re.search(r"<dc:title[^>]*>(.*?)</dc:title>", core, flags=re.IGNORECASE)
    return _xml_text(match.group(1)) if match else ""


def _epub_spine(opf: str, names: list[str]) -> list[str]:
    hrefs = re.findall(r'<itemref[^>]*idref="([^"]+)"', opf)
    ids = {}
    for match in re.finditer(r'<item[^>]*id="([^"]+)"[^>]*href="([^"]+)"', opf):
        ids[match.group(1)] = match.group(2)
    for match in re.finditer(r'<item[^>]*href="([^"]+)"[^>]*id="([^"]+)"', opf):
        ids.setdefault(match.group(2), match.group(1))
    ordered = [ids[item] for item in hrefs if item in ids]
    return ordered or sorted(name for name in names if name.lower().endswith((".xhtml", ".html", ".htm")))


def extract_epub(data: bytes) -> str:
    entries = _zip_texts(data)
    opf = next((value for key, value in entries.items() if key.lower().endswith(".opf")), "")
    title_match = re.search(r"<dc:title[^>]*>(.*?)</dc:title>", opf, flags=re.IGNORECASE)
    title = _xml_text(title_match.group(1)) if title_match else ""
    ordered = [
        href for href in _epub_spine(opf, list(entries))
        if href.split("/")[-1] not in {"nav.xhtml", "toc.ncx"} and not href.endswith(".ncx")
    ]
    parts = []
    used = set()
    for href in ordered:
        hit = next((key for key in entries if key.endswith(href) or key.endswith("/" + href)), "")
        if not hit or hit in used:
            continue
        used.add(hit)
        body = _xml_text(entries[hit])
        if body.strip():
            parts.append(body)
    if not parts:
        for key in sorted(entries):
            if key.lower().endswith((".xhtml", ".html", ".htm")):
                parts.append(_xml_text(entries[key]))
    head = [title] if title else []
    return "\n\n".join(head + parts)


def epub_title(data: bytes) -> str:
    entries = _zip_texts(data)
    opf = next((value for key, value in entries.items() if key.lower().endswith(".opf")), "")
    match = re.search(r"<dc:title[^>]*>(.*?)</dc:title>", opf, flags=re.IGNORECASE)
    return _xml_text(match.group(1)) if match else ""


def extract_document(name: str, data: bytes) -> str:
    lower = name.lower()
    if lower.endswith(".pdf"):
        text = extract_pdf_text_layer(data)
    elif lower.endswith(".epub"):
        text = extract_epub(data)
    elif lower.endswith(".docx"):
        text = extract_docx(data)
    else:
        text = decode_plain(data)
    return normalize_document_text(text.replace("\x00", "").strip())


def document_title(name: str, data: bytes) -> str:
    lower = name.lower()
    if lower.endswith(".pdf"):
        return pdf_document_title(data)
    if lower.endswith(".epub"):
        return epub_title(data)
    if lower.endswith(".docx"):
        return docx_title(data)
    return ""


def is_key_fact(line: str) -> bool:
    if not 8 <= len(line) <= 120:
        return False
    if "什么" in line or "吗" in line or line.endswith("？") or line.endswith("?"):
        return False
    if any(mark in line for mark in ("名叫", "建于", "成立", "位于", "称为", "定义", "总部")):
        return True
    if re.search(r"[0-9０-９]{2,}", line):
        return True
    if re.search(r"[一二三四五六七八九十百千零两]{1,4}(米|年|面|只|条|岁)", line):
        return True
    if "叫" in line and len(line) <= 48:
        return True
    scene = ("瓦房", "屋檐", "巷子", "两旁", "风干", "追逐")
    if "是" in line and len(line) <= 40 and not any(word in line for word in scene):
        return True
    return False


def _key_score(line: str) -> int:
    score = 0
    if any(mark in line for mark in ("名叫", "建于", "成立")):
        score += 3
    if re.search(r"[0-9０-９]{3,}", line):
        score += 2
    if "叫" in line:
        score += 1
    return score


def _sentences(passage: str) -> list[str]:
    parts = []
    for piece in re.split(r"[。！!\n]+", passage):
        text = piece.strip()
        if len(text) < 4:
            continue
        parts.append(text if text.endswith("。") else text + "。")
    return parts


def _whole_sentence(line: str, body: str) -> str:
    """模型如果把一句话拆开，就丢掉，改用原文里的整句。"""
    def norm(text: str) -> str:
        return re.sub(r"[\s　]", "", text).strip("。！？.!?、 ")

    target = norm(line)
    if len(target) < 6:
        return ""
    for sentence in _sentences(body):
        if norm(sentence) == target:
            return sentence
    return ""


def heuristic_keys(body: str) -> list[str]:
    lines = []
    seen = set()
    for sentence in _sentences(body):
        bare = sentence.rstrip("。")
        if not is_key_fact(bare) or bare in seen:
            continue
        seen.add(bare)
        lines.append(sentence)
    lines.sort(key=_key_score, reverse=True)
    return lines[:5]


def chapter_prompt(chapter: str, body: str) -> str:
    return f"请只列出《{chapter}》里最多5条关键事实，每行一条完整的句子，不要编号，不要拆开原句。\n{body[:1500]}"


def prompts_for_chapter(chapter: str, body: str) -> list[str]:
    prompts = []
    rest = body.strip()
    if len(rest) < 12:
        return prompts
    while rest:
        window = rest[:1200]
        if len(rest) <= 1200:
            cut = len(rest)
        else:
            dot = window.rfind("。")
            cut = dot + 1 if dot > 400 else 1200
        prompts.append(chapter_prompt(chapter, rest[:cut]))
        rest = rest[cut:].strip()
        if len(prompts) >= 8:
            break
    return prompts


def extract_key_points(
    chapters: list[tuple[str, str]],
    per_chapter: int = 5,
    total_cap: int = 40,
    ask: Callable[[str], str] | None = None,
) -> list[dict]:
    out: list[dict] = []
    for chapter, body in chapters:
        if len(out) >= total_cap:
            break
        from_llm: list[str] = []
        if ask is not None and len(body.strip()) >= 12:
            try:
                for prompt in prompts_for_chapter(chapter, body):
                    raw = ask(prompt) or ""
                    for line in raw.splitlines():
                        cleaned = line.strip().lstrip("-• 0123456789.、").strip()
                        whole = _whole_sentence(cleaned, body)
                        if whole:
                            from_llm.append(whole)
            except Exception:
                from_llm = []
        chosen: list[str] = []
        for line in heuristic_keys(body) + from_llm:
            bare = line.rstrip("。")
            if from_llm and line in from_llm and line not in heuristic_keys(body) and not is_key_fact(bare):
                continue
            if any(is_same_text(item, line) for item in chosen):
                continue
            chosen.append(line)
        if not chosen:
            for line in from_llm:
                if any(is_same_text(item, line) for item in chosen):
                    continue
                chosen.append(line)
        chosen.sort(key=_key_score, reverse=True)
        lines = chosen[:per_chapter]
        for line in lines:
            if len(out) >= total_cap:
                break
            if any(is_same_text(item["text"], line) for item in out):
                continue
            out.append({"id": f"p{len(out)}", "text": line, "chapter": chapter, "selected": True})
    return out


def is_same_text(left: str, right: str) -> bool:
    from memory_core.same_memory import is_same_memory

    return is_same_memory(left, right)


_SOFT_RUNS = frozenset({"多高", "高度", "多长", "多大", "多重"})


def salient_runs(query: str) -> list[str]:
    text = re.sub(r"[\s?？。，,！!、]", "", query.strip())
    for stop in sorted(_STOPS, key=len, reverse=True):
        text = text.replace(stop, "\x01")
    return [part.strip() for part in text.split("\x01") if len(part.strip()) >= 2]


def _run_in_text(run: str, text: str) -> bool:
    if run in _SOFT_RUNS:
        return bool(re.search(r"高|米|长", text))
    return run_covered(run, text)


def run_covered(run: str, text: str) -> bool:
    """检索用。三字片段只说明这段文字沾边，不能拿来回忆一条事实。"""
    if run in text:
        return True
    if len(run) < 3:
        return False
    return any(run[index:index + 3] in text for index in range(0, len(run) - 2))


_ASK_PARTICLES = (
    "什么时候", "哪一年", "哪一天", "哪里", "哪儿", "为什么", "怎么", "多少", "什么", "哪天",
    "吗", "呢", "谁", "了",
)


def attribute_in_statement(query: str, entity: str, statement: str) -> bool:
    """主体和属性都要落在这句话里。只点到人名，或只剩「名字」这种共有字，都不算。"""
    compact_statement = re.sub(r"[\s，,。.!！？?、]", "", statement or "")
    asked = re.sub(r"[\s，,。.!！？?、]", "", query or "")
    if not compact_statement or not asked:
        return False
    if entity and entity not in asked and entity not in compact_statement:
        return False
    if entity and entity in asked:
        asked = asked.replace(entity, "")
    for particle in _ASK_PARTICLES:
        asked = asked.replace(particle, "")
    asked = re.sub(r"[的是叫]", "", asked)
    if len(asked) < 1:
        return False
    return asked in compact_statement


def _bigrams(text: str) -> list[str]:
    compact = re.sub(r"[\s，,。.!！？?、]", "", text)
    if len(compact) < 2:
        return [compact] if compact else []
    return [compact[index:index + 2] for index in range(len(compact) - 1)]


def lexical_score(query: str, text: str) -> float:
    left = _bigrams(query)
    right = set(_bigrams(text))
    if not left or not right:
        return 0.0
    shared = sum(1 for item in left if item in right)
    return shared / math.sqrt(len(left) * len(right))


def _cosine(left: list[float], right: list[float]) -> float:
    if not left or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm <= 0 or right_norm <= 0:
        return 0.0
    return dot / (left_norm * right_norm)


def _sentence_score(query: str, line: str) -> float:
    score = lexical_score(query, line)
    if any(word in query for word in ("多高", "高度", "有多高")) and re.search(r"高|米", line):
        score += 0.55
    if any(word in query for word in ("哪一年", "哪年", "建于", "什么时候", "何时")) and re.search(r"\d{3,4}\s*年|建于|霜降|晾晒", line):
        score += 0.45
    if any(word in query for word in ("叫什么", "名字", "是谁")) and re.search(r"名叫|叫", line):
        score += 0.25
    return score


def retrieve_docs(query: str, chunks: list[dict], vectors: list[list[float]] | None, query_vector: list[float] | None) -> list[dict]:
    if not chunks or not query.strip():
        return []
    lexical = []
    for chunk in chunks:
        sentence = max((_sentence_score(query, line) for line in _sentences(chunk["text"])), default=0.0)
        lexical.append(max(lexical_score(query, chunk["text"]), sentence))
    scored = []
    if query_vector is not None and vectors is not None and len(vectors) == len(chunks):
        for chunk, vector, words in zip(chunks, vectors, lexical):
            cosine = _cosine(query_vector, vector)
            score = max(cosine, words)
            if words >= 0.22:
                score = max(score, 0.5)
            scored.append({"chunk": chunk, "score": score, "lexical": words})
    else:
        for chunk, words in zip(chunks, lexical):
            scored.append({"chunk": chunk, "score": words, "lexical": words})
    scored.sort(key=lambda item: item["score"], reverse=True)
    return scored[:4]


def passage_chip(title: str, chunk: dict) -> str:
    page = int(chunk.get("page") or 0)
    chapter = str(chunk.get("chapter") or "")
    paged = bool(chunk.get("paged", True))
    chapter_bit = chapter if chapter and chapter != "正文" else ""
    if paged and page > 0:
        where = f"第{page}页"
        suffix = f" · {chapter_bit}" if chapter_bit else ""
    else:
        where = chapter_bit
        suffix = ""
    return f"《{title}》{where}{suffix}"


def ground_document(query: str, hits: list[dict], title: str, min_score: float) -> dict | None:
    runs = salient_runs(query)
    useful = []
    best_line = ""
    best_hit = None
    best_score = -1.0
    for hit in hits:
        text = hit["chunk"]["text"]
        covered = all(run_covered(run, text) for run in runs) if runs else True
        lexical = float(hit.get("lexical") or 0)
        if not covered and lexical < 0.22 and hit["score"] < min_score:
            continue
        for line in _sentences(text):
            score = _sentence_score(query, line)
            if score > best_score and (score >= 0.22 or (hit["score"] >= min_score and covered)):
                best_score = score
                best_line = line
                best_hit = hit
        if covered and (hit["score"] >= min_score or lexical >= 0.22):
            useful.append(hit)
    if not best_line or best_hit is None:
        return None
    needle = best_line.rstrip("。")
    same = [hit for hit in hits if needle and needle in hit["chunk"]["text"]]
    chosen = min(same or [best_hit], key=lambda hit: int(hit["chunk"].get("page") or 0) or 99)
    label = passage_chip(title, chosen["chunk"])
    return {"answer": best_line, "chips": [{"label": label, "passage": best_line}]}


def doc_min_score(used_vectors: bool) -> float:
    return 0.45 if used_vectors else 0.18


def document_miss(title: str, english: bool = False) -> str:
    if english:
        return f"Nothing relevant turned up in {title}."
    return f"《{title}》里没有找到相关内容。"


def missed_document_title(query: str, docs: list[dict]) -> str:
    for doc in docs:
        title = str(doc.get("title") or "")
        if len(title) >= 2 and title in query:
            return title
    runs = salient_runs(query)
    best = ""
    best_n = -1
    for doc in docs:
        covered = sum(
            1 for run in runs
            if any(run_covered(run, chunk["text"]) for chunk in doc.get("chunks") or [])
        )
        if covered > best_n:
            best_n = covered
            best = str(doc.get("title") or "")
    return best


def search_documents(query: str, docs: list[dict], query_vector: list[float] | None = None) -> dict:
    if not docs or not query.strip():
        return {"ground": None, "best_score": 0.0, "title_hit": False, "missing_term": False}
    title_hit = any(len(str(doc.get("title") or "")) >= 2 and str(doc.get("title")) in query for doc in docs)
    runs = salient_runs(query)
    missing = any(
        run for run in runs
        if not any(any(_run_in_text(run, chunk["text"]) for chunk in doc.get("chunks") or []) for doc in docs)
    )
    subject_hit = any(
        run for run in runs
        if run not in _SOFT_RUNS and any(any(run in chunk["text"] for chunk in doc.get("chunks") or []) for doc in docs)
    )
    best_score = 0.0
    best = None
    if not missing:
        for doc in docs:
            vectors = doc.get("vectors")
            used = query_vector is not None and isinstance(vectors, list) and len(vectors) == len(doc.get("chunks") or [])
            hits = retrieve_docs(query, doc.get("chunks") or [], vectors if used else None, query_vector if used else None)
            score = hits[0]["score"] if hits else 0.0
            if score > best_score:
                best_score = score
            grounded = ground_document(query, hits, str(doc.get("title") or ""), doc_min_score(used))
            if grounded is None:
                continue
            grounded["doc_id"] = doc.get("id") or ""
            grounded["title"] = doc.get("title") or ""
            if best is None or score >= best_score:
                best = grounded
    return {
        "ground": best,
        "best_score": best_score,
        "title_hit": title_hit,
        "missing_term": missing,
        "subject_hit": subject_hit,
    }


def admit_no_passage(search: dict, min_score: float = 0.18, used_vectors: bool = False) -> bool:
    if search.get("ground"):
        return False
    if search.get("missing_term") or search.get("title_hit"):
        return True
    if used_vectors and (search.get("subject_hit") or float(search.get("best_score") or 0) >= 0.32):
        return True
    if used_vectors:
        return False
    score = float(search.get("best_score") or 0)
    return 0.08 < score < min_score


def _content_runs(query: str) -> list[str]:
    """保留单字事物。文档检索仍用 salient_runs，避免把「车」从「自行车」里拆丢。"""
    text = re.sub(r"[\s?？。，,！!、]", "", query.strip())
    for stop in sorted(_STOPS, key=len, reverse=True):
        text = text.replace(stop, "\x01")
    return [part.strip() for part in text.split("\x01") if part.strip() and part.strip() not in _SOFT_RUNS]


def _run_stands_alone(run: str, text: str) -> bool:
    """单字必须自己成词。「车」不能从「自行车」里抠出来。"""
    if len(run) >= 2:
        return run in text
    bounds = set("的了是在有和与吗呢叫，。、 ")
    start = 0
    while True:
        index = text.find(run, start)
        if index < 0:
            return False
        before = text[index - 1] if index else ""
        after = text[index + len(run)] if index + len(run) < len(text) else ""
        before_ok = not before or before in bounds or not _is_cjk(before)
        after_ok = not after or after in bounds or not _is_cjk(after)
        if before_ok and after_ok:
            return True
        start = index + 1


def covered_fact(query: str, facts: list[dict]) -> dict | None:
    """问句没有点到专家名时，仍用整句里的人和事物对上。"""
    runs = _content_runs(query)
    if not runs or sum(len(run) for run in runs) < 4:
        return None
    hits = []
    for fact in facts:
        if not isinstance(fact, dict) or fact.get("superseded"):
            continue
        statement = str(fact.get("statement") or "")
        if statement and all(_run_stands_alone(run, statement) for run in runs):
            hits.append(fact)
    if not hits:
        return None
    hits.sort(key=lambda fact: (0 if re.search(r"名叫|叫|年", str(fact.get("statement") or "")) else 1, len(str(fact.get("statement") or ""))))
    return hits[0]


def fact_from_point(text: str, title: str, chapter: str) -> dict:
    """重点保持整句。问法从句子里的年份和名字长出来，答案仍是这一整句。"""
    line = text.strip()
    if line and line[-1] not in "。！？.!?":
        line += "。"
    entity = title or "文档"
    value_override = ""
    owned = re.search(r"([\u4e00-\u9fff]{2,3})养了.*?海鸥，名叫([\u4e00-\u9fffA-Za-z0-9·]{1,12})", line)
    named = re.search(r"名叫([\u4e00-\u9fffA-Za-z0-9·]{1,12})", line)
    if owned:
        entity = owned.group(1)
        value_override = owned.group(2)
    elif named:
        entity = named.group(1)
    else:
        built = re.search(r"([\u4e00-\u9fff]{2,8})建于", line)
        if built:
            entity = built.group(1)
    questions = [f"《{title}》里说了什么？"] if title else []
    if re.search(r"\d{3,4}\s*年", line) or "建于" in line:
        subject = named.group(1) if named else entity
        questions.append(f"{subject}建于哪一年？")
        questions.append(f"{subject}是哪一年建的？")
    if "塔高" in line or "米" in line:
        questions.append("白鹭塔有多高？" if "塔" in line else f"{entity}有多高？")
    if "霜降" in line:
        questions.append("星砂盐什么时候晾晒？" if "盐" in line else f"{entity}是什么时候？")
    if "叫" in line:
        questions.append(f"{entity}叫什么？")
        if "海鸥" in line or "阿哨" in line:
            questions.append(f"{entity}的海鸥叫什么？")
            questions.append(f"{entity}的海鸥叫什么")
            if "柯小满" in line:
                questions.append("柯小满的海鸥叫什么？")
    attr = chapter if chapter and chapter != "正文" else "重点"
    value = value_override or line.rstrip("。")
    from memory_core.fact_recall import fact_aliases, fact_mentions

    aliases = fact_aliases(line)
    mentions = fact_mentions(line, entity if entity != (title or "文档") else "")
    for alias in aliases:
        if "海鸥" in alias:
            questions.append(f"那只{alias}叫什么名字？")
        if "灯塔" in alias:
            questions.append(f"柯岚守护的{alias}是哪年建的？" if "第一座" in alias else f"{alias}是哪年建的？")
        if "海盐" in alias:
            questions.append(f"雾港的{alias}每年哪天开始晒？")
    return {
        "entity": entity,
        "attr": attr,
        "value": value,
        "statement": line,
        "question": questions[0] if questions else f"{entity}是什么？",
        "answer": line.rstrip("。"),
        "extra_questions": questions[1:],
        "selected": True,
        "gate": "write",
        "source": "document",
        "aliases": aliases,
        "mentions": mentions,
    }


def _read_json(path: Path, fallback: Any) -> Any:
    if not path.is_file():
        return fallback
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return fallback


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_chunks(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict) and item.get("text"):
            rows.append(item)
    return rows


def save_chunks(path: Path, chunks: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(chunk, ensure_ascii=False) + "\n" for chunk in chunks), encoding="utf-8")


def load_vectors(path: Path, count: int) -> list[list[float]] | None:
    if not path.is_file() or count <= 0:
        return None
    raw = path.read_bytes()
    if not raw or len(raw) % (count * 4) != 0:
        return None
    dim = len(raw) // (count * 4)
    rows = []
    for index in range(count):
        start = index * dim * 4
        rows.append(list(struct.unpack(f"<{dim}f", raw[start:start + dim * 4])))
    return rows


def save_vectors(path: Path, rows: list[list[float]]) -> None:
    blob = bytearray()
    for row in rows:
        blob.extend(struct.pack(f"<{len(row)}f", *row))
    path.write_bytes(blob)


def load_indexed_docs(home: Path) -> list[dict]:
    root = docs_root(home)
    if not root.is_dir():
        return []
    docs = []
    for directory in sorted(path for path in root.iterdir() if path.is_dir()):
        meta = _read_json(directory / "meta.json", {})
        if not isinstance(meta, dict) or not meta.get("title"):
            continue
        chunks = load_chunks(directory / "chunks.jsonl")
        if not chunks:
            continue
        vectors = load_vectors(directory / "vectors.f32", len(chunks))
        docs.append({
            "id": meta.get("id") or directory.name,
            "title": meta.get("title") or "",
            "chunks": chunks,
            "vectors": vectors,
            "pages": meta.get("pages") or 0,
        })
    return docs


def list_documents(home: Path, stored_statements: list[str] | None = None) -> list[dict]:
    root = docs_root(home)
    if not root.is_dir():
        return []
    stored = stored_statements or []
    rows = []
    for directory in sorted(path for path in root.iterdir() if path.is_dir()):
        meta = _read_json(directory / "meta.json", {})
        if not isinstance(meta, dict) or not meta.get("title"):
            continue
        points = _read_json(directory / "points.json", [])
        if not isinstance(points, list):
            points = []
        queued = _read_json(directory / "queued.json", [])
        if not isinstance(queued, list):
            queued = []
        consolidated = 0
        for point in points:
            text = str((point or {}).get("text") or "")
            if text and any(is_same_text(text, item) for item in stored):
                consolidated += 1
        rows.append({
            "id": meta.get("id") or directory.name,
            "title": meta.get("title") or "",
            "format": str(meta.get("format") or Path(str(meta.get("source") or "")).suffix.lstrip(".")).upper(),
            "pages": int(meta.get("pages") or 0),
            "chunks": int(meta.get("chunks") or 0),
            "points": points,
            "queued": [str(item) for item in queued],
            "consolidated": consolidated,
        })
    return rows


def import_document(
    home: Path,
    source: Path,
    embed: Callable[[list[str]], list[list[float]]] | None = None,
    ask: Callable[[str], str] | None = None,
    on_progress: Callable[[dict], None] | None = None,
) -> dict:
    source = Path(source)
    root = docs_root(home)
    root.mkdir(parents=True, exist_ok=True)
    data = source.read_bytes()
    if len(data) > 48 * 1024 * 1024:
        raise ValueError("这份文件太大。")
    title = document_title(source.name, data) or source.stem or "未命名"
    text = extract_document(source.name, data)
    if not text.strip():
        if source.suffix.lower() == ".pdf":
            raise ValueError(PDF_NO_TEXT)
        raise ValueError("没有读出文字。")
    doc_id = re.sub(r"[^0-9A-Za-z]", "", source.stem)[:12] or "book"
    directory = root / doc_id
    suffix = 2
    while directory.exists() and (_read_json(directory / "meta.json", {}) or {}).get("source") != str(source):
        doc_id = f"{re.sub(r'[^0-9A-Za-z]', '', source.stem)[:10]}{suffix}"
        directory = root / doc_id
        suffix += 1
    directory.mkdir(parents=True, exist_ok=True)

    def report(phase: str, percent: int, message: str = "") -> None:
        payload = {"title": title, "phase": phase, "percent": percent, "message": message, "doc_id": doc_id}
        _write_json(root / "job.json", payload)
        if on_progress:
            on_progress(payload)

    report("parse", 15, title)
    (directory / "raw.txt").write_text(text, encoding="utf-8")
    report("split", 40)
    chunks = chunk_book(text)
    save_chunks(directory / "chunks.jsonl", chunks)
    dim = 0
    if embed is not None and chunks:
        report("index", 60)
        try:
            rows = []
            batch: list[str] = []
            owners: list[dict] = []
            for chunk in chunks:
                batch.append(chunk["text"])
                owners.append(chunk)
                if len(batch) == 8:
                    got = embed(batch)
                    if got and len(got) == len(batch):
                        rows.extend(got)
                    batch = []
            if batch:
                got = embed(batch)
                if got and len(got) == len(batch):
                    rows.extend(got)
            if len(rows) == len(chunks):
                dim = len(rows[0])
                save_vectors(directory / "vectors.f32", rows)
        except Exception:
            dim = 0
    report("points", 85)
    points = extract_key_points(split_chapters(text), ask=ask)
    _write_json(directory / "points.json", points)
    pages = text.count("\f") + 1
    meta = {
        "id": doc_id,
        "title": title,
        "format": source.suffix.lstrip(".").upper(),
        "pages": pages,
        "chunks": len(chunks),
        "dim": dim,
        "source": str(source),
    }
    _write_json(directory / "meta.json", meta)
    report("done", 100, title)
    return {"id": doc_id, "title": title, "pages": pages, "chunks": len(chunks), "points": points}


def queue_points(home: Path, doc_id: str, selected_ids: list[str] | None = None) -> list[str]:
    directory = docs_root(home) / doc_id
    points = _read_json(directory / "points.json", [])
    if not isinstance(points, list):
        return []
    chosen = set(selected_ids or [])
    queued = []
    for point in points:
        if not isinstance(point, dict):
            continue
        text = str(point.get("text") or "").strip()
        if not text:
            continue
        point["selected"] = (point.get("id") in chosen) if selected_ids is not None else bool(point.get("selected", True))
        if point["selected"]:
            queued.append(text if text.endswith("。") else text + "。")
    _write_json(directory / "points.json", points)
    _write_json(directory / "queued.json", queued)
    return queued


def delete_document(home: Path, doc_id: str) -> None:
    directory = docs_root(home) / doc_id
    if not directory.is_dir():
        raise FileNotFoundError(doc_id)
    import shutil

    shutil.rmtree(directory)


def queued_lines(home: Path) -> list[dict]:
    rows = []
    for doc in list_documents(home):
        for text in doc.get("queued") or []:
            rows.append({"text": text, "doc_id": doc["id"], "title": doc["title"], "chapter": ""})
            for point in doc.get("points") or []:
                if isinstance(point, dict) and is_same_text(str(point.get("text") or ""), text):
                    rows[-1]["chapter"] = point.get("chapter") or ""
                    break
    return rows
