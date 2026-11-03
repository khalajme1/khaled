"""التشغيل اليومي: سعر → مستويات → صورة → تيليجرام."""
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .levels import compute_levels
from .price import get_gold_price
from .render import render_png

KUWAIT = timezone(timedelta(hours=3))


def main() -> None:
    today = datetime.now(KUWAIT).strftime("%Y-%m-%d")
    price = get_gold_price()
    levels = compute_levels(price)
    out = Path(os.environ.get("OUTPUT", "signal.png"))
    render_png(levels, out, title="الذهب على فريم كبير", date=today)
    print(f"price={price:.2f} up={levels.up} down={levels.down} -> {out}")

    if os.environ.get("TELEGRAM_BOT_TOKEN"):
        from .telegram import send_photo

        send_photo(out)
        print("sent to Telegram")
    else:
        print("TELEGRAM_BOT_TOKEN غير موجود — تم حفظ الصورة فقط")


if __name__ == "__main__":
    main()
