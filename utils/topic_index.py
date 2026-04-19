# utils/topic_index.py

import json
from pathlib import Path
from typing import Dict, Set, List
import re
import unicodedata

from utils.io_utils import save_json_atomic

class TopicIndex:
    def __init__(self, path: Path):
        self.path = path
        self.index: Dict[str, Set[str]] = {}
        if path.exists():
            raw = json.loads(path.read_text(encoding="utf-8"))
            self.index = {k: set(v) for k, v in raw.items()}

    def register(self, topic: str, structured_definitions: List[Dict]):
        """注册知识点到主题索引"""
        for block in structured_definitions:
            subject = block.get("source", "").lower()
            if subject:
                self.index.setdefault(subject, set()).add(topic)

    def save(self):
        serializable = {k: list(v) for k, v in self.index.items()}
        save_json_atomic(self.path, serializable)

    def reparse_all_html(self, html_dir: Path):
        """重新解析所有 HTML 文件并更新索引"""
        from utils.extract import extract_sat_topic_info
        for file in html_dir.glob("*.html"):
            topic = file.stem
            html = file.read_text(encoding="utf-8")
            info = extract_sat_topic_info(html, topic)
            self.register(topic, info.get("structured_definitions", []))