import os
import logging
from typing import Optional, List
import pandas as pd
import const
from profiles.loaders.config_loader import ConfigLoader
from database.loaders.sqlite_loader import SQLiteLoader
from database.loaders.postgres_loader import PostgresLoader
from database.loaders.db_factory import get_db_loader
from profiles.loaders.db_columns_mapping import (
    BANK_COL_MAPPING,
    CREDIT_CARD_PRODUCTS_COL_MAPPING,
    BRIDGE_USER_CARDS_COL_MAPPING,
    REWARD_PROGRAM_COL_MAPPING,
    REWARD_CAMPAIGN_COL_MAPPING,
    MERCHANT_COL_MAPPING,
    PAYMENT_PROCESS_COL_MAPPING,
    EC_PLATFORM_COL_MAPPING,
    REWARD_RULE_COL_MAPPING,
    BRIDGE_CUBE_SELECTION_COL_MAPPING,
    BRIDGE_UNICARD_SELECTION_COL_MAPPING,
    BRIDGE_UNIOPEN_VISIT_SPOTS_COL_MAPPING,
    FX_TABLE_COL_MAPPING,
    BILLING_HISTORY_COL_MAPPING,
)

logger = logging.getLogger(__name__)

class ConfigSyncManager:
    """
    負責將 configs/*.csv 資料同步至 SQLite / PostgreSQL 資料庫。
    遵循 GEMINI.md 規範：
    1. 使用 ConfigLoader 處理編碼與私有檔合併 (Append/Replace)
    2. 使用 get_db_loader 支援 sqlite / postgres / dual 模式寫入與索引建立
    """
    def __init__(self, config_dir: Optional[str] = None, db_path=None, db_backend: Optional[str] = None):
        self.config_dir = config_dir if config_dir is not None else const.CONFIG_DIR
        self.db_path = db_path if db_path is not None else const.CONFIGS_DB_PATH
        self.db_backend = (db_backend or os.getenv('DB_BACKEND', getattr(const, 'DEFAULT_DB_BACKEND', 'sqlite'))).strip().lower()
        self.loader = get_db_loader(db_backend=self.db_backend, db_path=self.db_path)

    def _sync_item(self, name: str, csv_base: str, table_name: str, mapping_func, indices: Optional[List[str]] = None, strategy: str = 'append'):
        """通用同步邏輯"""
        try:
            logger.info(f"🔄 正在同步 {name} (Backend: {self.db_backend})...")
            df = ConfigLoader.load_config(self.config_dir, csv_base, strategy=strategy)
            
            if df.empty:
                logger.warning(f"⚠️ {name} 資料為空，跳過同步。")
                return

            # 套用欄位映射
            mapping = mapping_func()
            df_mapped = df.rename(columns=mapping)
            
            # 僅保留映射定義中的欄位
            cols_to_keep = [v for v in mapping.values() if v in df_mapped.columns]
            df_final = df_mapped[cols_to_keep]
            if not isinstance(df_final, pd.DataFrame):
                df_final = pd.DataFrame(df_final)
 
            # 寫入資料庫
            self.loader.load(df_final, table_name, mode='replace', indices=indices)
            logger.info(f"✅ {name} 同步完成 -> [{table_name}]")
        except Exception as e:
            logger.error(f"❌ {name} 同步失敗: {e}", exc_info=True)



    def sync_banks(self):
        try:
            logger.info(f"🔄 正在同步 銀行主檔 (Backend: {self.db_backend})...")
            bank_yaml = ConfigLoader.load_yaml("dim_banks", config_dir=self.config_dir)
            if bank_yaml and isinstance(bank_yaml, dict) and 'banks' in bank_yaml:
                df = pd.DataFrame(bank_yaml['banks'])
            else:
                df = ConfigLoader.load_config(self.config_dir, "dim_banks", strategy='replace')
            
            if df.empty:
                logger.warning("⚠️ 銀行主檔 資料為空，跳過同步。")
                return

            mapping = BANK_COL_MAPPING()
            df_mapped = df.rename(columns=mapping)
            cols_to_keep = [v for v in mapping.values() if v in df_mapped.columns]
            df_final = df_mapped[cols_to_keep]
            if not isinstance(df_final, pd.DataFrame):
                df_final = pd.DataFrame(df_final)

            self.loader.load(df_final, "dim_banks", mode='replace', indices=['bank_no'])
            logger.info("✅ 銀行主檔 同步完成 -> [dim_banks]")
        except Exception as e:
            logger.error(f"❌ 銀行主檔 同步失敗: {e}", exc_info=True)

    def sync_credit_card_products(self):
        self._sync_item(
            "信用卡產品規格主檔", 
            "dim_credit_card_products", 
            "dim_credit_card_products", 
            CREDIT_CARD_PRODUCTS_COL_MAPPING, 
            indices=['card_id', 'bank_no'],
            strategy='replace'
        )

    def sync_bridge_user_cards(self):
        try:
            logger.info(f"🔄 正在同步 個人持卡對照表 (Backend: {self.db_backend})...")
            from profiles.loaders.user_cards_loader import UserCardsLoader
            loader = UserCardsLoader()
            df_flat = loader.to_flat_dataframe()

            if not df_flat.empty:
                # 1. 寫入 1D 扁平視圖 / 對照表 bridge_user_cards
                mapping = BRIDGE_USER_CARDS_COL_MAPPING()
                df_mapped = df_flat.rename(columns=mapping)
                cols_to_keep = [v for v in mapping.values() if v in df_mapped.columns]
                df_final = df_mapped[cols_to_keep]
                if not isinstance(df_final, pd.DataFrame):
                    df_final = pd.DataFrame(df_final)

                self.loader.load(df_final, "bridge_user_cards", mode='replace', indices=['card_id', 'card_no', 'vpc_no'])
                logger.info("✅ 個人持卡對照表 (扁平 View) 同步完成 -> [bridge_user_cards]")

                # 2. 同步 3NF 正規化資料表 (user_card_products, user_card_histories, user_card_vpc_pay)
                tables_3nf = loader.to_relational_tables()
                if not tables_3nf['user_card_products'].empty:
                    self.loader.load(tables_3nf['user_card_products'], "user_card_products", mode='replace', indices=['card_id', 'bank_no'])
                if not tables_3nf['user_card_histories'].empty:
                    self.loader.load(tables_3nf['user_card_histories'], "user_card_histories", mode='replace', indices=['history_id', 'card_no'])
                if not tables_3nf['user_card_vpc_pay'].empty:
                    self.loader.load(tables_3nf['user_card_vpc_pay'], "user_card_vpc_pay", mode='replace', indices=['vpc_id', 'vpc_no'])
                logger.info("✅ 個人持卡歷史 3NF 關聯表同步完成 -> [user_card_products, user_card_histories, user_card_vpc_pay]")
            else:
                # Fallback: 嘗試載入舊版 bridge_user_cards.csv
                self._sync_item(
                    "個人持卡對照表", 
                    "bridge_user_cards", 
                    "bridge_user_cards", 
                    BRIDGE_USER_CARDS_COL_MAPPING, 
                    indices=['user_card_id', 'card_id', 'card_no'],
                    strategy='replace'
                )
        except Exception as e:
            logger.error(f"❌ 個人持卡對照表同步失敗: {e}", exc_info=True)

    def sync_cards(self):
        """同步所有卡片與銀行主檔 (dim_banks, dim_credit_card_products, bridge_user_cards)"""
        self.sync_banks()
        self.sync_credit_card_products()
        self.sync_bridge_user_cards()

    def sync_merchants(self):
        self._sync_item(
            "特約商店", 
            "dim_merchants", 
            "dim_merchants", 
            MERCHANT_COL_MAPPING, 
            indices=['merchant_display', 'category'],
            strategy='append'
        )

    def sync_payment_processes(self):
        self._sync_item(
            "支付/處理流程", 
            "dim_payment_process", 
            "dim_payment_process", 
            PAYMENT_PROCESS_COL_MAPPING, 
            indices=['payment_process', 'payment_process_pattern'],
            strategy='append'
        )

    def sync_ec_platforms(self):
        self._sync_item(
            "電商平台", 
            "dim_ec_platform", 
            "dim_ec_platform", 
            EC_PLATFORM_COL_MAPPING, 
            indices=['ec_platform', 'ec_platform_pattern'],
            strategy='append'
        )

    def sync_reward_base(self):
        self._sync_item(
            "基礎回饋計畫", 
            "dim_card_rewards_base", 
            "dim_card_rewards_base", 
            REWARD_PROGRAM_COL_MAPPING, 
            indices=['reward_program', 'card_type', 'bank_name'],
            strategy='replace'
        )

    def sync_reward_campaigns(self):
        self._sync_item(
            "活動加碼回饋", 
            "dim_card_rewards_campaigns", 
            "dim_card_rewards_campaigns", 
            REWARD_CAMPAIGN_COL_MAPPING, 
            indices=['campaign_name', 'card_type', 'bank_name'],
            strategy='append'
        )

    def sync_reward_rules(self):
        self._sync_item(
            "回饋規則 (Waterfall)", 
            "bridge_reward_rules", 
            "bridge_reward_rules", 
            REWARD_RULE_COL_MAPPING, 
            indices=['reward_program', 'priority'],
            strategy='append'
        )

    def sync_bridge_cube_selections(self):
        self._sync_item(
            "國泰Cube權益切換歷史", 
            "bridge_cube_selections", 
            "bridge_cube_selections", 
            BRIDGE_CUBE_SELECTION_COL_MAPPING, 
            indices=['base_reward_program', 'start_date', 'end_date'],
            strategy='replace'
        )

    def sync_bridge_unicard_selections(self):
        self._sync_item(
            "玉山Unicard方案訂閱歷史", 
            "bridge_unicard_selections", 
            "bridge_unicard_selections", 
            BRIDGE_UNICARD_SELECTION_COL_MAPPING, 
            indices=['rules_reward_program', 'campaign_reward_program', 'start_date', 'end_date'],
            strategy='replace'
        )

    def sync_bridge_uniopen_visit_spots(self):
        self._sync_item(
            "中信Uniopen踩點加碼歷史", 
            "bridge_uniopen_visit_spots", 
            "bridge_uniopen_visit_spots", 
            BRIDGE_UNIOPEN_VISIT_SPOTS_COL_MAPPING, 
            indices=['campaign_reward_program', 'rules_reward_program', 'start_date', 'end_date'],
            strategy='replace'
        )

    def sync_dim_fx_table(self):
        self._sync_item(
            "匯率每日表", 
            "dim_fx_table", 
            "dim_fx_table", 
            FX_TABLE_COL_MAPPING, 
            indices=['conversion_date', 'bank_name', 'currency_type'],
            strategy='replace'
        )

    def sync_dim_billing_history(self):
        self._sync_item(
            "對帳單歷史", 
            "dim_billing_history", 
            "dim_billing_history", 
            BILLING_HISTORY_COL_MAPPING, 
            indices=['bank_name', 'statement_month'],
            strategy='replace'
        )

    def sync_all(self):
        logger.info("🚀 開始執行全量配置同步...")
        # 1. 全域維度表
        self.sync_cards()
        self.sync_merchants()
        self.sync_payment_processes()
        self.sync_ec_platforms()
        
        # 2. 回饋與對照維度表
        self.sync_reward_base()
        self.sync_reward_campaigns()
        self.sync_reward_rules()
        self.sync_bridge_cube_selections()
        self.sync_bridge_unicard_selections()
        self.sync_bridge_uniopen_visit_spots()
        self.sync_dim_fx_table()
        self.sync_dim_billing_history()
        
        logger.info("🏁 全量配置同步完成！")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="configs/*.csv 資料同步至資料庫腳本")
    parser.add_argument("--backend", choices=["sqlite", "postgres", "dual"], default=None, help="指定 DB Backend (sqlite/postgres/dual)")
    args = parser.parse_args()

    # 設置基礎 Log 格式
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    sync_manager = ConfigSyncManager(db_backend=args.backend)
    sync_manager.sync_all()
