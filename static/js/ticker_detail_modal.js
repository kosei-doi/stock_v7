/**
 * 銘柄詳細モーダル（チャート + DVC 分析）。企業分析・日次レポート共通。
 *
 * TickerDetailModal.init({ syncUrlOnOpen, onOpen, onAnalyzeRequest })
 * TickerDetailModal.open({ ticker, name, hasOutput, contextMsg })
 */
(function (global) {
  'use strict';

  let config = {
    syncUrlOnOpen: false,
    onOpen: null,
    onAnalyzeRequest: null,
  };

  let chartInstance = null;
  let candleSeries = null;
  let selectedTicker = null;
  let modalOpen = false;
  let wired = false;

  const detailModal = () => document.getElementById('detail-modal');
  const detailBackdrop = () => document.getElementById('detail-modal-backdrop');
  const btnModalClose = () => document.getElementById('btn-modal-close');
  const detailTitle = () => document.getElementById('detail-title');
  const detailStatus = () => document.getElementById('detail-status-msg');
  const btnDetailAnalyze = () => document.getElementById('btn-detail-analyze');
  const chartEl = () => document.getElementById('detail-chart');
  const chartLoading = () => document.getElementById('chart-loading');

  function fmt(v, d) {
    d = d === undefined ? 2 : d;
    return v != null && v !== '' && !isNaN(v)
      ? typeof v === 'number' && v % 1 !== 0
        ? v.toFixed(d)
        : v
      : '-';
  }

  function fillDetail(data) {
    const set = (id, text) => {
      const el = document.getElementById(id);
      if (el) el.textContent = text;
    };
    set('detail-value', data.value_score != null ? Number(data.value_score).toFixed(1) : '-');
    set('detail-safety', data.safety_score != null ? Number(data.safety_score).toFixed(1) : '-');
    set('detail-momentum', data.momentum_score != null ? Number(data.momentum_score).toFixed(1) : '-');
    set('detail-total', data.total_score != null ? Number(data.total_score).toFixed(1) : '-');
    set('result-name', data.name || data.ticker || '-');
    set('result-sector', data.sector || '-');
    set(
      'result-last-close',
      data.last_close != null && data.last_close !== ''
        ? Number(data.last_close).toLocaleString() + ' 円'
        : '-'
    );
    set('result-pb', fmt(data.pb));
    set('result-pe', fmt(data.pe));
    set('result-beta', fmt(data.beta));
    set(
      'result-r2',
      data.r_squared != null && data.r_squared !== ''
        ? (Number(data.r_squared) * 100).toFixed(1) + '%'
        : '-'
    );
    set(
      'result-atr',
      data.atr_percent != null && data.atr_percent !== ''
        ? Number(data.atr_percent).toFixed(2) + '%'
        : '-'
    );
    set('result-peer-count', data.peer_count != null && data.peer_count !== '' ? data.peer_count : '-');
    const dmin = data.date_min;
    const dmax = data.date_max;
    set(
      'result-date-range',
      dmin && dmax
        ? String(dmin).replace(/ 00:00:00/, '') + ' 〜 ' + String(dmax).replace(/ 00:00:00/, '')
        : '-'
    );
    set('result-rows', data.rows != null && data.rows !== '' ? data.rows + ' 日' : '-');
    set('result-benchmark', data.benchmark || '-');
    set('result-time-z-pb', fmt(data.time_z_pb));
    set('result-time-z-pe', fmt(data.time_z_pe));
    set('result-space-z-pb', fmt(data.space_z_pb));
    set('result-space-z-pe', fmt(data.space_z_pe));
    set('result-target-pb', fmt(data.target_pb));
    set('result-target-pe', fmt(data.target_pe));
    const rankBadge = document.getElementById('result-rank-badge');
    if (rankBadge) {
      if (data.watchlist_rank != null && data.watchlist_total != null && data.watchlist_total > 0) {
        rankBadge.textContent =
          'ウォッチリスト順位: ' + data.watchlist_rank + ' / ' + data.watchlist_total;
        rankBadge.className = 'text-amber-400 font-medium';
      } else {
        rankBadge.textContent = '';
      }
    }
    const stopLoss = document.getElementById('result-stop-loss');
    if (stopLoss) {
      if (data.stop_loss_recommendation != null && !isNaN(data.stop_loss_recommendation)) {
        stopLoss.textContent =
          '推奨損切り: ' + Number(data.stop_loss_recommendation).toLocaleString() + ' 円';
      } else {
        stopLoss.textContent = '';
      }
    }
  }

  function destroyChart() {
    if (chartInstance) {
      chartInstance.remove();
      chartInstance = null;
      candleSeries = null;
    }
  }

  function ensureChart() {
    destroyChart();
    const el = chartEl();
    if (!el || typeof global.LightweightCharts === 'undefined') return;
    const h = el.clientHeight || 320;
    chartInstance = global.LightweightCharts.createChart(el, {
      layout: { background: { color: '#0f172a' }, textColor: '#94a3b8' },
      grid: { vertLines: { color: '#334155' }, horzLines: { color: '#334155' } },
      width: el.clientWidth,
      height: h,
    });
    candleSeries = chartInstance.addCandlestickSeries({
      upColor: '#ef4444',
      downColor: '#22c55e',
      borderVisible: false,
      wickUpColor: '#ef4444',
      wickDownColor: '#22c55e',
    });
  }

  function resizeChart() {
    const el = chartEl();
    if (!chartInstance || !modalOpen || !el) return;
    chartInstance.applyOptions({ width: el.clientWidth, height: el.clientHeight || 320 });
    chartInstance.timeScale().fitContent();
  }

  function renderChart(bars) {
    ensureChart();
    if (!candleSeries) return;
    candleSeries.setData(bars);
    requestAnimationFrame(resizeChart);
  }

  function openModal() {
    const modal = detailModal();
    if (!modal) return;
    modal.classList.remove('hidden');
    modal.setAttribute('aria-hidden', 'false');
    document.body.classList.add('overflow-hidden');
    modalOpen = true;
    requestAnimationFrame(resizeChart);
  }

  function closeModal() {
    const modal = detailModal();
    if (!modal) return;
    modal.classList.add('hidden');
    modal.setAttribute('aria-hidden', 'true');
    document.body.classList.remove('overflow-hidden');
    modalOpen = false;
    selectedTicker = null;
    destroyChart();
    if (config.syncUrlOnOpen) {
      const url = new URL(global.location.href);
      url.searchParams.delete('ticker');
      global.history.replaceState(null, '', url.pathname + (url.search || ''));
    }
  }

  function fetchJson(url) {
    const fn = global.dpaFetch || global.fetch;
    return fn(url).then(function (r) {
      if (!r.ok) {
        return r.json().then(function (d) {
          throw new Error(d.detail || r.statusText);
        });
      }
      return r.json();
    });
  }

  function open(opts) {
    wireOnce();
    opts = opts || {};
    const ticker = opts.ticker;
    if (!ticker) return;

    selectedTicker = ticker;
    const titleEl = detailTitle();
    const statusEl = detailStatus();
    const analyzeBtn = btnDetailAnalyze();

    if (titleEl) {
      titleEl.textContent =
        opts.name && opts.name !== '-' ? ticker + ' — ' + opts.name : ticker;
    }
    if (statusEl) {
      statusEl.textContent = opts.contextMsg || '';
    }
    if (analyzeBtn && config.onAnalyzeRequest) {
      analyzeBtn.classList.toggle('hidden', opts.hasOutput !== false);
    }

    if (typeof config.onOpen === 'function') {
      config.onOpen(ticker, opts);
    }

    openModal();

    if (config.syncUrlOnOpen) {
      const url = new URL(global.location.href);
      url.searchParams.set('ticker', ticker);
      global.history.replaceState(null, '', url);
    }

    const loadingEl = chartLoading();
    if (loadingEl) loadingEl.classList.remove('hidden');

    fetchJson('/api/ticker/' + encodeURIComponent(ticker) + '/ohlc?years=1')
      .then(function (data) {
        renderChart(data.bars || []);
      })
      .catch(function (e) {
        if (statusEl) statusEl.textContent = 'チャート: ' + (e.message || '取得失敗');
      })
      .finally(function () {
        if (loadingEl) loadingEl.classList.add('hidden');
      });

    if (opts.hasOutput === false) {
      if (statusEl) {
        statusEl.textContent =
          opts.unanalyzedMsg ||
          (config.onAnalyzeRequest
            ? '未分析です。「分析実行」で DVC を実行できます。'
            : '分析結果がありません。企業分析タブで分析を実行してください。');
      }
      return;
    }

    fetchJson('/api/ticker/' + encodeURIComponent(ticker) + '/analysis')
      .then(function (data) {
        fillDetail(data);
        if (statusEl && data.message && !opts.contextMsg) {
          statusEl.textContent = data.message;
        } else if (statusEl && opts.contextMsg) {
          statusEl.textContent = opts.contextMsg;
        }
      })
      .catch(function (e) {
        if (statusEl) statusEl.textContent = e.message || '分析の読み込みに失敗しました';
        if (analyzeBtn && config.onAnalyzeRequest) analyzeBtn.classList.remove('hidden');
      });
  }

  function wireOnce() {
    if (wired) return;
    wired = true;
    const closeBtn = btnModalClose();
    const backdrop = detailBackdrop();
    if (closeBtn) closeBtn.addEventListener('click', closeModal);
    if (backdrop) backdrop.addEventListener('click', closeModal);
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && modalOpen) closeModal();
    });
    global.addEventListener('resize', function () {
      if (modalOpen) resizeChart();
    });
    const analyzeBtn = btnDetailAnalyze();
    if (analyzeBtn) {
      analyzeBtn.addEventListener('click', function () {
        if (!selectedTicker || typeof config.onAnalyzeRequest !== 'function') return;
        config.onAnalyzeRequest(selectedTicker);
      });
    }
  }

  function init(userConfig) {
    config = Object.assign(
      {
        syncUrlOnOpen: false,
        onOpen: null,
        onAnalyzeRequest: null,
      },
      userConfig || {}
    );
    wireOnce();
  }

  global.TickerDetailModal = {
    init: init,
    open: open,
    close: closeModal,
    fillDetail: fillDetail,
    getSelectedTicker: function () {
      return selectedTicker;
    },
    isOpen: function () {
      return modalOpen;
    },
  };
})(typeof window !== 'undefined' ? window : this);
