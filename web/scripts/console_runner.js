// web/scripts/console_runner.js
/**
 * 全站共用任務執行與 Console 控制器模組 (TaskConsole)
 * 職責：
 * 1. 管理 EventSource (SSE) 串流任務呼叫
 * 2. 控制台文字日誌渲染、關鍵字上色高亮與自動捲動
 * 3. 全域按鈕鎖定/解鎖與狀態指示列即時更新
 * 4. 一鍵清空日誌與一鍵複製日誌功能
 */

const TaskConsole = (function () {
    let eventSource = null;

    function getElements() {
        return {
            consoleDiv: document.getElementById('console'),
            statusDiv: document.getElementById('status'),
            allButtons: document.querySelectorAll('button:not(.no-lock)')
        };
    }

    function append(message) {
        const { consoleDiv } = getElements();
        if (!consoleDiv) return;

        const span = document.createElement('span');

        // 關鍵字高亮樣式判斷
        if (message.includes('INFO') || message.includes('ℹ️')) {
            span.className = 'log-info';
        } else if (message.includes('WARNING') || message.includes('⚠️')) {
            span.className = 'log-warning';
        } else if (message.includes('ERROR') || message.includes('❌') || message.includes('失敗')) {
            span.className = 'log-error';
        }

        if (message.includes('✅') || message.includes('🎉') || message.includes('成功') || message.includes('完畢') || message.includes('完成')) {
            span.className = 'log-success';
        }

        span.textContent = message + '\n';
        consoleDiv.appendChild(span);

        // 自動向下捲動至底部
        consoleDiv.scrollTop = consoleDiv.scrollHeight;
    }

    function clear() {
        const { consoleDiv, statusDiv } = getElements();
        if (consoleDiv) {
            consoleDiv.innerHTML = '--- 控制台已清空 ---';
        }
        if (statusDiv) {
            statusDiv.className = 'status-box status-idle';
            statusDiv.textContent = '目前狀態：閒置中 (等待指令啟動)';
        }
    }

    function copy() {
        const { consoleDiv } = getElements();
        if (!consoleDiv) return;

        const text = consoleDiv.innerText || consoleDiv.textContent;
        navigator.clipboard.writeText(text).then(() => {
            const copyBtn = document.getElementById('btnCopyLog');
            if (copyBtn) {
                const originalText = copyBtn.innerHTML;
                copyBtn.innerHTML = '✅ 已複製！';
                setTimeout(() => copyBtn.innerHTML = originalText, 2000);
            }
        }).catch(err => {
            alert('複製日誌失敗: ' + err);
        });
    }

    function run(taskType, queryParams = '', customTaskName = '') {
        const { statusDiv, allButtons } = getElements();
        const displayName = customTaskName || taskType;

        // 1. 鎖定按鈕與更新狀態列
        allButtons.forEach(btn => btn.disabled = true);
        if (statusDiv) {
            statusDiv.className = 'status-box status-running';
            statusDiv.textContent = `狀態：任務 [${displayName}] 正在執行中...`;
        }

        append(`\n[${new Date().toLocaleTimeString()}] >>>>> 啟動任務: ${displayName} <<<<<`);

        // 2. 關閉既有 SSE 連線
        if (eventSource) {
            eventSource.close();
        }

        // 3. 建立新 SSE 串流連線
        const queryString = queryParams ? (queryParams.startsWith('?') ? queryParams : `?${queryParams}`) : '';
        const url = `/api/run/${taskType}${queryString}`;

        eventSource = new EventSource(url);

        eventSource.onmessage = function (event) {
            append(event.data);
        };

        eventSource.onerror = function () {
            eventSource.close();
            eventSource = null;

            // 解除鎖定
            allButtons.forEach(btn => btn.disabled = false);
            if (statusDiv) {
                statusDiv.className = 'status-box status-idle';
                statusDiv.textContent = '目前狀態：閒置中 (任務執行結束)';
            }
            append(`[${new Date().toLocaleTimeString()}] >>>>> 任務 ${displayName} 結束 <<<<<\n`);
        };
    }

    return {
        append,
        clear,
        copy,
        run
    };
})();
