# Zdic_Crawler.py
# 优化重构计划概览：
# - 拆分模块：结构提取、抓取控制、代理配置、拼音注册等模块化
# - 精简重复代码，如 fetch/create_session 等
# - 使用类封装全局状态与逻辑
# - 使用类型注解增强可读性与IDE支持
# - 日志与异常统一封装
#
# 本版本已补全以下功能：
# ✅ 测试模式支持（--test）
# ✅ HTML 缓存失败页面保存
# ✅ 推荐词动态加入抓取队列
# ✅ 定时保存 temp_progress.json 断点续跑

import os
import json
import aiohttp
import shutil
import logging
import asyncio
import random
import argparse
import tempfile
import time
from pathlib import Path
from typing import List, Dict, Any, Tuple, Set
from aiohttp_socks import ProxyConnector
from bs4 import BeautifulSoup
from collections import defaultdict, deque
from pypinyin import pinyin, Style
import unicodedata
import nest_asyncio
import traceback
import re
from tqdm import tqdm

from utils.proxy import ProxyManager
# from utils.session import create_session
from utils.extract import extract_idiom_info, extract_recommendations
from utils.pinyin_index import PinyinIndex
from utils.io_utils import save_json_atomic, init_logger
from utils.session_manager import SessionManager

MAX_SUGGEST_DEPTH = 2

def clean_recommendation(raw: str) -> str:
    """去除推荐词中的拼音信息，仅保留汉字部分"""
    return re.sub(r"[a-zA-Zāáǎàēéěèīíǐìōóǒòūúǔùüǖǘǚǜ\s]+$", "", raw).strip()

class ZdicCrawler:
    def __init__(self, args):
        self.args = args
        self.output_dir = Path("output_package")
        self.failures_file = self.output_dir / "Items_failures_final_async.txt"
        self.pinyin_index = PinyinIndex(self.output_dir / "PINYIN_DICT.json")
        self.proxy_manager = ProxyManager(args.proxy_mode)
        self.session_manager = SessionManager(self.proxy_manager)
        self.updated_idioms: Dict[str, Any] = {}
        self.failed: List[Tuple[str, str]] = []
        self.queue = deque()
        self.concurrency_limit = 30
        self.last_save_time = time.time()
        self.test_limit = getattr(args, "test", None)
        self.update_counter = 0
        self.last_saved_count = 0
        self.html_buffer = {}  # word -> html_content
        self.force_flush_interval = 1200  # 每 60 秒批量写盘
        self.html_batch_limit = 500   # 或每 100 条强制写盘
        self.seen_words: Set[str] = set()

    async def run(self):
        self.output_dir.mkdir(parents=True, exist_ok=True)
        init_logger(self.output_dir / "crawl_log.txt")
        self._load_data()
        semaphore = asyncio.Semaphore(self.concurrency_limit)
        await self.session_manager.init()

        try:
            counter = 0
            if self.test_limit:
                logging.info(f"🧪 测试模式启用，仅处理前 {self.test_limit} 项")
                self.queue = deque(list(self.queue)[:self.test_limit])

            progress = tqdm(total=len(self.queue), desc="📘 正在抓取词条")
            while self.queue:
                idiom_obj = self.queue.popleft()
                await self._process_idiom(idiom_obj, counter, semaphore)
                self.session_manager.maybe_rotate_identity()

                await asyncio.sleep(random.uniform(0.1, 0.6))
                counter += 1
                progress.update(1)

                if time.time() - self.last_save_time >= self.force_flush_interval or len(self.html_buffer) >= self.html_batch_limit:
                    self._flush_html_buffer()
                    if self.update_counter > self.last_saved_count:
                        save_json_atomic(self.output_dir / "temp_progress.json", self.updated_idioms)
                        self._finalize()
                        logging.info("📝 定时保存中间抓取进度")
                        self.last_saved_count = self.update_counter
                    progress.total = progress.n + len(self.queue)
                    progress.refresh()
                    self.session_manager._rotate_identity()
                    self.last_save_time = time.time()
            progress.close()
        finally:
            await self.session_manager.close()
        self._finalize()

    def _load_data(self):
        (self.output_dir / "failures_html").mkdir(exist_ok=True)
        (self.output_dir / "all_pages").mkdir(exist_ok=True)

        temp_path = self.output_dir / "temp_progress.json"
        if temp_path.exists():
            self.updated_idioms = json.loads(temp_path.read_text(encoding="utf-8"))
            finished = set(self.updated_idioms.keys()) | set(v.get("word") for v in self.updated_idioms.values())
            for path in self.args.input:
                items = json.loads(Path(path).read_text(encoding="utf-8"))
                for item in items:
                    word = item.get("word") or item.get("simplified")
                    if word and word not in finished:
                        self.queue.append({"word": word, "depth": 0})
        else:
            try:
                for path in self.args.input:
                    items = json.loads(Path(path).read_text(encoding="utf-8"))
                    for item in items:
                        word = item.get("word") or item.get("simplified")
                        if word and word not in self.updated_idioms:
                            self.queue.append({"word": word, "depth": 0})
            except (json.JSONDecodeError, FileNotFoundError) as e:
                logging.error(f"❌ 加载输入文件失败：{e}")
                raise

        # 初始化 seen_words 用于推荐词快速去重
        self.seen_words.update(self.updated_idioms.keys())
        self.seen_words.update(item.get("word") for item in self.queue)
        self.seen_words.update(word for word, _ in self.failed)

        if self.args.test:
            logging.info(f"🧪 测试模式启用，仅处理前 {self.args.test} 条")
            self.queue = deque(list(self.queue)[:self.args.test])

        if self.args.retry_failed:
            self.queue.clear()
            with open(self.failures_file, "r", encoding="utf-8") as f:
                for line in f:
                    word = line.strip().split("\t")[0]
                    if word:
                        self.queue.append({"word": word, "depth": 0})
            return

    def _flush_html_buffer(self):
        for word, html in self.html_buffer.items():
            html_path = self.output_dir / "all_pages" / f"{word}.html"
            try:
                with open(html_path, "w", encoding="utf-8") as f:
                    f.write(html)
            except Exception as e:
                logging.error(f"❌ 批量保存 HTML 失败：{word} | {e}")
        self.html_buffer.clear()

    async def _process_idiom(self, idiom_obj: dict, idx: int, semaphore: asyncio.Semaphore):
        word = idiom_obj.get("word")
        depth = idiom_obj.get("depth", 0)
        if re.search(r"[a-zA-Z0-9Ａ-Ｚａ-ｚ０-９@#$%^&*_=+<>~`|\\{}[\]]", word):
            logging.info(f"⛔ 非法词条，跳过：{word}")
            return
        if depth > MAX_SUGGEST_DEPTH:
            logging.info(f"🛑 推荐词超过最大抓取深度：{word}")
            return
        url = f"https://www.zdic.net/hans/{word}"
        html_path = self.output_dir / "all_pages" / f"{word}.html"
        html = html_path.read_text(encoding="utf-8") if html_path.exists() else await self.session_manager.fetch(url, semaphore)
        if not html:
            self.failed.append((word, "请求失败"))
            return
        
        if not html_path.exists():
            self.html_buffer[word] = html

        info = extract_idiom_info(html, word)
        if not info["structured_definitions"]:
            self.failed.append((word, "结构提取失败"))
            self.updated_idioms[str(idx)] = {"word": word, "note": "结构提取失败"}
            self.updated_idioms[str(idx)] = {
                "word": word,
                "note": "结构提取失败",
                "structured_definitions": []  # 👈 显式空结构
            }
            fail_html_path = self.output_dir / "failures_html" / f"{word}.html"
            with open(fail_html_path, "w", encoding="utf-8") as f:
                f.write(html)

            recommendations = extract_recommendations(html)
            for rec in recommendations:
                clean_rec = clean_recommendation(rec)
                if clean_rec and clean_rec not in self.seen_words:
                    self.queue.append({"word": clean_rec, "depth": idiom_obj.get("depth", 0) + 1})
                    self.seen_words.add(clean_rec)
                    logging.debug(f"🔁 推荐词加入抓取队列：{clean_rec}")
            return

        idiom_obj.update(info)
        self.updated_idioms[word] = idiom_obj
        self.seen_words.add(word)
        self.pinyin_index.register(word, info["structured_definitions"])
        self.update_counter += 1


    def _finalize(self):
        # 👉 只导出成功结构化的词条
        filtered = {
            k: v for k, v in self.updated_idioms.items()
            if "structured_definitions" in v and v["structured_definitions"]
        }
        save_json_atomic(self.output_dir / self.args.output, filtered)

        self.pinyin_index.save()

        if self.failed:
            with open(self.failures_file, "w", encoding="utf-8") as f:
                for word, reason in self.failed:
                    f.write(f"{word}\t{reason}\n")

        shutil.make_archive(str(self.output_dir / "Dictionary_crawl_results"), 'zip', str(self.output_dir))

        if self.args.force_reparse:
            self.pinyin_index.reparse_all_html(self.output_dir / "all_pages")
            self.pinyin_index.save()


def parse_args():
    parser = argparse.ArgumentParser(description="Zdic Async Idiom Crawler")
    parser.add_argument(
        "--input",
        nargs='+',
        default=["idiom.json", "ci.json", "word.json"],
        # default=["Lost_word.json"],
        help="一个或多个 JSON 输入文件"
    )
    parser.add_argument(
        "--output",
        default="Chineses_dictionary.json",
        help="输出 JSON 文件名"
    )
    parser.add_argument(
        "--retry_failed",
        #default=True, #is just retry failed only, set to True
        action="store_true",
        help="仅重新抓取失败词条"
    )
    parser.add_argument(
        "--proxy_mode",
        choices=["none", "auto", "local", "api"],
        default="none",
        help="代理模式：none 不使用代理，local 使用本地 SOCKS5，api 动态获取"
    )
    parser.add_argument(
        "--test",
        #default=TESTITEMS_NUMBER, 
        default=None,
        type=int,
        help="测试模式，仅抓取前 N 条"
    )
    parser.add_argument(
        "--force_reparse",
        action="store_true",
        help="强制重新解析 HTML 并生成拼音索引"
    )
    return parser.parse_args()


if __name__ == "__main__":
    try:
        import nest_asyncio
        nest_asyncio.apply()

        args = parse_args()
        crawler = ZdicCrawler(args)

        loop = asyncio.get_event_loop()
        loop.run_until_complete(crawler.run())

    except KeyboardInterrupt:
        print("🛑 用户中断了程序运行（KeyboardInterrupt）")
    except Exception as e:
        traceback.print_exc()
        print(f"❌ 程序发生异常：{e}")
