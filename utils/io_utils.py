# utils/io_utils.py

import os
import json
import tempfile
import logging
from pathlib import Path


def save_json_atomic(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".tmp", dir=str(path.parent))
    with os.fdopen(tmp_fd, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, path)


def init_logger(log_file_path: Path):
    if not logging.getLogger().handlers:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s [%(levelname)s] %(message)s",
            handlers=[
                logging.FileHandler(str(log_file_path), mode='w', encoding="utf-8"),
                logging.StreamHandler()
            ]
        )
