# conftest.py
import sys
import os

# 確保專案根目錄在所有測試執行前自動加入 sys.path
ROOT_DIR = os.path.abspath(os.path.dirname(__file__))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)
