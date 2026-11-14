// Live gold prices from Twelve Data for the site's chart:
// history on start, then live ticks over WebSocket (or REST polling if the plan has no WebSocket).
'use strict';

const BASE = process.env.TWELVEDATA_BASE || 'https://api.twelvedata.com';
const WS_URL = process.env.TWELVEDATA_WS_URL || 'wss://ws.twelvedata.com/v1/quotes/price';

// History pulled on start: [Twelve Data interval, site timeframe, bars]. 3-minute candles are built from 1-minute ones.
const BACKFILL = [['15min', '15', 1500], ['5min', '5', 2000], ['1min', '1', 5000]];

function createPriceFeed({ apiKey, symbol, useWs, pollSec, onBar, log = console }) {
  const status = {
    source: 'Twelve Data', symbol, mode: useWs ? 'websocket' : 'polling',
    connected: false, lastTick: null, lastPrice: null, lastError: null, backfilled: 0, startedAt: Date.now(),
  };
  let cur = null; // forming 1-minute bar
  let lastEmit = 0;

  const fail = (where, e) => {
    status.lastError = `${where}: ${e.message || e}`;
    log.error('[price feed]', status.lastError);
  };

  async function series(interval, outputsize) {
    const u = `${BASE}/time_series?symbol=${encodeURIComponent(symbol)}&interval=${interval}&outputsize=${outputsize}`
      + `&timezone=UTC&order=ASC&apikey=${encodeURIComponent(apiKey)}`;
    const r = await fetch(u, { signal: AbortSignal.timeout(30000) });
    const j = await r.json().catch(() => ({}));
    if (j.status !== 'ok' || !Array.isArray(j.values)) throw new Error(j.message || `HTTP ${r.status}`);
    return j.values
      .map((v) => ({ t: Date.parse(String(v.datetime).replace(' ', 'T') + 'Z'), o: +v.open, h: +v.high, l: +v.low, c: +v.close }))
      .filter((b) => Number.isFinite(b.t) && [b.o, b.h, b.l, b.c].every(Number.isFinite));
  }

  async function backfill() {
    for (const [interval, tf, size] of BACKFILL) {
      try {
        const bars = await series(interval, size);
        for (const b of bars) onBar(tf, b, { broadcast: false });
        status.backfilled += bars.length;
        if (tf === '1' && bars.length) cur = { ...bars[bars.length - 1] };
      } catch (e) { fail('history ' + interval, e); }
    }
  }

  // Re-read the last few 1-minute bars (exact OHLC; ticks can miss a wick).
  async function sync(size = 3, broadcast = true) {
    const bars = await series('1min', size);
    for (const b of bars) onBar('1', b, { broadcast });
    if (bars.length) {
      const last = bars[bars.length - 1];
      if (!cur || last.t >= cur.t) cur = { ...last };
      status.lastPrice = last.c;
      status.lastTick = Date.now();
      status.lastError = null;
    }
  }

  function tick(price, ts) {
    const m = Math.floor(ts / 60000) * 60000;
    if (!cur || m > cur.t) {
      if (cur) onBar('1', cur); // close the previous minute
      cur = { t: m, o: cur && m - cur.t <= 120000 ? cur.c : price, h: price, l: price, c: price };
      cur.h = Math.max(cur.h, cur.o); cur.l = Math.min(cur.l, cur.o);
    } else if (m === cur.t) {
      cur.c = price; cur.h = Math.max(cur.h, price); cur.l = Math.min(cur.l, price);
    } else return; // late tick for an old minute
    status.lastTick = Date.now();
    status.lastPrice = price;
    if (Date.now() - lastEmit >= 1000) { lastEmit = Date.now(); onBar('1', cur); }
  }

  function connectWs() {
    let hb = null;
    let ws;
    try { ws = new WebSocket(`${WS_URL}?apikey=${encodeURIComponent(apiKey)}`); } catch (e) { fail('websocket', e); setTimeout(connectWs, 10000); return; }
    ws.onopen = () => {
      status.connected = true;
      ws.send(JSON.stringify({ action: 'subscribe', params: { symbols: symbol } }));
      hb = setInterval(() => { try { ws.send(JSON.stringify({ action: 'heartbeat' })); } catch { /* reconnects on close */ } }, 10000);
    };
    ws.onmessage = (e) => {
      let m; try { m = JSON.parse(e.data); } catch { return; }
      if (m.event === 'price' && Number.isFinite(+m.price)) tick(+m.price, m.timestamp ? m.timestamp * 1000 : Date.now());
      else if (m.event === 'subscribe-status' && m.status !== 'ok') fail('websocket subscribe', new Error(JSON.stringify(m.fails || m.messages || m.status)));
    };
    ws.onerror = () => { status.lastError = 'websocket: connection error'; };
    ws.onclose = () => { clearInterval(hb); status.connected = false; setTimeout(connectWs, 5000); };
  }

  async function start() {
    log.log(`[price feed] Twelve Data ${symbol} (${status.mode})`);
    await backfill();
    if (useWs) {
      connectWs();
      // Correct the recent candles from REST every 5 minutes.
      setInterval(() => sync(6).catch((e) => fail('sync', e)), 5 * 60000).unref();
    } else {
      status.connected = true;
      const poll = () => sync(2).catch((e) => fail('poll', e));
      setInterval(poll, Math.max(5, pollSec) * 1000).unref();
    }
  }

  return { start, status };
}

module.exports = { createPriceFeed };
