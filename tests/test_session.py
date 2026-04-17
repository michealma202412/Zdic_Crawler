import pytest
import asyncio
from utils.proxy import ProxyManager
from utils.session import create_session


@pytest.mark.asyncio
async def test_create_session_none_mode():
    pm = ProxyManager("none")
    session, headers, proxy = await create_session(pm)
    assert session is not None
    assert proxy is None
    await session.close()
