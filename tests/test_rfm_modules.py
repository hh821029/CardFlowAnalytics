# tests/test_rfm_modules.py
"""
RFM 客群價值模型核心模組測試套件 (tests/test_rfm_modules.py)
驗證三大核心層次：
1. 基礎 RFM 指標計算與 Rank 百分比排名演算法
2. 商家維度五大客群分群 (Core, Churned, Rising, Active, Dormant)
3. 類別、支付管道與信用卡多維度 RFM 分群、持卡狀態關聯與客單價計算
4. 邊界條件 (空值、除以零、非消費類型過濾) 防禦性驗證
"""
import os
import pytest
import pandas as pd
import numpy as np
from datetime import timedelta, datetime

import const
from tests.fixtures.setup_fixtures import create_mock_fixtures
from etl.extraction import extract_raw_data
from etl.transformation import transform_data
from etl.loading import TransactionIdGenerator

from analytics.rfm.modules import (
    calculate_rfm_base,
    calculate_multi_window_rfm,
    calculate_merchant_rfm,
    calculate_category_rfm,
    calculate_payment_rfm,
    calculate_card_rfm,
    _load_merchant_dim_mapping,
    _load_card_status_mapping
)
from analytics.common import add_rfm_ranks, get_clean_df

# 標準測試用時間視窗設定
TEST_WINDOWS = [
    {'days': None, 'prefix': 'life_'},
    {'days': 180, 'prefix': 'm6_'},
    {'days': 90, 'prefix': 'm3_'},
    {'days': 30, 'prefix': 'm1_'}
]


@pytest.fixture(scope="module")
def mock_dataset_e2e(monkeypatch_module=None):
    """
    透過真實 Pipeline (Extract -> Transform -> TransactionIdGenerator)
    產生標準脫敏測試資料集 (全量 21 筆，覆蓋 2025/10 ~ 2026/06)
    """
    # 確保讀取 example_public 設定
    os.environ["ACTIVE_PROFILE"] = "example_public"
    fixtures = create_mock_fixtures()
    input_dir = os.path.dirname(list(fixtures.values())[0])

    df_raw = extract_raw_data(force=True, input_dir=input_dir)
    assert df_raw is not None and not df_raw.empty, "❌ 抽取脫敏帳單不得為空"

    df_clean = transform_data(df_raw)
    df_with_id = TransactionIdGenerator().generate_and_deduplicate(df_clean)
    assert not df_with_id.empty, "❌ 清洗後資料不得為空"
    assert 'transaction_id' in df_with_id.columns, "❌ 必須包含 transaction_id"
    return df_with_id


# ============================================================================
# 1. 基礎運算與 Rank 演算法測試 (Base Metrics & Ranking)
# ============================================================================
class TestRFMBaseCalculations:
    """測試基礎 RFM 指標彙算與百分比排名工具"""

    def test_calculate_rfm_base_standard(self):
        """驗證 calculate_rfm_base 正確彙算 Recency, Frequency, Monetary"""
        analysis_date = pd.Timestamp("2026-06-10")
        df_sample = pd.DataFrame({
            'transaction_date': pd.to_datetime(['2026-06-01', '2026-06-05', '2026-06-05']),
            'transaction_id': ['tx1', 'tx2', 'tx3'],
            'payment_amount': [100.0, 200.0, 300.0],
            'merchant': ['ShopA', 'ShopA', 'ShopB']
        })

        rfm = calculate_rfm_base(df_sample, analysis_date, group_cols='merchant', prefix='test_')
        assert not rfm.empty
        assert 'test_recency_days' in rfm.columns
        assert 'test_frequency' in rfm.columns
        assert 'test_monetary' in rfm.columns

        # ShopA: 最近消費日 2026-06-05 (10-5 = 5 天), 次數 2, 金額 300
        shop_a = rfm.loc['ShopA']
        assert shop_a['test_recency_days'] == 5
        assert shop_a['test_frequency'] == 2
        assert shop_a['test_monetary'] == 300.0

        # ShopB: 最近消費日 2026-06-05 (5 天), 次數 1, 金額 300
        shop_b = rfm.loc['ShopB']
        assert shop_b['test_recency_days'] == 5
        assert shop_b['test_frequency'] == 1
        assert shop_b['test_monetary'] == 300.0

    def test_calculate_rfm_base_empty_defense(self):
        """驗證空 DataFrame 輸入時安全回傳空 DataFrame"""
        rfm = calculate_rfm_base(pd.DataFrame(), pd.Timestamp.now(), 'merchant')
        assert rfm.empty

    def test_add_rfm_ranks_ordering(self):
        """
        驗證 add_rfm_ranks 之百分比排序方向：
        - Recency: 天數越少 PR 越接近 1.0 (ascending=False)
        - Frequency: 次數越多 PR 越接近 1.0 (ascending=True)
        - Monetary: 金額越大 PR 越接近 1.0 (ascending=True)
        """
        df = pd.DataFrame({
            'recency_days': [1, 10, 100],      # 1 天最佳 -> r_rank 應最高
            'frequency': [1, 5, 20],           # 20 次最佳 -> f_rank 應最高
            'monetary': [100.0, 500.0, 5000.0] # 5000 最佳 -> m_rank 應最高
        }, index=['A', 'B', 'C'])

        ranked = add_rfm_ranks(df)
        assert ranked.loc['A', 'r_rank'] == 1.0
        assert ranked.loc['C', 'r_rank'] == pytest.approx(1/3, rel=1e-2)

        assert ranked.loc['C', 'f_rank'] == 1.0
        assert ranked.loc['A', 'f_rank'] == pytest.approx(1/3, rel=1e-2)

        assert ranked.loc['C', 'm_rank'] == 1.0
        assert ranked.loc['A', 'm_rank'] == pytest.approx(1/3, rel=1e-2)

    def test_calculate_multi_window_rfm_fill_defaults(self):
        """驗證多時間視窗聯集時，歷史消費在近期視窗為空之自動填補 (9999天、0元、0次)"""
        df_sample = pd.DataFrame({
            'transaction_date': pd.to_datetime(['2025-01-01', '2026-06-01']),
            'transaction_id': ['tx_old', 'tx_new'],
            'payment_amount': [1000.0, 500.0],
            'merchant': ['OldShop', 'NewShop']
        })

        windows = [
            {'days': None, 'prefix': 'life_'},
            {'days': 30, 'prefix': 'm1_'}
        ]
        res = calculate_multi_window_rfm(df_sample, 'merchant', windows)
        assert not res.empty

        # OldShop 在 m1_ 視窗無交易，recency 補 9999，frequency 補 0，monetary 補 0
        assert res.loc['OldShop', 'm1_recency_days'] == 9999
        assert res.loc['OldShop', 'm1_frequency'] == 0
        assert res.loc['OldShop', 'm1_monetary'] == 0.0


# ============================================================================
# 2. 商家維度五大客群分群整合測試 (Merchant RFM Segmentation)
# ============================================================================
class TestMerchantRFMSegmentation:
    """使用真實脫敏樣本驗證商家維度 RFM 分群判定與欄位完整性"""

    def test_merchant_rfm_five_segments_coverage(self, mock_dataset_e2e):
        """
        驗證五大分群全部命中 (Core, Churned, Rising, Active, Dormant)：
        1. 統一超商 -> 核心商家 (Core)
        2. 新光三越 -> 流失高價值 (Churned)
        3. APPLE.COM/BILL -> 潛力商家 (Rising)
        4. 全家便利商店 -> 一般活躍 (Active)
        5. 麥當勞 -> 沉睡 (Dormant)
        """
        rfm_df = calculate_merchant_rfm(mock_dataset_e2e, TEST_WINDOWS)
        assert not rfm_df.empty, "❌ 商家 RFM 結果不應為空"

        # 轉為字典以便檢視指定商家之分群
        segment_map = dict(zip(rfm_df['normalized_merchant'], rfm_df['segment']))

        assert segment_map.get('統一超商') == "核心商家 (Core)", \
            f"❌ 統一超商應為核心商家，實測值: {segment_map.get('統一超商')}"

        # 新光三越正規化名稱為 新光三越百貨
        skm_segment = segment_map.get('新光三越百貨') or segment_map.get('新光三越')
        assert skm_segment == "流失高價值 (Churned)", \
            f"❌ 新光三越應為流失高價值，實測值: {skm_segment}"

        assert segment_map.get('APPLE.COM/BILL') == "潛力商家 (Rising)", \
            f"❌ APPLE.COM/BILL 應為潛力商家，實測值: {segment_map.get('APPLE.COM/BILL')}"

        assert segment_map.get('全家便利商店') == "一般活躍 (Active)", \
            f"❌ 全家便利商店應為一般活躍，實測值: {segment_map.get('全家便利商店')}"

        assert segment_map.get('麥當勞') == "沉睡 (Dormant)", \
            f"❌ 麥當勞應為沉睡商家，實測值: {segment_map.get('麥當勞')}"

    def test_merchant_rfm_category_and_subcategory_filling(self, mock_dataset_e2e):
        """驗證商家維度 category 與 sub_category 正常映射且無 '未分類' 殘留"""
        rfm_df = calculate_merchant_rfm(mock_dataset_e2e, TEST_WINDOWS)

        # 麥當勞應為 '連鎖飲食' / '快速主餐'
        mcd = rfm_df[rfm_df['normalized_merchant'] == '麥當勞']
        assert not mcd.empty
        assert mcd['category'].iloc[0] == "連鎖飲食"
        assert mcd['sub_category'].iloc[0] == "快速主餐"

        # 統一超商應為 '便利商店'
        seven = rfm_df[rfm_df['normalized_merchant'] == '統一超商']
        assert not seven.empty
        assert seven['category'].iloc[0] == "便利商店"

    def test_merchant_rfm_lead_columns_order(self, mock_dataset_e2e):
        """驗證輸出 DataFrame 前四欄固定為 ['normalized_merchant', 'category', 'sub_category', 'segment']"""
        rfm_df = calculate_merchant_rfm(mock_dataset_e2e, TEST_WINDOWS)
        expected_lead = ['normalized_merchant', 'category', 'sub_category', 'segment']
        assert list(rfm_df.columns[:4]) == expected_lead

    def test_merchant_rfm_fallback_when_normalized_merchant_missing(self):
        """驗證當輸入資料缺少 normalized_merchant 欄位時，自動回退 merchant_display 或 merchant"""
        df_minimal = pd.DataFrame({
            'transaction_date': pd.to_datetime(['2026-06-01']),
            'transaction_id': ['tx_fallback'],
            'payment_amount': [100.0],
            'merchant_display': ['FallbackStore']
        })
        rfm_df = calculate_merchant_rfm(df_minimal, TEST_WINDOWS)
        assert not rfm_df.empty
        assert 'FallbackStore' in rfm_df['normalized_merchant'].values


# ============================================================================
# 3. 消費類別維度 RFM 測試 (Category RFM)
# ============================================================================
class TestCategoryRFMSegmentation:
    """驗證消費類別維度 RFM 聚合與客群標註"""

    def test_category_rfm_execution(self, mock_dataset_e2e):
        """驗證消費類別 RFM 正常聚合，並產生對應分群標籤"""
        cat_rfm = calculate_category_rfm(mock_dataset_e2e, TEST_WINDOWS)
        assert not cat_rfm.empty
        assert 'category' in cat_rfm.columns
        assert 'segment' in cat_rfm.columns

        categories = cat_rfm['category'].tolist()
        assert '便利商店' in categories
        assert '百貨量販' in categories

        # 驗證分群標籤均符合類別語意 (包含 "類別")
        valid_labels = [
            "核心類別 (Core)", 
            "流失高價值類別 (Churned)", 
            "潛力新興類別 (Rising)", 
            "一般活躍類別 (Active)", 
            "沉睡類別 (Dormant)"
        ]
        for seg in cat_rfm['segment']:
            assert seg in valid_labels, f"❌ 未知的類別分群標籤: {seg}"

    def test_category_rfm_missing_category_column_fallback(self):
        """驗證資料缺少 category 欄位時，預設填補為 '未分類' 並正常完成計算"""
        df_no_cat = pd.DataFrame({
            'transaction_date': pd.to_datetime(['2026-06-01']),
            'transaction_id': ['tx_cat'],
            'payment_amount': [500.0]
        })
        res = calculate_category_rfm(df_no_cat, TEST_WINDOWS)
        assert not res.empty
        assert res['category'].iloc[0] == "未分類"


# ============================================================================
# 4. 付款管道維度 RFM 測試 (Payment RFM)
# ============================================================================
class TestPaymentRFMSegmentation:
    """驗證付款管道維度 RFM 聚合與支付活躍度判定"""

    def test_payment_rfm_execution(self, mock_dataset_e2e):
        """驗證支付管道 RFM 正確聚合 (Line Pay, 一卡通, 實體卡/其他等)"""
        pay_rfm = calculate_payment_rfm(mock_dataset_e2e, TEST_WINDOWS)
        assert not pay_rfm.empty
        assert 'payment_process' in pay_rfm.columns
        assert 'segment' in pay_rfm.columns

        valid_pay_segments = [
            "主力支付 (Main)", 
            "已棄用 (Abandoned)", 
            "輔助支付 (Backup)", 
            "冷門支付 (Rare)"
        ]
        for seg in pay_rfm['segment']:
            assert seg in valid_pay_segments, f"❌ 未知的支付分群標籤: {seg}"

    def test_payment_rfm_empty_channel_fallback(self):
        """驗證 payment_process 為空值時自動填補為 '實體卡/其他'"""
        df_no_pay = pd.DataFrame({
            'transaction_date': pd.to_datetime(['2026-06-01']),
            'transaction_id': ['tx_pay'],
            'payment_amount': [300.0],
            'payment_process': [None]
        })
        res = calculate_payment_rfm(df_no_pay, TEST_WINDOWS)
        assert not res.empty
        assert res['payment_process'].iloc[0] == "實體卡/其他"


# ============================================================================
# 5. 信用卡維度 RFM 測試 (Card RFM)
# ============================================================================
class TestCardRFMSegmentation:
    """驗證信用卡維度雙鍵聚合、持卡狀態關聯與客單價計算"""

    def test_card_rfm_execution_and_status(self, mock_dataset_e2e):
        """驗證信用卡雙鍵聚合 (bank_name, card_type) 與 status, segment 欄位順序"""
        card_rfm = calculate_card_rfm(mock_dataset_e2e, TEST_WINDOWS)
        assert not card_rfm.empty

        expected_lead = ['bank_name', 'card_type', 'status', 'segment']
        assert list(card_rfm.columns[:4]) == expected_lead

        # 驗證包含客單價 avg_ticket 欄位
        assert 'avg_ticket' in card_rfm.columns
        assert pd.api.types.is_integer_dtype(card_rfm['avg_ticket'])

        # 驗證分群標籤為合法的卡片象限
        valid_card_segments = [
            "👑 主要使用卡片",
            "🎯 特定用途使用卡片",
            "🔄 備用卡片",
            "📉 不常用卡片",
            "❄️ 冷凍/沉睡"
        ]
        for seg in card_rfm['segment']:
            assert seg in valid_card_segments, f"❌ 未知的信用卡分群標籤: {seg}"

    def test_card_rfm_filters_out_empty_card_types(self):
        """驗證 card_type 為空值或 NaN 的交易不會納入信用卡 RFM 運算"""
        df_mixed = pd.DataFrame({
            'transaction_date': pd.to_datetime(['2026-06-01', '2026-06-02']),
            'transaction_id': ['c1', 'c2'],
            'bank_name': ['國泰世華', '玉山銀行'],
            'card_type': ['CUBE卡', None],
            'payment_amount': [100.0, 200.0]
        })
        res = calculate_card_rfm(df_mixed, TEST_WINDOWS)
        assert len(res) == 1
        assert res['card_type'].iloc[0] == 'CUBE卡'


# ============================================================================
# 6. 邊界條件與防禦性測試 (Defensive & Edge Cases)
# ============================================================================
class TestRFMDefensiveEdgeCases:
    """驗證極端輸入、異常欄位與非消費類型排除"""

    def test_non_consumption_filtering_via_get_clean_df(self):
        """驗證 get_clean_df 能精準排除繳款、各項費用、退刷與紅利折抵"""
        df_mixed = pd.DataFrame({
            'transaction_type': ['一般消費', '繳款', '各項費用', '退刷', '紅利折抵', '國外交易手續費'],
            'payment_amount': [1000, -1000, 150, -500, -100, 30]
        })
        cleaned = get_clean_df(df_mixed)
        # 排除 繳款, 各項費用, 退刷, 紅利折抵 -> 剩 一般消費 與 國外交易手續費
        assert len(cleaned) == 2
        assert '一般消費' in cleaned['transaction_type'].values
        assert '國外交易手續費' in cleaned['transaction_type'].values

    def test_all_modules_handle_empty_dataframe(self):
        """驗證所有 RFM 模組面對空 DataFrame 均安全回傳空 DataFrame，無拋出例外"""
        empty_df = pd.DataFrame()
        assert calculate_merchant_rfm(empty_df, TEST_WINDOWS).empty
        assert calculate_category_rfm(empty_df, TEST_WINDOWS).empty
        assert calculate_payment_rfm(empty_df, TEST_WINDOWS).empty
        assert calculate_card_rfm(empty_df, TEST_WINDOWS).empty

    def test_single_transaction_edge_case(self):
        """驗證僅有 1 筆交易時，Rank 計算與分群不引發 ZeroDivisionError 或例外"""
        df_single = pd.DataFrame({
            'transaction_date': pd.to_datetime(['2026-06-01']),
            'transaction_id': ['single_1'],
            'payment_amount': [999.0],
            'normalized_merchant': ['OnlyStore'],
            'category': ['便利商店'],
            'payment_process': ['Linepay'],
            'bank_name': ['中信'],
            'card_type': ['LINE Pay卡']
        })
        # 商家 RFM
        m_rfm = calculate_merchant_rfm(df_single, TEST_WINDOWS)
        assert len(m_rfm) == 1
        # 單一商家 life_m_rank 為 1.0 (>=0.8) 且近期次數 > 0 -> 核心商家 (Core)
        assert m_rfm['segment'].iloc[0] == "核心商家 (Core)"

        # 類別 RFM
        c_rfm = calculate_category_rfm(df_single, TEST_WINDOWS)
        assert len(c_rfm) == 1

        # 支付 RFM
        p_rfm = calculate_payment_rfm(df_single, TEST_WINDOWS)
        assert len(p_rfm) == 1

        # 卡片 RFM
        card_rfm = calculate_card_rfm(df_single, TEST_WINDOWS)
        assert len(card_rfm) == 1
