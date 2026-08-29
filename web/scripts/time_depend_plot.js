// web/scripts/time_depend_plot.js
/**
 * 時間相依圖表與金流桑基圖儀表板前端邏輯
 * 整合 Apache ECharts 繪製月度消費趨勢、桑基圖流向與佔比分析
 */

let trendChartInstance = null;
let sankeyChartInstance = null;
let cardPieChartInstance = null;
let paymentPieChartInstance = null;

// ECharts 深色主題預設配色盤
const CHART_THEME_COLORS = [
    '#38bdf8', '#818cf8', '#c084fc', '#f472b6', 
    '#34d399', '#fbbf24', '#fb923c', '#a78bfa',
    '#4ade80', '#22d3ee', '#e879f9', '#f87171'
];

document.addEventListener('DOMContentLoaded', () => {
    initCharts();
    loadDashboardData();
    
    // 響應式調整圖表尺寸
    window.addEventListener('resize', () => {
        if (trendChartInstance) trendChartInstance.resize();
        if (sankeyChartInstance) sankeyChartInstance.resize();
        if (cardPieChartInstance) cardPieChartInstance.resize();
        if (paymentPieChartInstance) paymentPieChartInstance.resize();
    });
});

function initCharts() {
    const trendDom = document.getElementById('trendChart');
    if (trendDom) trendChartInstance = echarts.init(trendDom);

    const sankeyDom = document.getElementById('sankeyChart');
    if (sankeyDom) sankeyChartInstance = echarts.init(sankeyDom);

    const cardPieDom = document.getElementById('cardPieChart');
    if (cardPieDom) cardPieChartInstance = echarts.init(cardPieDom);

    const payPieDom = document.getElementById('paymentPieChart');
    if (payPieDom) paymentPieChartInstance = echarts.init(payPieDom);
}

async function loadDashboardData() {
    const timeWindow = document.getElementById('timeWindowSelect').value;
    const includeDirect = document.getElementById('includeDirectPay').checked;

    showLoading();

    try {
        const queryParams = new URLSearchParams({
            time_window: timeWindow,
            include_direct_payment: includeDirect ? 'true' : 'false'
        });

        // 1. 同步請求月度趨勢與桑基圖資料
        const [trendRes, sankeyRes] = await Promise.all([
            fetch(`/api/analytics/monthly-trend?${queryParams.toString()}`),
            fetch(`/api/analytics/sankey?${queryParams.toString()}`)
        ]);

        const trendJson = await trendRes.json();
        const sankeyJson = await sankeyRes.json();

        if (trendJson.success && trendJson.data) {
            renderTrendChart(trendJson.data);
            renderPieCharts(trendJson.data);
            if (trendJson.data.summary) {
                updateKpiCards(trendJson.data.summary);
            }
        }

        if (sankeyJson.success && sankeyJson.data) {
            renderSankeyChart(sankeyJson.data);
            if (!trendJson.data?.summary && sankeyJson.data.summary) {
                updateKpiCards(sankeyJson.data.summary);
            }
        }

    } catch (error) {
        console.error('❌ 載入圖表數據失敗:', error);
    } finally {
        hideLoading();
    }
}

function showLoading() {
    if (trendChartInstance) trendChartInstance.showLoading({ color: '#38bdf8', maskColor: 'rgba(31, 41, 61, 0.6)' });
    if (sankeyChartInstance) sankeyChartInstance.showLoading({ color: '#38bdf8', maskColor: 'rgba(31, 41, 61, 0.6)' });
    if (cardPieChartInstance) cardPieChartInstance.showLoading({ color: '#38bdf8', maskColor: 'rgba(31, 41, 61, 0.6)' });
    if (paymentPieChartInstance) paymentPieChartInstance.showLoading({ color: '#38bdf8', maskColor: 'rgba(31, 41, 61, 0.6)' });
}

function hideLoading() {
    if (trendChartInstance) trendChartInstance.hideLoading();
    if (sankeyChartInstance) sankeyChartInstance.hideLoading();
    if (cardPieChartInstance) cardPieChartInstance.hideLoading();
    if (paymentPieChartInstance) paymentPieChartInstance.hideLoading();
}

function updateKpiCards(summary) {
    if (!summary) return;
    const total = (summary.total_amount || 0).toLocaleString('zh-TW', { minimumFractionDigits: 0 });
    document.getElementById('kpiTotalAmount').innerText = `NT$ ${total}`;
    document.getElementById('kpiActiveMonths').innerText = `${summary.active_months !== undefined ? summary.active_months : 0} 個月`;
    document.getElementById('kpiCardCount').innerText = `${summary.card_count || 0} 張`;
    document.getElementById('kpiPaymentCount').innerText = `${summary.payment_count || 0} 種`;
}

function renderTrendChart(data) {
    if (!trendChartInstance || !data.months || data.months.length === 0) return;

    const validCategories = (data.categories || []).filter(c => c !== '未分類' && c !== '銀行費用');
    const validSeries = (data.series || []).filter(s => s.name !== '未分類' && s.name !== '銀行費用');

    const option = {
        color: CHART_THEME_COLORS,
        tooltip: {
            trigger: 'axis',
            axisPointer: { type: 'cross', label: { backgroundColor: '#334155' } },
            valueFormatter: (value) => `NT$ ${(value || 0).toLocaleString('zh-TW')}`
        },
        legend: {
            data: validCategories,
            textStyle: { color: '#94a3b8' },
            top: '0%',
            type: 'scroll'
        },
        grid: {
            left: '3%',
            right: '4%',
            bottom: '3%',
            containLabel: true
        },
        xAxis: [
            {
                type: 'category',
                boundaryGap: false,
                data: data.months,
                axisLine: { lineStyle: { color: '#475569' } },
                axisLabel: { color: '#94a3b8' }
            }
        ],
        yAxis: [
            {
                type: 'value',
                axisLine: { lineStyle: { color: '#475569' } },
                splitLine: { lineStyle: { color: 'rgba(255, 255, 255, 0.05)' } },
                axisLabel: { color: '#94a3b8' }
            }
        ],
        series: validSeries
    };

    trendChartInstance.setOption(option, true);
}

function renderSankeyChart(data) {
    if (!sankeyChartInstance || !data.nodes || data.nodes.length === 0) return;

    const option = {
        color: CHART_THEME_COLORS,
        tooltip: {
            trigger: 'item',
            triggerOn: 'mousemove',
            formatter: (params) => {
                if (params.dataType === 'edge') {
                    return `🌊 <b>${params.data.source}</b> ➔ <b>${params.data.target}</b><br/>💰 金額: NT$ ${(params.data.value || 0).toLocaleString('zh-TW')}`;
                }
                return `📌 節點: <b>${params.name}</b>`;
            }
        },
        series: [
            {
                type: 'sankey',
                layout: 'none',
                emphasis: { focus: 'adjacency' },
                data: data.nodes,
                links: data.links,
                lineStyle: {
                    color: 'gradient',
                    curveness: 0.5,
                    opacity: 0.4
                },
                itemStyle: {
                    borderWidth: 1,
                    borderColor: '#1e293b'
                },
                label: {
                    color: '#f8fafc',
                    fontSize: 12,
                    fontWeight: 500
                },
                nodeGap: 14,
                nodeWidth: 20
            }
        ]
    };

    sankeyChartInstance.setOption(option, true);
}

function renderPieCharts(data) {
    // 1. 卡片消費佔比圓餅圖
    if (cardPieChartInstance && data.card_summary) {
        // 加總每張卡片金額
        const cardMap = {};
        data.card_summary.forEach(item => {
            const card = item.card_type || '其他卡片';
            cardMap[card] = (cardMap[card] || 0) + (item.total_amount || 0);
        });

        const cardData = Object.entries(cardMap).map(([name, value]) => ({
            name,
            value: Math.round(value)
        }));

        cardPieChartInstance.setOption({
            color: CHART_THEME_COLORS,
            tooltip: {
                trigger: 'item',
                formatter: '{b}: NT$ {c} ({d}%)'
            },
            legend: {
                orient: 'vertical',
                left: 'left',
                textStyle: { color: '#94a3b8' },
                type: 'scroll'
            },
            series: [
                {
                    name: '信用卡別',
                    type: 'pie',
                    radius: ['40%', '70%'],
                    avoidLabelOverlap: false,
                    itemStyle: {
                        borderRadius: 6,
                        borderColor: '#273549',
                        borderWidth: 2
                    },
                    label: { show: false, position: 'center' },
                    emphasis: {
                        label: { show: true, fontSize: 14, fontWeight: 'bold', color: '#f8fafc' }
                    },
                    data: cardData
                }
            ]
        }, true);
    }

    // 2. 類別消費佔比圓餅圖
    if (paymentPieChartInstance && data.category_summary) {
        const catMap = {};
        data.category_summary.forEach(item => {
            const cat = item.category || '未分類';
            if (cat === '未分類' || cat === '銀行費用') return;
            catMap[cat] = (catMap[cat] || 0) + (item.total_amount || 0);
        });

        const catData = Object.entries(catMap).map(([name, value]) => ({
            name,
            value: Math.round(value)
        }));

        paymentPieChartInstance.setOption({
            color: CHART_THEME_COLORS.slice().reverse(),
            tooltip: {
                trigger: 'item',
                formatter: '{b}: NT$ {c} ({d}%)'
            },
            legend: {
                orient: 'vertical',
                left: 'left',
                textStyle: { color: '#94a3b8' },
                type: 'scroll'
            },
            series: [
                {
                    name: '消費類別',
                    type: 'pie',
                    radius: ['40%', '70%'],
                    avoidLabelOverlap: false,
                    itemStyle: {
                        borderRadius: 6,
                        borderColor: '#273549',
                        borderWidth: 2
                    },
                    label: { show: false, position: 'center' },
                    emphasis: {
                        label: { show: true, fontSize: 14, fontWeight: 'bold', color: '#f8fafc' }
                    },
                    data: catData
                }
            ]
        }, true);
    }
}
