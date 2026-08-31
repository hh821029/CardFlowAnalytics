import sys
import os
import pytest
import pandas as pd

# 路徑設定：加入專案根目錄動態
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import const
from profiles.loaders.config_loader import ConfigLoader


class TestCardDataLoading:
    """測試銀行、信用卡產品主檔與個人持卡橋接表的資料讀取與 3NF 外鍵參照完整性"""

    @pytest.fixture(autouse=True)
    def setup_data(self):
        """測試前的共用資料載入 Fixture (固定使用 example_public 測試資料集)"""
        profile = 'example_public'
        # 1. 載入銀行主檔 dim_banks (優先讀取 dim_banks.yaml)
        bank_yaml = ConfigLoader.load_yaml(base_name='dim_banks', profile_name=profile)
        if bank_yaml and isinstance(bank_yaml, dict) and 'banks' in bank_yaml:
            self.df_banks = pd.DataFrame(bank_yaml['banks'])
        else:
            self.df_banks = ConfigLoader.load_config(base_name='dim_banks', profile_name=profile)
        
        # 2. 載入卡片產品主檔 dim_cards
        self.df_credit_card_products = ConfigLoader.load_config(base_name='dim_credit_card_products', profile_name=profile)
        
        # 3. 載入個人持卡橋接檔 bridge_user_cards
        self.df_user_cards = ConfigLoader.load_config(base_name='bridge_user_cards', profile_name=profile)

    def test_dim_banks_structure(self):
        """測試 1: 驗證 dim_banks (銀行主檔) 的欄位與資料格式"""
        assert not self.df_banks.empty, "❌ dim_banks.csv 不應為空檔"
        
        required_cols = ['bank_no', 'bank_name','bills_mapping_name']
        for col in required_cols:
            assert col in self.df_banks.columns, f"❌ dim_banks 缺少必要欄位: {col}"
            
        # 驗證 bank_code 必須為長度 3 的字串 (如 '808', '013')
        for code in self.df_banks['bank_no'].dropna():
            assert len(str(code).zfill(3)) == 3, f"❌ bank_no 格式不符 (應為3碼): {code}"

    def test_dim_cards_structure_and_fk(self):
        """測試 2: 驗證 dim_cards (產品主檔) 的欄位與外鍵 (bank_no) 參照完整性"""
        assert not self.df_credit_card_products.empty, "❌ dim_credit_card_products.csv 不應為空檔"
        
        required_cols = ['card_id', 'bank_no', 'is_co_branded','is_dual_currency']
        for col in required_cols:
            assert col in self.df_credit_card_products.columns, f"❌ dim_credit_card_products 缺少必要欄位: {col}"

        # 🔗 3NF 外鍵參照測試：dim_cards 的 bank_no 必須存在於 dim_banks 的 bank_no 中
        valid_bank_nos = set(self.df_banks['bank_no'].astype(str).str.lower().str.zfill(3))
        for bank_no in self.df_credit_card_products['bank_no'].dropna():
            assert str(bank_no).lower().zfill(3) in valid_bank_nos, f"❌ 找不到對應的銀行代碼 (FK 參照錯誤): {bank_no}"

    def test_bridge_user_cards_structure_and_fk(self):
        """測試 3: 驗證 bridge_user_cards (個人持卡對照表) 的外鍵 (card_id) 參照完整性"""
        assert not self.df_user_cards.empty, "❌ bridge_user_cards 不應為空檔"
        
        required_cols = ['card_id', 'card_no', 'card_network']
        for col in required_cols:
            assert col in self.df_user_cards.columns, f"❌ bridge_user_cards 缺少必要欄位: {col}"

        # 🔗 3NF 外鍵參照測試：bridge_user_cards 的 card_id 必須存在於 dim_cards 的 card_id 中
        valid_card_ids = set(self.df_credit_card_products['card_id'].astype(str).str.lower())
        for card_id in self.df_user_cards['card_id'].dropna():
            assert str(card_id).lower() in valid_card_ids, f"❌ 找不到對應的信用卡產品 (FK 參照錯誤): {card_id}"

    def test_card_no_formatting(self):
        """測試 4: 驗證卡號末四碼 (card_no) 是否正確認確為 4 位數格式"""
        for card_no in self.df_user_cards['card_no'].dropna():
            card_no_str = str(card_no).strip()
            assert len(card_no_str) == 4 and card_no_str.isdigit(), f"❌ 卡號末四碼格式異常: {card_no_str}"

    def test_card_network_type(self):
        """測試 5: 驗證發卡組織 (card_network) 是否符合 const.CardNetwork 列舉"""
        # 1. 先提取所有合法的 CardNetwork 字串集合 (Set)
        valid_networks = {item.label for item in const.CardNetwork}
        
        # 2. 逐一比對 bridge_user_cards 裡面的發卡組織
        for card_network in self.df_user_cards['card_network'].dropna():
            assert card_network in valid_networks, f"❌ 發卡組織格式異常: '{card_network}' (合法允許值為: {valid_networks})"
    
    def test_smart_card_type(self):
        """測試 6: 驗證電子票證 (smart_card_type) 是否符合 const.SmartCardType 列舉"""
        # 1. 先提取所有合法的 SmartCardType 字串集合 (Set)
        valid_smart_card_types = {item.code for item in const.SmartCardType}
        
        # 2. 逐一比對 bridge_user_cards 裡面的電子票證
        for smart_card_type in self.df_user_cards['smart_card_type'].dropna():
            assert smart_card_type in valid_smart_card_types, f"❌ 電子票證格式異常: '{smart_card_type}' (合法允許值為: {valid_smart_card_types})"

    def test_fx_type(self):
        """測試 7: 驗證雙幣卡幣別 (fx_type) 是否符合 const.Currency 列舉"""
        # 1. 先提取所有合法的 Currency 字串集合 (Set)
        valid_fx_types = {item.code for item in const.Currency}
        
        # 2. bridge_user_cards 先跟 df_credit_card_products 進行 INNER JOIN 合併後取得 is_dual_currency = True 的資料表
        user_cards_subset = self.df_user_cards.drop(columns=['is_dual_currency'], errors='ignore')
        merged_df = pd.merge(
            user_cards_subset, 
            self.df_credit_card_products[['card_id', 'is_dual_currency']], 
            on='card_id', 
            how='inner'
        )

        # 3. 修正：只針對雙幣卡 (is_dual_currency == True) 的列進行幣別驗證
        dual_cards = merged_df[merged_df['is_dual_currency'].astype(str).str.upper() == 'TRUE']
        assert not dual_cards.empty, "❌ 應存在雙幣卡設定"
        for fx_type in dual_cards['fx_type'].dropna():
            assert fx_type in valid_fx_types, f"❌ 幣別格式異常: '{fx_type}'"

    def test_vpc_type(self):
        """測試 8: 驗證虛擬卡類型 (vpc_type) 是否符合 const.VPCType 列舉"""
        # 1. 先提取所有合法的 VPCType 字串集合 (Set)
        valid_vpc_types = {item.code for item in const.VPCType}
        
        # 2. 逐一比對 bridge_user_cards 裡面的虛擬卡類型
        for vpc_type in self.df_user_cards['vpc_type'].dropna():
            assert vpc_type in valid_vpc_types, f"❌ 虛擬卡類型格式異常: '{vpc_type}' (合法允許值為: {valid_vpc_types})"

    def test_card_active_status_and_dates(self):
        """測試 9: 驗證卡片使用狀態 (is_active) 與開停卡日期 (card_start_date, card_end_date) 的邏輯一致性"""
        for idx, row in self.df_user_cards.iterrows():
            card_id = row.get('card_id')
            raw_active = row.get('is_active')
            if isinstance(raw_active, bool):
                is_active = raw_active
            elif pd.notna(raw_active):
                is_active = str(raw_active).strip().upper() in ('TRUE', '1')
            else:
                is_active = False

            start_date_str = str(row.get('card_start_date')).strip() if pd.notna(row.get('card_start_date')) else None
            end_date_str = str(row.get('card_end_date')).strip() if pd.notna(row.get('card_end_date')) else None
            
            # 1. 驗證 card_start_date 必須存在且格式正確 (YYYY-MM-DD)
            assert start_date_str is not None, f"❌ [card_id={card_id}] card_start_date 不可為空"
            try:
                start_date = pd.to_datetime(start_date_str)
            except Exception:
                pytest.fail(f"❌ [card_id={card_id}] card_start_date 日期格式異常: {start_date_str}")
                
            # 2. 當 card_end_date 有值時 (已停卡)
            if end_date_str:
                try:
                    end_date = pd.to_datetime(end_date_str)
                except Exception:
                    pytest.fail(f"❌ [card_id={card_id}] card_end_date 日期格式異常: {end_date_str}")
                
                # 驗證 2a: 停卡日必須大於等於開卡日
                assert end_date >= start_date, (
                    f"❌ [card_id={card_id}] 停卡日 ({end_date_str}) 不能早於開卡日 ({start_date_str})"
                )
                
                # 驗證 2b: 已填停卡日者，is_active 應為 False
                assert is_active is False, (
                    f"❌ [card_id={card_id}] 已有停卡日 ({end_date_str})，但 is_active 為 True"
                )
            
            # 3. 當 card_end_date 為空值時 (使用中)
            else:
                # 驗證 3a: 無停卡日者，is_active 應為 True
                assert is_active is True, (
                    f"❌ [card_id={card_id}] 無停卡日，但 is_active 被標記為 False"
                )

