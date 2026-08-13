import pdfplumber
import pandas as pd
import re
from typing import List, Dict, Optional, Any
import const
from etl.parsers.base import BasePdfParser

class SinopacBillParser(BasePdfParser):
    def __init__(self, bank_id_or_keyword: Optional[str] = None, **kwargs):
        super().__init__(bank_id_or_keyword=bank_id_or_keyword, **kwargs)

    def parse(self, pdf_path: str) -> pd.DataFrame:
        """
        三明治結構修復版：
        針對被切成 3 行的交易紀錄進行邏輯合併。
        """
        all_clean_rows = []
        found_header = False  # 追蹤是否已跨過「消費日」標題列（跨頁面持續）
        
        try:
            with pdfplumber.open(pdf_path) as pdf:
                for page in pdf.pages:
                    # 使用 lines 策略
                    tables = page.extract_tables(table_settings={
                        "vertical_strategy": "lines",
                        "horizontal_strategy": "lines"
                    })

                    for table in tables:
                        num_rows = len(table)

                        if not found_header:
                            # 尚未找到標題列：掃描此 table 找「消費日」
                            header_idx = None
                            for hi, hrow in enumerate(table):
                                if any(cell and '消費日' in cell for cell in hrow):
                                    header_idx = hi
                                    break
                            if header_idx is None:
                                continue  # 此 table 無標題列，略過（如摘要表）
                            found_header = True
                            row_start = header_idx + 1  # 標題列以上全略過
                            current_amount_col = 6  # 第一頁標題表格：金額在 col_6
                        else:
                            row_start = 0  # 第 2 頁以後直接從第一行開始
                            current_amount_col = 4  # 第 2 頁以後：金額在 col_4

                        for i in range(row_start, num_rows):
                            row = table[i]
                            
                            # 1. 錨點偵測 (呼叫基底類別方法)
                            # 欄數不足以取得金額欄，視為結構異常直接跳過
                            if not self._is_date_pattern(row[0]) or len(row) <= current_amount_col:
                                continue
                                
                            # 2. 開始組裝 (Reconstruction)
                            try:
                                desc_parts = []
                                
                                # A. 檢查上一行 (Top Bun)
                                if i > 0:
                                    prev_row = table[i-1]
                                    if not self._is_date_pattern(prev_row[0]) and len(prev_row) > 3:
                                        part = f"{prev_row[3] or ''}".strip()
                                        if part: desc_parts.append(part)

                                # B. 檢查當前行 (Meat)
                                if len(row) > 3:
                                    curr_part = f"{row[3] or ''}".strip()
                                    if curr_part: desc_parts.append(curr_part)

                                # C. 檢查下一行 (Bottom Bun)
                                if i < num_rows - 1:
                                    next_row = table[i+1]
                                    if not self._is_date_pattern(next_row[0]) and len(next_row) > 3:
                                        part = f"{next_row[3] or ''}".strip()
                                        if part: desc_parts.append(part)
                                
                                # 合併說明
                                full_description = "".join(desc_parts).replace('\r\n', '').replace('\n', '').replace('\r', '').strip()

                                # 建立資料物件 (使用基底定義的 target_columns)
                                _card_raw = row[2].strip() if row[2] is not None else ''
                                _card_match = re.match(r'\d+', _card_raw)
                                item = {
                                    const.COL_TXN_DATE: row[0],
                                    const.COL_POST_DATE: row[1],
                                    const.COL_CARD_NO: _card_match.group() if _card_match else _card_raw,
                                    const.COL_MERCHANT: full_description,
                                    const.COL_PAY_AMOUNT: self._clean_pdf_amount(
                                        row[current_amount_col], strip_prefix='$'  # 永豐帳單金額前綴為 $ (如 $-300)
                                    ), # 呼叫基底類別方法
                                    const.COL_CONV_DATE: None,
                                    const.COL_CURR_AMOUNT: 0.0
                                }
                                all_clean_rows.append(item)

                            except IndexError:
                                continue

            # 轉成 DataFrame
            df = pd.DataFrame(all_clean_rows, columns=self.target_columns)
            # 加上銀行名稱標籤
            df[const.COL_BANK_NAME] = self.bank_name

            # 呼叫 BaseBillParser 的通用處理 (日期轉換與型態強制)
            df = self.transform_common_dates(df, pdf_path)
            
            # 最終正規化 (補齊 TWD 等)
            df = self._finalize_normalization(df)
            
            df = self._enforce_dtypes(df)
            return df

        except Exception as e:
            print(f"Error parsing Sinopac PDF: {e}")
            return pd.DataFrame(columns=self.target_columns)
