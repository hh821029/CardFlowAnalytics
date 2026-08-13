# rfm_analysis/__init__.py
"""
RFM 分析模組
包含 RFM 多維度分群計算與消費矩陣分析
"""
from .rfm_modules import (
    calculate_merchant_rfm,
    calculate_payment_rfm,
    calculate_card_rfm,
    generate_spending_matrix
)
from . import rfm_utils

__all__ = [
    'calculate_merchant_rfm',
    'calculate_payment_rfm',
    'calculate_card_rfm',
    'generate_spending_matrix',
    'rfm_utils'
]
