# etl/exceptions.py
"""
CardFlow Analytics ETL 專屬例外模組
定義帳單安全掃描、格式錯位與銀行分派之自訂例外類別
"""

class ETLException(Exception):
    """ETL 模組基礎例外"""
    pass


class UnmappedBankError(ETLException):
    """【狀況一】查無銀行映射或檔名無特徵之例外"""
    def __init__(self, filename: str, message: str = "檔名無法比對至任何合法銀行代碼 (dim_banks.yaml)"):
        self.filename = filename
        self.message = f"{message}: {filename}"
        super().__init__(self.message)


class InvalidBillFormatError(ETLException):
    """【狀況三】帳單格式錯誤、0 位元組空檔案或缺少必要標題列"""
    def __init__(self, filepath: str, reason: str = "帳單格式錯位或缺乏關鍵 Header"):
        self.filepath = filepath
        self.reason = reason
        self.message = f"帳單結構無效 ({reason}): {filepath}"
        super().__init__(self.message)


class MaliciousPayloadDetectedError(ETLException):
    """【狀況二】偵測到危險代碼注入、命令執行或毀滅性 SQL 語句"""
    def __init__(self, payload: str, reason: str = "偵測到惡意程式碼或指令注入攻擊"):
        self.payload = payload
        self.reason = reason
        self.message = f"🚨 安全阻斷 ({reason}): {payload[:100]}"
        super().__init__(self.message)
