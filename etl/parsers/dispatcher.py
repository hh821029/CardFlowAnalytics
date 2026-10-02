# etl/parsers/dispatcher.py
"""
ETL 模組 - Extract / Dispatcher (帳單讀取、去重與解析器分派核心)
負責依銀行特徵分派對應 Parser 實例，支援單檔安全解析 (extract_file)
與逐檔串流提取 (extract_raw_data_stream) 達成錯誤隔離。
"""
import os
import pandas as pd
import logging
from typing import Optional, List, Dict, Any, Generator

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

from etl.exceptions import (
    save_anomaly_report,
    UnmappedBankError,
    InvalidBillFormatError,
    MaliciousPayloadDetectedError
)

logger = logging.getLogger(__name__)

DATA_DIR = const.DATA_DIR
OUTPUT_DIR = const.OUTPUT_DIR
CONFIG_DIR = const.CONFIG_DIR

os.makedirs(OUTPUT_DIR, exist_ok=True)

def get_bank_info(filename: Optional[str] = None, strict: bool = False) -> Optional[Dict[str, Any]]:
    """
    透過 dim_banks.yaml 比對檔名中的 bill_mapping_name 與 keywords
    回傳比對到的銀行資訊字典 (bank_id, bank_no, bank_name, bill_mapping_name)
    若 strict=True 且查無銀行，則拋出 UnmappedBankError
    """
    if not filename:
        if strict:
            raise UnmappedBankError("", message="未提供檔名無法比對銀行代碼")
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

    if strict:
        raise UnmappedBankError(filename)
    return None

def get_parser(filename: Optional[str] = None):
    """
    根據檔名與 dim_banks.yaml 特徵，回傳對應的 Parser 實例與銀行資訊
    """
    if not filename:
        return None
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



# ==========================================
# Extract 階段進入點 (單檔處理與串流產生器)
# ==========================================
def extract_file(
    filepath: str,
    force: bool = True,
    registry_mgr: Optional[Any] = None
) -> Dict[str, Any]:
    """
    單一帳單檔案解構與安全讀取核心函式 (Per-File Extraction):
    1. 計算檔案雜湊 (SHA-256) 與大小
    2. 比對 FileRegistry (若 force=False 且已成功入庫則標記 SKIPPED)
    3. 自動分派對應 Parser 進行安全解析
    4. 補齊標準維度欄位 (bank_no, bank_name)
    5. 攔截解析例外 (InvalidBillFormatError, MaliciousPayloadDetectedError 等)

    回傳字典結構:
    {
        'filepath': str,
        'filename': str,
        'file_size': int,
        'file_hash': Optional[str],
        'bank_id': Optional[str],
        'bank_no': Optional[str],
        'bank_name': Optional[str],
        'df': Optional[pd.DataFrame],
        'record_count': int,
        'status': 'SUCCESS' | 'SKIPPED' | 'FAILED',
        'error': Optional[str]
    }
    """
    filename = os.path.basename(filepath)
    file_size = os.path.getsize(filepath) if os.path.exists(filepath) else 0
    file_hash = None

    if registry_mgr and os.path.exists(filepath):
        file_hash = registry_mgr.calculate_file_hash(filepath)
        if not force and registry_mgr.is_file_ingested(file_hash):
            logger.info(f"  ⏭️ [SKIP] 檔案已成功解析過 ({file_hash[:8]}...): {filename}")
            return {
                'filepath': filepath,
                'filename': filename,
                'file_size': file_size,
                'file_hash': file_hash,
                'bank_id': None,
                'bank_no': None,
                'bank_name': None,
                'df': None,
                'record_count': 0,
                'status': 'SKIPPED',
                'error': None
            }

    bank_info = get_bank_info(filename)
    parser = get_parser(filename)
    bank_id = bank_info.get('bank_id') if bank_info else None
    bills_mapping_name = bank_info.get('bills_mapping_name') if bank_info else None
    official_bank_name = bank_info.get('bank_name') if bank_info else None
    target_bank_name = bills_mapping_name or official_bank_name or bank_id
    target_bank_no = bank_info.get('bank_no') if bank_info else None
    if target_bank_no:
        target_bank_no = str(target_bank_no).zfill(3)

    if not parser:
        if not bank_info and filename.lower().endswith(('.csv', '.xls', '.xlsx', '.pdf', '.html')):
            logger.warning(f"  ⚠️ [UnmappedBank] 查無可映射銀行代碼: {filename}")
        else:
            logger.debug(f"  ⏭️ 跳過不支援或未定義 Parser 的檔案: {filename}")
        return {
            'filepath': filepath,
            'filename': filename,
            'file_size': file_size,
            'file_hash': file_hash,
            'bank_id': bank_id,
            'bank_no': target_bank_no,
            'bank_name': target_bank_name,
            'df': None,
            'record_count': 0,
            'status': 'SKIPPED',
            'error': 'Unmapped bank or unsupported file type'
        }

    try:
        logger.info(f"處理中: {filename} ...")
        df = parser.parse(filepath)
        if df is not None and not df.empty:
            if const.COL_BANK_NO not in df.columns or df[const.COL_BANK_NO].isna().all() or (df[const.COL_BANK_NO] == '').all():
                if target_bank_no:
                    df[const.COL_BANK_NO] = target_bank_no
            elif target_bank_no:
                df[const.COL_BANK_NO] = df[const.COL_BANK_NO].replace('', target_bank_no).fillna(target_bank_no)

            if 'bank_name' not in df.columns or df['bank_name'].isna().all() or (df['bank_name'] == '').all():
                df['bank_name'] = target_bank_name
            else:
                df['bank_name'] = df['bank_name'].replace('', target_bank_name).fillna(target_bank_name)

            record_cnt = len(df)
            logger.info(f"  ✅ 解析成功 ({record_cnt} 筆): {filename}")
            return {
                'filepath': filepath,
                'filename': filename,
                'file_size': file_size,
                'file_hash': file_hash,
                'bank_id': bank_id,
                'bank_no': target_bank_no,
                'bank_name': target_bank_name,
                'df': df,
                'record_count': record_cnt,
                'status': 'SUCCESS',
                'error': None
            }
        else:
            logger.warning(f"  ⚠️ 解析成功但無資料: {filename}")
            return {
                'filepath': filepath,
                'filename': filename,
                'file_size': file_size,
                'file_hash': file_hash,
                'bank_id': bank_id,
                'bank_no': target_bank_no,
                'bank_name': target_bank_name,
                'df': pd.DataFrame() if df is None else df,
                'record_count': 0,
                'status': 'SUCCESS',
                'error': None
            }

    except InvalidBillFormatError as e:
        logger.warning(f"  ⚠️ [InvalidBillFormat] 略過格式錯位或空檔案 {filename}: {e}")
        return {
            'filepath': filepath,
            'filename': filename,
            'file_size': file_size,
            'file_hash': file_hash,
            'bank_id': bank_id,
            'bank_no': target_bank_no,
            'bank_name': target_bank_name,
            'df': None,
            'record_count': 0,
            'status': 'FAILED',
            'error': str(e)
        }
    except MaliciousPayloadDetectedError as e:
        logger.error(f"  🚨 [SecurityBlock] 攔截並阻斷惡意帳單攻擊 {filename}: {e}")
        return {
            'filepath': filepath,
            'filename': filename,
            'file_size': file_size,
            'file_hash': file_hash,
            'bank_id': bank_id,
            'bank_no': target_bank_no,
            'bank_name': target_bank_name,
            'df': None,
            'record_count': 0,
            'status': 'FAILED',
            'error': str(e)
        }
    except Exception as e:
        logger.error(f"  ❌ 解析失敗 {filename}: {str(e)}")
        return {
            'filepath': filepath,
            'filename': filename,
            'file_size': file_size,
            'file_hash': file_hash,
            'bank_id': bank_id,
            'bank_no': target_bank_no,
            'bank_name': target_bank_name,
            'df': None,
            'record_count': 0,
            'status': 'FAILED',
            'error': str(e)
        }


def extract_raw_data_stream(
    force: bool = True,
    input_dir: Optional[str] = None,
    registry_mgr: Optional[Any] = None
) -> Generator[Dict[str, Any], None, None]:
    """
    掃描資料夾中的帳單檔案並以 Generator 串流模式逐檔產出解析結果：
    徹底消除全量 Concat 的記憶體高峰，並實現單檔錯誤隔離 (Fault Isolation)。
    """
    target_dir = input_dir or (
        const.PROFILE_DATA_DIR
        if (os.path.exists(const.PROFILE_DATA_DIR) and len(os.listdir(const.PROFILE_DATA_DIR)) > 0)
        else const.DATA_DIR
    )

    if not os.path.exists(target_dir):
        logger.error(f"❌ 找不到資料目錄: {target_dir}")
        return

    files = [f for f in os.listdir(target_dir) if not f.startswith('.')]
    logger.info(f"📂 掃描到 {len(files)} 個檔案 ({target_dir})")

    active_registry = registry_mgr if registry_mgr is not None else (FileRegistryManager() if FileRegistryManager else None)

    for filename in files:
        filepath = os.path.join(target_dir, filename)
        if not os.path.isfile(filepath):
            continue
        file_result = extract_file(filepath=filepath, force=force, registry_mgr=active_registry)
        yield file_result


__all__ = [
    'extract_raw_data_stream',
    'extract_file',
    'get_bank_info',
    'get_parser',
    'get_parser_mapping'
]
