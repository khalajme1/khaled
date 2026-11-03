"""جلب سعر الذهب (آخر إغلاق يومي)."""
import os


def get_gold_price() -> float:
    manual = os.environ.get("MANUAL_PRICE", "").strip()
    if manual:
        return float(manual)
    import yfinance as yf

    symbol = os.environ.get("GOLD_SYMBOL", "GC=F")  # عقود الذهب الآجلة
    hist = yf.Ticker(symbol).history(period="5d", interval="1d")
    if hist.empty:
        raise RuntimeError(f"تعذر جلب سعر {symbol}")
    return float(hist["Close"].iloc[-1])
