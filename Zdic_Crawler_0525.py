# SAT_Crawler.py
# 基于 Zdic Crawler 改造为 SAT 知识点爬虫
# - 移除汉语专用逻辑（拼音、汉字处理）
# - 适配 SAT 知识点结构
# - 保留异步抓取框架和断点续跑机制

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
from typing import List, Dict, Any, Tuple, Set, Optional
from aiohttp_socks import ProxyConnector
from bs4 import BeautifulSoup
from collections import defaultdict, deque
import unicodedata
import nest_asyncio
import traceback
import re
from urllib.parse import quote_plus
from tqdm import tqdm
from playwright.async_api import async_playwright

from utils.proxy import ProxyManager
from utils.extract import extract_sat_topic_info, extract_related_topics
from utils.question_parser import SATQuestionParser
from utils.topic_index import TopicIndex
from utils.ai_tagger import AITagger
from utils.topic_index import TopicIndex  # 重命名后的索引模块
from utils.io_utils import save_json_atomic, init_logger
from utils.session_manager import SessionManager

MAX_SUGGEST_DEPTH = 2

class SATCrawler:
    def __init__(self, args):
        self.args = args
        self.output_dir = Path("output_package")
        self.failures_file = self.output_dir / "Items_failures_final_async.txt"
        self.topic_index = TopicIndex(self.output_dir / "TOPIC_INDEX.json")  # 重命名索引
        self.question_parser = SATQuestionParser()  # SAT 题目解析器
        self.ai_tagger = AITagger()  # AI 自动标注器
        self.questions: List[Dict[str, Any]] = []  # 存储解析的题目
        self.proxy_manager = ProxyManager(args.proxy_mode)
        self.session_manager = SessionManager(self.proxy_manager)
        self.updated_topics: Dict[str, Any] = {}  # 重命名数据存储
        self.failed: List[Tuple[str, str]] = []
        self.queue = deque()
        self.concurrency_limit = 30
        self.last_save_time = time.time()
        self.test_limit = getattr(args, "test", None)
        self.update_counter = 0
        self.last_saved_count = 0
        self.html_buffer = {}  # topic -> html_content
        self.force_flush_interval = 1200  # 每 60 秒批量写盘
        self.html_batch_limit = 500   # 或每 100 条强制写盘
        self.seen_topics: Set[str] = set()  # 重命名去重集合
        self.playwright_browser = None  # Playwright 浏览器实例

    async def init_browser(self):
        """初始化 Playwright 浏览器"""
        if not self.playwright_browser:
            playwright = await async_playwright().start()
            self.playwright_browser = await playwright.chromium.launch(headless=True)
        return self.playwright_browser

    async def fetch_with_playwright(self, url: str) -> str:
        """从本地文件或真实网络获取页面内容。"""
        try:
            if url.startswith('file://'):
                # 处理 Windows 文件路径
                file_path = url.replace('file:///', '').replace('/', '\\')
                with open(file_path, 'r', encoding='utf-8') as f:
                    return f.read()
            else:
                # 使用 session_manager 进行真实 HTTP 请求
                return await self.session_manager.fetch(url, asyncio.Semaphore(1), retries=3, timeout=15) or ""
        except Exception as e:
            logging.error(f"页面请求失败 {url}: {e}")
            return ""

    async def run(self):
        self.output_dir.mkdir(parents=True, exist_ok=True)
        init_logger(self.output_dir / "crawl_log.txt")
        # await self.init_browser()  # 暂时注释掉 Playwright 初始化
        self._load_data()
        semaphore = asyncio.Semaphore(self.concurrency_limit)
        await self.session_manager.init()

        try:
            counter = 0
            if self.test_limit:
                logging.info(f"🧪 测试模式启用，仅处理前 {self.test_limit} 项")
                self.queue = deque(list(self.queue)[:self.test_limit])

            progress = tqdm(total=len(self.queue), desc="📘 正在抓取 SAT 内容")
            while self.queue:
                item = self.queue.popleft()

                if item.get("type") == "question":
                    # 处理题目
                    await self._process_question(item, semaphore)
                else:
                    # 处理知识点
                    await self._process_topic(item, counter, semaphore)

                self.session_manager.maybe_rotate_identity()

                await asyncio.sleep(random.uniform(0.1, 0.6))
                counter += 1
                progress.update(1)

                if time.time() - self.last_save_time >= self.force_flush_interval or len(self.html_buffer) >= self.html_batch_limit:
                    self._flush_html_buffer()
                    if self.update_counter > self.last_saved_count:
                        save_json_atomic(self.output_dir / "temp_progress.json", self.updated_topics)
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
            if self.playwright_browser:
                await self.playwright_browser.close()
        self._finalize()

    def _load_data(self):
        (self.output_dir / "failures_html").mkdir(exist_ok=True)
        (self.output_dir / "all_pages").mkdir(exist_ok=True)

        temp_path = self.output_dir / "temp_progress.json"
        if temp_path.exists():
            self.updated_topics = json.loads(temp_path.read_text(encoding="utf-8"))
            finished = set(self.updated_topics.keys()) | set(v.get("topic") for v in self.updated_topics.values())
            for path in self.args.input:
                items = json.loads(Path(path).read_text(encoding="utf-8"))
                for item in items:
                    if item.get("type") == "question":
                        # 题目项
                        question_id = item.get("question_id")
                        question_url = item.get("question_url")
                        if question_id or question_url:
                            self.queue.append({
                                "question_id": question_id,
                                "question_url": question_url,
                                "type": "question",
                                "depth": 0
                            })
                    else:
                        # 知识点项
                        topic = item.get("topic") or item.get("name") or item.get("skill")
                        if topic and topic not in finished:
                            self.queue.append({"topic": topic, "depth": 0})
        else:
            try:
                for path in self.args.input:
                    items = json.loads(Path(path).read_text(encoding="utf-8"))
                    for item in items:
                        if item.get("type") == "question":
                            # 题目项
                            question_id = item.get("question_id")
                            question_url = item.get("question_url")
                            if question_id or question_url:
                                self.queue.append({
                                    "question_id": question_id,
                                    "question_url": question_url,
                                    "type": "question",
                                    "depth": 0
                                })
                        else:
                            # 知识点项
                            topic = item.get("topic") or item.get("name") or item.get("skill")
                            if topic and topic not in self.updated_topics:
                                self.queue.append({"topic": topic, "depth": 0})
            except (json.JSONDecodeError, FileNotFoundError) as e:
                logging.error(f"❌ 加载输入文件失败：{e}")
                raise

        # 初始化 seen_topics 用于推荐知识点快速去重
        self.seen_topics.update(self.updated_topics.keys())
        self.seen_topics.update(item.get("topic") for item in self.queue if item.get("topic"))
        self.seen_topics.update(item.get("question_id") for item in self.queue if item.get("question_id"))
        self.seen_topics.update(topic for topic, _ in self.failed)

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
        for topic, html in self.html_buffer.items():
            html_path = self.output_dir / "all_pages" / f"{topic}.html"
            try:
                with open(html_path, "w", encoding="utf-8") as f:
                    f.write(html)
            except Exception as e:
                logging.error(f"❌ 批量保存 HTML 失败：{topic} | {e}")
        self.html_buffer.clear()

    async def _process_topic(self, topic_obj: dict, idx: int, semaphore: asyncio.Semaphore):
        topic = topic_obj.get("topic")
        depth = topic_obj.get("depth", 0)
        if depth > MAX_SUGGEST_DEPTH:
            logging.info(f"🛑 推荐知识点超过最大抓取深度：{topic}")
            return
        url = self._build_topic_url(topic)  # 使用通用 URL 构造器
        logging.info(f"🌐 请求 URL: {url}")
        html_path = self.output_dir / "all_pages" / f"{topic}.html"
        html = html_path.read_text(encoding="utf-8") if html_path.exists() else await self.fetch_with_playwright(url)
        if not html:
            logging.error(f"❌ 请求失败: {url}")
            self.failed.append((topic, "请求失败"))
            return

        logging.info(f"📄 HTML 长度: {len(html)} 字符")

        if not html_path.exists():
            self.html_buffer[topic] = html

        info = extract_sat_topic_info(html, topic)
        if not info.get("structured_definitions"):
            self.failed.append((topic, "结构提取失败"))
            self.updated_topics[str(idx)] = {
                "topic": topic,
                "note": "结构提取失败",
                "structured_definitions": []
            }
            fail_html_path = self.output_dir / "failures_html" / f"{topic}.html"
            with open(fail_html_path, "w", encoding="utf-8") as f:
                f.write(html)

            related_topics = extract_related_topics(html)
            for rec in related_topics:
                if rec and rec not in self.seen_topics:
                    self.queue.append({"topic": rec, "depth": topic_obj.get("depth", 0) + 1})
                    self.seen_topics.add(rec)
                    logging.debug(f"🔁 相关知识点加入抓取队列：{rec}")
            return

        topic_obj.update(info)
        self.updated_topics[topic] = topic_obj
        self.seen_topics.add(topic)
        self.topic_index.register(topic, info.get("structured_definitions", []))
        self.update_counter += 1

    async def _process_question(self, item: Dict[str, Any], semaphore: asyncio.Semaphore):
        """处理单个 SAT 题目"""
        question_id = item.get("question_id")
        question_url = item.get("question_url")
        url = self._build_question_url(question_id, question_url)
        logging.info(f"🧩 请求题目 URL: {url}")

        html = await self.fetch_with_playwright(url)
        if not html:
            logging.error(f"❌ 题目请求失败: {url}")
            self.failed.append((question_id or url, "请求失败"))
            return

        logging.info(f"📄 题目 HTML 长度: {len(html)} 字符")

        # 解析题目
        questions = self.question_parser.parse_question_block(html)

        if not questions:
            logging.warning(f"⚠️ 题目解析失败: {question_id}")
            self.failed.append((question_id, "解析失败"))
            fail_html_path = self.output_dir / "failures_html" / f"question_{question_id}.html"
            with open(fail_html_path, "w", encoding="utf-8") as f:
                f.write(html)
            return

        # 保存解析的题目
        for question in questions:
            # 使用 AI 标注器为题目添加知识点标注
            tagged_question = self.ai_tagger.tag_question(question, self.updated_topics)
            self.questions.append(tagged_question)
            logging.info(f"✅ 成功解析并标注题目: {tagged_question.get('id', question_id)} - 知识点: {tagged_question.get('knowledge_points', [])}")

    def _slugify_topic(self, topic: str) -> str:
        """将主题名称转换为 Khan Academy URL slug。"""
        text = topic.strip().lower()
        text = re.sub(r"[\s_]+", "-", text)
        text = re.sub(r"[^a-z0-9\-]", "", text)
        return text.strip("-")

    def _build_topic_url(self, topic: str) -> str:
        """构建 Khan Academy SAT 主题 URL。"""
        topic_text = topic.strip()
        if topic_text.lower().startswith("http"):
            return topic_text
        if topic_text.startswith("//"):
            return "https:" + topic_text
        if "khanacademy.org" in topic_text and not topic_text.lower().startswith("http"):
            return "https://" + topic_text.lstrip("/")

        topic_slug = self._slugify_topic(topic_text)
        if self.args.topic_url_template and "{topic_slug}" in self.args.topic_url_template:
            return self.args.topic_url_template.format(topic_slug=topic_slug, topic=topic_text)

        # 默认使用 Khan Academy SAT 主题页面模板
        if topic_slug:
            return f"https://www.khanacademy.org/test-prep/sat/{topic_slug}"

        # 回退到搜索页面 URL
        return f"https://www.khanacademy.org/search?page_search_query={quote_plus(topic_text)}"

    def _build_question_url(self, question_id: Optional[str], question_url: Optional[str] = None) -> str:
        """College Board SAT 题目 URL 构造器。

        支持：
        - 直接提供 question_url
        - question_id 已经是 URL
        - question_id 为 College Board ID，通过模板构建 URL
        - 缺失模板时自动使用常见 College Board 练习题 URL 格式
        """
        if question_url:
            normalized_url = question_url.strip()
            if normalized_url.startswith("//"):
                normalized_url = "https:" + normalized_url
            return normalized_url

        if question_id:
            normalized_id = question_id.strip()
            if normalized_id.lower().startswith("http"):
                return normalized_id
            if normalized_id.startswith("//"):
                return "https:" + normalized_id
            if "collegeboard.org" in normalized_id and not normalized_id.lower().startswith("http"):
                return "https://" + normalized_id.lstrip("/")

            if self.args.question_url_template and "{question_id}" in self.args.question_url_template:
                return self.args.question_url_template.format(question_id=normalized_id)

            # 如果未提供模板，则使用 College Board 常见实践题 URL 结构
            return f"https://satpractice.collegeboard.org/sat/practice-question/{normalized_id}"

        raise ValueError("缺少 question_id 或 question_url，无法构建题目 URL。请在输入中提供 question_url，或检查 question_id 是否有效。\n"
                         "如果需要，可使用 --question_url_template 指定 URL 模板。")


    def _finalize(self):
        # 只导出成功结构化的知识点
        filtered = {
            k: v for k, v in self.updated_topics.items()
            if "structured_definitions" in v and v["structured_definitions"]
        }
        save_json_atomic(self.output_dir / self.args.output, filtered)
        # 保存题目数据
        if self.questions:
            questions_file = self.output_dir / "sat_questions.json"
            save_json_atomic(questions_file, self.questions)
            logging.info(f"💾 保存了 {len(self.questions)} 道题目到 {questions_file}")

            # 生成题目-知识点映射报告
            mapping_report = self.ai_tagger.build_topic_question_mapping(self.questions, self.updated_topics)
            mapping_file = self.output_dir / "topic_question_mapping.json"
            save_json_atomic(mapping_file, mapping_report)
            logging.info(f"📊 生成题目-知识点映射报告到 {mapping_file}")
        self.topic_index.save()

        if self.failed:
            with open(self.failures_file, "w", encoding="utf-8") as f:
                for topic, reason in self.failed:
                    f.write(f"{topic}\t{reason}\n")

        shutil.make_archive(str(self.output_dir / "SAT_crawl_results"), 'zip', str(self.output_dir))

        if self.args.force_reparse:
            self.topic_index.reparse_all_html(self.output_dir / "all_pages")
            self.topic_index.save()


def parse_args():
    parser = argparse.ArgumentParser(description="SAT Async Topic Crawler")
    parser.add_argument(
        "--input",
        nargs='+',
        default=["sat_topics.json"],
        help="一个或多个 JSON 输入文件"
    )
    parser.add_argument(
        "--output",
        default="SAT_knowledge_base.json",
        help="输出 JSON 文件名"
    )
    parser.add_argument(
        "--retry_failed",
        action="store_true",
        help="仅重新抓取失败知识点"
    )
    parser.add_argument(
        "--proxy_mode",
        choices=["none", "auto", "local", "api"],
        default="none",
        help="代理模式：none 不使用代理，local 使用本地 SOCKS5，api 动态获取"
    )
    parser.add_argument(
        "--topic_url_template",
        default="https://www.khanacademy.org/test-prep/sat/{topic_slug}",
        help="用于构建 Khan Academy 主题 URL 的模板，{topic_slug} 将替换为主题 slug，{topic} 将替换为原始主题名"
    )
    parser.add_argument(
        "--question_url_template",
        default="https://satpractice.collegeboard.org/sat/practice-question/{question_id}",
        help="用于构建 College Board 题目 URL 的模板，{question_id} 将替换为实际题目 ID"
    )
    parser.add_argument(
        "--test",
        default=None,
        type=int,
        help="测试模式，仅抓取前 N 条"
    )
    parser.add_argument(
        "--force_reparse",
        action="store_true",
        help="强制重新解析 HTML 并生成主题索引"
    )
    return parser.parse_args()


if __name__ == "__main__":
    try:
        import nest_asyncio
        nest_asyncio.apply()

        args = parse_args()
        crawler = SATCrawler(args)

        loop = asyncio.get_event_loop()
        loop.run_until_complete(crawler.run())

    except KeyboardInterrupt:
        print("🛑 用户中断了程序运行（KeyboardInterrupt）")
    except Exception as e:
        traceback.print_exc()
        print(f"❌ 程序发生异常：{e}")
