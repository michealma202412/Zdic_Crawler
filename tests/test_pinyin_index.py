from utils.pinyin_index import PinyinIndex
from pathlib import Path


def test_pinyin_index_register(tmp_path):
    path = tmp_path / "PINYIN_DICT.json"
    pi = PinyinIndex(path)
    pi.register("爱国", [{"readings": [{"pinyin": "ài guó"}]}])
    pi.save()

    assert "aiguo" in pi.data
    assert "爱国" in pi.data["aiguo"]
    assert path.exists()
