import os
import sys

# 確保專案根目錄納入 sys.path
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

import shutil
import hashlib
from typing import cast
import pandas as pd
import numpy as np
import logging

import const
from etl.etl_api import run_etl_pipeline, run_stage2_pipeline
from database.loaders.db_reader import DBReader

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

MOCK_DATA_DIR = os.path.join(const.ROOT_DIR, "profiles", "example_public", "data")
OUTPUT_DIR = const.OUTPUT_DIR
BASELINE_CSV = os.path.join(OUTPUT_DIR, "result_baseline.csv")
COMPARISON_CSV = os.path.join(OUTPUT_DIR, "result_stage2_comparison.csv")
REPORT_MD = os.path.join(OUTPUT_DIR, "dual_track_verification_report.md")


def get_df_hash(df: pd.DataFrame) -> str:
    """計算 DataFrame 排序後純文字內容的 SHA-256 雜湊值"""
    df_sorted = df.sort_values(by=list(df.columns)).reset_index(drop=True)
    csv_str = df_sorted.to_csv(index=False)
    return hashlib.sha256(csv_str.encode('utf-8')).hexdigest()


def run_verification():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    logger.info("🏁 啟動雙軌驗證流程 (Dual-Track Verification)...")

    # ==========================================
    # 步驟 1: 基準測試 (Baseline - 全量實體檔案解析)
    # ==========================================
    logger.info(f"📁 [Baseline] 執行全量實體檔案解析入庫: {MOCK_DATA_DIR}")
    success_base = run_etl_pipeline(force=True, input_dir=MOCK_DATA_DIR)
    assert success_base, "Baseline 全量 ETL 執行失敗！"

    # 備份 Baseline 輸出的 CSV
    src_final = os.path.join(OUTPUT_DIR, "result_final.csv")
    assert os.path.exists(src_final), "Baseline 未產生 result_final.csv！"
    shutil.copyfile(src_final, BASELINE_CSV)

    # 讀取 Baseline 之 all_transactions 表
    df_db_base = DBReader.read_sql("SELECT * FROM all_transactions ORDER BY transaction_id")
    df_csv_base = pd.read_csv(BASELINE_CSV)

    logger.info(f"✅ [Baseline] 完成，DB 筆數: {len(df_db_base)}，CSV 筆數: {len(df_csv_base)}")

    # ==========================================
    # 步驟 2: 對比測試 (Comparison - 獨立重跑 Stage 2)
    # ==========================================
    logger.info("🔄 [Comparison] 執行獨立重跑 Stage 2 (讀取 raw_transactions，不碰實體檔案)...")
    success_comp = run_stage2_pipeline(force=True)
    assert success_comp, "Stage 2 獨立重跑流程失敗！"

    # 備份 Comparison 輸出的 CSV
    assert os.path.exists(src_final), "Comparison 未產生 result_final.csv！"
    shutil.copyfile(src_final, COMPARISON_CSV)

    # 讀取 Comparison 之 all_transactions 表
    df_db_comp = DBReader.read_sql("SELECT * FROM all_transactions ORDER BY transaction_id")
    df_csv_comp = pd.read_csv(COMPARISON_CSV)

    logger.info(f"✅ [Comparison] 完成，DB 筆數: {len(df_db_comp)}，CSV 筆數: {len(df_csv_comp)}")

    # ==========================================
    # 步驟 3: 雙軌內容嚴格比對 (Compare & Verify)
    # ==========================================
    logger.info("🔍 開始執行比對分析...")

    # A. 筆數比對
    db_count_match = len(df_db_base) == len(df_db_comp)
    csv_count_match = len(df_csv_base) == len(df_csv_comp)

    # B. 欄位清單比對
    db_cols_match = list(df_db_base.columns) == list(df_db_comp.columns)
    csv_cols_match = list(df_csv_base.columns) == list(df_csv_comp.columns)

    # C. DB 內容一致性比對
    # 排除更新時間戳等動態欄位
    ignore_cols = {'created_at', 'updated_at'}
    check_cols_db: list[str] = [str(c) for c in df_db_base.columns if c not in ignore_cols]
    
    df_db_base_clean = cast(pd.DataFrame, df_db_base[check_cols_db].fillna('').astype(str))
    df_db_comp_clean = cast(pd.DataFrame, df_db_comp[check_cols_db].fillna('').astype(str))

    if db_count_match and db_cols_match:
        diff_db_cells = int(np.sum(df_db_base_clean.to_numpy() != df_db_comp_clean.to_numpy()))
    else:
        diff_db_cells = abs(len(df_db_base_clean) - len(df_db_comp_clean)) or -1
    db_exact_match = (diff_db_cells == 0)

    # D. CSV 內容一致性比對 (依 transaction_id 排序對齊)
    check_cols_csv: list[str] = [str(c) for c in df_csv_base.columns if c not in ignore_cols]
    sort_col = 'transaction_id' if 'transaction_id' in df_csv_base.columns else check_cols_csv[0]
    df_csv_base_clean = cast(pd.DataFrame, df_csv_base.sort_values(by=sort_col).reset_index(drop=True)[check_cols_csv].fillna('').astype(str))
    df_csv_comp_clean = cast(pd.DataFrame, df_csv_comp.sort_values(by=sort_col).reset_index(drop=True)[check_cols_csv].fillna('').astype(str))

    if csv_count_match and csv_cols_match:
        diff_csv_cells = int(np.sum(df_csv_base_clean.to_numpy() != df_csv_comp_clean.to_numpy()))
    else:
        diff_csv_cells = abs(len(df_csv_base_clean) - len(df_csv_comp_clean)) or -1
    csv_exact_match = (diff_csv_cells == 0)



    # SHA-256 雜湊
    hash_base_db = get_df_hash(df_db_base_clean)
    hash_comp_db = get_df_hash(df_db_comp_clean)
    hash_match = (hash_base_db == hash_comp_db)

    # E. 核心商業特徵個別動態檢驗 (Dynamic Feature Verification)
    def check_feature_match(df1, df2, cols):
        valid_cols = [c for c in cols if c in df1.columns and c in df2.columns]
        if not valid_cols:
            return True, 0
        if len(df1) != len(df2):
            return False, abs(len(df1) - len(df2))
        diff_count = 0
        for c in valid_cols:
            diff_count += int(np.sum(df1[c].to_numpy() != df2[c].to_numpy()))
        return (diff_count == 0), diff_count

    # 1. 唯一鍵值
    id_match, id_diff = check_feature_match(df_db_base_clean, df_db_comp_clean, ['transaction_id'])
    
    # 2. 商家清洗特徵 (涵蓋 DB 與 CSV 的 merchant, display, normalized)
    m_db_match, m_db_diff = check_feature_match(df_db_base_clean, df_db_comp_clean, ['merchant_name'])
    m_csv_match, m_csv_diff = check_feature_match(df_csv_base_clean, df_csv_comp_clean, ['merchant', 'merchant_display', 'normalized_merchant'])
    merchant_diff = m_db_diff + m_csv_diff
    merchant_match = (merchant_diff == 0)

    # 3. 卡片歸戶與支付 (涵蓋 card_id, card_no, card_type, payment_process, vpc_type)
    c_db_match, c_db_diff = check_feature_match(df_db_base_clean, df_db_comp_clean, ['card_id', 'card_no', 'payment_process', 'vpc_type'])
    c_csv_match, c_csv_diff = check_feature_match(df_csv_base_clean, df_csv_comp_clean, ['card_type'])
    card_diff = c_db_diff + c_csv_diff
    card_match = (card_diff == 0)

    # 4. 交易分類 (transaction_type)
    type_match, type_diff = check_feature_match(df_db_base_clean, df_db_comp_clean, ['transaction_type'])

    is_100_percent_match = (
        db_count_match and db_cols_match and db_exact_match and 
        csv_exact_match and hash_match and id_match and 
        merchant_match and card_match and type_match
    )

    # ==========================================
    # 步驟 4: 輸出 Markdown 比對檢驗報告
    # ==========================================
    report_content = f"""# 雙軌驗證報告 (Dual-Track Verification Report)
- **執行時間**: {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S')}
- **測試資料來源**: `{MOCK_DATA_DIR}`
- **驗證規範依據**: `GEMINI.md` 第 3 節核心變更驗證規範 (Refactoring Protocol)

---

## 一、 比對結果總表

| 檢驗維度 | 基準結果 (Baseline: 檔案掃描全量) | 對比結果 (Comparison: Stage 2 重跑) | 判定狀態 |
| :--- | :--- | :--- | :---: |
| **資料庫表總筆數** | {len(df_db_base)} 筆 | {len(df_db_comp)} 筆 | {"✅ 100% 一致" if db_count_match else "❌ 不一致"} |
| **匯出 CSV 總筆數** | {len(df_csv_base)} 筆 | {len(df_csv_comp)} 筆 | {"✅ 100% 一致" if csv_count_match else "❌ 不一致"} |
| **資料表欄位結構** | {len(df_db_base.columns)} 欄 | {len(df_db_comp.columns)} 欄 | {"✅ 100% 一致" if db_cols_match else "❌ 不一致"} |
| **資料表內容相異格數** | 0 格 | {diff_db_cells} 格差異 | {"✅ 100% 完全相符" if db_exact_match else "❌ 存在差異"} |
| **CSV 內容相異格數** | 0 格 | {diff_csv_cells} 格差異 | {"✅ 100% 完全相符" if csv_exact_match else "❌ 存在差異"} |
| **SHA-256 內容雜湊比對** | `{hash_base_db[:16]}...` | `{hash_comp_db[:16]}...` | {"✅ 雜湊完全吻合" if hash_match else "❌ 雜湊相異"} |

---

## 二、 核心商業特徵比對詳情 (動態檢驗)

1. **唯一鍵值 (transaction_id)**: {"✅ 100% 保持一致，Stage 2 成功復用 Stage 1 確立之主鍵" if id_match else f"❌ 發現 {id_diff} 筆鍵值不一致"}
2. **商家清洗特徵 (merchant / display / normalized)**: {"✅ 100% 保持一致，正規化與前後綴拆分結果完全相同" if merchant_match else f"❌ 發現 {merchant_diff} 格商家特徵不一致"}
3. **卡片歸戶與支付 (card_id / card_type / payment_process)**: {"✅ 100% 保持一致，第三方支付管道與卡別標記完全吻合" if card_match else f"❌ 發現 {card_diff} 格卡片/支付特徵不一致"}
4. **交易分類 (transaction_type)**: {"✅ 100% 保持一致，交易類型判定完全相同" if type_match else f"❌ 發現 {type_diff} 筆交易分類不一致"}

---

## 三、 決策結論

> **驗證結論**: **{"【完全一致】雙軌驗證通過！Stage 2 解耦成功，新舊邏輯輸出 100% 吻合。" if is_100_percent_match else "【不一致】雙軌驗證未通過，請排查差異原因。"}**
- 基準檔案已存檔於: `output/result_baseline.csv`
- 對比檔案已存檔於: `output/result_stage2_comparison.csv`
"""


    with open(REPORT_MD, "w", encoding="utf-8") as f:
        f.write(report_content)

    logger.info(f"📄 比對報告已產出至: {REPORT_MD}")

    if is_100_percent_match:
        logger.info("🎉 雙軌驗證 100% 完全吻合！通過！")
    else:
        logger.error(f"❌ 雙軌比對不一致！DB 差異格數: {diff_db_cells}, CSV 差異格數: {diff_csv_cells}")

    return is_100_percent_match


if __name__ == "__main__":
    result = run_verification()
    exit(0 if result else 1)
