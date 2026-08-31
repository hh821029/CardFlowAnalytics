import sys
import os
import pytest
import pandas as pd

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from profiles.loaders.user_cards_loader import (
    UserCardsLoader,
    UserCardRelationalBuilder,
    UserCardVLookupEngine
)

class TestUserCardsLoader:
    """測試 UserCardsLoader (bridge_user_cards.json / bridge_user_cards_mock.json 展開與 3NF / Flat 轉換)"""

    def test_load_json(self):
        """測試載入 bridge_user_cards_mock.json"""
        loader = UserCardsLoader(profile_name='example_public')
        data = loader.load_json()
        assert isinstance(data, list)
        assert len(data) > 0

    def test_to_flat_dataframe(self):
        """測試將 JSON 展平為 1D 扁平 DataFrame"""
        loader = UserCardsLoader(profile_name='example_public')
        df_flat = loader.to_flat_dataframe()
        assert isinstance(df_flat, pd.DataFrame)
        
        expected_cols = [
            'card_id', 'bank_no', 'card_type', 'card_no', 'card_network',
            'smart_card_type', 'is_co_branded', 'is_dual_currency',
            'card_start_date', 'status', 'note', 'vpc_no', 'vpc_type'
        ]
        for col in expected_cols:
            assert col in df_flat.columns

        if not df_flat.empty:
            for val in df_flat['vpc_no']:
                assert not isinstance(val, (list, dict))

    def test_to_relational_tables(self):
        """測試將 JSON 拆解為相容 3NF 的三張 DataFrames"""
        loader = UserCardsLoader(profile_name='example_public')
        tables = loader.to_relational_tables()
        
        assert 'user_card_products' in tables
        assert 'user_card_histories' in tables
        assert 'user_card_vpc_pay' in tables

        df_prods = tables['user_card_products']
        df_hists = tables['user_card_histories']
        df_vpcs = tables['user_card_vpc_pay']

        assert isinstance(df_prods, pd.DataFrame)
        assert isinstance(df_hists, pd.DataFrame)
        assert isinstance(df_vpcs, pd.DataFrame)

        if not df_prods.empty:
            assert 'card_id' in df_prods.columns
            assert 'bank_no' in df_prods.columns
        if not df_hists.empty:
            assert 'history_id' in df_hists.columns
            assert 'card_no' in df_hists.columns
        if not df_vpcs.empty:
            assert 'vpc_id' in df_vpcs.columns
            assert 'history_id' in df_vpcs.columns
            assert 'vpc_no' in df_vpcs.columns


class TestUserCardVLookupEngine:
    """測試 UserCardVLookupEngine 精確 VLOOKUP 檢索引擎"""

    def test_existing_vpc_type_rule(self):
        """測試 1: current_vpc_type 已有非空值時，直接保持原值不重新查找"""
        engine = UserCardVLookupEngine(profile_name='example_public')
        res = engine.lookup_vpc(vpc_no='1000', current_vpc_type='LinePay')
        assert res['matched'] is True
        assert res['vpc_type'] == 'LinePay'
        assert res['match_source'] == 'existing_vpc_type'

    def test_valid_4digit_vpc_no_lookup(self):
        """測試 2: vpc_no 為 4 位數字 (如 '1000')，觸發 1-to-1 精準 VLOOKUP 比對"""
        engine = UserCardVLookupEngine(profile_name='example_public')
        res = engine.lookup_vpc(vpc_no='1000', current_vpc_type=None)
        assert res['matched'] is True
        assert res['vpc_type'] == 'SamsungPay'
        assert res['card_type'] == 'Cube卡'
        assert res['bank_no'] == '013'

    def test_invalid_or_non_4digit_vpc_no(self):
        """測試 3: vpc_no 非 4 位數字或為空 (如 'ABC' 或 None)，不觸發 vpc_no 查找且不傳入 card_no"""
        engine = UserCardVLookupEngine(profile_name='example_public')
        res1 = engine.lookup_vpc(vpc_no='ABC', card_no='8888', current_vpc_type=None)
        assert res1['matched'] is False
        assert res1['vpc_type'] is None

        res2 = engine.lookup_vpc(vpc_no=None, card_no='8888', current_vpc_type=None)
        assert res2['matched'] is False
        assert res2['vpc_type'] is None

    def test_enrich_dataframe_zero_inflation(self):
        """測試 4: 擴充交易 DataFrame，確保總筆數 100% 維持不變 (零膨脹)"""
        engine = UserCardVLookupEngine(profile_name='example_public')
        df_test_txns = pd.DataFrame([
            {'txn_id': 1, 'vpc_no': '1000', 'vpc_type': None},
            {'txn_id': 2, 'vpc_no': '8888', 'vpc_type': None},
            {'txn_id': 3, 'vpc_no': '0123', 'vpc_type': None},
            {'txn_id': 4, 'vpc_no': 'INVALID', 'vpc_type': 'ApplePay'},
        ])

        df_result = engine.enrich_dataframe(df_test_txns)
        # 驗證總筆數完全不變
        assert len(df_result) == 4
        # 驗證 '1000' 正確擴充為 SamsungPay
        assert df_result.loc[df_result['txn_id'] == 1, 'vpc_type'].values[0] == 'SamsungPay'
        # 驗證 'INVALID' 但已有 ApplePay 時維持原值
        assert df_result.loc[df_result['txn_id'] == 4, 'vpc_type'].values[0] == 'ApplePay'
