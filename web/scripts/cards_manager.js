/**
 * web/scripts/cards_manager.js
 * 個人信用卡視覺化管理面板 - 前端互動邏輯模組
 */

let cardsData = [];
let availableBanks = [];
let bankMap = {};
let cardProducts = [];
let cardProductsMap = {};

// 頁面載入初始化
document.addEventListener('DOMContentLoaded', async () => {
    await checkAuthStatus();
    await loadBanks();
    await loadCardProducts();
    await loadCardsJson();
});

// 檢查驗證狀態
async function checkAuthStatus() {
    try {
        const res = await fetch('/api/auth/status');
        const data = await res.json();
        const userBadge = document.getElementById('userBadge');
        if (data.logged_in) {
            if (userBadge) {
                userBadge.innerText = `👤 帳號: ${data.username} (${data.active_profile})`;
                userBadge.style.display = 'inline-flex';
            }
        } else {
            window.location.href = 'login.html';
        }
    } catch (e) {
        console.error('Auth check error:', e);
    }
}

// 登出
async function logout() {
    await fetch('/api/auth/logout', { method: 'POST' });
    window.location.href = 'login.html';
}

// 讀取銀行清單 (from dim_banks.yaml API)
async function loadBanks() {
    try {
        const res = await fetch('/api/cards/banks');
        const data = await res.json();
        if (res.ok && data.status === 'ok') {
            availableBanks = data.banks || [];
            bankMap = {};
            availableBanks.forEach(b => {
                const bNo = String(b.bank_no).trim();
                const bName = b.bills_mapping_name || b.bank_name || bNo;
                bankMap[bNo] = bName;
            });
            populateBankSelect();
            if (cardProducts.length > 0) {
                populateCardTypeSelect();
            }
        }
    } catch (err) {
        console.error('Failed to load banks:', err);
    }
}

function populateBankSelect() {
    const select = document.getElementById('inputBankNo');
    if (!select) return;
    if (availableBanks.length === 0) {
        select.innerHTML = `<option value="">無可用銀行</option>`;
        return;
    }
    select.innerHTML = availableBanks.map(b => {
        const bNo = String(b.bank_no).trim();
        const bName = b.bills_mapping_name || b.bank_name || bNo;
        return `<option value="${bNo}">${bNo} (${bName})</option>`;
    }).join('');
}

// 讀取卡片產品定義 (from dim_credit_card_products.csv API)
async function loadCardProducts() {
    try {
        const res = await fetch('/api/cards/products');
        const data = await res.json();
        if (res.ok && data.status === 'ok') {
            cardProducts = data.products || [];
            cardProductsMap = {};
            cardProducts.forEach(p => {
                if (p.card_id) {
                    cardProductsMap[p.card_id] = p;
                }
            });
            populateCardTypeSelect();
        }
    } catch (err) {
        console.error('Failed to load card products:', err);
    }
}

function populateCardTypeSelect() {
    const select = document.getElementById('inputCardType');
    if (!select) return;
    if (cardProducts.length === 0) {
        select.innerHTML = `<option value="">無可用卡片產品</option>`;
        return;
    }
    select.innerHTML = cardProducts.map(p => {
        const cId = p.card_id || '';
        const cType = p.card_type || cId;
        const bNo = String(p.bank_no || '').trim();
        const bName = bankMap[bNo] ? `${bNo} (${bankMap[bNo]})` : bNo;
        return `<option value="${cId}" data-bank="${bNo}" data-type="${cType}">${cType} — ${bName}</option>`;
    }).join('');
    onCardTypeChange();
}

function onCardTypeChange() {
    const select = document.getElementById('inputCardType');
    if (!select || select.options.length === 0) return;
    const selectedOption = select.options[select.selectedIndex];
    if (!selectedOption) return;

    const cardId = selectedOption.value;
    const product = cardProductsMap[cardId];

    if (product) {
        document.getElementById('inputCardId').value = product.card_id;
        const bankSelect = document.getElementById('inputBankNo');
        if (bankSelect) {
            bankSelect.value = String(product.bank_no).trim();
        }
    } else {
        const bankNo = selectedOption.getAttribute('data-bank') || '';
        document.getElementById('inputCardId').value = cardId;
        const bankSelect = document.getElementById('inputBankNo');
        if (bankSelect && bankNo) {
            bankSelect.value = bankNo;
        }
    }
}

// 讀取卡片 JSON
async function loadCardsJson() {
    try {
        const res = await fetch('/api/cards/json');
        const data = await res.json();
        if (res.ok && data.status === 'ok') {
            cardsData = data.cards || [];
            const label = document.getElementById('filePathLabel');
            if (label) {
                label.innerText = data.file_path || 'bridge_user_cards.json';
            }
            renderCards();
        } else {
            showAlert('❌ 載入失敗: ' + (data.detail || '未知錯誤'), 'danger');
        }
    } catch (err) {
        showAlert('❌ 無法連線 API 伺服器: ' + err.message, 'danger');
    }
}

// 渲染卡片清單 UI（精巧網格化設計）
function renderCards() {
    const container = document.getElementById('cardsGrid');
    if (!container) return;

    if (!cardsData || cardsData.length === 0) {
        container.innerHTML = `
            <div style="grid-column: 1 / -1; text-align: center; color: #94a3b8; padding: 40px; background: rgba(15,23,42,0.4); border-radius: 12px; border: 1px dashed rgba(255,255,255,0.1);">
                💳 目前尚無任何卡片設定。點擊上方「➕ 新增卡片產品」開始建立！
            </div>
        `;
        return;
    }

    container.innerHTML = cardsData.map((card, cIdx) => {
        const bNo = String(card.bank_no || '').trim();
        const bDisplay = bankMap[bNo] ? `${bNo} ${bankMap[bNo]}` : (bNo || '---');
        const histories = card.card_history || [];

        return `
        <div class="card-item">
            <div class="card-item-header">
                <div class="card-item-title-wrap">
                    <div class="card-item-tags">
                        <span class="bank-chip">${bDisplay}</span>
                        <span class="card-id-text">${card.card_id || ''}</span>
                    </div>
                    <div class="card-title-text">${card.card_type || '未命名卡片'}</div>
                </div>
                <div class="card-header-actions">
                    <button class="btn-sm btn-edit" title="編輯產品主檔" onclick="openEditCardModal(${cIdx})">✏️ 編輯</button>
                    <button class="btn-sm btn-success" title="新增換卡履歷" onclick="openAddHistoryModal(${cIdx})">➕ 履歷</button>
                    <button class="btn-sm btn-danger" title="刪除整張卡片" onclick="deleteCard(${cIdx})">🗑️</button>
                </div>
            </div>

            <div class="history-list">
                ${histories.length === 0 ? `
                    <div class="history-empty">尚未設定任何卡號履歷</div>
                ` : histories.map((hist, hIdx) => `
                    <div class="history-card">
                        <div class="history-header">
                            <div class="history-card-no-wrap">
                                <span class="card-no-badge">末 4 碼 <strong>${hist.card_no || '----'}</strong></span>
                                <span class="card-meta-text">${hist.card_network || ''} ${hist.smart_card_type && hist.smart_card_type !== 'NONE' ? `• ${hist.smart_card_type}` : ''}</span>
                            </div>
                            <div class="history-actions-wrap">
                                <span class="status-badge ${hist.status === 'active' ? 'status-active' : 'status-cancelled'}">${hist.status || 'active'}</span>
                                <button class="btn-icon" title="編輯履歷" onclick="openEditHistoryModal(${cIdx}, ${hIdx})">✏️</button>
                                <button class="btn-icon btn-icon-danger" title="刪除履歷" onclick="deleteHistory(${cIdx}, ${hIdx})">✕</button>
                            </div>
                        </div>
                        ${hist.start_date ? `<div class="history-date">📅 發卡日: ${hist.start_date}</div>` : ''}
                        ${hist.note ? `<div class="history-note">📝 ${hist.note}</div>` : ''}

                        <!-- VPC 綁定支付區塊 -->
                        <div class="vpc-container">
                            <div class="vpc-header-line">
                                <span class="vpc-title">📱 綁定 (${(hist.vpc_pay || []).length})</span>
                                <button class="btn-xs btn-add-vpc" onclick="openAddVpcModal(${cIdx}, ${hIdx})">+ 綁定</button>
                            </div>
                            <div class="vpc-chips-wrap">
                                ${(hist.vpc_pay || []).map((vpc, vIdx) => `
                                    <span class="vpc-chip" title="${vpc.vpc_type} (${vpc.vpc_no})">
                                        <span class="vpc-type-name">${vpc.vpc_type}</span>
                                        <span class="vpc-no-tag">${vpc.vpc_no}</span>
                                        <span class="vpc-del-btn" title="解除綁定" onclick="deleteVpc(${cIdx}, ${hIdx}, ${vIdx})">×</span>
                                    </span>
                                `).join('')}
                            </div>
                        </div>
                    </div>
                `).join('')}
            </div>
        </div>
        `;
    }).join('');
}

// 儲存至 JSON API
async function saveCardsToJson(syncDb = true) {
    try {
        showAlert('⌛ 正在儲存至 bridge_user_cards.json...', 'info');
        const res = await fetch(`/api/cards/json?sync_db=${syncDb}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(cardsData)
        });
        const data = await res.json();
        if (res.ok && data.status === 'ok') {
            showAlert('✅ ' + data.message, 'success');
        } else {
            showAlert('❌ 儲存失敗: ' + (data.detail || '未知錯誤'), 'danger');
        }
    } catch (err) {
        showAlert('❌ 儲存請求失敗: ' + err.message, 'danger');
    }
}

// Modal 操作邏輯
function closeModal(modalId) {
    const el = document.getElementById(modalId);
    if (el) el.style.display = 'none';
}

function openAddCardModal() {
    document.getElementById('cardModalTitle').innerText = '新增卡片產品';
    document.getElementById('editCardIndex').value = '-1';
    const select = document.getElementById('inputCardType');
    if (select && cardProducts.length > 0) {
        select.selectedIndex = 0;
        onCardTypeChange();
    }
    document.getElementById('cardModal').style.display = 'flex';
}

function openEditCardModal(cIdx) {
    const card = cardsData[cIdx];
    document.getElementById('cardModalTitle').innerText = '編輯卡片產品';
    document.getElementById('editCardIndex').value = cIdx;
    document.getElementById('inputCardId').value = card.card_id || '';

    const select = document.getElementById('inputCardType');
    if (select) {
        let foundIdx = -1;
        for (let i = 0; i < select.options.length; i++) {
            const opt = select.options[i];
            if (opt.value === card.card_id || opt.getAttribute('data-type') === card.card_type) {
                foundIdx = i;
                break;
            }
        }
        if (foundIdx >= 0) {
            select.selectedIndex = foundIdx;
        }
        onCardTypeChange();
    }
    document.getElementById('cardModal').style.display = 'flex';
}

function submitCardForm() {
    const cIdx = parseInt(document.getElementById('editCardIndex').value);
    const card_id = document.getElementById('inputCardId').value.trim();
    const bank_no = document.getElementById('inputBankNo').value.trim();

    const select = document.getElementById('inputCardType');
    const selectedOption = select && select.options.length > 0 ? select.options[select.selectedIndex] : null;
    const card_type = selectedOption ? (selectedOption.getAttribute('data-type') || selectedOption.text.split(' — ')[0]) : '';

    if (!card_id || !bank_no || !card_type) {
        alert('請選擇有效的卡片產品！');
        return;
    }

    if (cIdx >= 0) {
        cardsData[cIdx].card_id = card_id;
        cardsData[cIdx].bank_no = bank_no;
        cardsData[cIdx].card_type = card_type;
    } else {
        cardsData.push({
            card_id, bank_no, card_type, card_history: []
        });
    }
    closeModal('cardModal');
    renderCards();
}

function deleteCard(cIdx) {
    if (confirm(`確定要刪除卡片產品 "${cardsData[cIdx].card_type}" 嗎？`)) {
        cardsData.splice(cIdx, 1);
        renderCards();
    }
}

// History Modal 操作
function openAddHistoryModal(cIdx) {
    const card = cardsData[cIdx];
    document.getElementById('historyModalTitle').innerText = '新增卡片履歷';
    document.getElementById('histTargetCardIdx').value = cIdx;
    document.getElementById('histTargetHistIdx').value = '-1';
    document.getElementById('inputCardNo').value = '';

    let defaultNetwork = 'VISA';
    if (card) {
        let product = cardProductsMap[card.card_id];
        if (!product) {
            product = cardProducts.find(p => p.card_type === card.card_type);
        }
        if (product && product.default_card_network) {
            const rawNet = String(product.default_card_network).trim().toUpperCase();
            if (rawNet) {
                const select = document.getElementById('inputCardNetwork');
                if (select) {
                    for (let opt of select.options) {
                        if (opt.value.toUpperCase() === rawNet) {
                            defaultNetwork = opt.value;
                            break;
                        }
                    }
                }
            }
        }
    }

    document.getElementById('inputCardNetwork').value = defaultNetwork;
    document.getElementById('inputSmartCardType').value = 'NONE';
    document.getElementById('inputStatus').value = 'active';
    document.getElementById('inputStartDate').value = new Date().toISOString().split('T')[0];
    document.getElementById('inputNote').value = '';
    document.getElementById('historyModal').style.display = 'flex';
}

function openEditHistoryModal(cIdx, hIdx) {
    const hist = cardsData[cIdx].card_history[hIdx];
    document.getElementById('historyModalTitle').innerText = '編輯卡片履歷';
    document.getElementById('histTargetCardIdx').value = cIdx;
    document.getElementById('histTargetHistIdx').value = hIdx;
    document.getElementById('inputCardNo').value = hist.card_no || '';
    document.getElementById('inputCardNetwork').value = hist.card_network || 'VISA';
    document.getElementById('inputSmartCardType').value = hist.smart_card_type || 'NONE';
    document.getElementById('inputStatus').value = hist.status || 'active';
    document.getElementById('inputStartDate').value = hist.start_date || '';
    document.getElementById('inputNote').value = hist.note || '';
    document.getElementById('historyModal').style.display = 'flex';
}

function submitHistoryForm() {
    const cIdx = parseInt(document.getElementById('histTargetCardIdx').value);
    const hIdx = parseInt(document.getElementById('histTargetHistIdx').value);
    const card_no = document.getElementById('inputCardNo').value.trim();

    if (!card_no) {
        alert('請輸入實體卡號末四碼！');
        return;
    }

    const histObj = {
        card_no: card_no,
        card_network: document.getElementById('inputCardNetwork').value,
        smart_card_type: document.getElementById('inputSmartCardType').value,
        is_co_branded: false,
        is_dual_currency: false,
        start_date: document.getElementById('inputStartDate').value,
        status: document.getElementById('inputStatus').value,
        note: document.getElementById('inputNote').value.trim(),
        vpc_pay: (hIdx >= 0 && cardsData[cIdx].card_history[hIdx].vpc_pay) ? cardsData[cIdx].card_history[hIdx].vpc_pay : [
            { vpc_no: card_no, vpc_type: 'CARD' }
        ]
    };

    if (hIdx >= 0) {
        cardsData[cIdx].card_history[hIdx] = histObj;
    } else {
        cardsData[cIdx].card_history = cardsData[cIdx].card_history || [];
        cardsData[cIdx].card_history.push(histObj);
    }

    closeModal('historyModal');
    renderCards();
}

function deleteHistory(cIdx, hIdx) {
    if (confirm('確定要刪除這筆卡號履歷嗎？')) {
        cardsData[cIdx].card_history.splice(hIdx, 1);
        renderCards();
    }
}

// VPC Modal 操作
function openAddVpcModal(cIdx, hIdx) {
    document.getElementById('vpcCardIdx').value = cIdx;
    document.getElementById('vpcHistIdx').value = hIdx;
    const hist = cardsData[cIdx].card_history[hIdx];
    document.getElementById('inputVpcNo').value = hist.card_no || '';
    document.getElementById('vpcModal').style.display = 'flex';
}

function submitVpcForm() {
    const cIdx = parseInt(document.getElementById('vpcCardIdx').value);
    const hIdx = parseInt(document.getElementById('vpcHistIdx').value);
    const vpc_no = document.getElementById('inputVpcNo').value.trim();
    const vpc_type = document.getElementById('inputVpcType').value;

    if (!vpc_no) {
        alert('請輸入虛擬卡號 / 特徵號！');
        return;
    }

    cardsData[cIdx].card_history[hIdx].vpc_pay = cardsData[cIdx].card_history[hIdx].vpc_pay || [];
    cardsData[cIdx].card_history[hIdx].vpc_pay.push({ vpc_no, vpc_type });

    closeModal('vpcModal');
    renderCards();
}

function deleteVpc(cIdx, hIdx, vIdx) {
    cardsData[cIdx].card_history[hIdx].vpc_pay.splice(vIdx, 1);
    renderCards();
}

function showAlert(msg, type) {
    const alert = document.getElementById('statusAlert');
    if (!alert) return;
    alert.innerText = msg;
    alert.style.display = 'block';
    alert.style.background = type === 'success' ? 'rgba(34, 197, 94, 0.2)' : (type === 'danger' ? 'rgba(239, 68, 68, 0.2)' : 'rgba(56, 189, 248, 0.2)');
    alert.style.color = type === 'success' ? '#86efac' : (type === 'danger' ? '#fca5a5' : '#7dd3fc');
    alert.style.border = `1px solid ${type === 'success' ? '#22c55e' : (type === 'danger' ? '#ef4444' : '#38bdf8')}`;
    setTimeout(() => { alert.style.display = 'none'; }, 4000);
}
