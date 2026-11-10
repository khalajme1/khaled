// Economic calendar: high-impact news that moves gold, with Arabic titles.
'use strict';

// Arabic names for common calendar events (matched in order, first wins).
const TITLES_AR = [
  [/^ADP Non-Farm Employment Change/i, 'وظائف القطاع الخاص ADP'],
  [/Non-Farm Employment Change|Non-Farm Payrolls/i, 'الوظائف غير الزراعية (NFP)'],
  [/^Unemployment Rate/i, 'معدل البطالة'],
  [/Unemployment Claims/i, 'طلبات إعانة البطالة'],
  [/Average Hourly Earnings/i, 'متوسط الأجر بالساعة'],
  [/JOLTS Job Openings/i, 'فرص العمل JOLTS'],
  [/^Core CPI/i, 'مؤشر أسعار المستهلك الأساسي (التضخم)'],
  [/^CPI/i, 'مؤشر أسعار المستهلك (التضخم)'],
  [/^Core PPI/i, 'مؤشر أسعار المنتجين الأساسي'],
  [/^PPI/i, 'مؤشر أسعار المنتجين'],
  [/Core PCE Price Index/i, 'مؤشر نفقات الاستهلاك الأساسي (PCE)'],
  [/PCE Price Index/i, 'مؤشر نفقات الاستهلاك (PCE)'],
  [/Federal Funds Rate/i, 'قرار الفائدة الأمريكية'],
  [/FOMC Statement/i, 'بيان الفيدرالي الأمريكي'],
  [/FOMC Press Conference/i, 'المؤتمر الصحفي للفيدرالي'],
  [/FOMC Meeting Minutes/i, 'محضر اجتماع الفيدرالي'],
  [/FOMC Economic Projections/i, 'توقعات الفيدرالي الاقتصادية'],
  [/Fed Chair .* (Speaks|Testifies)/i, 'خطاب رئيس الفيدرالي الأمريكي'],
  [/FOMC Member .* Speaks|Fed .* Speaks/i, 'خطاب عضو في الفيدرالي'],
  [/President .* Speaks/i, 'خطاب الرئيس الأمريكي'],
  [/Treasury Sec.* Speaks/i, 'خطاب وزير الخزانة الأمريكي'],
  [/GDP/i, 'الناتج المحلي الإجمالي'],
  [/^Core Retail Sales/i, 'مبيعات التجزئة الأساسية'],
  [/Retail Sales/i, 'مبيعات التجزئة'],
  [/ISM Manufacturing Prices/i, 'أسعار التصنيع ISM'],
  [/ISM Manufacturing PMI/i, 'مؤشر مديري المشتريات الصناعي ISM'],
  [/ISM Services PMI/i, 'مؤشر مديري المشتريات الخدمي ISM'],
  [/Flash Manufacturing PMI/i, 'مؤشر مديري المشتريات الصناعي (أولي)'],
  [/Flash Services PMI/i, 'مؤشر مديري المشتريات الخدمي (أولي)'],
  [/UoM Consumer Sentiment/i, 'ثقة المستهلك (ميشيغان)'],
  [/UoM Inflation Expectations/i, 'توقعات التضخم (ميشيغان)'],
  [/CB Consumer Confidence/i, 'ثقة المستهلك'],
  [/Empire State Manufacturing/i, 'مؤشر نيويورك الصناعي'],
  [/Philly Fed Manufacturing/i, 'مؤشر فيلادلفيا الصناعي'],
  [/Durable Goods Orders/i, 'طلبيات السلع المعمرة'],
  [/Crude Oil Inventories/i, 'مخزونات النفط الخام'],
  [/Existing Home Sales/i, 'مبيعات المنازل القائمة'],
  [/New Home Sales/i, 'مبيعات المنازل الجديدة'],
  [/Building Permits/i, 'تصاريح البناء'],
  [/Trade Balance/i, 'الميزان التجاري'],
  [/Industrial Production/i, 'الإنتاج الصناعي'],
  [/Employment Cost Index/i, 'مؤشر تكلفة التوظيف'],
  [/Bank Holiday/i, 'عطلة رسمية'],
];

const SUFFIX_AR = [
  [/\bm\/m\b/i, ' - شهري'],
  [/\by\/y\b/i, ' - سنوي'],
  [/\bq\/q\b/i, ' - ربع سنوي'],
];

const COUNTRY_AR = { USD: 'أمريكا', EUR: 'أوروبا', GBP: 'بريطانيا', CNY: 'الصين', JPY: 'اليابان', CHF: 'سويسرا' };

function translateTitle(title) {
  const t = String(title || '');
  const hit = TITLES_AR.find(([re]) => re.test(t));
  if (!hit) return t;
  const suffix = SUFFIX_AR.find(([re]) => re.test(t));
  return hit[1] + (suffix ? suffix[1] : '');
}

const IMPACT_RANK = { Low: 1, Medium: 2, High: 3 };

// Parses a Forex-Factory-style weekly calendar JSON array.
function parseFeed(items, { currencies, minImpact }) {
  const min = IMPACT_RANK[minImpact] || 3;
  const out = [];
  for (const it of Array.isArray(items) ? items : []) {
    const currency = String(it.country || it.currency || '').toUpperCase();
    const impact = String(it.impact || '');
    if (!currencies.includes(currency)) continue;
    if ((IMPACT_RANK[impact] || 0) < min) continue;
    const eventAt = Date.parse(it.date);
    if (!Number.isFinite(eventAt)) continue;
    const titleEn = String(it.title || '').slice(0, 200);
    out.push({
      ext_key: `ff:${currency}:${titleEn}:${eventAt}`,
      title_en: titleEn,
      title_ar: translateTitle(titleEn),
      currency,
      impact,
      event_at: eventAt,
      forecast: it.forecast ? String(it.forecast).slice(0, 30) : null,
      previous: it.previous ? String(it.previous).slice(0, 30) : null,
    });
  }
  return out;
}

module.exports = { translateTitle, parseFeed, COUNTRY_AR };
