# utils/extract.py

from bs4 import BeautifulSoup
import re
from pypinyin import pinyin, Style

def extract_idiom_info(html: str, idiom: str):
    soup = BeautifulSoup(html, "html.parser")
    result = {
        "structured_definitions": [],
        "traditional": ""
    }

    def clean(text):
        line = re.sub(r"[●◎©]", "", text)
        line = line.replace("基本字义", "")\
                    .replace("基本解释", "")\
                    .replace("汉典", "")\
                    .replace("百度百科", "")
        return re.sub(r"\s+", " ", line).strip()

    def get_pinyin_tone(hanzi: str) -> str:
        py = pinyin(hanzi, style=Style.TONE, heteronym=False)
        return ' '.join([item[0] for item in py])

    def merge_lines_to_paragraphs(lines: list, max_len: int = 100) -> list:
        paragraphs = []
        buffer = ""
        for line in lines:
            line = clean(line)
            if not line:
                continue
            if re.match(r"^【[^】]+】", line):
                if buffer:
                    paragraphs.append(buffer.strip())
                    buffer = ""
                paragraphs.append(line)
            else:
                if len(buffer) + len(line) < max_len:
                    buffer += (" " if buffer else "") + line
                else:
                    if buffer:
                        paragraphs.append(buffer.strip())
                    buffer = line
        if buffer:
            paragraphs.append(buffer.strip())
        return paragraphs

    def extract_readings(def_block):
        readings = []
        spans = def_block.find_all("span", class_="dicpy")
        if spans:
            for span in spans:
                py = span.get_text(strip=True)
                parent = span.find_parent("p")
                defs = []
                if parent:
                    for sib in parent.find_next_siblings("p"):
                        text = sib.get_text()
                        if text:
                            defs.append(text)
                merged_defs = merge_lines_to_paragraphs(defs)
                readings.append({
                    "pinyin": py,
                    "zhuyin": "",
                    "definitions": merged_defs,
                    "audio": ""
                })
        else:   # 若无拼音结构，兜底提取解释文本
            raw_text = def_block.get_text(separator="\n", strip=True)
            lines = raw_text.split("\n")
            merged_defs = merge_lines_to_paragraphs(lines)

            if merged_defs:
                readings.append({
                    "pinyin": get_pinyin_tone(idiom), 
                    "zhuyin": "",
                    "definitions": merged_defs,
                    "audio": ""
                })
        
        return readings

    # 顶部“●”解释结构
    top_dots = extract_multiple_readings_by_dot(soup, idiom)
    if top_dots:
        result["structured_definitions"].append({
            "source": "基本解释",
            "readings": top_dots
        })

    blocks = soup.select("div.content.definitions," \
                         " div.content.knr," \
                         " div.content.swr," \
                         " div.content.jnr," \
                         " div.content.cnr")
    for div in blocks:
        source = div.get("class", [""])[-1]
        readings = extract_readings(div)
        if readings:
            result["structured_definitions"].append({
                "source": source,
                "readings": readings
            })

    # 提取繁体字（简化版）
    z_bt = soup.find("div", class_="z_bt")
    if z_bt:
        match = re.search(r"繁体[:：]?\s*([一-龥]{1,4})", z_bt.get_text())
        if match:
            result["traditional"] = match.group(1)

    return result

def extract_multiple_readings_by_dot(soup, idiom):
    result = []
    all_p_tags = soup.find_all("p")
    idx = 0

    while idx < len(all_p_tags):
        p = all_p_tags[idx]
        text = p.get_text(strip=True)

        if text.startswith("●"):
            idx += 1
            pinyin, zhuyin = "", ""
            defs = []

            while idx < len(all_p_tags):
                cur_text = all_p_tags[idx].get_text(strip=True)
                if not pinyin:
                    py_match = re.search(r"[a-zA-Zāáǎàēéěèīíǐìōóǒòūúǔùǖǘǚǜü]+", cur_text)
                    if py_match:
                        pinyin = py_match.group(0)
                if not zhuyin:
                    zhuyin_match = re.search(r"[ㄅ-ㄩˉˊˇˋ˙]{2,}", cur_text)
                    if zhuyin_match:
                        zhuyin = zhuyin_match.group(0)
                if pinyin and zhuyin:
                    idx += 1
                    break
                idx += 1

            while idx < len(all_p_tags):
                cur_text = all_p_tags[idx].get_text(strip=True)
                if cur_text.startswith("●"):
                    break
                if cur_text:
                    defs.append(cur_text)
                idx += 1

            if pinyin:
                result.append({
                    "pinyin": pinyin,
                    "zhuyin": zhuyin,
                    "definitions": defs,
                    "audio": ""
                })
        else:
            idx += 1

    return result

def extract_recommendations(html: str):
    soup = BeautifulSoup(html, "html.parser")
    related = soup.select("div.nr-box a.usual, div.suggestword a, div.noresult a")
    
    def keep_only_chinese(text: str) -> str:
        return re.sub(r"[^\u4e00-\u9fa5]", "", text)

    return [
        keep_only_chinese(a.get_text(strip=True))
        for a in related if a.get_text(strip=True)
    ]
