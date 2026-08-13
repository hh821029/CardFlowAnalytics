# 1. 使用官方 Python 3.11 輕量級基礎映像檔
FROM python:3.11-slim

# 2. 設定容器內的工作目錄
WORKDIR /app

# 3. 設定 Python 環境變數
# 防止 Python 產生 .pyc 檔案，保持容器乾淨
ENV PYTHONDONTWRITEBYTECODE=1
# 防止 Python 緩衝輸出，確保 stdout 和 stderr 的 log 能即時在 Docker 中顯示
ENV PYTHONUNBUFFERED=1

# 4. 安裝系統依賴（可選，通常 pip 安裝 pandas/cryptography 的 wheel 已足夠）
# RUN apt-get update && apt-get install -y --no-install-recommends gcc build-essential && rm -rf /var/lib/apt/lists/*

# 5. 複製 requirements.txt 並安裝依賴
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 6. 複製專案程式碼
# 配合 .dockerignore，configs/、data/、input/、output/、.venv/ 等都不會被複製
COPY . .

# 7. 宣告暴露的 Port (FastAPI 預設為 8000)
EXPOSE 8000

# 8. 啟動 FastAPI 服務
# 為了能讓容器外部連線，此處使用 uvicorn 並強制將 host 綁定在 0.0.0.0
CMD ["uvicorn", "api.server:app", "--host", "0.0.0.0", "--port", "8000"]
