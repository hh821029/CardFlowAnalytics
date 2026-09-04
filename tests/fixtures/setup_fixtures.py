"""
產生測試用脫敏帳單樣本檔案 (直接複用 generate_mock_data 確保與 example_public 完全一致)
"""
import os
import sys

# 確保專案根目錄可被引用
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from typing import Dict
from generate_mock_data import generate_mock_data

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "bills")

def create_mock_fixtures(target_dir: str = FIXTURES_DIR) -> Dict[str, str]:
    """
    在指定目錄產生與 example_public 完全一致的脫敏帳單檔案 (SSOT 原制)
    """
    return generate_mock_data(mock_dir=target_dir)

if __name__ == "__main__":
    paths = create_mock_fixtures()
    print("Fixtures created (aligned with example_public):", paths)
