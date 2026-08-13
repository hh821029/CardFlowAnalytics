# database/loaders/schema_enforcer.py
import pandas as pd
import numpy as np
import logging
import const

logger = logging.getLogger(__name__)

class SchemaEnforcer:
    """
    [型別與長度執法模組]
    職責：根據 const.TransactionColumn 的定義強制規範 DataFrame。
    功能：
    1. 強制型別轉換 (float, str, date, bool)
    2. 長度限制 (自動截斷，特別處理卡號)
    3. 異常格式修復 (如 .0 尾巴)
    """

    @staticmethod
    def enforce(df: pd.DataFrame) -> pd.DataFrame:
        if df is None or df.empty:
            return df

        df_enforced = df.copy()

        # 遍歷 Enum 成員進行自動執法
        for col_enum in const.TransactionColumn:
            col_name = col_enum.col_name
            target_type = col_enum.dtype
            max_len = col_enum.max_length

            if col_name not in df_enforced.columns:
                continue

            # --- 1. 型別轉換 ---
            if target_type == 'float':
                if df_enforced[col_name].dtype == 'object':
                    df_enforced[col_name] = df_enforced[col_name].astype(str).str.replace(',', '', regex=False)
                df_enforced[col_name] = pd.to_numeric(df_enforced[col_name], errors='coerce')

            elif target_type == 'str':
                s = df_enforced[col_name].astype(str)
                # 1. 基礎清洗：移除 .0 (float 殘留)、前後空白、處理各種空值字串
                s = s.str.replace(r'\.0$', '', regex=True)
                s = s.str.strip()
                s = s.replace({'nan': None, 'None': None, '': None, 'None.0': None})

                # 2. 長度與特殊邏輯執法
                if max_len:
                    # 找出非空值的索引進行處理
                    mask = s.notna()
                    if mask.any():
                        s_loc = s.loc[mask]
                        if isinstance(s_loc, pd.Series):
                            if col_enum in [const.TransactionColumn.CARD_NO, const.TransactionColumn.VPC_NO, const.TransactionColumn.BANK_NO]:
                                s.loc[mask] = s_loc.str.zfill(max_len).str[-max_len:]
                            else:
                                s.loc[mask] = s_loc.str.slice(0, max_len)

                df_enforced[col_name] = s

            elif target_type == 'date':
                if not pd.api.types.is_datetime64_any_dtype(df_enforced[col_name]):
                    df_enforced[col_name] = pd.to_datetime(df_enforced[col_name], format='mixed', errors='coerce')

            elif target_type == 'bool':
                df_enforced[col_name] = df_enforced[col_name].map({'True': True, 'False': False, True: True, False: False, 1: True, 0: False, '1': True, '0': False})
                df_enforced[col_name] = df_enforced[col_name].fillna(False).astype(bool)

        return df_enforced

    @staticmethod
    def list_inconsistent_columns(df: pd.DataFrame):
        """
        [診斷用] 列出目前 DataFrame 中與 Schema 定義不符的欄位 (供開發者檢查)
        """
        inconsistencies = []
        for col_name, target_type in const.COLUMN_TYPES.items():
            if col_name in df.columns:
                current_dtype = str(df[col_name].dtype)
                if target_type == 'str' and 'float' in current_dtype:
                    inconsistencies.append(f"⚠️ {col_name}: Current={current_dtype}, Target=str")
                elif target_type == 'float' and 'object' in current_dtype:
                    inconsistencies.append(f"⚠️ {col_name}: Current={current_dtype}, Target=float")
        
        if inconsistencies:
            logger.warning("Detected schema inconsistencies:\n" + "\n".join(inconsistencies))
        return inconsistencies
