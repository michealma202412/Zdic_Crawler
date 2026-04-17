from utils.io_utils import save_json_atomic, init_logger
from pathlib import Path
import logging


def test_save_json_atomic(tmp_path):
    path = tmp_path / "data.json"
    save_json_atomic(path, {"key": "value"})
    assert path.exists()
    assert path.read_text(encoding="utf-8").startswith("{")

def test_init_logger(tmp_path):
    log_path = tmp_path / "test.log"
    init_logger(log_path)
    logger = logging.getLogger()
    logger.info("test message")
    assert logger.handlers
