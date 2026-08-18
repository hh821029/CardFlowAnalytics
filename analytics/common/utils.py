# analytics/common/utils.py
"""
Analytics 共用前處理與防護工具
"""
import pandas as pd
from typing import cast, List, Optional

def get_clean_df(df_raw: pd.DataFrame, exclude_types: Optional[List[str]] = None) -> pd.DataFrame:
    """
    過濾掉非消費類型的紀錄 (如繳款、退刷、費用等)
    """
    if df_raw is None or df_raw.empty:
        return pd.DataFrame()
        
    if 'transaction_type' not in df_raw.columns:
        return df_raw.copy()
        
    if exclude_types is None:
        try:
            from analytics.common import EXCLUDE_TYPES
            target_excludes = EXCLUDE_TYPES
        except ImportError:
            target_excludes = ['繳款', '各項費用', '退刷', '紅利折抵']
    else:
        target_excludes = exclude_types
        
    mask = ~df_raw['transaction_type'].isin(target_excludes)
    return cast(pd.DataFrame, df_raw[mask].copy())
