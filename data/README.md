# داده دمو

این پوشه شامل داده **شبیه‌سازی‌شده و قطعی** برای اجرای خط لوله است؛ نماینده بازار واقعی نیست.

| فایل | توضیح |
|---|---|
| `EURUSD_H1.csv` | ۴۶۵۸ کندل H1 از ۲۰۲۶-۰۲-۰۱ تا ۲۰۲۶-۱۰-۳۰ (Seed=7) |
| `DXY_H1.csv` | سری مرجع بین‌بازاری با همبستگی منفی به EURUSD |
| `economic_events.csv` | تقویم اقتصادی نمونه (NFP/CPI/FOMC/ECB/BOE/BOJ) |
| `fxars.db` | پایگاه داده SQLite (پس از seed-demo) |

بازتولید:

```powershell
python -m fxars seed-demo
```

پارامترهای تولید در `fxars/data/synthetic.py` و دستور `seed-demo` تعریف شده‌اند. هر تغییر Seed یا دوره، `data_snapshot_id` جدید می‌سازد و نتایج قبلی قابل مقایسه نخواهند بود.
