# profiles/profiles_api.py
"""
Profiles / Config 模組統一對外調度介面 (Service-Level Dispatcher / Facade API)
提供獨立且高內聚的設定檔同步 (ConfigSyncManager)、維度表過濾 (ConfigFilter) 與規則表格載入
"""
import os
import logging
import pandas as pd
from typing import Optional, List, Union, Dict, Any
import sqlite3

import const
from .loaders.sync_configs_to_db import ConfigSyncManager
from .loaders.config_loader import ConfigFilter
from database.loaders.schema_enforcer import SchemaEnforcer

logger = logging.getLogger(__name__)

def _get_sync_manager() -> ConfigSyncManager:
    """自動判定 DB Backend 並回傳 ConfigSyncManager 實體"""
    db_backend = os.getenv('DB_BACKEND', 'postgres' if getattr(const, 'PG_HOST', None) else 'sqlite')
    return ConfigSyncManager(db_backend=db_backend)

def run_config_card_sync():
    """信用卡資料同步服務"""
    _get_sync_manager().sync_cards()

def run_config_reward_sync():
    """回饋計畫與規則同步服務"""
    sync = _get_sync_manager()
    sync.sync_reward_base()
    sync.sync_reward_campaigns()
    sync.sync_reward_rules()
    sync.sync_bridge_cube_selections()

    sync.sync_reward_linked_lists()
    sync.sync_reward_pools()

def run_config_merchant_sync():
    """特約商店資料同步服務"""
    _get_sync_manager().sync_merchants()

def run_config_ec_platform_sync():
    """電商平台資料同步服務"""
    _get_sync_manager().sync_ec_platforms()

def run_config_paygate_sync():
    """支付平台資料同步服務"""
    _get_sync_manager().sync_payment_processes()

def run_all_config_sync():
    """全量設定同步服務"""
    _get_sync_manager().sync_all()

def run_config_billing_history_sync():
    """對帳單歷史資料同步服務"""
    _get_sync_manager().sync_dim_billing_history()

def run_config_fx_table_sync():
    """匯率每日表同步服務"""
    _get_sync_manager().sync_dim_fx_table()

def get_analyzable_data(db_path: Optional[str] = None) -> dict:
    """取得系統中可供前端篩選分析的維度資料 (來自 ConfigFilter)"""
    return ConfigFilter.get_analyzable_data(db_path=db_path)

