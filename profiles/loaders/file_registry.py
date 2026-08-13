import os
import json
import hashlib
import sqlite3
import logging
from datetime import datetime
from typing import Optional, Dict, Any

import const

logger = logging.getLogger(__name__)

class FileRegistryManager:
    """
    帳單檔案重複性檢查與登記管理器 (SHA-256 Ingestion Registry)
    
    支援雙重持久化：
    1. JSON 檔 (ingested_files.json) - 採用 Atomic Write (臨時檔 + replace)
    2. SQLite 資料表 (sys_bill_file_registry) - 於 TransactionsBills.db 中備份
    """

    TABLE_NAME = "sys_bill_file_registry"

    def __init__(self, db_path: Optional[str] = None, json_path: Optional[str] = None):
        self.db_path = db_path or const.DB_PATH
        
        # 決定 JSON 存檔路徑 (優先放在 Profile 目錄，否則降級置於 Output 目錄)
        if json_path:
            self.json_path = json_path
        elif hasattr(const, 'ACTIVE_PROFILE_DIR') and os.path.exists(const.ACTIVE_PROFILE_DIR):
            self.json_path = os.path.join(const.ACTIVE_PROFILE_DIR, 'ingested_files.json')
        else:
            self.json_path = os.path.join(const.OUTPUT_DIR, 'ingested_files.json')

        self.registry_data: Dict[str, Dict[str, Any]] = {}
        
        # 初始化 DB 與載入既有 JSON 紀錄
        self._init_db_table()
        self._load_json_registry()

    @staticmethod
    def calculate_file_hash(filepath: str, chunk_size: int = 65536) -> str:
        """
        分塊計算檔案 SHA-256 雜湊值
        """
        sha256 = hashlib.sha256()
        with open(filepath, 'rb') as f:
            while chunk := f.read(chunk_size):
                sha256.update(chunk)
        return sha256.hexdigest()

    def _init_db_table(self):
        """
        於 SQLite 資料庫中建立 sys_bill_file_registry 資料表 (若不存在)
        """
        try:
            db_dir = os.path.dirname(self.db_path)
            if db_dir:
                os.makedirs(db_dir, exist_ok=True)

            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(f"""
                    CREATE TABLE IF NOT EXISTS {self.TABLE_NAME} (
                        file_hash TEXT PRIMARY KEY,
                        filename TEXT NOT NULL,
                        file_size INTEGER NOT NULL,
                        bank_id TEXT,
                        parsed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        record_count INTEGER DEFAULT 0,
                        status TEXT NOT NULL
                    )
                """)
                conn.commit()
        except Exception as e:
            logger.error(f"❌ 初始化檔案登記資料庫表失敗: {e}")

    def _load_json_registry(self):
        """
        從 JSON 檔載入既有 Hash 登記表
        """
        if os.path.exists(self.json_path):
            try:
                with open(self.json_path, 'r', encoding='utf-8') as f:
                    self.registry_data = json.load(f)
            except Exception as e:
                logger.warning(f"⚠️ 載入 ingested_files.json 失敗 ({e})，將初始化空登記表。")
                self.registry_data = {}
        else:
            self.registry_data = {}

    def _save_json_registry(self):
        """
        採用 Atomic Write (安全原子寫入) 存檔 ingested_files.json
        """
        dir_name = os.path.dirname(self.json_path)
        if dir_name:
            os.makedirs(dir_name, exist_ok=True)
            
        tmp_path = f"{self.json_path}.tmp"
        try:
            with open(tmp_path, 'w', encoding='utf-8') as f:
                json.dump(self.registry_data, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, self.json_path)
        except Exception as e:
            logger.error(f"❌ 寫入 ingested_files.json 失敗: {e}")
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass

    def is_ingested(self, file_hash_or_path: str) -> bool:
        """
        檢查 Hash 值或檔案是否已經解析過且 status == 'SUCCESS'
        """
        file_hash = file_hash_or_path
        if os.path.exists(file_hash_or_path):
            file_hash = self.calculate_file_hash(file_hash_or_path)

        # 1. 先查記憶體/JSON 紀錄
        if file_hash in self.registry_data:
            return self.registry_data[file_hash].get("status") == "SUCCESS"
            
        # 2. 查 SQLite DB 紀錄 (防護降級)
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(f"SELECT status FROM {self.TABLE_NAME} WHERE file_hash = ?", (file_hash,))
                row = cursor.fetchone()
                if row and row[0] == "SUCCESS":
                    return True
        except Exception as e:
            logger.warning(f"⚠️ 查詢 SQLite 檔案登記表失敗: {e}")

        return False

    def is_file_ingested(self, filepath_or_hash: str) -> bool:
        """相容別名介面"""
        return self.is_ingested(filepath_or_hash)

    def register_file(
        self,
        file_hash: str,
        filename: str,
        file_size: int,
        bank_id: Optional[str] = None,
        record_count: int = 0,
        status: str = "SUCCESS"
    ) -> str:
        """
        將已計算 Hash 的檔案紀錄登記至 JSON 與 DB 雙層持久化庫中
        """
        now_iso = datetime.now().isoformat()

        record = {
            "filename": filename,
            "file_size": file_size,
            "bank_id": bank_id or "unknown",
            "parsed_at": now_iso,
            "record_count": record_count,
            "status": status
        }

        # 1. 更新記憶體與 JSON
        self.registry_data[file_hash] = record
        self._save_json_registry()

        # 2. 更新 SQLite DB (REPLACE INTO)
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(f"""
                    REPLACE INTO {self.TABLE_NAME} 
                    (file_hash, filename, file_size, bank_id, parsed_at, record_count, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (file_hash, filename, file_size, bank_id or "unknown", now_iso, record_count, status))
                conn.commit()
                logger.info(f"📝 檔案解析登記成功 [{bank_id}]: {filename} (Hash: {file_hash[:8]}...)")
        except Exception as e:
            logger.error(f"❌ 登記檔案至 SQLite 失敗: {e}")

        return file_hash

    def register_ingestion(
        self, 
        filepath: str, 
        bank_id: Optional[str] = None, 
        record_count: int = 0, 
        status: str = "SUCCESS"
    ) -> str:
        """
        相容傳入 filepath 的舊版介面
        """
        if not os.path.exists(filepath):
            raise FileNotFoundError(f"無法登記不存在的檔案: {filepath}")

        file_hash = self.calculate_file_hash(filepath)
        filename = os.path.basename(filepath)
        file_size = os.path.getsize(filepath)
        return self.register_file(
            file_hash=file_hash,
            filename=filename,
            file_size=file_size,
            bank_id=bank_id,
            record_count=record_count,
            status=status
        )
