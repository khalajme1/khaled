# منصة توصيات الذهب (TradingView → موقع للمشتركين)

الصفقات اللي يطلعها المؤشر في TradingView توصل للموقع مباشرة، والمشترك يشوفها بعد ما يسجل دخول بالإيميل وكلمة المرور، وكل حساب له اشتراك شهري ينتهي تلقائياً.

## طريقة التسجيل
1. المشترك يفتح الموقع ويضغط **سجّل الآن** (أو الرابط المباشر `https://your-domain.com/#register`).
2. يفتح حساب تداول عن طريق أحد روابط الوكالة: Exness أو JustMarkets أو FxPro.
3. يعبي النموذج: الشركة، ورقم الحساب فيها، والإيميل المسجل فيها، وبعدها اسمه وإيميل وكلمة مرور للموقع.
4. الطلب يوصل لك في `/admin` تحت **طلبات التسجيل**. تتأكد من لوحة الشريك إن الحساب تحت وكالتك، وبعدها تختار المدة وتضغط **موافقة** أو **رفض**.
5. قبل الموافقة ما يقدر يدخل ("طلبك قيد المراجعة"). وبعد الموافقة يدخل ويبدأ اشتراكه.

ما يقدر أحد يسجل نفس رقم الحساب مرتين. روابط الوكالة موجودة في `BROKERS` أعلى ملف `server.js`.

## المميزات
- تسجيل دخول بالإيميل + كلمة مرور (مشفرة بـ scrypt).
- اشتراك لكل مستخدم بتاريخ انتهاء؛ لما ينتهي يوقف عرض الصفقات تلقائياً.
- **جهاز واحد لكل حساب**: لو سجل دخول من جهاز ثاني، الأول يطلع (يمنع مشاركة الحساب). تقدر تلغيها بـ `SINGLE_DEVICE=false`.
- الصفقات تظهر **مباشرة** بدون تحديث الصفحة + صوت + إشعار بالمتصفح.
- لوحة تحكم `/admin`: إضافة مشترك، تمديد شهر/3 شهور، إيقاف، تغيير كلمة المرور، حذف.
- يشتغل على الجوال ويقدر المشترك يضيفه للشاشة الرئيسية كأنه تطبيق.

## التشغيل
يحتاج Node.js 22.5 أو أحدث.
```bash
npm install
WEBHOOK_SECRET="سر-طويل-وعشوائي-123456" \
ADMIN_EMAIL="you@example.com" \
ADMIN_PASSWORD="كلمة-مرور-قوية" \
COOKIE_SECURE=true \
npm start
```
| المتغير | الوصف |
|---|---|
| `WEBHOOK_SECRET` | سر رابط الويبهوك (12 حرف على الأقل) — لا تشاركه مع أحد |
| `ADMIN_EMAIL` / `ADMIN_PASSWORD` | حساب المدير (ينشأ تلقائياً) |
| `PORT` | المنفذ (افتراضي 3000) |
| `DATA_DIR` | مكان قاعدة البيانات (افتراضي `./data`) |
| `COOKIE_SECURE` | خلّه `true` لما يكون الموقع على https |
| `SINGLE_DEVICE` | `false` للسماح بأكثر من جهاز |

## ربط TradingView
1. انشر الموقع على دومين بـ **https** (مثلاً Railway أو Render أو VPS). TradingView يرسل فقط على المنفذ 80/443.
2. في TradingView افتح Alert على المؤشر ← تبويب Notifications ← فعّل **Webhook URL** وحط:
   ```
   https://your-domain.com/webhook/<WEBHOOK_SECRET>
   ```
   (الويبهوك يحتاج اشتراك TradingView مدفوع وتفعيل التحقق الثنائي 2FA).
3. في خانة **Message** حط JSON. أفضل طريقة من داخل كود Pine Script:
```pine
if buySignal
    alert('{"symbol":"' + syminfo.ticker + '","action":"BUY","price":' + str.tostring(close) +
          ',"sl":' + str.tostring(slLevel) + ',"tp1":' + str.tostring(tp1) +
          ',"tp2":' + str.tostring(tp2) + ',"tp3":' + str.tostring(tp3) +
          ',"timeframe":"' + timeframe.period + '"}', alert.freq_once_per_bar_close)
if sellSignal
    alert('{"symbol":"' + syminfo.ticker + '","action":"SELL","price":' + str.tostring(close) +
          ',"sl":' + str.tostring(slLevel) + ',"tp1":' + str.tostring(tp1) + '}', alert.freq_once_per_bar_close)
```
   وبعدها تسوي Alert بشرط **"Any alert() function call"**.

   أو لو تستخدم `alertcondition`، حط بالرسالة:
   ```
   {"symbol":"{{ticker}}","action":"BUY","price":{{close}},"timeframe":"{{interval}}"}
   ```
الحقول المدعومة: `symbol`, `action` (BUY/SELL/LONG/SHORT), `price`, `sl`, `tp1`, `tp2`, `tp3`, `timeframe`, `note`. أي رسالة نص عادي تنعرض كتنبيه.

## الاستخدام اليومي
- ادخل `/admin` بحساب المدير ← أضف المشترك (إيميل + كلمة مرور + المدة) ← أرسل له البيانات.
- لما يدفع التجديد اضغط **+ شهر** (يتمدد من تاريخ الانتهاء الحالي، ما يضيع عليه أيام).

## تجربة الويبهوك يدوياً
```bash
curl -X POST https://your-domain.com/webhook/<WEBHOOK_SECRET> \
  -H "Content-Type: application/json" \
  -d '{"symbol":"XAUUSD","action":"BUY","price":2650.5,"sl":2640,"tp1":2660}'
```
