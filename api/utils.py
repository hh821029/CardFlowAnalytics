# api/utils.py
"""
API 通用工具模組：包含任務並發鎖與非同步 SSE (Server-Sent Events) 串流處理器
"""
import asyncio
import logging
import threading
import os
from typing import Callable, Any

import const

# 控制同時只能有一個任務執行 (Thread Safe)
_task_lock = threading.Lock()

class AsyncStreamHandler(logging.Handler):
    """
    非同步 Log Handler，將 Log 訊息寫入 asyncio.Queue 以供 SSE 讀取
    """
    def __init__(self, queue: asyncio.Queue, loop: asyncio.AbstractEventLoop):
        super().__init__()
        self.queue = queue
        self.loop = loop

    def emit(self, record: logging.LogRecord):
        msg = self.format(record)
        # 確保在非同步環境中安全地將訊息放入 Queue
        self.loop.call_soon_threadsafe(self.queue.put_nowait, msg)

async def run_task_and_stream(task_func: Callable[[], Any], task_name: str, require_db: bool = False):
    """
    執行任務並即時回傳 Log 之 SSE (Server-Sent Events) 串流
    """
    # 1. 檢查任務鎖 (防止衝突)
    if _task_lock.locked():
        yield f"data: ⚠️ [系統忙碌] 任務 '{task_name}' 無法啟動。目前已有其他任務正在執行，請稍後再試。\n\n"
        return

    # 2. 檢查資料庫 (若需要)
    if require_db and not os.path.exists(const.DB_PATH):
        yield f"data: ❌ [找不到資料庫] 任務 '{task_name}' 失敗。原因：找不到主資料庫檔案，請先執行 ETL 載入帳單資料。\n\n"
        return

    queue: asyncio.Queue = asyncio.Queue()
    loop = asyncio.get_running_loop()

    # 設定 Log 攔截
    handler = AsyncStreamHandler(queue, loop)
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    if root_logger.level > logging.INFO or root_logger.level == 0:
        root_logger.setLevel(logging.INFO)
    root_logger.addHandler(handler)

    def task_wrapper():
        # 使用 Thread 執行同步任務，避免阻塞 Event Loop
        with _task_lock:
            try:
                logging.info(f"--- 啟動 {task_name} (Web API 呼叫) ---")
                task_func()
                logging.info(f"--- {task_name} 執行完畢 ---")
            except Exception as e:
                logging.exception(f"❌ {task_name} 執行過程中發生非預期錯誤: {e}")
            finally:
                # 放入 None 作為結束訊號
                loop.call_soon_threadsafe(queue.put_nowait, None)

    # 在獨立執行緒執行同步任務
    thread = threading.Thread(target=task_wrapper)
    thread.start()

    try:
        while True:
            msg = await queue.get()
            if msg is None:
                break
            # 格式化為 SSE 格式
            yield f"data: {msg}\n\n"
    finally:
        # 移除 Handler 釋放資源
        root_logger.removeHandler(handler)
