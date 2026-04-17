# utils/session_manager.py

import aiohttp
import random
import logging
import asyncio
from typing import Optional
from aiohttp_socks import ProxyConnector
from .proxy import ProxyManager

UA_LIST = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 Version/15.1 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/91.0.4472.114 Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 14_0 like Mac OS X) AppleWebKit/605.1.15 Version/14.0 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Linux; Android 10; SM-G975F) AppleWebKit/537.36 Chrome/83.0.4103.106 Mobile Safari/537.36",
    "Mozilla/5.0 (iPad; CPU OS 13_2 like Mac OS X) AppleWebKit/605.1.15 Version/13.0 Mobile/15E148 Safari/604.1",
]

REFERER_POOL = [
    "https://www.zdic.net/",
    "https://www.baidu.com/s?wd=zdic",
    "https://cn.bing.com/search?q=zdic",
    "https://zh.wikipedia.org/wiki/Zdic.net",
    "https://tieba.baidu.com/f?kw=汉典",
    "https://zh.moegirl.org.cn/Zdic",
]

class SessionManager:
    def __init__(self, proxy_manager: ProxyManager):
        self.proxy_manager = proxy_manager
        self.session = None
        self.headers = {}
        self.proxy_url = None
        self.identity_counter = 0
        self.identity_cycle = 50
        self.failure_count = 0
        self.failure_threshold = 3
        self.last_ua = None

    async def init(self):
        self._rotate_identity()
        proxy = self.proxy_manager.get_proxy()
        if proxy and proxy.startswith("socks5"):
            connector = ProxyConnector.from_url(f"socks5://{proxy}")
            self.session = aiohttp.ClientSession(connector=connector)
            self.proxy_url = None
        else:
            self.session = aiohttp.ClientSession()
            self.proxy_url = f"http://{proxy}" if proxy else None

    def _rotate_identity(self):
        ua = random.choice([ua for ua in UA_LIST if ua != self.last_ua])
        self.last_ua = ua
        self.headers = {
            "User-Agent": ua,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Referer": random.choice(REFERER_POOL),
            # "Cookie": f"zdic_session={random.randint(100000, 999999)}",
            "Accept-Encoding": "gzip, deflate",
            "Connection": "keep-alive",
        }

        if self.proxy_manager.mode == "api":
            proxy = self.proxy_manager.get_proxy()
            self.proxy_url = f"http://{proxy}" if proxy else None

        logging.debug(f"🔄 新 UA: {self.headers['User-Agent']}")
        logging.debug(f"🔄 新 Referer: {self.headers['Referer']}")


    def maybe_rotate_identity(self):
        self.identity_counter += 1
        if self.identity_counter >= self.identity_cycle:
            self._rotate_identity()
            self.identity_counter = 0

    async def fetch(self, url, semaphore: asyncio.Semaphore, retries=3, timeout=10) -> Optional[str]:
        async with semaphore:
            for attempt in range(retries):
                try:
                    async with self.session.get(url, headers=self.headers, proxy=self.proxy_url, timeout=timeout) as resp:
                        if resp.status == 200:
                            self.failure_count = 0
                            return await resp.text()
                        else:
                            logging.warning(f"⚠️ 状态码异常 {resp.status}：{url}")
                except Exception as e:
                    logging.warning(f"⚠️ 第 {attempt+1} 次请求失败：{url} | {e}")
                    await asyncio.sleep(0.2 *(1 + attempt))
                    if self.proxy_url:
                        self.proxy_manager.report_failure(self.proxy_url.replace("http://", "").replace("socks5://", ""))
                    self.failure_count += 1

                if self.failure_count >= self.failure_threshold:
                    logging.warning("🔁 连续失败触发身份轮换")
                    self._rotate_identity()
                    self.failure_count = 0
        self.maybe_rotate_identity()
        return None

    async def close(self):
        if self.session:
            await self.session.close()
