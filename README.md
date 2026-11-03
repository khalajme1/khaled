# صفقات الذهب اليومية

ترسل صورة الصفقات (نفس التصميم) كل يوم الساعة **3:00 الفجر بتوقيت الكويت** إلى تيليجرام عن طريق GitHub Actions.

![مثال](example.png)

## الإعداد (مرة وحدة)
1. افتح [@BotFather](https://t.me/BotFather) في تيليجرام، وسوّ بوت جديد بالأمر `/newbot`، وانسخ الـ **Token**.
2. أرسل أي رسالة للبوت (أو أضفه للقروب/القناة كمشرف)، ثم افتح
   `https://api.telegram.org/bot<TOKEN>/getUpdates` وانسخ رقم `chat.id`.
3. في GitHub: **Settings → Secrets and variables → Actions → New repository secret**، وأضف:
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_CHAT_ID`
4. للتجربة الحين: **Actions → Daily gold signal → Run workflow**.

## تعديل منطق المؤشر
المعادلة موجودة في `gold_signals/levels.py`. المعادلة الحالية مستنتجة من الصورة
(أهداف تبعد 16 / 30 / 47 / 69 / 95 / 125 نقطة عن نقطة الثبات).
استبدلها بمعادلة مؤشرك الحقيقية.

## تشغيل محلي
```bash
pip install -r requirements.txt && python -m playwright install chromium
MANUAL_PRICE=3947 python -m gold_signals.main   # يحفظ signal.png
```
