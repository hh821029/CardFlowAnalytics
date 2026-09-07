# tests/test_matrix_modules.py
"""
消費交叉透視矩陣核心模組測試套件 (tests/test_matrix_modules.py)
驗證三大核心層次：
1. 支付管道三層分級 (Tier 1 強制 / Tier 2 動態 / 其他) 與固定類別順序 (保險費用置底)
2. 交叉透視樞紐表金額加總與橫向佔比百分比運算 (create_pivot_matrix)
3. 多時間視窗矩陣生成 (generate_spending_matrix) 與 CSV 報表輸出 (save_spending_matrix_reports)
4. 排除特定類別 (銀行費用、未分類) 與極端邊界條件防護
"""
import os
import pytest
import pandas as pd
import numpy as np

import const
from tests.fixtures.setup_fixtures import create_mock_fixtures
from etl.extraction import extract_raw_data
from etl.transformation import transform_data
from etl.loading import TransactionIdGenerator

from analytics.matrix.modules import (
    _load_payment_tiers,
    _standardize_payment_tier_name,
    _get_fixed_category_order,
    create_pivot_matrix,
    generate_spending_matrix,
    save_spending_matrix_reports,
    EXCLUDE_CATEGORIES
)

# 標準測試用時間視窗設定
MATRIX_WINDOWS = [
    {'days': None, 'suffix': 'lifetime'},
    {'days': 180, 'suffix': 'm6'},
    {'days': 90, 'suffix': 'm3'}
]


@pytest.fixture(scope="module")
def mock_dataset_e2e():
    """
    透過真實 Pipeline 產生標準脫敏測試資料集 (全量 21 筆，覆蓋多銀行與多時間軸)
    """
    os.environ["ACTIVE_PROFILE"] = "example_public"
    fixtures = create_mock_fixtures()
    input_dir = os.path.dirname(list(fixtures.values())[0])

    df_raw = extract_raw_data(force=True, input_dir=input_dir)
    assert df_raw is not None and not df_raw.empty

    df_clean = transform_data(df_raw)
    df_with_id = TransactionIdGenerator().generate_and_deduplicate(df_clean)
    assert not df_with_id.empty
    return df_with_id


# ============================================================================
# 1. 支付分層與類別排序演算法測試 (Helpers & Ordering)
# ============================================================================
class TestMatrixHelpers:
    """測試支付分級載入、標準化對照與類別置底演算法"""

    def test_load_payment_tiers(self):
        """驗證從 dim_payment_process 讀取之 Tier 1 與 Tier 2 清單結構"""
        t1, t2 = _load_payment_tiers()
        assert isinstance(t1, list) and len(t1) > 0
        assert isinstance(t2, list) and len(t2) > 0

        # Tier 1 (Priority 1 ~ 7): 必含 Linepay, 街口支付, icash Pay, 一卡通
        assert any("line" in x.lower() for x in t1)
        assert "街口支付" in t1
        assert "一卡通" in t1

        # Tier 2 (Priority 8 ~ 16): 必含玉山Wallet, OPEN錢包等
        assert "玉山Wallet" in t2 or "OPEN錢包" in t2

    @pytest.mark.parametrize("input_val,expected", [
        (None, "實體卡/虛擬卡"),
        ("", "實體卡/虛擬卡"),
        ("實體卡", "實體卡/虛擬卡"),
        ("虛擬卡", "實體卡/虛擬卡"),
        ("實體卡/其他", "實體卡/虛擬卡"),
        ("Line Pay", "Linepay"),
        ("LINEPAY", "Linepay"),
        ("連加", "Linepay"),
        ("街口支付", "街口支付"),
        ("icash Pay", "icash Pay"),
        ("一卡通", "一卡通"),
        ("玉山Wallet", "玉山Wallet"),
        ("OPEN錢包", "OPEN錢包"),
        ("智冠藍新金流", "其他"),  # Priority 29 -> 其他
        ("未知神秘支付", "其他"),  # 未知管道 -> 其他
    ])
    def test_standardize_payment_tier_name(self, input_val, expected):
        """驗證各類支付管道字串皆能精確映射至標準 Tier 或 '其他'"""
        t1, t2 = _load_payment_tiers()
        result = _standardize_payment_tier_name(input_val, t1, t2)
        assert result == expected

    def test_fixed_category_order_insurance_pinned_to_bottom(self):
        """驗證類別排序演算法排除銀行費用且固定將 '保險費用' 排列在最後一列"""
        df_dummy = pd.DataFrame({
            'category': ['便利商店', '保險費用', '百貨量販', '連鎖飲食', '銀行費用', '未分類', '生活服務']
        })
        ordered = _get_fixed_category_order(df_dummy)

        # 1. 驗證排除銀行費用與未分類
        for exc in EXCLUDE_CATEGORIES:
            assert exc not in ordered, f"❌ {exc} 應被排除在類別排序之外"

        # 2. 驗證保險費用必在最後一名
        assert ordered[-1] == "保險費用", f"❌ 保險費用必須為最後一項，實測最後項: {ordered[-1]}"

    def test_fixed_category_order_appends_unknown_categories_before_insurance(self):
        """驗證若出現 dim_categories.yaml 未列出之新合法類別，會追加於一般類別之後、保險費用之前"""
        df_dummy = pd.DataFrame({
            'category': ['百貨量販', '罕見海外特店類別', '保險費用']
        })
        ordered = _get_fixed_category_order(df_dummy)
        assert "罕見海外特店類別" in ordered
        assert ordered[-1] == "保險費用"
        assert ordered.index("罕見海外特店類別") < ordered.index("保險費用")


# ============================================================================
# 2. 交叉透視樞紐表核心運算測試 (create_pivot_matrix)
# ============================================================================
class TestCreatePivotMatrix:
    """測試樞紐表生成、Total_Amount、百分比計算與三層欄位規則"""

    def test_create_pivot_matrix_percentages_and_totals(self):
        """驗證 Total_Amount 金額正確且橫列佔比百分比加總等於 100%"""
        df_sample = pd.DataFrame({
            'category': ['便利商店', '便利商店', '百貨量販'],
            'payment_process': ['Line Pay', '一卡通', '街口支付'],
            'payment_amount': [300.0, 700.0, 2000.0]
        })

        pivot = create_pivot_matrix(df_sample, index_col='category', column_col='payment_process')
        assert not pivot.empty
        assert 'Total_Amount' in pivot.columns

        # 便利商店: Total_Amount = 1000, Linepay = 30%, 一卡通 = 70%
        conv = pivot.loc['便利商店']
        assert conv['Total_Amount'] == 1000.0
        assert conv['Linepay'] == pytest.approx(30.0)
        assert conv['一卡通'] == pytest.approx(70.0)

        # 百貨量販: Total_Amount = 2000, 街口支付 = 100%
        dept = pivot.loc['百貨量販']
        assert dept['Total_Amount'] == 2000.0
        assert dept['街口支付'] == pytest.approx(100.0)

    def test_create_pivot_matrix_tier1_zero_padding(self):
        """驗證 Tier 1 (主要通用支付) 即使全無消費亦強制保留獨立欄位並補 0"""
        df_sample = pd.DataFrame({
            'category': ['便利商店'],
            'payment_process': ['實體卡'],
            'payment_amount': [500.0]
        })
        pivot = create_pivot_matrix(df_sample)
        t1, _ = _load_payment_tiers()

        # 實體卡/虛擬卡 與所有 Tier 1 欄位必須存在
        assert '實體卡/虛擬卡' in pivot.columns
        for t1_col in t1:
            assert t1_col in pivot.columns, f"❌ Tier 1 欄位 [{t1_col}] 應強制存在"
            assert pivot.loc['便利商店', t1_col] == 0.0

    def test_create_pivot_matrix_tier2_dynamic_visibility(self):
        """驗證 Tier 2 通路錢包僅在該期有消費 (sum > 0) 時才出現獨立欄位"""
        df_with_wallet = pd.DataFrame({
            'category': ['便利商店', '百貨量販'],
            'payment_process': ['玉山Wallet', '實體卡'],
            'payment_amount': [100.0, 200.0]
        })
        pivot = create_pivot_matrix(df_with_wallet)

        # 玉山Wallet 有消費 -> 出現
        assert '玉山Wallet' in pivot.columns

        # OPEN錢包 無消費 -> 不得出現 (除非在 Tier 1，但其為 Tier 2)
        _, t2 = _load_payment_tiers()
        if 'OPEN錢包' in t2:
            assert 'OPEN錢包' not in pivot.columns

    def test_create_pivot_matrix_empty_defense(self):
        """驗證空 DataFrame 或缺少欄位時安全回傳空 DataFrame"""
        assert create_pivot_matrix(pd.DataFrame()).empty
        df_missing_col = pd.DataFrame({'category': ['A']})
        assert create_pivot_matrix(df_missing_col, index_col='category', column_col='not_exist').empty


# ============================================================================
# 3. 多時間視窗消費矩陣端到端整合測試 (generate_spending_matrix)
# ============================================================================
class TestGenerateSpendingMatrixE2E:
    """使用真實脫敏樣本驗證完整管線多時間視窗矩陣報表"""

    def test_generate_spending_matrix_excludes_bank_fees(self, mock_dataset_e2e):
        """驗證 generate_spending_matrix 必然排除 '銀行費用' 與 '未分類'"""
        results = generate_spending_matrix(mock_dataset_e2e, time_windows=MATRIX_WINDOWS)
        assert len(results) > 0

        for filename, df_matrix in results:
            for exc in EXCLUDE_CATEGORIES:
                assert exc not in df_matrix.index, f"❌ 矩陣報表 {filename} 中不得包含排除類別: {exc}"

    def test_generate_spending_matrix_pinned_insurance_in_all_windows(self, mock_dataset_e2e):
        """驗證所有時間視窗產出的矩陣中，若有保險費用，必置於縱軸最後一列"""
        results = generate_spending_matrix(mock_dataset_e2e, time_windows=MATRIX_WINDOWS)

        for filename, df_matrix in results:
            if '保險費用' in df_matrix.index:
                assert df_matrix.index[-1] == '保險費用', \
                    f"❌ 報表 {filename} 之最後一列應為保險費用，實為: {df_matrix.index[-1]}"

    def test_generate_spending_matrix_lifetime_amounts_and_tiers(self, mock_dataset_e2e):
        """驗證全期 (Lifetime) 消費矩陣中各類別金額與動態 Tier 2 錢包呈現"""
        results = generate_spending_matrix(mock_dataset_e2e, time_windows=[{'days': None, 'suffix': 'lifetime'}])
        assert len(results) == 1
        filename, df_matrix = results[0]
        assert filename == "spending_matrix_lifetime.csv"

        # 驗證類別金額 (Total_Amount)
        assert df_matrix.loc['保險費用', 'Total_Amount'] == 15000.0
        assert df_matrix.loc['便利商店', 'Total_Amount'] in [38810.0, 38925.0]

        # 驗證本期有消費的 Tier 2 錢包 (玉山Wallet 與 OPEN錢包) 均獨立呈現
        assert '玉山Wallet' in df_matrix.columns
        assert 'OPEN錢包' in df_matrix.columns

        # 驗證無消費之類別 (商圈) Total_Amount 補 0 且佔比為 0
        if '商圈' in df_matrix.index:
            assert df_matrix.loc['商圈', 'Total_Amount'] == 0.0


# ============================================================================
# 4. 報表儲存與序列化測試 (save_spending_matrix_reports)
# ============================================================================
class TestSaveSpendingMatrixReports:
    """驗證消費矩陣 CSV 檔案輸出規格 (UTF-8-SIG, 小數兩位, index_label)"""

    def test_save_spending_matrix_reports_creates_valid_csv(self, mock_dataset_e2e, tmp_path):
        """驗證 save_spending_matrix_reports 產出之 CSV 檔案格式正確"""
        results = generate_spending_matrix(mock_dataset_e2e, time_windows=[{'days': None, 'suffix': 'test'}])
        assert len(results) == 1

        output_dir = str(tmp_path / "matrix_reports")
        save_spending_matrix_reports(results, output_dir=output_dir)

        expected_csv = os.path.join(output_dir, "spending_matrix_test.csv")
        assert os.path.exists(expected_csv), f"❌ 報表檔案未生成: {expected_csv}"

        # 驗證 CSV 內容能正常以 utf-8-sig 讀回且第一欄欄位名稱為 category
        df_read = pd.read_csv(expected_csv, encoding='utf-8-sig')
        assert df_read.columns[0] == 'category'
        assert 'Total_Amount' in df_read.columns
        assert '保險費用' in df_read['category'].values


# ============================================================================
# 5. 極端輸入與邊界條件測試 (Defensive Edge Cases)
# ============================================================================
class TestMatrixDefensiveEdgeCases:
    """驗證極端空值、無有效消費與單筆交易情境"""

    def test_only_bank_fees_returns_empty_results(self):
        """驗證輸入資料若全為銀行費用或未分類時，安全回傳空列表，不引發例外"""
        df_only_fees = pd.DataFrame({
            'transaction_date': pd.to_datetime(['2026-06-01']),
            'transaction_type': ['交易'],
            'category': ['銀行費用'],
            'payment_process': ['實體卡'],
            'payment_amount': [150.0]
        })
        results = generate_spending_matrix(df_only_fees, time_windows=MATRIX_WINDOWS)
        assert results == []

    def test_empty_dataframe_or_none_windows(self):
        """驗證傳入空 DataFrame 或 time_windows=None 均安全回傳空列表"""
        assert generate_spending_matrix(pd.DataFrame(), time_windows=MATRIX_WINDOWS) == []
        assert generate_spending_matrix(pd.DataFrame(), time_windows=MATRIX_WINDOWS) == []
        df_dummy = pd.DataFrame({'category': ['便利商店'], 'payment_amount': [100]})
        assert generate_spending_matrix(df_dummy, time_windows=None) == []

    def test_single_transaction_matrix_calculation(self):
        """驗證僅 1 筆消費時，樞紐矩陣正確計算該支付管道為 100% 佔比"""
        df_single = pd.DataFrame({
            'transaction_date': pd.to_datetime(['2026-06-01']),
            'transaction_type': ['交易'],
            'category': ['連鎖飲食'],
            'payment_process': ['Linepay'],
            'payment_amount': [250.0]
        })
        results = generate_spending_matrix(df_single, time_windows=[{'days': None, 'suffix': 'single'}])
        assert len(results) == 1
        _, matrix = results[0]
        assert matrix.loc['連鎖飲食', 'Total_Amount'] == 250.0
        assert matrix.loc['連鎖飲食', 'Linepay'] == pytest.approx(100.0)
