import pytest
from utils.proxy import ProxyManager


def test_proxy_local_list_loading(monkeypatch, tmp_path):
    proxies_file = tmp_path / "proxies.json"
    proxies_file.write_text('{"http": ["127.0.0.1:1080", "127.0.0.2:1080"]}', encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    pm = ProxyManager("local")
    assert len(pm.proxies) == 2
    assert pm.get_proxy() in pm.proxies
