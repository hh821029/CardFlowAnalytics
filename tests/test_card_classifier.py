import sys
import os
import unittest
import pandas as pd

# 加入專案根目錄至 sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import const
from etl.processors.classifier import CardClassifier
from profiles.loaders.config_loader import ConfigLoader

class TestCardClassifierMapping(unittest.TestCase):
    """測試 CardClassifier 的 card_type 映射邏輯"""

    def setUp(self):
        # 載入 example_public 公開脫敏測試資料集之持卡規則進行真實比對測試
        df_rules = ConfigLoader.load_config(base_name='bridge_user_cards', profile_name='example_public', strategy='replace')
        df_gateways = ConfigLoader.load_config(base_name='dim_payment_process', profile_name='example_public', strategy='append')
        self.classifier = CardClassifier(config_dir=const.CONFIG_DIR, rules=df_rules, gateways=df_gateways)

    def test_physical_card_mapping_without_vpc_no(self):
        """測試只有 card_no 而無 vpc_no 時，能否正確映射實體卡卡別 (使用 example_public 範例卡號)"""
        mock_txns = pd.DataFrame([
            {const.COL_CARD_NO: '8888', const.COL_MERCHANT: '家樂福'},
            {const.COL_CARD_NO: '0711', const.COL_MERCHANT: '統一超商'},
            {const.COL_CARD_NO: '5413', const.COL_MERCHANT: '全家便利商店'},
            {const.COL_CARD_NO: '1313', const.COL_MERCHANT: '日本消費'},
        ])
        res = self.classifier.process(mock_txns)
        
        self.assertEqual(res.at[0, const.COL_CARD_TYPE], 'Cube卡')
        self.assertEqual(res.at[1, const.COL_CARD_TYPE], 'Uniopen聯名卡')
        self.assertEqual(res.at[2, const.COL_CARD_TYPE], 'Unicard')
        self.assertEqual(res.at[3, const.COL_CARD_TYPE], '熊本熊雙幣卡(很友好)')

    def test_physical_card_mapping_with_leading_zero(self):
        """測試卡號含前導零時（如 0711 vs 711），能否精確雙向相容比對"""
        mock_txns = pd.DataFrame([
            {const.COL_CARD_NO: '0711', const.COL_MERCHANT: '7-11實體門市'},
            {const.COL_CARD_NO: '711', const.COL_MERCHANT: '7-11實體門市（遺失前導零）'},
        ])
        res = self.classifier.process(mock_txns)
        self.assertEqual(res.at[0, const.COL_CARD_TYPE], 'Uniopen聯名卡')
        self.assertEqual(res.at[1, const.COL_CARD_TYPE], 'Uniopen聯名卡')

    def test_mobile_pay_dual_condition_mapping(self):
        """測試同時有 card_no 與 vpc_no 時的行動支付雙條件比對與交叉清洗 (使用 example_public 範例卡號)"""
        mock_txns = pd.DataFrame([
            # 國泰 Cube 卡 (8888) 綁 HamiPay (vpc_no=0100, 在 dim_payment_process 中)
            {const.COL_CARD_NO: '8888', const.COL_VPC_NO: '0100', const.COL_MERCHANT: '中華電信'},
            # 國泰 Cube 卡 (8888) 綁 SamsungPay (vpc_no=1500, OEM Pay)
            {const.COL_CARD_NO: '8888', const.COL_VPC_NO: '1500', const.COL_MERCHANT: '寶雅'},
        ])
        res = self.classifier.process(mock_txns)
        
        # 驗證卡別均正確映射
        self.assertEqual(res.at[0, const.COL_CARD_TYPE], 'Cube卡')
        self.assertEqual(res.at[1, const.COL_CARD_TYPE], 'Cube卡')

        # 驗證 HamiPay 符合 dim_payment_process 被交叉清洗至 payment_process
        self.assertEqual(res.at[0, const.COL_PAYMENT_PROCESS], 'HamiPay')
        # 驗證 SamsungPay 保留在 vpc_type (OEM Pay)
        self.assertEqual(res.at[1, const.COL_VPC_TYPE], 'SamsungPay')

if __name__ == '__main__':
    unittest.main()
