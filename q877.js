// Reads the Arabic alert text of the Q877 indicator and turns each line into a site event.
// The text formats below come from the indicator's alert() messages; anything not recognised
// is kept as an "info" event so no message is lost.
'use strict';

const N = '(-?\\d+(?:\\.\\d+)?)';
const re = (s, flags = '') => new RegExp(s, flags);
const num = (m, i = 1) => (m ? Number(m[i]) : null);
const sideOf = (s) => (/شراء/.test(s) ? 'BUY' : /بيع/.test(s) ? 'SELL' : null);

// Lines that continue the previous message (pending-order block of a setup).
const CONTINUATION = [/^📌/, /^(Buy|Sell) Limit/, /^🛑 الوقف للكل/, /^🎯 أهداف الدخول/, /^⚠ إذا الدخول/];

function splitMessages(text) {
  const lines = String(text || '')
    .split(/\s*¶\s*|\r?\n/)
    .map((l) => l.trim())
    .filter((l) => l && !/^Q877 ·/.test(l));
  const msgs = [];
  for (const l of lines) {
    if (msgs.length && CONTINUATION.some((r) => r.test(l))) msgs[msgs.length - 1] += '\n' + l;
    else msgs.push(l);
  }
  return msgs;
}

function tps(m, label) {
  const r = m.match(re(label + ':?\\s*' + N + '\\s*/\\s*' + N + '\\s*/\\s*' + N));
  return r ? { tp1: Number(r[1]), tp2: Number(r[2]), tp3: Number(r[3]) } : {};
}
const groupOf = (m) => num(m.match(/#(\d+)/));
const strongOf = (m) => /⚡|قوي جداً/.test(m);

function parseMessage(m) {
  const first = m.split('\n')[0];
  let r;

  // Strong setup: "⚡⏳ استعداد بيع قوي جداً عند X · باقي d$ · ⚠ مخاطرة عالية"
  if ((r = first.match(/^⚡⏳ استعداد (شراء|بيع) قوي جداً عند/))) {
    return { type: 'setup', action: sideOf(r[1]), price: num(first.match(re('عند ' + N))), strong: true };
  }
  // Strong entry: "⚡🟢 شراء قوي جداً عند X · ... · الخروج a / b / c · تعزيز كل s · الوقف y"
  if ((r = first.match(/^⚡(?:🟢|🔴) (شراء|بيع) قوي جداً عند/))) {
    return {
      type: 'entry', action: sideOf(r[1]), strong: true,
      price: num(first.match(re('عند ' + N))), sl: num(first.match(re('الوقف ' + N))),
      step: num(first.match(re('تعزيز كل ' + N))), ...tps(first, 'الخروج'),
    };
  }
  // Entry: "🟢 شراء الآن [#2] عند X · الخروج a / b / c · تعزيز كل s · الوقف y"
  if ((r = first.match(/^(?:🟢|🔴) (شراء|بيع) الآن/))) {
    return {
      type: 'entry', action: sideOf(r[1]), group: groupOf(first), strong: /⚡/.test(first),
      price: num(first.match(re('عند ' + N))), sl: num(first.match(re('الوقف ' + N))),
      step: num(first.match(re('تعزيز كل ' + N))), ...tps(first, 'الخروج'),
    };
  }
  // Setup: "⏳ استعداد شراء - انتظر رجوع السعر إلى X" (+ pending orders block)
  //        "⏳ استعداد بيع - أول لمسة للمستوى ، انتظر وصول السعر إلى X · باقي d$"
  if ((r = first.match(/^⏳ استعداد (شراء|بيع)/))) {
    const zones = [...m.matchAll(re('Limit ' + N + '\\s*\\(تعزيز (\\d)\\)', 'g'))].map((x) => Number(x[1]));
    return {
      type: 'setup', action: sideOf(r[1]), firstTouch: /أول لمسة/.test(first),
      price: num(first.match(re('إلى ' + N))), sl: num(m.match(re('الوقف للكل:\\s*' + N))),
      zones: zones.length ? zones : undefined, ...tps(m, 'أهداف الدخول'),
    };
  }
  // Near entry: "⚠ قرب الشراء من X · باقي d$"
  if ((r = first.match(re('^⚠ قرب (الشراء|البيع) من ' + N)))) {
    return { type: 'near', action: sideOf(r[1]), price: Number(r[2]), distance: num(first.match(re('باقي ' + N))) };
  }
  // Cancel: "❌ انلغى الشراء - why · لا تدخل"
  if ((r = first.match(/^❌ انلغى (الشراء|البيع)/))) {
    return { type: 'cancel', action: sideOf(r[1]) };
  }
  // Reinforcement filled: "➕ تعزيز الآن [tag]شراء 2 من X · أهدافه a / b / c · الوقف y"
  if (/^➕ تعزيز الآن/.test(first)) {
    r = first.match(re('(شراء|بيع)\\s*(\\d)\\s*من\\s*' + N));
    return {
      type: 'reinforce', action: r && sideOf(r[1]), zone: r && Number(r[2]), price: r && Number(r[3]),
      sl: num(first.match(re('الوقف ' + N))), group: groupOf(first), strong: strongOf(first), ...tps(first, 'أهدافه'),
    };
  }
  // Whole trade closed: "🏁 / ⚖ / 🛑 [tag]تسكّرت الصفقة كلها · النتيجة ..."
  if (/تسكّرت الصفقة كلها/.test(first)) {
    const outcome = /^🏁/.test(first) ? 'win' : /^⚖/.test(first) ? 'breakeven' : 'loss';
    return { type: 'close', outcome, result: (first.match(/النتيجة\s*(.+)$/) || [])[1], group: groupOf(first), strong: strongOf(first) };
  }
  // Target hit: "✅ خروج 25% من [tag]شراء 1 الآن عند X (الهدف 1) · ..."
  if (/^✅ خروج/.test(first)) {
    r = first.match(re('(شراء|بيع)\\s*(\\d)\\s*الآن عند\\s*' + N + '\\s*\\(الهدف (\\d)\\)'));
    return { type: 'tp', action: r && sideOf(r[1]), zone: r && Number(r[2]), price: r && Number(r[3]), target: r && Number(r[4]), group: groupOf(first), strong: strongOf(first) };
  }
  // Safer mode: an add-on hit its target 1 -> everything before it closes.
  if (/^🛡 .*حقق هدفه 1/.test(first)) {
    return { type: 'info', sub: 'safe', zone: num(first.match(/تعزيز (\d)/)), price: num(first.match(re('عند ' + N))), group: groupOf(first), strong: strongOf(first) };
  }
  // Main entry stop moved to break-even.
  if (/^🛡 السعر تجاوز الدخول الرئيسي/.test(first)) {
    r = first.match(re('(شراء|بيع)\\s*1 على الدخول\\s*' + N));
    return { type: 'info', sub: 'breakeven', action: r && sideOf(r[1]), price: r && Number(r[2]) };
  }
  // Remainder closed at entry / trailing stop.
  if (/^🚪 خروج الباقي/.test(first)) {
    r = first.match(re('(شراء|بيع)\\s*(\\d)\\s*الآن عند\\s*' + N));
    return { type: 'info', sub: 'exit', action: r && sideOf(r[1]), zone: r && Number(r[2]), price: r && Number(r[3]) };
  }
  // Stop loss hit for zones that had not reached target 1.
  if ((r = first.match(re('^🛑 .*خروج الآن \\(وقف\\) عند\\s*' + N)))) {
    return { type: 'info', sub: 'stop', price: Number(r[1]), group: groupOf(first), strong: strongOf(first) };
  }
  if (/^⏳ قرب التعزيز/.test(first)) {
    r = first.match(re('(شراء|بيع)\\s*(\\d)\\s*من\\s*' + N));
    return { type: 'info', sub: 'near_reinforce', action: r && sideOf(r[1]), zone: r && Number(r[2]), price: r && Number(r[3]) };
  }
  if (/^🎯 هدف اليوم/.test(first)) return { type: 'info', sub: 'day_target' };
  if (/^📅 نهاية الأسبوع/.test(first)) return { type: 'info', sub: 'week_end' };
  return { type: 'info', sub: 'other' };
}

// One alert text -> list of events (each keeps its own line as the note).
function parseQ877(text) {
  return splitMessages(text).map((m) => {
    const ev = parseMessage(m);
    for (const k of Object.keys(ev)) if (ev[k] === undefined || ev[k] === null || Number.isNaN(ev[k])) delete ev[k];
    ev.note = m.split('\n')[0].slice(0, 500);
    return ev;
  });
}

const isQ877Text = (s) => typeof s === 'string' && /^\s*Q877 ·/.test(s);

module.exports = { parseQ877, splitMessages, isQ877Text };
