# utils/porxy.py

import json
import random
import logging


import json
import time
import random
import logging
import requests
from typing import Optional


class ProxyManager:
    def __init__(
        self,
        mode: str = "none",
        local_source: str = "proxies.json",
        max_failures: int = 3,
        refresh_interval: int = 1200,
        api_url: str = "https://yourproxyapi.com/api/get"  # 可自定义 API
    ):
        self.mode = mode
        self.local_source = local_source
        self.max_failures = max_failures
        self.refresh_interval = refresh_interval
        self.api_url = api_url

        self.proxies = []
        self.fail_counts = {}  # proxy -> int
        self.last_refresh = 0

        if mode == "local":
            self._refresh_local_proxies(force=True)

    def _refresh_local_proxies(self, force=False):
        if not force and (time.time() - self.last_refresh < self.refresh_interval):
            return
        try:
            with open(self.local_source, "r", encoding="utf-8") as f:
                raw = json.load(f)
                self.proxies = raw.get("http", [])
                self.fail_counts = {p: 0 for p in self.proxies}
                self.last_refresh = time.time()
                logging.debug(f"🔄 本地代理列表已刷新，共 {len(self.proxies)} 个")
        except Exception as e:
            logging.warning(f"⚠️ 无法加载本地代理文件 {self.local_source}：{e}")
            self.proxies = []

    def _get_valid_local_proxy(self) -> Optional[str]:
        self._refresh_local_proxies()
        valid = [p for p in self.proxies if self.fail_counts.get(p, 0) < self.max_failures]
        return random.choice(valid) if valid else None

    def _fetch_from_api(self) -> Optional[str]:
        try:
            res = requests.get(self.api_url, timeout=5)
            if res.status_code == 200:
                proxy = res.text.strip()
                logging.debug(f"🌐 动态代理拉取成功：{proxy}")
                return proxy
            else:
                logging.warning(f"⚠️ 动态代理 API 状态码异常：{res.status_code}")
        except Exception as e:
            logging.warning(f"❌ 动态代理获取失败：{e}")
        return None

    def get_proxy(self) -> Optional[str]:
        if self.mode == "none":
            return None
        elif self.mode == "local":
            return self._get_valid_local_proxy()
        elif self.mode == "api":
            return self._fetch_from_api()
        else:
            logging.warning(f"⚠️ 未知代理模式：{self.mode}")
            return None

    def report_failure(self, proxy: str):
        if self.mode == "local" and proxy in self.fail_counts:
            self.fail_counts[proxy] += 1
            if self.fail_counts[proxy] >= self.max_failures:
                logging.warning(f"🚫 代理淘汰：{proxy}")
        elif self.mode == "api":
            logging.info(f"⚠️ 动态代理失败记录（无淘汰机制）：{proxy}")
