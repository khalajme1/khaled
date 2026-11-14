// Live gold chart: candles from the TradingView indicator, the current trade drawn on it,
// and an alert strip above it for every timeframe that has a trade coming or open.
// Uses globals from index.html ($, api, fmtNum, fmtTime) at call time.
'use strict';

const TF_LABELS = { '1': 'دقيقة', '3': '3 دقائق', '5': '5 دقائق', '15': '15 دقيقة', '30': '30 دقيقة', '60': 'ساعة', '240': '4 ساعات', D: 'يومي' };
const tfLabel = (tf) => TF_LABELS[tf] || tf || '';
const tfShort = (tf) => (/^\d+$/.test(String(tf)) ? tf + 'د' : tf);
const sideAr = (a) => (a === 'BUY' ? 'شراء' : a === 'SELL' ? 'بيع' : '');

// Title of a signal, for cards (withTf=false) and notifications (withTf=true).
function signalTitle(s, withTf) {
  const x = s.extra || {};
  const side = sideAr(s.action);
  const tf = withTf && s.timeframe ? ' على فريم ' + tfLabel(s.timeframe) : '';
  const strong = x.strong ? ' قوي جداً' : '';
  switch (s.kind) {
    case 'setup': return `${x.strong ? '⚡' : ''}⏳ ${withTf ? 'استعد: ' : ''}صفقة ${side}${strong} محتملة${x.firstTouch ? ' (أول لمسة)' : ''}${tf}`;
    case 'near': return `⚠ قرب ${side === 'شراء' ? 'الشراء' : 'البيع'}${x.distance != null ? ' · باقي ' + fmtNum(x.distance) + '$' : ''}${tf}`;
    case 'reinforce': return `➕ تعزيز ${x.zone || ''} ${side}${tf}`;
    case 'tp': return `✅ الهدف ${x.target || ''}${x.zone > 1 ? ' (تعزيز ' + x.zone + ')' : ''}${tf}`;
    case 'cancel': return `✖️ إلغاء الصفقة المحتملة${tf}`;
    case 'close': return (x.outcome === 'win' ? '🏁 تسكّرت الصفقة — ربح' : x.outcome === 'breakeven' ? '⚖ تسكّرت على الدخول' : x.outcome === 'loss' ? '🛑 تسكّرت الصفقة — خسارة' : '✅ إغلاق الصفقة') + (x.result ? ' ' + x.result : '') + tf;
    case 'info': return ({
      safe: '🛡 أكثر أمان: تسكّر اللي قبل التعزيز', breakeven: '🛡 الوقف على الدخول', exit: '🚪 خروج الباقي',
      stop: '🛑 وقف', near_reinforce: '⏳ قرب التعزيز', day_target: '🎯 هدف اليوم تحقق', week_end: '📅 نهاية الأسبوع',
    }[x.sub] || 'ℹ️ تحديث') + tf;
    default: return `${x.strong ? '⚡' : ''}${s.action === 'SELL' ? '🔴' : '🟢'} ${withTf ? 'صفقة ' : ''}${side}${strong}${withTf ? '' : (s.action ? ' ' + s.action : '')}${tf}`;
  }
}
function signalBadgeClass(s) {
  if (s.kind === 'entry' || !s.kind) return s.action === 'BUY' ? 'BUY' : s.action === 'SELL' ? 'SELL' : 'OTHER';
  if (s.kind === 'tp' || (s.kind === 'close' && (s.extra || {}).outcome === 'win')) return 'BUY';
  if ((s.kind === 'info' && (s.extra || {}).sub === 'stop') || (s.kind === 'close' && (s.extra || {}).outcome === 'loss')) return 'SELL';
  return 'OTHER';
}
const modeChip = (m) => (!m ? '' : /أمان/.test(m) ? '🛡 أكثر أمان' : /هدف اليوم/.test(m) ? '🎯 هدف اليوم' : /مضاربة/.test(m) ? 'مضاربة' : '');

// Lightweight Charts shows UTC; shift bar times so the axis reads in the viewer's local time.
const TZ_SHIFT = -new Date().getTimezoneOffset() * 60;
const toChartTime = (ms) => Math.floor(ms / 1000) + TZ_SHIFT;

const C = {
  tf: null,
  tfs: ['1', '3', '5', '15'],
  trades: [],
  recent: [], // recent entries, for arrows on the chart
  candles: [],
  chart: null,
  series: null,
  lines: [],
  pickedAt: 0, // when the viewer last picked a tab by hand
};

function liveTrades() {
  const t = Date.now();
  return C.trades.filter((x) => x.status === 'active' && (!x.expires_at || x.expires_at > t));
}

function initChart() {
  if (C.chart || !window.LightweightCharts) return;
  C.chart = LightweightCharts.createChart($('chart'), {
    autoSize: true,
    layout: { background: { color: 'transparent' }, textColor: '#9aa1ad', fontFamily: 'Tajawal, system-ui, sans-serif' },
    grid: { vertLines: { color: 'rgba(42,47,58,.45)' }, horzLines: { color: 'rgba(42,47,58,.45)' } },
    rightPriceScale: { borderColor: '#2a2f3a' },
    timeScale: { borderColor: '#2a2f3a', timeVisible: true, secondsVisible: false, rightOffset: 6 },
    crosshair: { mode: 0 },
    localization: { priceFormatter: (p) => p.toFixed(2) },
  });
  C.series = C.chart.addCandlestickSeries({
    upColor: '#22c55e', downColor: '#ef4444', borderVisible: false, wickUpColor: '#22c55e', wickDownColor: '#ef4444',
  });
}

async function loadChartData() {
  const [{ data: tr }, { data: sg }] = await Promise.all([api('/api/trades/active'), api('/api/signals?limit=200')]);
  if (tr && tr.timeframes) C.tfs = tr.timeframes;
  C.trades = (tr && tr.trades) || [];
  C.recent = ((sg && sg.signals) || []).filter((s) => s.kind === 'entry');
  if (!C.tf) {
    const first = liveTrades().find((x) => C.tfs.includes(x.timeframe));
    C.tf = first ? first.timeframe : C.tfs.includes('5') ? '5' : C.tfs[0];
  }
  renderTabs();
  renderTradeAlerts();
  await selectTf(C.tf, false);
}

async function selectTf(tf, byHand) {
  C.tf = tf;
  if (byHand) C.pickedAt = Date.now();
  renderTabs();
  initChart();
  const { data } = await api('/api/candles?tf=' + encodeURIComponent(tf) + '&limit=500');
  if (C.tf !== tf) return; // another tab was picked meanwhile
  C.candles = (data && data.candles) || [];
  if (C.series) {
    C.series.setData(C.candles.map((b) => ({ time: toChartTime(b.t), open: b.o, high: b.h, low: b.l, close: b.c })));
    C.chart.timeScale().scrollToRealTime();
  }
  $('chartEmpty').classList.toggle('hidden', C.candles.length > 0);
  $('chartTitle').textContent = 'XAUUSD · فريم ' + tfLabel(tf);
  drawTradeOnChart();
}

function renderTabs() {
  const box = $('tfTabs');
  box.innerHTML = '';
  const live = liveTrades();
  for (const tf of C.tfs) {
    const b = document.createElement('button');
    b.className = 'tf-tab' + (tf === C.tf ? ' on' : '');
    b.textContent = tfShort(tf);
    b.title = 'فريم ' + tfLabel(tf);
    const entry = live.find((x) => x.timeframe === tf && x.kind === 'entry');
    const setup = live.find((x) => x.timeframe === tf && x.kind === 'setup');
    if (entry || setup) {
      const d = document.createElement('span');
      d.className = 'tf-dot ' + (setup && !entry ? 'setup' : entry.action === 'SELL' ? 'sell' : 'buy');
      b.appendChild(d);
    }
    b.onclick = () => selectTf(tf, true);
    box.appendChild(b);
  }
}

// One strip per open trade/setup: "get ready" for setups, "there is a trade on frame X" for entries.
function renderTradeAlerts() {
  const box = $('tradeAlerts');
  box.innerHTML = '';
  const all = liveTrades();
  const live = all.filter((x) => x.kind !== 'reinforce')
    .sort((a, b) => (a.kind === b.kind ? b.id - a.id : a.kind === 'setup' ? -1 : 1));
  for (const x of live) {
    const ex = x.extra || {};
    const el = document.createElement('button');
    const side = sideAr(x.action);
    const strong = ex.strong ? ' قوي جداً' : '';
    el.innerHTML = '<b></b><span></span>';
    if (x.kind === 'setup') {
      el.className = 'ta setup' + (ex.strong ? ' strong' : '');
      el.querySelector('b').textContent = `${ex.strong ? '⚡' : ''}⏳ استعد: صفقة ${side}${strong} محتملة على فريم ${tfLabel(x.timeframe)}`;
      el.querySelector('span').textContent = [
        x.price != null && (ex.firstTouch ? 'أول لمسة عند ' : 'الدخول عند ') + fmtNum(x.price),
        x.sl != null && 'الوقف ' + fmtNum(x.sl),
        ex.strong ? '⚠ مخاطرة عالية' : 'انتظر وصول السعر',
      ].filter(Boolean).join(' · ');
    } else {
      el.className = 'ta entry ' + (x.action === 'SELL' ? 'sell' : 'buy') + (ex.strong ? ' strong' : '');
      el.querySelector('b').textContent = `${ex.strong ? '⚡' : ''}${x.action === 'SELL' ? '🔴' : '🟢'} فيه صفقة ${side}${strong} على فريم ${tfLabel(x.timeframe)}`;
      const filled = all.filter((r) => r.kind === 'reinforce' && r.timeframe === x.timeframe && r.action === x.action && r.id > x.id)
        .map((r) => (r.extra || {}).zone).filter(Boolean);
      const hits = (ex.hits || {})['1'] || 0;
      el.querySelector('span').textContent = [
        x.price != null && 'الدخول ' + fmtNum(x.price),
        x.sl != null && 'الوقف ' + fmtNum(x.sl),
        hits ? '✓ هدف ' + hits : x.tp1 != null && 'الهدف ' + fmtNum(x.tp1),
        filled.length ? '➕ تعزيز ' + filled.join('، ') : null,
        modeChip(ex.mode),
        'منذ ' + fmtTime(x.created_at),
      ].filter(Boolean).join(' · ');
    }
    if (C.tfs.includes(x.timeframe)) el.onclick = () => selectTf(x.timeframe, true);
    box.appendChild(el);
  }
}

function drawTradeOnChart() {
  if (!C.series) return;
  for (const l of C.lines) C.series.removePriceLine(l);
  C.lines = [];
  const live = liveTrades().filter((x) => x.timeframe === C.tf);
  const entry = live.filter((x) => x.kind === 'entry').pop();
  const setup = live.filter((x) => x.kind === 'setup').pop();
  const line = (price, color, title, style = 0, width = 1) => {
    if (price == null) return;
    C.lines.push(C.series.createPriceLine({ price, color, title, lineStyle: style, lineWidth: width, axisLabelVisible: true }));
  };
  if (entry) {
    const ex = entry.extra || {};
    const hit = (ex.hits || {})['1'] || 0;
    line(entry.price, '#d4af37', (ex.strong ? '⚡ ' : '') + 'دخول ' + sideAr(entry.action), 0, 2);
    line(entry.sl, '#ef4444', 'وقف الخسارة', 0, 1);
    line(entry.tp1, '#22c55e', (hit >= 1 ? '✓ ' : '') + 'هدف 1', 2, 1);
    line(entry.tp2, '#22c55e', (hit >= 2 ? '✓ ' : '') + 'هدف 2', 2, 1);
    line(entry.tp3, '#22c55e', (hit >= 3 ? '✓ ' : '') + 'هدف 3', 2, 1);
    // Reinforcement (تعزيز) levels: dashed until filled, solid once the add-on is in.
    const filled = live.filter((r) => r.kind === 'reinforce' && r.id > entry.id).map((r) => (r.extra || {}).zone);
    (ex.zones || []).forEach((z, i) => {
      const k = i + 2;
      const on = filled.includes(k);
      line(z, on ? '#60a5fa' : 'rgba(96,165,250,.55)', (on ? '➕ ' : '') + 'تعزيز ' + k, on ? 0 : 2, 1);
    });
  }
  if (setup) {
    line(setup.price, '#e5b93b', 'دخول محتمل ' + sideAr(setup.action), 1, 1);
    line(setup.sl, 'rgba(239,68,68,.6)', 'وقف محتمل', 1, 1);
  }
  // Arrows on the candles where trades on this frame were entered.
  const times = C.candles.map((b) => b.t);
  const snap = (ms) => { let t = null; for (const bt of times) { if (bt <= ms) t = bt; else break; } return t; };
  const markers = [];
  for (const s of C.recent.filter((x) => x.timeframe === C.tf)) {
    const t = snap(s.created_at);
    if (t == null) continue;
    const buy = s.action === 'BUY';
    markers.push({
      time: toChartTime(t), position: buy ? 'belowBar' : 'aboveBar', color: buy ? '#22c55e' : '#ef4444',
      shape: buy ? 'arrowUp' : 'arrowDown', text: sideAr(s.action),
    });
  }
  markers.sort((a, b) => a.time - b.time);
  C.series.setMarkers(markers);
}

// ---------- Live updates (called from the event stream in index.html) ----------
function chartOnCandle(u) {
  if (!C.series || u.tf !== C.tf) return;
  const b = u.bar;
  const last = C.candles[C.candles.length - 1];
  if (last && b.t < last.t) return; // late correction of an old bar: ignore until next reload
  if (last && last.t === b.t) C.candles[C.candles.length - 1] = b; else C.candles.push(b);
  C.series.update({ time: toChartTime(b.t), open: b.o, high: b.h, low: b.l, close: b.c });
  $('chartEmpty').classList.add('hidden');
}

function chartOnTrades(trades) {
  C.trades = trades || [];
  renderTabs();
  renderTradeAlerts();
  drawTradeOnChart();
}

function chartOnSignal(s) {
  if (s.kind === 'entry') C.recent.unshift(s);
  // Jump to the frame of a new trade, unless the viewer picked a tab in the last minute.
  if ((s.kind === 'entry' || s.kind === 'setup') && C.tfs.includes(s.timeframe) && s.timeframe !== C.tf && Date.now() - C.pickedAt > 60000) {
    selectTf(s.timeframe, false);
  } else {
    drawTradeOnChart();
  }
}

// Setups expire on their own; refresh the strips so they disappear on time.
setInterval(() => { if (C.chart) { renderTabs(); renderTradeAlerts(); drawTradeOnChart(); } }, 15000);
