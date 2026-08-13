# etl/etl_extraction.py
"""
ETL 模組 - Extract (資料讀取、去重與解析器分派)
零邏輯變更說明：自 etl_api.py 完全等價遷移 parser 分派與檔案解析邏輯
"""
import os
import pandas as pd
import logging
from typing import Optional, List, Dict, Any

import const
from etl.parsers.sinopac import SinopacBillParser
from etl.parsers.esun import EsunParser
from etl.parsers.cathay import CubeParser
from etl.parsers.ctbc import CTBCParser
from etl.parsers.hncb import HNCBParser

try:
    from profiles.loaders.file_registry import FileRegistryManager
except ImportError:
    FileRegistryManager = None

try:
    from profiles.loaders.config_loader import ConfigLoader
except ImportError:
    ConfigLoader = None

logger = logging.getLogger(__name__)

DATA_DIR = const.DATA_DIR
OUTPUT_DIR = const.OUTPUT_DIR
CONFIG_DIR = const.CONFIG_DIR

os.makedirs(OUTPUT_DIR, exist_ok=True)

def get_bank_info(filename: str) -> Optional[Dict[str, Any]]:
    """
    透過 dim_banks.yaml 比對檔名中的 bill_mapping_name 與 keywords
    回傳比對到的銀行資訊字典 (bank_id, bank_no, bank_name, bill_mapping_name)
    """
    if not filename:
        return None

    try:
        if ConfigLoader:
            yaml_data = ConfigLoader.load_yaml(base_name='dim_banks')
        else:
            yaml_data = {}
        banks = yaml_data.get('banks', []) if isinstance(yaml_data, dict) else []
    except Exception as e:
        logger.warning(f"⚠️ 無法讀取 dim_banks.yaml 配置檔: {e}")
        banks = []

    filename_lower = filename.lower()
    for bank in banks:
        # 1. 比對 bill_mapping_name
        mapping_name = bank.get('bill_mapping_name', '')
        if mapping_name and mapping_name.lower() in filename_lower:
            return bank

        # 2. 比對 keywords 陣列
        keywords = bank.get('keywords', [])
        for kw in keywords:
            if kw and kw.lower() in filename_lower:
                return bank
    return None

def get_parser(filename: str):
    """
    根據檔名與 dim_banks.yaml 特徵，回傳對應的 Parser 實例與銀行資訊
    """
    bank_info = get_bank_info(filename)
    if not bank_info:
        return None

    bank_id = bank_info.get('bank_id')
    filename_lower = filename.lower()

    if bank_id == 'sinopac' and filename_lower.endswith('.pdf'):
        return SinopacBillParser(bank_id_or_keyword=bank_id)
    if bank_id in ['esun'] and filename_lower.endswith('.csv'):
        return EsunParser(bank_id_or_keyword=bank_id)
    if bank_id in ['cube', 'cathay'] and filename_lower.endswith('.csv'):
        return CubeParser(bank_id_or_keyword=bank_id)
    if bank_id == 'ctbc' and filename_lower.endswith('.csv'):
        return CTBCParser(bank_id_or_keyword=bank_id)
    if bank_id == 'hncb' and (filename_lower.endswith('.xls') or filename_lower.endswith('.html')):
        return HNCBParser(bank_id_or_keyword=bank_id)

    return None

def get_parser_mapping() -> Dict[str, Any]:
    """取得所有支援的銀行解析器對照表"""
    return {
        "sinopac": SinopacBillParser(bank_id_or_keyword="sinopac"),
        "esun": EsunParser(bank_id_or_keyword="esun"),
        "cathay": CubeParser(bank_id_or_keyword="cube"),
        "ctbc": CTBCParser(bank_id_or_keyword="ctbc"),
        "hncb": HNCBParser(bank_id_or_keyword="hncb")
    }

def save_anomaly_report(df: pd.DataFrame, filename: str, message: str):
    """
    將異常或未定義的交易資料匯出至 output 資料夾，供使用者檢查。
    """
    try:
        if df is None or df.empty:
            return
        
        report_path = os.path.join(OUTPUT_DIR, filename)
        df.to_csv(report_path, index=False, encoding='utf-8-sig')
        logger.warning(f"⚠️ {message}，已將診斷資料匯出至: {report_path}")
    except Exception as e:
        logger.error(f"❌ 無法匯出異常報告: {e}")

# ==========================================
# Extract 階段進入點
# ==========================================
def extract_raw_data(force: bool = True, input_dir: Optional[str] = None) -> Optional[pd.DataFrame]:
    """
    掃描資料夾中的帳單檔案並進行解構與批次讀取：
    1. 使用 FileRegistryManager 進行去重檢查 (若 force=False)
    2. 自動為每個檔案指派 Parser 並調用 parse() 方法
    3. 整合多檔案資料為單一 Raw DataFrame
    """
    all_raw_dfs: List[pd.DataFrame] = []
    registry_mgr = FileRegistryManager() if FileRegistryManager else None

    target_dir = input_dir or (const.PROFILE_DATA_DIR if (os.path.exists(const.PROFILE_DATA_DIR) and len(os.listdir(const.PROFILE_DATA_DIR)) > 0) else const.DATA_DIR)
    
    if not os.path.exists(target_dir):
        logger.error(f"❌ 找不到資料目錄: {target_dir}")
        return None

    files = [f for f in os.listdir(target_dir) if not f.startswith('.')]
    logger.info(f"📂 掃描到 {len(files)} 個檔案 ({target_dir})")

    for filename in files:
        filepath = os.path.join(target_dir, filename)
        
        if not os.path.isfile(filepath):
            continue

        file_size = os.path.getsize(filepath)
        file_hash = None
        if registry_mgr:
            file_hash = registry_mgr.calculate_file_hash(filepath)
            if not force and registry_mgr.is_file_ingested(file_hash):
                logger.info(f"  ⏭️ [SKIP] 檔案已成功解析過 ({file_hash[:8]}...): {filename}")
                continue

        bank_info = get_bank_info(filename)
        parser = get_parser(filename)
        bank_id = bank_info.get('bank_id') if bank_info else None
        bills_mapping_name = bank_info.get('bills_mapping_name') if bank_info else None
        official_bank_name = bank_info.get('bank_name') if bank_info else None
        target_bank_name = bills_mapping_name or official_bank_name or bank_id
        
        if parser:
            try:
                logger.info(f"處理中: {filename} ...")
                df = parser.parse(filepath)
                if not df.empty:
                    if 'bank_name' not in df.columns or df['bank_name'].isna().all() or (df['bank_name'] == '').all():
                        df['bank_name'] = target_bank_name
                    else:
                        df['bank_name'] = df['bank_name'].replace('', target_bank_name).fillna(target_bank_name)
                    all_raw_dfs.append(df)
                    record_cnt = len(df)
                    logger.info(f"  ✅ 解析成功 ({record_cnt} 筆): {filename}")
                    if registry_mgr and file_hash:
                        registry_mgr.register_file(
                            file_hash=file_hash,
                            filename=filename,
                            file_size=file_size,
                            bank_id=bank_id,
                            record_count=record_cnt,
                            status='SUCCESS'
                        )
                else:
                    logger.warning(f"  ⚠️ 解析成功但無資料: {filename}")
                    if registry_mgr and file_hash:
                        registry_mgr.register_file(
                            file_hash=file_hash,
                            filename=filename,
                            file_size=file_size,
                            bank_id=bank_id,
                            record_count=0,
                            status='SUCCESS'
                        )
            except Exception as e:
                logger.error(f"  ❌ 解析失敗 {filename}: {str(e)}")
                if registry_mgr and file_hash:
                    registry_mgr.register_file(
                        file_hash=file_hash,
                        filename=filename,
                        file_size=file_size,
                        bank_id=bank_id,
                        record_count=0,
                        status='FAILED'
                    )
        else:
            logger.debug(f"  ⏭️ 跳過不支援或未定義 Parser 的檔案: {filename}")

    if not all_raw_dfs:
        logger.warning("🚫 本次執行未取得任何新有效資料（可能全部已解析或資料夾為空），流程結束。")
        return None

    merged_df = pd.concat(all_raw_dfs, ignore_index=True)
    logger.info(f"🔗 合併完成，共 {len(merged_df)} 筆原始資料")
    return merged_df
