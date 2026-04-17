# utils/pinyin_index.py

import json
from pathlib import Path
from typing import Dict, Set, List
import re
import unicodedata

from utils.io_utils import save_json_atomic  # ✅ 关键导入

def remove_tone_marks(pinyin: str) -> str:
    return ''.join(
        c for c in unicodedata.normalize('NFD', pinyin)
        if unicodedata.category(c) != 'Mn'
    ).lower()


class PinyinIndex:
    def __init__(self, path: Path):
        self.path = path
        self.index: Dict[str, Set[str]] = {}
        if path.exists():
            raw = json.loads(path.read_text(encoding="utf-8"))
            self.index = {k: set(v) for k, v in raw.items()}

    def register(self, word: str, structured_definitions: List[Dict]):
        for block in structured_definitions:
            for reading in block.get("readings", []):
                py = reading.get("pinyin", "").strip()
                if not py:
                    continue
                flat = ''.join(re.findall(r"[a-züv]+", remove_tone_marks(py)))
                if flat:
                    self.index.setdefault(flat, set()).add(word)

    def save(self):
        serializable = {k: list(v) for k, v in self.index.items()}
        save_json_atomic(self.path, serializable)

    def reparse_all_html(self, html_dir: Path):
        from utils.extract import extract_idiom_info
        for file in html_dir.glob("*.html"):
            word = file.stem
            html = file.read_text(encoding="utf-8")
            info = extract_idiom_info(html, word)
            self.register(word, info.get("structured_definitions", []))
