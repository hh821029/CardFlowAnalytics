# etl/sanitizer.py
"""
CardFlow Analytics 帳單安全過濾與消毒模組 (BillSanitizer)
負責防範 CSV 公式注入 (DDE)、代碼執行、SQL 注入、二進位字元與 ReDoS 攻擊，
並確保日常合法邊界消費 (Disney+, LINE@, -120 退款等) 100% 不受誤殺。
"""

import re
import logging
from typing import Any
import pandas as pd
from etl.exceptions import MaliciousPayloadDetectedError

logger = logging.getLogger(__name__)

# 最大字串長度 (防 ReDoS 災難性回溯)
MAX_STRING_LENGTH = 255

# 致命代碼與破壞性語句 (立即阻斷拋出 MaliciousPayloadDetectedError)
LETHAL_PATTERNS = [
    re.compile(r'__import__\s*\(', re.IGNORECASE),
    re.compile(r'\beval\s*\(', re.IGNORECASE),
    re.compile(r'\bexec\s*\(', re.IGNORECASE),
    re.compile(r'<script[\s>]', re.IGNORECASE),
    re.compile(r'javascript\s*:', re.IGNORECASE),
    re.compile(r';\s*(?:DROP|ALTER|TRUNCATE)\s+(?:TABLE|DATABASE)\b|;\s*DELETE\s+FROM\b', re.IGNORECASE),
    re.compile(r';\s*UPDATE\s+.*?\bSET\b', re.IGNORECASE),
    re.compile(r'\bUNION\s+(?:ALL\s+)?SELECT\b', re.IGNORECASE),
    re.compile(r'\bxp_cmdshell\b', re.IGNORECASE),
    re.compile(r'\bWAITFOR\s+DELAY\b', re.IGNORECASE),
]

# CSV 公式注入 (DDE) 識別特徵：以 =, @, +, - 開頭並帶有指令或函式執行特徵
DDE_CMD_PATTERN = re.compile(
    r'^[=@+\-]\s*(?:cmd(?:\.exe)?|powershell|calc(?:\.exe)?|certutil|mshta|cscript|wscript|bash|sh|curl|wget)\b',
    re.IGNORECASE
)
DDE_PIPE_PATTERN = re.compile(
    r'^[=@+\-]\s*[\'"]?[a-zA-Z0-9_\\]+[\'"]?\s*\|',
    re.IGNORECASE
)
DDE_FUNC_PATTERN = re.compile(
    r'^[=@+\-]\s*(?:SUM|AVERAGE|COUNT|IF|VLOOKUP|HYPERLINK|EXEC|DDE)\s*\(.*?(?:cmd|calc|powershell|http|\|)',
    re.IGNORECASE
)

# 純數字（可含正負號與小數點）正則，用於放行一般數值 (例如 -120, +50, -120.5)
NUMERIC_PATTERN = re.compile(r'^[+\-]?\d+(?:\.\d+)?$')


class BillSanitizer:
    """帳單資料安全消毒與檢核器"""

    @classmethod
    def sanitize_text(cls, value: Any) -> Any:
        """
        對單一文字儲存格進行安全性清洗：
        1. 轉為字串並移除二進位空字元 (Null Byte) 與有害控制字元
        2. 長度截斷防範 ReDoS (>255 字元)
        3. 偵測致命程式碼 / SQL 毀滅指令 (拋出 MaliciousPayloadDetectedError)
        4. 消毒 CSV / Excel 公式注入 (以 ' 前綴轉義，同時放行合法消費)
        """
        if value is None or pd.isna(value):
            return value

        if not isinstance(value, str):
            # 若已經是數值、日期等非字串物件，直接放行
            return value

        val_str = str(value)

        # 1. 過濾二進位 Null Byte 與非法 ASCII 控制字元 (保留 \t, \n, \r)
        if '\x00' in val_str:
            val_str = val_str.replace('\x00', '')

        # 過濾 0x01-0x08, 0x0B-0x0C, 0x0E-0x1F, 0x7F
        val_str = re.sub(r'[\x01-\x08\x0b\x0c\x0e-\x1f\x7f]', '', val_str)

        # 2. 長度截斷防 ReDoS
        if len(val_str) > MAX_STRING_LENGTH:
            logger.warning(f"⚠️ 欄位字串過長 ({len(val_str)} 字元)，強制截斷至 {MAX_STRING_LENGTH} 字元以防 ReDoS: {val_str[:30]}...")
            val_str = val_str[:MAX_STRING_LENGTH]

        # 3. 致命攻擊偵測 (若有則拋出異常阻斷)
        for pattern in LETHAL_PATTERNS:
            match = pattern.search(val_str)
            if match:
                matched_text = match.group(0)
                logger.error(f"🚨 攔截到致命代碼/SQL注入 Payload: {val_str}")
                raise MaliciousPayloadDetectedError(val_str, reason=f"匹配到高風險指令 '{matched_text}'")

        # 4. CSV 公式注入 (DDE) 消毒與防誤殺機制
        stripped = val_str.strip()

        # 防誤殺檢驗：若為純數值 (如 "-120", "+50")，100% 正常放行，絕不轉義
        if NUMERIC_PATTERN.match(stripped):
            return val_str

        # 判斷是否為公式開頭 (=)
        # 若以 '=' 開頭，除非是已經單引號跳脫，否則強制加上單引號跳脫轉義
        if stripped.startswith('='):
            return f"'{val_str}"

        # 若以 @, +, - 開頭，且符合 DDE 指令執行模式 (cmd|, powershell, calc 等)
        if stripped.startswith(('@', '+', '-')):
            if DDE_CMD_PATTERN.search(stripped) or DDE_PIPE_PATTERN.search(stripped) or DDE_FUNC_PATTERN.search(stripped):
                logger.warning(f"⚠️ 偵測到可疑 DDE 公式注入，已自動轉義: {val_str}")
                return f"'{val_str}"

        # 其餘一般文字（如 "Disney+", "Google +1", "LINE@官方店家", "連加＊一般商品"）保持原樣
        return val_str

    @classmethod
    def sanitize_dataframe(cls, df: pd.DataFrame) -> pd.DataFrame:
        """
        對 DataFrame 的所有字串與物件欄位進行全域安全掃描與消毒
        """
        if df.empty:
            return df

        # 檢查欄位名稱本身是否含有致命 Payload
        for col in df.columns:
            for pattern in LETHAL_PATTERNS:
                if pattern.search(str(col)):
                    raise MaliciousPayloadDetectedError(str(col), reason=f"欄位名稱包含危險語法: {col}")

        # 對各欄位進行逐格消毒
        for col in df.columns:
            if df[col].dtype == 'object' or pd.api.types.is_string_dtype(df[col]):
                df[col] = df[col].apply(cls.sanitize_text)

        return df
