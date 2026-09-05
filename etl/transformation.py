# etl/transformation.py
"""
ETL 模組 - Transform (資料清洗與商業邏輯處理)
"""
import os
import pandas as pd
import logging
from typing import Optional, Dict, Any

import const

from etl.processors.merchant import (
    MerchantNormalizer,
    PaymentProcessTagger,
    ECPlatformTagger,
    _apply_final_prefixes
)
from etl.processors.card_classifier import CardClassifier
from etl.processors.transaction_classifier import TransactionClassifier


try:
    from profiles.loaders.config_loader import ConfigLoader
except ImportError:
    ConfigLoader = None

from etl.utils import save_anomaly_report

logger = logging.getLogger(__name__)

CONFIG_DIR = const.CONFIG_DIR
OUTPUT_DIR = const.OUTPUT_DIR


class DataRefiner:
    def __init__(self, config_dir: str, configs: Optional[dict] = None):
        configs = configs or {}
        self.card_classifier = CardClassifier(config_dir, rules=configs.get('cards'), gateways=configs.get('gateways'))
        self.ec_tagger = ECPlatformTagger(config_dir, rules=configs.get('ec_platforms'))
        self.merchant_normalizer = MerchantNormalizer(config_dir, rules=configs.get('merchants'))
        self.payment_tagger = PaymentProcessTagger(config_dir, rules=configs.get('gateways'))
        self.classifier = TransactionClassifier(config_dir, config=configs.get('txn_types'))

    def process(self, df: pd.DataFrame) -> pd.DataFrame:
        if df.empty: return df

        if const.COL_LOCATION not in df.columns:
            df[const.COL_LOCATION] = 'TW'

        # 1. 卡片歸戶與支付分類 (Card & VPC Classifier)
        #    標記卡別、vpc_type 並完成第三方支付交叉流轉
        df = self.card_classifier.process(df)

        # 2. 支付管道識別 (Payment Gateway - 最外層)
        #    標記 payment_process, process_prefix (以及 OEM vpc_type)
        df = self.payment_tagger.process(df)

        # 3. 電商平台識別 (EC Platform - 中層)
        #    標記 ec_platform, ec_platform_type, ec_category, ec_sub_category
        df = self.ec_tagger.process(df)

        # 4. 商家正規化 (Merchant Normalization - 最內層)
        #    依據 dim_merchants.csv 替換商家名稱，結果存入 normalized_merchant, category, sub_category
        res = self.merchant_normalizer.process(df, return_mask=True)
        if isinstance(res, tuple):
            df, processed_mask = res
        else:
            df = res
            processed_mask = pd.Series(False, index=df.index)

        # 5 階層式補位 (Stack Fallback & Cascade)
        if const.COL_NORMALIZED_MERCHANT not in df.columns:
            df[const.COL_NORMALIZED_MERCHANT] = None

        # 5.1 特店名稱補位：未被 dim_merchants 匹配時，若有電商平台則以電商平台名稱為準
        has_ec = (df[const.COL_EC_PLATFORM].fillna('') != '') if const.COL_EC_PLATFORM in df.columns else pd.Series(False, index=df.index)
        ec_fallback_mask = (~processed_mask) & has_ec
        if ec_fallback_mask.any():
            df.loc[ec_fallback_mask, const.COL_NORMALIZED_MERCHANT] = df.loc[ec_fallback_mask, const.COL_EC_PLATFORM]
            logger.info(f"💡 已為 {ec_fallback_mask.sum()} 筆未匹配商家套用電商平台 Fallback 清洗")

        # 5.2 若既無商家正規化也無電商平台，補為原始 merchant (銀行原始名稱)
        raw_fallback_mask = df[const.COL_NORMALIZED_MERCHANT].isna() | (df[const.COL_NORMALIZED_MERCHANT].astype(str).str.strip() == '')
        if raw_fallback_mask.any() and const.COL_MERCHANT in df.columns:
            df.loc[raw_fallback_mask, const.COL_NORMALIZED_MERCHANT] = df.loc[raw_fallback_mask, const.COL_MERCHANT]

        # 5.3 分類階層補位：若 category 為空且有 ec_category，則以 ec_category 補位
        if const.COL_EC_CATEGORY in df.columns and const.COL_CATEGORY in df.columns:
            cat_empty = df[const.COL_CATEGORY].isna() | (df[const.COL_CATEGORY].astype(str).str.strip() == '')
            cat_ec_has = df[const.COL_EC_CATEGORY].fillna('').astype(str).str.strip() != ''
            cat_fallback = cat_empty & cat_ec_has
            if cat_fallback.any():
                df.loc[cat_fallback, const.COL_CATEGORY] = df.loc[cat_fallback, const.COL_EC_CATEGORY]

        if const.COL_EC_SUB_CATEGORY in df.columns and const.COL_SUB_CATEGORY in df.columns:
            subcat_empty = df[const.COL_SUB_CATEGORY].isna() | (df[const.COL_SUB_CATEGORY].astype(str).str.strip() == '')
            subcat_ec_has = df[const.COL_EC_SUB_CATEGORY].fillna('').astype(str).str.strip() != ''
            subcat_fallback = subcat_empty & subcat_ec_has
            if subcat_fallback.any():
                df.loc[subcat_fallback, const.COL_SUB_CATEGORY] = df.loc[subcat_fallback, const.COL_EC_SUB_CATEGORY]

        # 6. 堆疊拼裝最終顯示名稱 (Compose Merchant Display)
        #    公式：[支付前綴]－[電商平台]－[正規化商家名稱]
        df = _apply_final_prefixes(df)

        # 7. 交易分類 (Transaction Classification)
        #    根據 merchant_display / category 標記 transaction_type
        df = self.classifier.process(df)

        return df


def transform_data(merged_df: pd.DataFrame) -> pd.DataFrame:
    """
    STEP 2: 呼叫 DataRefiner 進行商家名稱正規化、前綴處理與交易類型分類
    """
    final_df = merged_df

    if merged_df is not None and not merged_df.empty:
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

            logger.info("✨ 資料清洗完成")
        except Exception as e:
            logger.error(f"❌ Refiner 清洗過程發生嚴重錯誤: {e}")
            save_anomaly_report(merged_df, 'crash_dump_refiner.csv', "清洗過程發生崩潰，已備份原始合併資料")
            final_df = merged_df

    return final_df
