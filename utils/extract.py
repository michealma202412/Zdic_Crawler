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


def extract_recommendations(html: str):
    """从页面中提取推荐词或链接文本。"""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    recommendations = []

    for elem in soup.select('.nr-box a, .recommendation a, a.usual'):
        text = elem.get_text(strip=True)
        if text and text not in recommendations:
            recommendations.append(text)

    return recommendations


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

def extract_sat_topic_info(html: str, topic: str):
    """提取 Khan Academy SAT 知识点信息"""
    soup = BeautifulSoup(html, "html.parser")
    result = {
        "structured_definitions": [],
        "related_topics": []
    }

    # Khan Academy 页面结构分析
    # 1. 页面标题
    title_elem = soup.select_one('h1, ._1b7ozl9, [data-testid="unit-title"], [data-testid="lesson-title"]')
    if not title_elem:
        title_elem = soup.select_one('.title, ._o6nj3i, ._1l1qzyl')
    title = title_elem.get_text(strip=True) if title_elem else topic

    # 2. 学习目标/描述
    description = ""
    desc_elem = soup.select_one('.topic-summary, .description, p:first-of-type')
    if desc_elem:
        description = desc_elem.get_text(strip=True)
    else:
        # 查找页面中的主要段落
        main_content = soup.select_one('main, [role="main"], ._w5j2sk')
        if main_content:
            paragraphs = main_content.select('p')
            if paragraphs:
                description = paragraphs[0].get_text(strip=True)[:500]  # 限制长度

    # 3. 关键点/学习目标
    key_points = []
    
    # 查找学习目标列表
    objectives = soup.select('.learning-objective, .learning-objectives li, ._1q8g1c4')
    for obj in objectives[:10]:
        text = obj.get_text(strip=True)
        if text and len(text) > 10:
            key_points.append(text)
    
    # 如果没有找到学习目标，查找技能列表
    if not key_points:
        skills = soup.select('.skill, [data-testid*="skill"], ._1k8e8d2')
        for skill in skills[:10]:
            text = skill.get_text(strip=True)
            if text:
                key_points.append(text)

    # 4. 相关主题/课程
    related_links = soup.select('a[href*="/test-prep/sat/"], [data-testid*="related"] a, ._1q8g1c4 a')
    for link in related_links:
        href = link.get('href', '')
        text = link.get_text(strip=True)
        if text and len(text) > 3 and '/test-prep/sat/' in href:
            # 提取主题名称
            clean_text = re.sub(r'^(Learn|Practice|Quiz|Test|Skill):\s*', '', text, flags=re.IGNORECASE)
            if clean_text not in result["related_topics"]:
                result["related_topics"].append(clean_text)

    # 5. 构建结构化定义
    if title or description or key_points:
        result["structured_definitions"].append({
            "source": "Khan Academy SAT",
            "readings": [
                {
                    "title": title,
                    "summary": description,
                    "details": key_points,
                    "examples": []
                }
            ]
        })

    return result

def extract_related_topics(html: str):
    """提取相关 SAT 知识点"""
    soup = BeautifulSoup(html, "html.parser")
    related = soup.select("a[href*='topic'], a[href*='lesson'], .related-topics a, .next-lesson a")

    def clean_topic_text(text: str) -> str:
        """清理知识点文本，移除多余字符"""
        text = text.strip()
        # 移除常见的前缀
        text = re.sub(r"^(Learn|Practice|Quiz|Test):\s*", "", text, flags=re.IGNORECASE)
        return text

    return [
        clean_topic_text(a.get_text(strip=True))
        for a in related if a.get_text(strip=True) and len(a.get_text(strip=True)) > 3
    ]
