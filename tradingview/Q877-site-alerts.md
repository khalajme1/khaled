# ربط مؤشر Q877 بموقع التوصيات

التعديل ما يغيّر أي شي في منطق المؤشر ولا في الصفقات. بس يضيف خيار **"📡 إرسال التنبيهات لموقع التوصيات"**.
لما تشغّله، نفس نصوص التنبيهات اللي يطلعها المؤشر تنرسل للموقع، ومعها الفريم وسعر الشمعة (عشان الشارت).
والموقع يقرأ النص ويحوّله لمراحل: استعداد ← قرب ← دخول ← تعزيز ← أهداف ← تسكير.

افتح المؤشر في محرر Pine وسوِّ هالتعديلات الأربعة:

---

## 1) إضافة الخيار

ابحث عن هالسطر:
```pine
magOn = input.bool(true, "حسبة دقيقة للشموع السريعة", group = G_V,
```
(السطر طويل، كمّله لآخره). **تحته مباشرة** أضف:
```pine
siteOn = input.bool(false, "📡 إرسال التنبيهات لموقع التوصيات", group = G_V, tooltip = "مفعّل = التنبيهات تنرسل للموقع (رابط الويبهوك) مع الفريم وسعر الشمعة.\nسوِّ تنبيه على كل فريم (1 و 3 و 5 و 15 دقيقة) بشرط: أي استدعاء لدالة alert()")
```

---

## 2) تنبيه "استعداد قوي جداً" اللحظي

ابحث عن:
```pine
        if barstate.isrealtime and not sWarn.get(sb)
```
وغيّره إلى:
```pine
        if barstate.isrealtime and not sWarn.get(sb) and not siteOn
```

---

## 3) تنبيهات "اللمس" و"القرب" اللحظية

ابحث عن:
```pine
        if hit and barstate.isrealtime
```
وغيّره إلى:
```pine
        if hit and barstate.isrealtime and not siteOn
```

وتحته ابحث عن:
```pine
        else if near and barstate.isrealtime and not btNear.get(best)
```
وغيّره إلى:
```pine
        else if near and barstate.isrealtime and not btNear.get(best) and not siteOn
```

> هذي التنبيهات مكررة (نفس الدخول ونفس القرب يوصلون من التنبيهات الأساسية)، فنوقفها بس لما يكون الموقع شغال.

---

## 4) التنبيهات الأساسية

ابحث عن هالجزء (تحت عنوان `// ════════════════════ التنبيهات ════════════════════`):
```pine
// الدخول: ينرسل لحظة اللمس (مرة وحدة بالشمعة) بدون انتظار الإغلاق
if entryMsg != ""
    alert("Q877 · " + syminfo.ticker + entryMsg, alert.freq_once_per_bar)
// باقي الأحداث (أهداف ، تعزيز ، وقف ، استعداد...) مع إغلاق الشمعة
if alertMsg != ""
    alert("Q877 · " + syminfo.ticker + alertMsg, alert.freq_once_per_bar_close)
```
وبدّله كله بهذا:
```pine
// رسالة الموقع: نفس نص التنبيه + الفريم + شمعة السعر (JSON للويبهوك)
siteMsg(string phase, string msg, bool withBar) =>
    string body = str.replace_all(str.replace_all(str.trim(msg), '"', "'"), "\n", " ¶ ")
    string bar  = withBar ? ',"bar":{"time":' + str.tostring(time) + ',"open":' + str.tostring(open, format.mintick) + ',"high":' + str.tostring(high, format.mintick) + ',"low":' + str.tostring(low, format.mintick) + ',"close":' + str.tostring(close, format.mintick) + '}' : ""
    '{"source":"q877","symbol":"' + syminfo.ticker + '","timeframe":"' + timeframe.period + '","mode":"' + mode + '","phase":"' + phase + '","text":"' + body + '"' + bar + '}'

if siteOn
    // الدخول: لحظة اللمس
    if entryMsg != ""
        alert(siteMsg("entry", entryMsg, false), alert.freq_once_per_bar)
    // باقي الأحداث + شمعة السعر للشارت: مع إغلاق كل شمعة
    if barstate.isconfirmed
        alert(siteMsg("close", alertMsg, true), alert.freq_once_per_bar_close)
else
    // الدخول: ينرسل لحظة اللمس (مرة وحدة بالشمعة) بدون انتظار الإغلاق
    if entryMsg != ""
        alert("Q877 · " + syminfo.ticker + entryMsg, alert.freq_once_per_bar)
    // باقي الأحداث (أهداف ، تعزيز ، وقف ، استعداد...) مع إغلاق الشمعة
    if alertMsg != ""
        alert("Q877 · " + syminfo.ticker + alertMsg, alert.freq_once_per_bar_close)
```

احفظ المؤشر (Save) وتأكد ما طلع خطأ تحت المحرر.

---

## تشغيله

1. حط المؤشر على شارت الذهب (نفس الرمز اللي تتداول عليه، مثلاً `OANDA:XAUUSD`).
2. من إعدادات المؤشر ← **④ العرض** ← فعّل **📡 إرسال التنبيهات لموقع التوصيات**.
3. سوِّ تنبيه (Alert):
   - **الشرط:** `Q877 REBOUND ZONE & SIGNALS` ← **أي استدعاء لدالة alert() (Any alert() function call)**
   - **Notifications ← Webhook URL:** `https://دومين-موقعك/webhook/<WEBHOOK_SECRET>`
   - الرسالة (Message) اتركها، المؤشر يكتبها بنفسه.
4. كرر الخطوة 3 على كل فريم تبيه في الموقع: **1 دقيقة، 3، 5، 15** (غيّر فريم الشارت وسوِّ تنبيه جديد).

**ملاحظات:**
- تنبيه فريم الدقيقة هو اللي يعبّي الشارت بالموقع بشموع الدقيقة (ومنها تنبني 3 و5 و15).
- لما يكون الخيار مفعّل، التنبيهات اللي توصلك من TradingView تكون بصيغة الموقع (JSON). إذا تبي تنبيهات نصية لجوالك بعد، الموقع نفسه يرسل الإشعارات بالعربي.
- إذا الخيار **مطفي**، المؤشر يرجع مثل ما كان بالضبط.
