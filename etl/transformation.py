# etl/etl_transformation.py
"""
ETL 模組 - Transform (資料清洗與商業邏輯處理)
零邏輯變更說明：自 etl_api.py 完全等價遷移 DataRefiner 與分類對照邏輯
"""
import os
import pandas as pd
import logging
from typing import Optional, Dict, Any

import const

try:
    from etl.processors.refiner import DataRefiner
except ImportError:
    DataRefiner = None

try:
    from profiles.loaders.config_loader import ConfigLoader
except ImportError:
    ConfigLoader = None

from etl.utils import save_anomaly_report

logger = logging.getLogger(__name__)

CONFIG_DIR = const.CONFIG_DIR
OUTPUT_DIR = const.OUTPUT_DIR

def transform_data(merged_df: pd.DataFrame) -> pd.DataFrame:
    """
    STEP 2: 呼叫 DataRefiner 進行商家名稱正規化、前綴處理與交易類型分類
    """
    final_df = merged_df

    if DataRefiner is not None and merged_df is not None and not merged_df.empty:
        try:
            logger.info("🔧 啟動 Refiner 進行商業邏輯清洗...")
            if ConfigLoader:
                configs = {
                    'merchants': ConfigLoader.load_config(CONFIG_DIR, 'dim_merchants', strategy='append'),
                    'cards': ConfigLoader.load_config(CONFIG_DIR, 'bridge_user_cards', strategy='replace'),
                    'gateways': ConfigLoader.load_config(CONFIG_DIR, 'dim_payment_process', strategy='append'),
                    'ec_platforms': ConfigLoader.load_config(CONFIG_DIR, 'dim_ec_platform', strategy='append'),
                    'txn_types': ConfigLoader.load_yaml('transaction_types.yaml', config_dir=CONFIG_DIR)
                }
                refiner = DataRefiner(config_dir=CONFIG_DIR, configs=configs)
            else:
                refiner = DataRefiner(config_dir=CONFIG_DIR)
            
            final_df = refiner.process(merged_df)
            
            if 'transaction_type' in final_df.columns:
                anomalies = final_df[final_df['transaction_type'].isin(['未分類', 'Unknown', '', None])]
                if not isinstance(anomalies, pd.DataFrame):
                    anomalies = pd.DataFrame(anomalies)
                if not anomalies.empty:
                    save_anomaly_report(anomalies, 'anomaly_uncategorized.csv', f"發現 {len(anomalies)} 筆未分類交易")

            logger.info("✨ 資料清洗完成")
        except Exception as e:
            logger.error(f"❌ Refiner 清洗過程發生嚴重錯誤: {e}")
            save_anomaly_report(merged_df, 'crash_dump_refiner.csv', "清洗過程發生崩潰，已備份原始合併資料")
            final_df = merged_df

    return final_df
