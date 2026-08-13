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
    sync.sync_bridge_unicard_selections()
    sync.sync_bridge_uniopen_visit_spots()

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

def get_rewards_configs_table(
    banks: Optional[List[str]] = None,
    cards: Optional[List[str]] = None,
    payments: Optional[List[str]] = None,
    time_window: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    location: Optional[Union[str, List[str]]] = None,
    enable_billing_validation: bool = True,
    limit_by_card_start: bool = False
) -> dict:
    """從多個 RewardsConfigs_{bank}.db 提取回饋配置，並將其合併為單一配置字典返回"""
    if not banks:
        banks = list(const.BANK_REWARDS_DB_MAP.keys())
    
    logger.info(f"🔑 開始從分庫載入回饋配置，銀行清單: {banks}")
    
    rules_list, base_list, camp_list = [], [], []
    cards_list, cube_list, unicard_list = [], [], []
    uniopen_list, billing_list = [], []
    
    for bank in banks:
        db_path = const.BANK_REWARDS_DB_MAP.get(bank)
        if not db_path or not os.path.exists(db_path):
            continue
            
        try:
            with sqlite3.connect(db_path) as conn:
                for table, target_list in [
                    ("bridge_reward_rules", rules_list),
                    ("dim_card_rewards_base", base_list),
                    ("dim_card_rewards_campaigns", camp_list),
                    ("dim_cards", cards_list),
                    ("bridge_cube_selections", cube_list),
                    ("bridge_unicard_selections", unicard_list),
                    ("bridge_uniopen_visit_spots", uniopen_list),
                    ("dim_billing_history", billing_list)
                ]:
                    try:
                        df = pd.read_sql_query(f"SELECT * FROM {table}", conn)
                        if not df.empty:
                            target_list.append(df)
                    except Exception:
                        pass
        except Exception as e:
            logger.error(f"❌ 讀取銀行 [{bank}] 配置失敗: {e}")

    def concat_and_clean(df_list, table_name):
        if not df_list:
            return pd.DataFrame()
        df_concat = pd.concat(df_list, ignore_index=True).drop_duplicates().reset_index(drop=True)
        return SchemaEnforcer.enforce(df_concat)

    return {
        'reward_rules': concat_and_clean(rules_list, 'bridge_reward_rules'),
        'rewards_base': concat_and_clean(base_list, 'dim_card_rewards_base'),
        'rewards_campaigns': concat_and_clean(camp_list, 'dim_card_rewards_campaigns'),
        'dim_cards': concat_and_clean(cards_list, 'dim_cards'),
        'bridge_cube_selections': concat_and_clean(cube_list, 'bridge_cube_selections'),
        'bridge_unicard_selections': concat_and_clean(unicard_list, 'bridge_unicard_selections'),
        'bridge_uniopen_visit_spots': concat_and_clean(uniopen_list, 'bridge_uniopen_visit_spots'),
        'dim_billing_history': concat_and_clean(billing_list, 'dim_billing_history')
    }
