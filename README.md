# khaled — GoldScalperPro

سكالبر للذهب (XAUUSD) على فريمات M1 / M3 / M5 لمنصة MT5، مع إدارة مخاطر صارمة: الحد الأقصى للتراجع 9٪ يوقف الإكسبيرت.

| الملف | الوصف |
|---|---|
| `docs/STUDY_AR.md` | الدراسة الكاملة: مقارنة الفريمات، حسبة الهدف والتراجع، وخطوات الاختبار |
| `mql5/Experts/GoldScalperPro.mq5` | الإكسبيرت |
| `mql5/Scripts/ExportM1Bars.mq5` | سكربت يصدّر بيانات M1 من MT5 إلى CSV |
| `research/backtest.py` | دراسة الفريمات + باكتست + تحسين مع اختبار خارج العينة |
| `research/make_synthetic.py` | بيانات مصطنعة لاختبار البرنامج فقط |

```bash
python research/backtest.py XAUUSD_M1.csv --spread 0.26 --optimize
```
