# database/database_api.py
"""
Database 模組統一對外調度介面 (Service-Level Dispatcher / Facade API)
提供獨立且高內聚的 DBReader (讀取抽象)、get_db_loader (寫入/Upsert 工廠)、SchemaEnforcer (型別執法) 與 交易資料庫查詢 (transaction_query)
"""
from .loaders.db_reader import DBReader
from .loaders.db_factory import get_db_loader
from .loaders.schema_enforcer import SchemaEnforcer
from .transaction_query import get_transactions, query_transactions_modular

__all__ = [
    'DBReader',
    'get_db_loader',
    'SchemaEnforcer',
    'get_transactions',
    'query_transactions_modular'
]
