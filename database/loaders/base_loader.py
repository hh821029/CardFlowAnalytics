import pandas as pd
import logging
from abc import ABC, abstractmethod
from typing import Optional, List, Literal

logger = logging.getLogger(__name__)

class BaseDBLoader(ABC):
    """
    [資料載入層 - 基礎類別]
    所有資料庫載入器 (SQLite, PostgreSQL) 的基礎類別。
    提供通用的 DataFrame 清理工具 (日期格式化、NaN/NaT 處理) 及統一的 load 介面。
    """

    @abstractmethod
    def load(
        self, 
        df: pd.DataFrame, 
        table_name: str, 
        mode: Literal['append', 'delete_rows', 'fail', 'replace'] = 'replace', 
        indices: Optional[List[str]] = None
    ) -> None:
        """
        將 DataFrame 寫入資料庫抽象介面
        """
        pass

    @classmethod
    def _sanitize_dataframe(cls, df: pd.DataFrame) -> pd.DataFrame:
        """
        通用的 DataFrame 清理與標準化處理：
        1. 處理日期欄位：將 Timestamp 物件或包含 date 的日期欄位轉為 YYYY-MM-DD 純字串
        2. 處理空值：字串欄位將 NaN, NaT, 'nan', pd.NA 統一轉換為 None (SQL NULL)，數值欄位保持 float/int 型態
        """
        if df.empty:
            return df.copy()

        import datetime
        import numpy as np

        df_final = df.copy()

        # 1. 處理日期與時間欄位：強制將所有 datetime64 / Timestamp / date 物件轉換為 YYYY-MM-DD 字串
        for col in df_final.columns:
            try:
                col_series = df_final[col]
                if col_series.isnull().all():
                    continue

                is_dt_type = pd.api.types.is_datetime64_any_dtype(col_series)
                is_date_name = any(k in col.lower() for k in ['date', 'month'])

                has_dt_instance = False
                if not is_dt_type:
                    valid_idx = col_series.first_valid_index() if hasattr(col_series, 'first_valid_index') else None
                    if valid_idx is not None:
                        sample_val = col_series.loc[valid_idx]
                        has_dt_instance = isinstance(sample_val, (pd.Timestamp, datetime.date, datetime.datetime))

                if is_dt_type or has_dt_instance or is_date_name:
                    dt_s = pd.to_datetime(col_series, format='mixed' if is_date_name else None, errors='coerce')
                    if isinstance(dt_s, pd.Series):
                        df_final[col] = dt_s.dt.strftime('%Y-%m-%d')
            except Exception as e:
                logger.debug(f"跳過非日期欄位 {col}: {e}")

        # 2. 處理布林欄位正規化 (統一洗為標準大寫字串 'TRUE' / 'FALSE' 寫入資料庫)
        bool_cols = {
            'reward_cal_break', 'base_reward_cal_break', 'campaign_reward_cal_break',
            'is_active', 'is_enable_reward_calc', 'is_co_branded', 'is_dual_currency',
            'rfm_exclusion', 'is_nccc_listed'
        }
        for col in df_final.columns:
            if col.lower() in bool_cols:
                def to_bool_str(v):
                    if v is None or pd.isna(v) or v == '':
                        return 'FALSE'
                    if isinstance(v, bool):
                        return 'TRUE' if v else 'FALSE'
                    s = str(v).strip().lower()
                    if s in ('true', '1', 't', 'y', 'yes'):
                        return 'TRUE'
                    return 'FALSE'
                df_final[col] = df_final[col].map(to_bool_str)

        # 3. 處理空值 (字串/object 欄位轉 None；數值/float 欄位保持原本 float64 以避開 to_sql object 轉型失敗)
        for col in df_final.columns:
            if col.lower() not in bool_cols and (pd.api.types.is_object_dtype(df_final[col]) or pd.api.types.is_string_dtype(df_final[col])):
                df_final[col] = df_final[col].replace({pd.NA: None, np.nan: None, 'nan': None, 'None': None, '': None})

        return df_final
