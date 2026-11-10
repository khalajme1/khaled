// Gold signals platform: receives TradingView webhook alerts and shows them
// to subscribers who log in with email + password and have an active monthly subscription.
'use strict';

const path = require('node:path');
const fs = require('node:fs');
const crypto = require('node:crypto');
const { DatabaseSync } = require('node:sqlite');
const express = require('express');
const news = require('./news');

// ---------- Config ----------
const PORT = Number(process.env.PORT || 3000);
const WEBHOOK_SECRET = process.env.WEBHOOK_SECRET || '';
const ADMIN_EMAIL = (process.env.ADMIN_EMAIL || '').trim().toLowerCase();
const ADMIN_PASSWORD = process.env.ADMIN_PASSWORD || '';
const DATA_DIR = process.env.DATA_DIR || path.join(__dirname, 'data');
const SESSION_DAYS = 30;
const SINGLE_DEVICE = process.env.SINGLE_DEVICE !== 'false'; // one active login per user
const COOKIE_SECURE = process.env.COOKIE_SECURE === 'true';

// Economic news alerts.
const NEWS_FEED_URL = process.env.NEWS_FEED_URL || 'https://nfs.faireconomy.media/ff_calendar_thisweek.json';
const NEWS_CURRENCIES = (process.env.NEWS_CURRENCIES || 'USD').split(',').map((x) => x.trim().toUpperCase()).filter(Boolean);
const NEWS_MIN_IMPACT = process.env.NEWS_MIN_IMPACT || 'High'; // High | Medium
const NEWS_WARN_BEFORE_MIN = Number(process.env.NEWS_WARN_BEFORE_MIN || 60); // caution window before news
const NEWS_WARN_AFTER_MIN = Number(process.env.NEWS_WARN_AFTER_MIN || 30); // caution window after news
const NEWS_ALERT_MIN = Number(process.env.NEWS_ALERT_MIN || 30); // send alert this many minutes before

// Partner (affiliate) brokers: a new member must open an account through one of these links.
const BROKERS = [
  { id: 'exness', name: 'Exness', url: 'https://one.exnessonelink.com/a/7w3b6fma5a' },
  { id: 'justmarkets', name: 'JustMarkets', url: 'https://one.justmarkets.link/a/tpvqxa0odj' },
  { id: 'fxpro', name: 'FxPro', url: 'https://direct.fxpro.group/ar/partner/8bGa6fgc' },
];

// Telegram channels shown to approved members who asked to join. Fill in your invite links.
const TELEGRAM_CHANNELS = [
  // { name: 'قناة التوصيات', url: 'https://t.me/+xxxxxxxx' },
];

if (!WEBHOOK_SECRET || WEBHOOK_SECRET.length < 12) {
  console.error('WEBHOOK_SECRET must be set (at least 12 characters).');
  process.exit(1);
}

fs.mkdirSync(DATA_DIR, { recursive: true });
const db = new DatabaseSync(path.join(DATA_DIR, 'app.db'));
db.exec(`
  PRAGMA journal_mode = WAL;
  CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL UNIQUE,
    name TEXT,
    pass_hash TEXT NOT NULL,
    is_admin INTEGER NOT NULL DEFAULT 0,
    expires_at INTEGER,              -- ms timestamp; NULL = no subscription
    created_at INTEGER NOT NULL
  );
  CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expires_at INTEGER NOT NULL,
    created_at INTEGER NOT NULL
  );
  CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT,
    action TEXT,
    price REAL,
    sl REAL,
    tp1 REAL,
    tp2 REAL,
    tp3 REAL,
    timeframe TEXT,
    note TEXT,
    raw TEXT,
    created_at INTEGER NOT NULL
  );
`);

db.exec(`
  CREATE TABLE IF NOT EXISTS news (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,              -- feed | manual
    ext_key TEXT UNIQUE,
    title_en TEXT,
    title_ar TEXT NOT NULL,
    currency TEXT,
    impact TEXT,
    event_at INTEGER NOT NULL,
    forecast TEXT,
    previous TEXT,
    hidden INTEGER NOT NULL DEFAULT 0,
    alerted INTEGER NOT NULL DEFAULT 0,
    created_at INTEGER NOT NULL
  );
  CREATE INDEX IF NOT EXISTS news_event_at ON news(event_at);
`);
{
  const cols = db.prepare('PRAGMA table_info(signals)').all().map((c) => c.name);
  if (!cols.includes('news')) db.exec('ALTER TABLE signals ADD COLUMN news TEXT'); // JSON: nearby news at signal time
}

// Migrations for the registration/approval flow.
{
  const cols = db.prepare('PRAGMA table_info(users)').all().map((c) => c.name);
  const add = (name, def) => { if (!cols.includes(name)) db.exec(`ALTER TABLE users ADD COLUMN ${name} ${def}`); };
  add('status', "TEXT NOT NULL DEFAULT 'approved'"); // pending | approved | rejected
  add('broker', 'TEXT');
  add('broker_account', 'TEXT');
  add('broker_email', 'TEXT');
  add('phone', 'TEXT');
  add('wants_telegram', 'INTEGER NOT NULL DEFAULT 0');
  add('telegram_username', 'TEXT');
}

// ---------- Helpers ----------
const now = () => Date.now();
const DAY = 24 * 60 * 60 * 1000;

function hashPassword(password) {
  const salt = crypto.randomBytes(16);
  const hash = crypto.scryptSync(password, salt, 64);
  return `${salt.toString('hex')}:${hash.toString('hex')}`;
}
function verifyPassword(password, stored) {
  const [saltHex, hashHex] = String(stored).split(':');
  if (!saltHex || !hashHex) return false;
  const hash = crypto.scryptSync(password, Buffer.from(saltHex, 'hex'), 64);
  const expected = Buffer.from(hashHex, 'hex');
  return expected.length === hash.length && crypto.timingSafeEqual(hash, expected);
}
const sha256 = (s) => crypto.createHash('sha256').update(s).digest('hex');
function safeEqual(a, b) {
  const x = Buffer.from(String(a));
  const y = Buffer.from(String(b));
  return x.length === y.length && crypto.timingSafeEqual(x, y);
}
function addMonths(fromMs, months) {
  const d = new Date(fromMs);
  d.setMonth(d.getMonth() + months);
  return d.getTime();
}
function num(v) {
  if (v === undefined || v === null || v === '') return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}
function publicUser(u) {
  return {
    id: u.id,
    email: u.email,
    name: u.name,
    is_admin: !!u.is_admin,
    status: u.status,
    broker: u.broker,
    broker_account: u.broker_account,
    broker_email: u.broker_email,
    phone: u.phone,
    wants_telegram: !!u.wants_telegram,
    telegram_username: u.telegram_username,
    expires_at: u.expires_at,
    active: !!u.is_admin || (u.status === 'approved' && u.expires_at != null && u.expires_at > now()),
    created_at: u.created_at,
  };
}

// Seed / update the admin account from env.
if (ADMIN_EMAIL && ADMIN_PASSWORD) {
  const existing = db.prepare('SELECT id FROM users WHERE email = ?').get(ADMIN_EMAIL);
  if (existing) {
    db.prepare('UPDATE users SET is_admin = 1, pass_hash = ? WHERE id = ?').run(hashPassword(ADMIN_PASSWORD), existing.id);
  } else {
    db.prepare('INSERT INTO users (email, name, pass_hash, is_admin, created_at) VALUES (?, ?, ?, 1, ?)')
      .run(ADMIN_EMAIL, 'Admin', hashPassword(ADMIN_PASSWORD), now());
  }
}

// ---------- App ----------
const app = express();
app.set('trust proxy', 1);
app.use(express.json({ limit: '50kb' }));
app.use(express.text({ type: ['text/plain', 'text/*'], limit: '50kb' }));

function readCookie(req, name) {
  const header = req.headers.cookie || '';
  for (const part of header.split(';')) {
    const [k, ...v] = part.trim().split('=');
    if (k === name) return decodeURIComponent(v.join('='));
  }
  return null;
}
function setSessionCookie(res, token, maxAgeMs) {
  const parts = [
    `sid=${encodeURIComponent(token)}`, 'Path=/', 'HttpOnly', 'SameSite=Lax', `Max-Age=${Math.floor(maxAgeMs / 1000)}`,
  ];
  if (COOKIE_SECURE) parts.push('Secure');
  res.setHeader('Set-Cookie', parts.join('; '));
}

function loadUser(req, _res, next) {
  req.user = null;
  const token = readCookie(req, 'sid');
  if (token) {
    const row = db.prepare(`
      SELECT u.* FROM sessions s JOIN users u ON u.id = s.user_id
      WHERE s.token_hash = ? AND s.expires_at > ?`).get(sha256(token), now());
    if (row) req.user = row;
  }
  next();
}
app.use(loadUser);

const requireAuth = (req, res, next) => (req.user ? next() : res.status(401).json({ error: 'not_logged_in' }));
const requireAdmin = (req, res, next) => (req.user && req.user.is_admin ? next() : res.status(403).json({ error: 'forbidden' }));
const requireActive = (req, res, next) => {
  if (!req.user) return res.status(401).json({ error: 'not_logged_in' });
  if (publicUser(req.user).active) return next();
  return res.status(402).json({ error: 'subscription_expired', expires_at: req.user.expires_at });
};

// Simple in-memory login rate limiting (per IP).
const loginAttempts = new Map();
function rateLimited(ip) {
  const t = now();
  const rec = loginAttempts.get(ip) || { count: 0, reset: t + 15 * 60 * 1000 };
  if (t > rec.reset) { rec.count = 0; rec.reset = t + 15 * 60 * 1000; }
  rec.count += 1;
  loginAttempts.set(ip, rec);
  return rec.count > 20;
}

// ---------- Registration ----------
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
app.get('/api/brokers', (_req, res) => res.json({ brokers: BROKERS }));

app.post('/api/register', (req, res) => {
  if (rateLimited(req.ip)) return res.status(429).json({ error: 'too_many_attempts' });
  const b = req.body || {};
  const name = String(b.name || '').trim().slice(0, 80);
  const phone = String(b.phone || '').trim().slice(0, 30) || null;
  const wantsTelegram = b.wants_telegram ? 1 : 0;
  const telegramUsername = wantsTelegram ? String(b.telegram_username || '').trim().replace(/^@/, '').slice(0, 40) || null : null;
  if (telegramUsername && !/^[A-Za-z0-9_]{4,40}$/.test(telegramUsername)) return res.status(400).json({ error: 'invalid_telegram' });
  const email = String(b.email || '').trim().toLowerCase();
  const password = String(b.password || '');
  const broker = String(b.broker || '');
  const brokerAccount = String(b.broker_account || '').trim();
  const brokerEmail = String(b.broker_email || '').trim().toLowerCase();

  if (!name) return res.status(400).json({ error: 'name_required' });
  if (!BROKERS.some((x) => x.id === broker)) return res.status(400).json({ error: 'invalid_broker' });
  if (!/^[A-Za-z0-9-]{4,30}$/.test(brokerAccount)) return res.status(400).json({ error: 'invalid_broker_account' });
  if (!EMAIL_RE.test(brokerEmail)) return res.status(400).json({ error: 'invalid_broker_email' });
  if (!EMAIL_RE.test(email)) return res.status(400).json({ error: 'invalid_email' });
  if (password.length < 6) return res.status(400).json({ error: 'password_too_short' });
  if (db.prepare('SELECT 1 FROM users WHERE email = ?').get(email)) return res.status(409).json({ error: 'email_exists' });
  if (db.prepare('SELECT 1 FROM users WHERE broker = ? AND broker_account = ?').get(broker, brokerAccount)) {
    return res.status(409).json({ error: 'broker_account_exists' });
  }
  db.prepare(`INSERT INTO users (email, name, phone, pass_hash, is_admin, status, broker, broker_account, broker_email, wants_telegram, telegram_username, expires_at, created_at)
    VALUES (?, ?, ?, ?, 0, 'pending', ?, ?, ?, ?, ?, NULL, ?)`)
    .run(email, name, phone, hashPassword(password), broker, brokerAccount, brokerEmail, wantsTelegram, telegramUsername, now());
  res.json({ ok: true, status: 'pending' });
});

// ---------- Auth ----------
app.post('/api/login', (req, res) => {
  if (rateLimited(req.ip)) return res.status(429).json({ error: 'too_many_attempts' });
  const email = String(req.body?.email || '').trim().toLowerCase();
  const password = String(req.body?.password || '');
  const user = db.prepare('SELECT * FROM users WHERE email = ?').get(email);
  if (!user || !verifyPassword(password, user.pass_hash)) {
    return res.status(401).json({ error: 'invalid_credentials' });
  }
  if (!user.is_admin && user.status === 'pending') return res.status(403).json({ error: 'pending' });
  if (!user.is_admin && user.status === 'rejected') return res.status(403).json({ error: 'rejected' });
  if (SINGLE_DEVICE && !user.is_admin) {
    // Logging in on a new device signs out the previous one (prevents account sharing).
    db.prepare('DELETE FROM sessions WHERE user_id = ?').run(user.id);
    closeStreamsForUser(user.id);
  }
  const token = crypto.randomBytes(32).toString('hex');
  db.prepare('INSERT INTO sessions (token_hash, user_id, expires_at, created_at) VALUES (?, ?, ?, ?)')
    .run(sha256(token), user.id, now() + SESSION_DAYS * DAY, now());
  setSessionCookie(res, token, SESSION_DAYS * DAY);
  res.json({ user: publicUser(user) });
});

app.post('/api/logout', (req, res) => {
  const token = readCookie(req, 'sid');
  if (token) db.prepare('DELETE FROM sessions WHERE token_hash = ?').run(sha256(token));
  setSessionCookie(res, '', 0);
  res.json({ ok: true });
});

app.get('/api/me', requireAuth, (req, res) => res.json({ user: publicUser(req.user) }));

app.post('/api/change-password', requireAuth, (req, res) => {
  const { current, next: newPass } = req.body || {};
  if (!verifyPassword(String(current || ''), req.user.pass_hash)) return res.status(400).json({ error: 'wrong_password' });
  if (String(newPass || '').length < 6) return res.status(400).json({ error: 'password_too_short' });
  db.prepare('UPDATE users SET pass_hash = ? WHERE id = ?').run(hashPassword(String(newPass)), req.user.id);
  res.json({ ok: true });
});

// Telegram links, only for active members who opted in.
app.get('/api/telegram', requireActive, (req, res) => {
  const ok = req.user.is_admin || req.user.wants_telegram;
  res.json({ channels: ok ? TELEGRAM_CHANNELS : [] });
});

// ---------- Signals ----------
function parseSignalRow(r) {
  let n = [];
  try { n = r.news ? JSON.parse(r.news) : []; } catch { n = []; }
  return { ...r, news: n };
}
app.get('/api/signals', requireActive, (req, res) => {
  const limit = Math.min(Number(req.query.limit) || 100, 500);
  const rows = db.prepare('SELECT id, symbol, action, price, sl, tp1, tp2, tp3, timeframe, note, news, created_at FROM signals ORDER BY id DESC LIMIT ?').all(limit);
  res.json({ signals: rows.map(parseSignalRow) });
});

// ---------- News ----------
const newsPublic = (n) => ({
  id: n.id, title: n.title_ar, title_en: n.title_en, currency: n.currency, impact: n.impact,
  event_at: n.event_at, forecast: n.forecast, previous: n.previous, source: n.source,
});
function newsBetween(from, to) {
  return db.prepare('SELECT * FROM news WHERE hidden = 0 AND event_at BETWEEN ? AND ? ORDER BY event_at').all(from, to);
}
// News that a signal at time t should be warned about.
function newsNear(t) {
  return newsBetween(t - NEWS_WARN_AFTER_MIN * 60000, t + NEWS_WARN_BEFORE_MIN * 60000)
    .map((n) => ({ title: n.title_ar, event_at: n.event_at, impact: n.impact }));
}

app.get('/api/news', requireActive, (_req, res) => {
  const t = now();
  res.json({
    news: newsBetween(t - DAY, t + 8 * DAY).map(newsPublic),
    warn_before_min: NEWS_WARN_BEFORE_MIN,
    warn_after_min: NEWS_WARN_AFTER_MIN,
  });
});

let lastNewsFetch = { at: null, ok: null, count: 0, error: null };
async function fetchNews() {
  try {
    const r = await fetch(NEWS_FEED_URL, { headers: { 'User-Agent': 'gold-signals/1.0' }, signal: AbortSignal.timeout(20000) });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const items = news.parseFeed(await r.json(), { currencies: NEWS_CURRENCIES, minImpact: NEWS_MIN_IMPACT });
    const keys = new Set(items.map((i) => i.ext_key));
    const from = Math.min(...items.map((i) => i.event_at));
    const to = Math.max(...items.map((i) => i.event_at));
    db.exec('BEGIN');
    try {
      const upsert = db.prepare(`INSERT INTO news (source, ext_key, title_en, title_ar, currency, impact, event_at, forecast, previous, created_at)
        VALUES ('feed', ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(ext_key) DO UPDATE SET title_ar = excluded.title_ar, impact = excluded.impact,
          forecast = excluded.forecast, previous = excluded.previous`);
      for (const i of items) upsert.run(i.ext_key, i.title_en, i.title_ar, i.currency, i.impact, i.event_at, i.forecast, i.previous, now());
      // Drop feed events in this range that disappeared (rescheduled/cancelled).
      if (items.length) {
        for (const row of db.prepare("SELECT id, ext_key FROM news WHERE source = 'feed' AND event_at BETWEEN ? AND ?").all(from, to)) {
          if (!keys.has(row.ext_key)) db.prepare('DELETE FROM news WHERE id = ?').run(row.id);
        }
      }
      db.exec('COMMIT');
    } catch (e) { db.exec('ROLLBACK'); throw e; }
    lastNewsFetch = { at: now(), ok: true, count: items.length, error: null };
  } catch (e) {
    lastNewsFetch = { at: now(), ok: false, count: 0, error: String(e.message || e) };
    console.error('News fetch failed:', lastNewsFetch.error);
  }
  return lastNewsFetch;
}
if (NEWS_FEED_URL !== 'off') {
  setTimeout(fetchNews, 2000).unref();
  setInterval(fetchNews, 60 * 60 * 1000).unref();
}

// Alert subscribers NEWS_ALERT_MIN minutes before each news event.
function checkNewsAlerts() {
  const t = now();
  const due = db.prepare('SELECT * FROM news WHERE hidden = 0 AND alerted = 0 AND event_at > ? AND event_at <= ?')
    .all(t, t + NEWS_ALERT_MIN * 60000);
  for (const n of due) {
    db.prepare('UPDATE news SET alerted = 1 WHERE id = ?').run(n.id);
    broadcast('news', newsPublic(n));
  }
}
setInterval(checkNewsAlerts, 30000).unref();

// Live updates via Server-Sent Events.
const streams = new Set(); // { res, userId, expiresAt, isAdmin }
function closeStreamsForUser(userId) {
  for (const s of streams) if (s.userId === userId) { s.res.end(); streams.delete(s); }
}
app.get('/api/stream', requireActive, (req, res) => {
  res.writeHead(200, {
    'Content-Type': 'text/event-stream',
    'Cache-Control': 'no-cache, no-transform',
    Connection: 'keep-alive',
    'X-Accel-Buffering': 'no',
  });
  res.write('retry: 5000\n\n');
  const entry = { res, userId: req.user.id, expiresAt: req.user.expires_at, isAdmin: !!req.user.is_admin };
  streams.add(entry);
  req.on('close', () => streams.delete(entry));
});
function broadcast(event, data) {
  const payload = `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;
  const t = now();
  for (const s of streams) {
    if (!s.isAdmin && !(s.expiresAt && s.expiresAt > t)) { s.res.end(); streams.delete(s); continue; }
    s.res.write(payload);
  }
}
setInterval(() => { for (const s of streams) s.res.write(': ping\n\n'); }, 25000).unref();

// TradingView webhook. URL: https://your-domain/webhook/<WEBHOOK_SECRET>
// Body: JSON (recommended) or plain text.
app.post('/webhook/:secret', (req, res) => {
  if (!safeEqual(req.params.secret, WEBHOOK_SECRET)) return res.status(404).end();

  let body = req.body;
  let raw = typeof body === 'string' ? body : JSON.stringify(body);
  if (typeof body === 'string') {
    try { body = JSON.parse(body); } catch { body = { note: body }; }
  }
  body = body && typeof body === 'object' ? body : {};

  let action = String(body.action || body.side || body.signal || '').trim().toUpperCase();
  if (['LONG', 'BUY'].includes(action)) action = 'BUY';
  else if (['SHORT', 'SELL'].includes(action)) action = 'SELL';

  const signal = {
    symbol: String(body.symbol || body.ticker || 'XAUUSD').slice(0, 30),
    action: action.slice(0, 30) || null,
    price: num(body.price ?? body.entry ?? body.close),
    sl: num(body.sl ?? body.stop ?? body.stoploss),
    tp1: num(body.tp1 ?? body.tp),
    tp2: num(body.tp2),
    tp3: num(body.tp3),
    timeframe: body.timeframe || body.interval ? String(body.timeframe || body.interval).slice(0, 10) : null,
    note: body.note || body.message || body.comment ? String(body.note || body.message || body.comment).slice(0, 500) : null,
    created_at: now(),
  };
  signal.news = newsNear(signal.created_at);
  const r = db.prepare(`INSERT INTO signals (symbol, action, price, sl, tp1, tp2, tp3, timeframe, note, news, raw, created_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`).run(
    signal.symbol, signal.action, signal.price, signal.sl, signal.tp1, signal.tp2, signal.tp3,
    signal.timeframe, signal.note, signal.news.length ? JSON.stringify(signal.news) : null,
    String(raw).slice(0, 5000), signal.created_at,
  );
  signal.id = Number(r.lastInsertRowid);
  broadcast('signal', signal);
  res.json({ ok: true, id: signal.id });
});

// ---------- Admin ----------
app.get('/api/admin/users', requireAdmin, (_req, res) => {
  const users = db.prepare('SELECT * FROM users ORDER BY id DESC').all().map(publicUser);
  res.json({ users });
});

app.post('/api/admin/users', requireAdmin, (req, res) => {
  const email = String(req.body?.email || '').trim().toLowerCase();
  const password = String(req.body?.password || '');
  const name = String(req.body?.name || '').trim() || null;
  const months = Math.max(0, Math.min(Number(req.body?.months) || 1, 36));
  if (!EMAIL_RE.test(email)) return res.status(400).json({ error: 'invalid_email' });
  if (password.length < 6) return res.status(400).json({ error: 'password_too_short' });
  if (db.prepare('SELECT 1 FROM users WHERE email = ?').get(email)) return res.status(409).json({ error: 'email_exists' });
  const expires = months > 0 ? addMonths(now(), months) : null;
  const r = db.prepare('INSERT INTO users (email, name, pass_hash, is_admin, expires_at, created_at) VALUES (?, ?, ?, 0, ?, ?)')
    .run(email, name, hashPassword(password), expires, now());
  res.json({ user: publicUser(db.prepare('SELECT * FROM users WHERE id = ?').get(Number(r.lastInsertRowid))) });
});

// Approve a pending registration and start the subscription.
app.post('/api/admin/users/:id/approve', requireAdmin, (req, res) => {
  const user = db.prepare('SELECT * FROM users WHERE id = ?').get(Number(req.params.id));
  if (!user) return res.status(404).json({ error: 'not_found' });
  const months = Math.max(1, Math.min(Math.trunc(Number(req.body?.months) || 1), 36));
  const expires = addMonths(Math.max(now(), user.expires_at || 0), months);
  db.prepare("UPDATE users SET status = 'approved', expires_at = ? WHERE id = ?").run(expires, user.id);
  res.json({ user: publicUser({ ...user, status: 'approved', expires_at: expires }) });
});

app.post('/api/admin/users/:id/reject', requireAdmin, (req, res) => {
  const id = Number(req.params.id);
  db.prepare("UPDATE users SET status = 'rejected' WHERE id = ? AND is_admin = 0").run(id);
  db.prepare('DELETE FROM sessions WHERE user_id = ? AND user_id NOT IN (SELECT id FROM users WHERE is_admin = 1)').run(id);
  closeStreamsForUser(id);
  res.json({ ok: true });
});

// Extend by N months (from the later of now / current expiry). Negative months shortens.
app.post('/api/admin/users/:id/extend', requireAdmin, (req, res) => {
  const user = db.prepare('SELECT * FROM users WHERE id = ?').get(Number(req.params.id));
  if (!user) return res.status(404).json({ error: 'not_found' });
  const months = Math.trunc(Number(req.body?.months) || 1);
  const base = months > 0 ? Math.max(now(), user.expires_at || 0) : (user.expires_at || now());
  const expires = addMonths(base, months);
  db.prepare("UPDATE users SET expires_at = ?, status = 'approved' WHERE id = ?").run(expires, user.id);
  res.json({ user: publicUser({ ...user, status: 'approved', expires_at: expires }) });
});

app.post('/api/admin/users/:id/deactivate', requireAdmin, (req, res) => {
  const id = Number(req.params.id);
  db.prepare('UPDATE users SET expires_at = ? WHERE id = ? AND is_admin = 0').run(now() - 1000, id);
  db.prepare('DELETE FROM sessions WHERE user_id = ? AND user_id NOT IN (SELECT id FROM users WHERE is_admin = 1)').run(id);
  closeStreamsForUser(id);
  res.json({ ok: true });
});

app.post('/api/admin/users/:id/password', requireAdmin, (req, res) => {
  const password = String(req.body?.password || '');
  if (password.length < 6) return res.status(400).json({ error: 'password_too_short' });
  const id = Number(req.params.id);
  db.prepare('UPDATE users SET pass_hash = ? WHERE id = ?').run(hashPassword(password), id);
  db.prepare('DELETE FROM sessions WHERE user_id = ?').run(id);
  closeStreamsForUser(id);
  res.json({ ok: true });
});

app.delete('/api/admin/users/:id', requireAdmin, (req, res) => {
  const id = Number(req.params.id);
  if (id === req.user.id) return res.status(400).json({ error: 'cannot_delete_self' });
  db.prepare('DELETE FROM sessions WHERE user_id = ?').run(id);
  db.prepare('DELETE FROM users WHERE id = ? AND is_admin = 0').run(id);
  closeStreamsForUser(id);
  res.json({ ok: true });
});

app.delete('/api/admin/signals/:id', requireAdmin, (req, res) => {
  db.prepare('DELETE FROM signals WHERE id = ?').run(Number(req.params.id));
  res.json({ ok: true });
});

// News management.
app.get('/api/admin/news', requireAdmin, (_req, res) => {
  const t = now();
  const rows = db.prepare('SELECT * FROM news WHERE event_at > ? ORDER BY event_at').all(t - DAY);
  res.json({ news: rows.map((n) => ({ ...newsPublic(n), hidden: !!n.hidden })), last_fetch: lastNewsFetch, feed: NEWS_FEED_URL !== 'off' });
});
app.post('/api/admin/news', requireAdmin, (req, res) => {
  const title = String(req.body?.title || '').trim().slice(0, 200);
  const eventAt = Number(req.body?.event_at);
  const impact = ['High', 'Medium'].includes(req.body?.impact) ? req.body.impact : 'High';
  if (!title) return res.status(400).json({ error: 'title_required' });
  if (!Number.isFinite(eventAt)) return res.status(400).json({ error: 'invalid_time' });
  const r = db.prepare(`INSERT INTO news (source, title_ar, currency, impact, event_at, created_at) VALUES ('manual', ?, 'USD', ?, ?, ?)`)
    .run(title, impact, eventAt, now());
  res.json({ news: newsPublic(db.prepare('SELECT * FROM news WHERE id = ?').get(Number(r.lastInsertRowid))) });
});
app.post('/api/admin/news/:id/hide', requireAdmin, (req, res) => {
  const hidden = req.body?.hidden === false ? 0 : 1;
  const id = Number(req.params.id);
  const n = db.prepare('SELECT source FROM news WHERE id = ?').get(id);
  if (n && n.source === 'manual' && hidden) db.prepare('DELETE FROM news WHERE id = ?').run(id);
  else db.prepare('UPDATE news SET hidden = ? WHERE id = ?').run(hidden, id);
  res.json({ ok: true });
});
app.post('/api/admin/news/refresh', requireAdmin, async (_req, res) => res.json({ last_fetch: await fetchNews() }));

// Housekeeping: remove expired sessions hourly.
setInterval(() => db.prepare('DELETE FROM sessions WHERE expires_at < ?').run(now()), 60 * 60 * 1000).unref();

// ---------- Static frontend ----------
app.use(express.static(path.join(__dirname, 'public')));
app.get('/admin', (_req, res) => res.sendFile(path.join(__dirname, 'public', 'admin.html')));

app.listen(PORT, () => console.log(`Server running on http://localhost:${PORT}`));
