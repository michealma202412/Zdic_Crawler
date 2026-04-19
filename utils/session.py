# utils/session.py

from typing import Tuple, Optional
from .session_manager import SessionManager
from aiohttp import ClientSession

async def create_session(proxy_manager) -> Tuple[ClientSession, dict, Optional[str]]:
    """创建并返回 aiohttp 会话、请求头和代理地址。"""
    manager = SessionManager(proxy_manager)
    await manager.init()
    return manager.session, manager.headers, manager.proxy_url
