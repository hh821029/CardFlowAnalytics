from typing import List

# 定義不列入消費統計、RFM 與 Spending Matrix 的非消費類型交易 (共用常數防護網)
EXCLUDE_TYPES: List[str] = ['繳款', '各項費用', '退刷', '紅利折抵']
EXCLUDE_TRANSACTION_TYPES: List[str] = EXCLUDE_TYPES

from .transaction_query import get_transactions, query_transactions_modular
from .utils import get_clean_df
from .ranking import add_rfm_ranks

__all__ = [
    'EXCLUDE_TYPES',
    'EXCLUDE_TRANSACTION_TYPES',
    'get_transactions',
    'query_transactions_modular',
    'get_clean_df',
    'add_rfm_ranks'
]
