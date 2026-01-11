/**
 * Polymarket Trading Dashboard
 * Real-time analytics for the MM bot
 */

// Configuration
const CONFIG = {
    API_BASE_URL: '',
    REFRESH_INTERVAL: 5000, // 5 seconds
    STATE_FILE_PATH: '../polymarket/state.json'
};

// State
let state = {
    fills: [],
    positions: {},
    totalMakerVolume: 0,
    totalRebatesEstimate: 0,
    lastUpdated: null,
    pnlHistory: [],
    isLive: false
};

// Charts
let pnlChart = null;
let volumeChart = null;

// Initialize Dashboard
document.addEventListener('DOMContentLoaded', () => {
    initializeCharts();
    initializeEventListeners();
    loadData();
    startAutoRefresh();
});

// Event Listeners
function initializeEventListeners() {
    // Refresh button
    document.getElementById('refreshBtn').addEventListener('click', () => {
        loadData();
        animateRefreshButton();
    });

    // Trade filter
    document.getElementById('tradeFilter').addEventListener('change', (e) => {
        filterTrades(e.target.value);
    });

    // Chart range buttons
    document.querySelectorAll('.chart-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
            document.querySelectorAll('.chart-btn').forEach(b => b.classList.remove('active'));
            e.target.classList.add('active');
            updatePnlChart(e.target.dataset.range);
        });
    });

    // Navigation
    document.querySelectorAll('.nav-item').forEach(item => {
        item.addEventListener('click', (e) => {
            e.preventDefault();
            document.querySelectorAll('.nav-item').forEach(i => i.classList.remove('active'));
            item.classList.add('active');
        });
    });
}

// Load Data
async function loadData() {
    try {
        // Try to fetch from API first
        const response = await fetch(`${CONFIG.API_BASE_URL}/api/stats`);
        if (response.ok) {
            const data = await response.json();
            updateState(data);
            state.isLive = true;
        }
    } catch (error) {
        // Fallback: Load from state.json file
        try {
            const response = await fetch(CONFIG.STATE_FILE_PATH);
            if (response.ok) {
                const data = await response.json();
                updateState(data);
            }
        } catch (fileError) {
            console.log('Using demo data - bot not running');
            loadDemoData();
        }
    }

    updateUI();
}

// Update state from loaded data
function updateState(data) {
    state.fills = data.fills || [];
    state.positions = data.positions || {};
    state.totalMakerVolume = data.total_maker_volume || 0;
    state.totalRebatesEstimate = data.total_rebates_estimate || 0;
    state.lastUpdated = data.last_updated ? new Date(data.last_updated) : new Date();

    // Calculate PnL history from fills
    calculatePnlHistory();
}

// Calculate PnL history
function calculatePnlHistory() {
    let cumulativePnl = 0;
    state.pnlHistory = state.fills.map(fill => {
        // Simplified PnL calculation (actual would be more complex)
        const pnl = fill.maker ? fill.price * fill.size * 0.001 : -fill.price * fill.size * 0.0025;
        cumulativePnl += pnl;
        return {
            timestamp: new Date(fill.timestamp),
            pnl: cumulativePnl
        };
    });
}

// Load demo data for visualization
function loadDemoData() {
    const now = new Date();

    // Generate demo fills
    state.fills = [];
    for (let i = 0; i < 25; i++) {
        const timestamp = new Date(now.getTime() - (25 - i) * 300000); // 5 min intervals
        state.fills.push({
            order_id: `demo_${i}`,
            token_id: `0x${Math.random().toString(16).slice(2, 10)}`,
            outcome: Math.random() > 0.5 ? 'YES' : 'NO',
            side: Math.random() > 0.5 ? 'BUY' : 'SELL',
            price: 0.3 + Math.random() * 0.4,
            size: 10 + Math.random() * 90,
            timestamp: timestamp.toISOString(),
            maker: true
        });
    }

    // Generate demo positions
    state.positions = {
        'demo_market_1': {
            condition_id: 'demo_1',
            yes_position: { quantity: 45, total_cost: 18.5 },
            no_position: { quantity: 52, total_cost: 26.0 }
        },
        'demo_market_2': {
            condition_id: 'demo_2',
            yes_position: { quantity: 30, total_cost: 12.0 },
            no_position: { quantity: 28, total_cost: 14.0 }
        }
    };

    state.totalMakerVolume = state.fills.reduce((sum, f) => sum + f.price * f.size, 0);
    state.totalRebatesEstimate = state.totalMakerVolume * 0.001;
    state.lastUpdated = now;
    state.isLive = false;

    calculatePnlHistory();
}

// Update UI
function updateUI() {
    updateSummaryCards();
    updateTradesTable();
    updatePositionsList();
    updateCharts();
    updateActivityFeed();
    updateLastUpdated();
    updateBotStatus();
}

// Update Summary Cards
function updateSummaryCards() {
    const totalPnl = state.pnlHistory.length > 0
        ? state.pnlHistory[state.pnlHistory.length - 1].pnl
        : 0;

    document.getElementById('totalPnl').textContent = formatCurrency(totalPnl);
    document.getElementById('pnlChange').textContent = totalPnl >= 0 ? `+${(totalPnl * 100 / Math.max(state.totalMakerVolume, 1)).toFixed(2)}%` : `${(totalPnl * 100 / Math.max(state.totalMakerVolume, 1)).toFixed(2)}%`;
    document.getElementById('pnlChange').className = `card-change ${totalPnl >= 0 ? 'positive' : 'negative'}`;

    document.getElementById('totalVolume').textContent = formatCurrency(state.totalMakerVolume);
    document.getElementById('volumeChange').textContent = `${state.fills.length} trades`;

    document.getElementById('totalRebates').textContent = formatCurrency(state.totalRebatesEstimate);

    const positionCount = Object.keys(state.positions).length;
    document.getElementById('activePositions').textContent = positionCount;
    document.getElementById('marketsActive').textContent = `${positionCount} markets`;
}

// Update Trades Table
function updateTradesTable() {
    const tbody = document.getElementById('tradesBody');

    if (state.fills.length === 0) {
        tbody.innerHTML = '<tr class="empty-row"><td colspan="7">No trades yet</td></tr>';
        return;
    }

    // Show most recent first
    const recentFills = [...state.fills].reverse().slice(0, 50);

    tbody.innerHTML = recentFills.map(fill => `
        <tr>
            <td>${formatTime(fill.timestamp)}</td>
            <td title="${fill.token_id}">${truncateId(fill.token_id)}</td>
            <td class="side-${fill.side.toLowerCase()}">${fill.side}</td>
            <td class="outcome-${fill.outcome.toLowerCase()}">${fill.outcome}</td>
            <td>$${fill.price.toFixed(2)}</td>
            <td>${fill.size.toFixed(2)}</td>
            <td>${formatCurrency(fill.price * fill.size)}</td>
        </tr>
    `).join('');
}

// Filter trades
function filterTrades(filter) {
    const rows = document.querySelectorAll('#tradesBody tr:not(.empty-row)');
    rows.forEach(row => {
        const side = row.querySelector('td:nth-child(3)').textContent.toLowerCase();
        if (filter === 'all' || side === filter) {
            row.style.display = '';
        } else {
            row.style.display = 'none';
        }
    });
}

// Update Positions List
function updatePositionsList() {
    const container = document.getElementById('positionsList');
    const positions = Object.values(state.positions);

    if (positions.length === 0) {
        container.innerHTML = `
            <div class="empty-state">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                    <path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"></path>
                </svg>
                <p>No active positions</p>
            </div>
        `;
        return;
    }

    container.innerHTML = positions.map((pos, idx) => {
        const yesQty = pos.yes_position?.quantity || 0;
        const noQty = pos.no_position?.quantity || 0;
        const total = yesQty + noQty;
        const yesPercent = total > 0 ? (yesQty / total * 100) : 50;
        const noPercent = total > 0 ? (noQty / total * 100) : 50;
        const totalCost = (pos.yes_position?.total_cost || 0) + (pos.no_position?.total_cost || 0);

        return `
            <div class="position-item">
                <div class="position-header">
                    <span class="position-market">Market ${idx + 1}</span>
                    <span class="position-value">${formatCurrency(totalCost)}</span>
                </div>
                <div class="position-bars">
                    <div class="position-bar">
                        <div class="position-bar-fill yes" style="width: ${yesPercent}%"></div>
                    </div>
                    <div class="position-bar">
                        <div class="position-bar-fill no" style="width: ${noPercent}%"></div>
                    </div>
                </div>
                <div class="position-details">
                    <span>YES: ${yesQty.toFixed(2)}</span>
                    <span>NO: ${noQty.toFixed(2)}</span>
                </div>
            </div>
        `;
    }).join('');
}

// Update Activity Feed
function updateActivityFeed() {
    const feed = document.getElementById('activityFeed');
    const recentFills = [...state.fills].reverse().slice(0, 5);

    if (recentFills.length === 0) {
        feed.innerHTML = `
            <div class="activity-item">
                <span class="activity-time">--:--</span>
                <span class="activity-message">Waiting for bot activity...</span>
            </div>
        `;
        return;
    }

    feed.innerHTML = recentFills.map(fill => `
        <div class="activity-item">
            <span class="activity-time">${formatTimeShort(fill.timestamp)}</span>
            <span class="activity-message">
                ${fill.side} ${fill.size.toFixed(2)} ${fill.outcome} @ $${fill.price.toFixed(2)}
            </span>
        </div>
    `).join('');
}

// Initialize Charts
function initializeCharts() {
    // PnL Chart
    const pnlCtx = document.getElementById('pnlChart').getContext('2d');
    pnlChart = new Chart(pnlCtx, {
        type: 'line',
        data: {
            labels: [],
            datasets: [{
                label: 'Cumulative P&L',
                data: [],
                borderColor: '#8b5cf6',
                backgroundColor: 'rgba(139, 92, 246, 0.1)',
                fill: true,
                tension: 0.4,
                pointRadius: 0,
                pointHoverRadius: 6,
                pointHoverBackgroundColor: '#8b5cf6',
                borderWidth: 2
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false },
                tooltip: {
                    backgroundColor: 'rgba(13, 17, 23, 0.9)',
                    titleColor: '#f0f6fc',
                    bodyColor: '#8b949e',
                    borderColor: 'rgba(139, 92, 246, 0.3)',
                    borderWidth: 1,
                    padding: 12,
                    displayColors: false,
                    callbacks: {
                        label: (context) => `P&L: ${formatCurrency(context.raw)}`
                    }
                }
            },
            scales: {
                x: {
                    grid: { color: 'rgba(255, 255, 255, 0.04)' },
                    ticks: { color: '#6e7681', font: { size: 10 } }
                },
                y: {
                    grid: { color: 'rgba(255, 255, 255, 0.04)' },
                    ticks: {
                        color: '#6e7681',
                        font: { size: 10 },
                        callback: (value) => formatCurrency(value)
                    }
                }
            },
            interaction: {
                intersect: false,
                mode: 'index'
            }
        }
    });

    // Volume Chart
    const volumeCtx = document.getElementById('volumeChart').getContext('2d');
    volumeChart = new Chart(volumeCtx, {
        type: 'doughnut',
        data: {
            labels: ['YES', 'NO'],
            datasets: [{
                data: [50, 50],
                backgroundColor: ['#22c55e', '#ef4444'],
                borderColor: 'transparent',
                borderWidth: 0,
                hoverOffset: 8
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            cutout: '70%',
            plugins: {
                legend: {
                    position: 'bottom',
                    labels: {
                        color: '#8b949e',
                        padding: 16,
                        font: { size: 12 }
                    }
                },
                tooltip: {
                    backgroundColor: 'rgba(13, 17, 23, 0.9)',
                    titleColor: '#f0f6fc',
                    bodyColor: '#8b949e',
                    borderColor: 'rgba(139, 92, 246, 0.3)',
                    borderWidth: 1,
                    padding: 12
                }
            }
        }
    });
}

// Update Charts
function updateCharts() {
    updatePnlChart('1h');
    updateVolumeChart();
}

// Update PnL Chart
function updatePnlChart(range = '1h') {
    const now = new Date();
    let filteredData = state.pnlHistory;

    // Filter by time range
    switch (range) {
        case '1h':
            filteredData = state.pnlHistory.filter(d =>
                (now - d.timestamp) < 3600000
            );
            break;
        case '24h':
            filteredData = state.pnlHistory.filter(d =>
                (now - d.timestamp) < 86400000
            );
            break;
        case '7d':
            filteredData = state.pnlHistory.filter(d =>
                (now - d.timestamp) < 604800000
            );
            break;
    }

    // Use all data if no data in range
    if (filteredData.length === 0) {
        filteredData = state.pnlHistory;
    }

    pnlChart.data.labels = filteredData.map(d => formatTimeShort(d.timestamp));
    pnlChart.data.datasets[0].data = filteredData.map(d => d.pnl);
    pnlChart.update('none');
}

// Update Volume Chart
function updateVolumeChart() {
    let yesVolume = 0;
    let noVolume = 0;

    state.fills.forEach(fill => {
        const value = fill.price * fill.size;
        if (fill.outcome === 'YES') {
            yesVolume += value;
        } else {
            noVolume += value;
        }
    });

    volumeChart.data.datasets[0].data = [yesVolume, noVolume];
    volumeChart.update('none');
}

// Update Last Updated
function updateLastUpdated() {
    const el = document.getElementById('lastUpdated');
    if (state.lastUpdated) {
        el.textContent = formatDateTime(state.lastUpdated);
    }
}

// Update Bot Status
function updateBotStatus() {
    const indicator = document.querySelector('.status-indicator');
    const text = document.querySelector('.status-text');
    const modeText = document.getElementById('tradingMode');
    const modeContainer = document.querySelector('.trading-mode');

    if (state.isLive) {
        indicator.classList.add('online');
        text.textContent = 'Bot Running';
        modeText.textContent = 'Live Trading';
        modeContainer.classList.remove('paper');
        modeContainer.classList.add('live');
    } else {
        indicator.classList.remove('online');
        text.textContent = 'Demo Mode';
        modeText.textContent = 'Paper Trading';
        modeContainer.classList.remove('live');
        modeContainer.classList.add('paper');
    }
}

// Auto Refresh
function startAutoRefresh() {
    setInterval(() => {
        loadData();
    }, CONFIG.REFRESH_INTERVAL);
}

// Animate Refresh Button
function animateRefreshButton() {
    const btn = document.getElementById('refreshBtn');
    btn.style.transform = 'rotate(360deg)';
    setTimeout(() => {
        btn.style.transition = 'none';
        btn.style.transform = 'rotate(0deg)';
        setTimeout(() => {
            btn.style.transition = '';
        }, 50);
    }, 300);
}

// Utility Functions
function formatCurrency(value) {
    return new Intl.NumberFormat('en-US', {
        style: 'currency',
        currency: 'USD',
        minimumFractionDigits: 2,
        maximumFractionDigits: 2
    }).format(value);
}

function formatTime(timestamp) {
    const date = new Date(timestamp);
    return date.toLocaleTimeString('en-US', {
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit'
    });
}

function formatTimeShort(timestamp) {
    const date = new Date(timestamp);
    return date.toLocaleTimeString('en-US', {
        hour: '2-digit',
        minute: '2-digit'
    });
}

function formatDateTime(date) {
    return date.toLocaleString('en-US', {
        month: 'short',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit'
    });
}

function truncateId(id) {
    if (!id) return '--';
    return `${id.slice(0, 6)}...${id.slice(-4)}`;
}
