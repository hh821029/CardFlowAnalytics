# etl/refinement.py
"""
Stage 2 (Silver) 商業規則清洗與資料集市 (Business Refinement & Feature Engineering)
核心職責：
1. 純函數式商業清洗介面 refine_transactions(raw_df) -> refined_df
2. 獨立調度入口 run_stage2_pipeline()：免重新掃描實體帳單，直接自 raw_transactions 重跑 Stage 2 清洗
"""
import os
import pandas as pd
import logging
from typing import Optional, Dict, Any

import const
from etl.processors.merchant import MerchantPipeline
from etl.processors.card_classifier import CardClassifier
from etl.processors.transaction_classifier import TransactionClassifier
from etl.utils import save_anomaly_report

try:
    from profiles.loaders.config_loader import ConfigLoader
except ImportError:
    ConfigLoader = None

try:
    from database.loaders.db_reader import DBReader
except ImportError:
    DBReader = None

logger = logging.getLogger(__name__)

CONFIG_DIR = const.CONFIG_DIR
OUTPUT_DIR = const.OUTPUT_DIR


class DataRefiner:
    """
    商業邏輯精煉器：協調卡片歸戶、第三方支付前綴、商家正規化與交易分類
    """
    def __init__(self, config_dir: str, configs: Optional[dict] = None):
        configs = configs or {}
        self.card_classifier = CardClassifier(
            config_dir,
            rules=configs.get('cards'),
            gateways=configs.get('gateways')
        )
        self.merchant_pipeline = MerchantPipeline(config_dir=config_dir, configs=configs)
        self.classifier = TransactionClassifier(config_dir, config=configs.get('txn_types'))

    def process(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        純記憶體處理管線
        """
        if df.empty:
            return df

        df_working = df.copy()

        # 0. 若存在 raw_extra 欄位，還原銀行原始特有欄位 (如行動支付註記、vpc_type 等)
        if 'raw_extra' in df_working.columns:
            for idx, extra_val in df_working['raw_extra'].items():
                extra_dict = None
                if isinstance(extra_val, dict):
                    extra_dict = extra_val
                elif isinstance(extra_val, str) and extra_val.strip().startswith('{'):
                    try:
                        import json
                        extra_dict = json.loads(extra_val)
                    except Exception:
                        pass
                if isinstance(extra_dict, dict):
                    for k, v in extra_dict.items():
                        if k not in df_working.columns:
                            df_working[k] = None
                        if pd.isna(df_working.at[idx, k]) or df_working.at[idx, k] is None:
                            df_working.at[idx, k] = v

        # 1. 欄位對齊 (相容 raw_transactions 的原始欄位與舊有命名)
        if 'raw_merchant' in df_working.columns:
            if const.COL_MERCHANT not in df_working.columns or df_working[const.COL_MERCHANT].isna().all():
                df_working[const.COL_MERCHANT] = df_working['raw_merchant']
        elif const.COL_MERCHANT in df_working.columns and 'raw_merchant' not in df_working.columns:
            df_working['raw_merchant'] = df_working[const.COL_MERCHANT]

        if 'raw_location' in df_working.columns:
            if const.COL_LOCATION not in df_working.columns or df_working[const.COL_LOCATION].isna().all():
                df_working[const.COL_LOCATION] = df_working['raw_location']
        elif const.COL_LOCATION not in df_working.columns:
            df_working[const.COL_LOCATION] = 'TW'

        df_working[const.COL_LOCATION] = df_working[const.COL_LOCATION].fillna('TW')

        # 幣別與金額欄位對齊
        if 'raw_currency' in df_working.columns and const.COL_CURRENCY not in df_working.columns:
            df_working[const.COL_CURRENCY] = df_working['raw_currency']
        elif const.COL_CURRENCY not in df_working.columns:
            df_working[const.COL_CURRENCY] = 'TWD'
        df_working[const.COL_CURRENCY] = df_working[const.COL_CURRENCY].fillna('TWD')

        if 'payment_currency' in df_working.columns and const.COL_PAY_CURR not in df_working.columns:
            df_working[const.COL_PAY_CURR] = df_working['payment_currency']
        elif const.COL_PAY_CURR not in df_working.columns:
            df_working[const.COL_PAY_CURR] = 'TWD'
        df_working[const.COL_PAY_CURR] = df_working[const.COL_PAY_CURR].fillna('TWD')

        if 'raw_amount' in df_working.columns and const.COL_CURR_AMOUNT not in df_working.columns:
            df_working[const.COL_CURR_AMOUNT] = df_working['raw_amount']
        elif const.COL_CURR_AMOUNT not in df_working.columns and const.COL_PAY_AMOUNT in df_working.columns:
            df_working[const.COL_CURR_AMOUNT] = df_working[const.COL_PAY_AMOUNT]

        if 'payment_amount' in df_working.columns and const.COL_PAY_AMOUNT not in df_working.columns:
            df_working[const.COL_PAY_AMOUNT] = df_working['payment_amount']
        elif const.COL_PAY_AMOUNT not in df_working.columns and const.COL_CURR_AMOUNT in df_working.columns:
            df_working[const.COL_PAY_AMOUNT] = df_working[const.COL_CURR_AMOUNT]

        if const.COL_AMOUNT not in df_working.columns:
            df_working[const.COL_AMOUNT] = df_working.get(const.COL_PAY_AMOUNT, df_working.get(const.COL_CURR_AMOUNT, 0))

        if const.COL_VPC_NO not in df_working.columns:
            df_working[const.COL_VPC_NO] = None

        if const.COL_VPC_TYPE not in df_working.columns:
            df_working[const.COL_VPC_TYPE] = None

        # 補齊銀行名稱 (若有 bank_no 但缺少 bank_name)
        if 'bank_name' not in df_working.columns or df_working['bank_name'].isna().all():
            if 'bank_no' in df_working.columns:
                def resolve_bname(bno):
                    if pd.isna(bno): return ''
                    b_info = const.get_bank_by_no(str(bno).strip()) or const.get_bank_by_keyword(str(bno).strip())
                    return b_info.get('bills_mapping_name', b_info.get('bank_name', '')) if b_info else ''
                df_working['bank_name'] = df_working['bank_no'].apply(resolve_bname)


        # 2. 卡片歸戶與支付分類 (Card & VPC Classifier)
        #    標記卡別、vpc_type 並完成第三方支付交叉流轉
        df_working = self.card_classifier.process(df_working)

        # 3. 商家名稱管線清洗 (Merchant Pipeline: Gateway -> EC -> Normalizer -> Fallback -> Display)
        df_working = self.merchant_pipeline.process(df_working)

        # 4. 交易分類 (Transaction Classification)
        #    根據 merchant_display / category 標記 transaction_type
        df_working = self.classifier.process(df_working)

        return df_working


def refine_transactions(raw_df: pd.DataFrame, configs: Optional[dict] = None) -> pd.DataFrame:
    """
    Stage 2 純函數式介面：
    接收包含銀行原始資訊之 raw_df，輸出具備完整商業特徵（歸戶、管道、正規化、分類）之 refined_df
    """
    if raw_df is None or raw_df.empty:
        return pd.DataFrame() if raw_df is None else raw_df.copy()

    try:
        logger.info(f"🔧 [Stage 2] 啟動商業邏輯清洗 (共 {len(raw_df)} 筆)...")
        if configs is None and ConfigLoader:
            configs = {
                'merchants': ConfigLoader.load_config(CONFIG_DIR, 'dim_merchants', strategy='append'),
                'cards': ConfigLoader.load_config(CONFIG_DIR, 'bridge_user_cards', strategy='replace'),
                'gateways': ConfigLoader.load_config(CONFIG_DIR, 'dim_payment_process', strategy='append'),
                'ec_platforms': ConfigLoader.load_config(CONFIG_DIR, 'dim_ec_platform', strategy='append'),
                'txn_types': ConfigLoader.load_yaml('transaction_types.yaml', config_dir=CONFIG_DIR)
            }

        refiner = DataRefiner(config_dir=CONFIG_DIR, configs=configs)
        refined_df = refiner.process(raw_df)
        logger.info("✨ [Stage 2] 商業邏輯清洗完成")
        return refined_df

    except Exception as e:
        logger.error(f"❌ [Stage 2] 清洗過程發生嚴重錯誤: {e}", exc_info=True)
        save_anomaly_report(raw_df, 'crash_dump_refiner.csv', "Stage 2 清洗過程發生崩潰，已備份原始輸入資料")
        return raw_df.copy()


def run_stage2_pipeline(
    db_backend: Optional[str] = None, 
    force: bool = True,
    db_path: Optional[str] = None
) -> bool:
    """
    Stage 2 獨立重跑管線 (免重新掃描檔案)：
    1. 自資料庫 raw_transactions 讀取未清洗的標準原始資料
    2. 調用 refine_transactions 重新計算商業規則
    3. 入庫至 all_transactions / refined_transactions 並自動刷新 Views 與索引
    """
    logger.info("🚀 [Stage 2 Pipeline] 啟動商業規則重算 (讀取 raw_transactions，略過實體檔案解析)...")

    if DBReader is None:
        logger.error("❌ 無法載入 DBReader 模組，請確認資料庫配置。")
        return False

    try:
        # 1. 自 raw_transactions 讀取資料
        logger.info("📥 正在從資料庫讀取 [raw_transactions]...")
        raw_df = DBReader.read_sql("SELECT * FROM raw_transactions", db_path=db_path)

        if raw_df is None or raw_df.empty:
            logger.warning("⚠️ 資料庫 [raw_transactions] 表目前無資料！請先執行完整 ETL (選項 1) 解析帳單入庫。")
            return False

        logger.info(f"📊 成功讀取 {len(raw_df)} 筆原始交易資料")

        # 2. 執行純記憶體商業清洗
        refined_df = refine_transactions(raw_df)
        if refined_df is None or refined_df.empty:
            logger.error("❌ Stage 2 商業清洗後無資料產出。")
            return False

        # 3. 入庫與視圖刷新
        from etl.loading import load_data
        success = load_data(
            final_df=refined_df,
            force=force,
            db_backend=db_backend,
            output_dir=OUTPUT_DIR,
            db_path=db_path
        )

        if success:
            logger.info("🎉 [Stage 2 Pipeline] 商業規則重算與資料庫入庫刷新全部成功！")
        return success

    except Exception as e:
        logger.error(f"🚨 [Stage 2 Pipeline] 重跑流程發生異常: {e}", exc_info=True)
        return False
