"""رسم صورة الصفقات: عنوان + بطاقة صاعد (أخضر) + بطاقة هابط (أحمر) + الأهداف مرقمة."""
import html
import os
from pathlib import Path

from .levels import Levels

TEMPLATE = """<!doctype html>
<html lang="ar" dir="rtl"><head><meta charset="utf-8">
<link href="https://fonts.googleapis.com/css2?family=Noto+Sans+Arabic:wght@500;700;800&display=swap" rel="stylesheet">
<style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ background:#000; font-family:'Noto Sans Arabic', sans-serif; color:#fff; }}
  #card {{ width:1080px; background:#0b0b0d; padding:36px; }}
  .n {{ unicode-bidi:isolate; direction:ltr; font-variant-numeric:tabular-nums; }}

  header {{ display:flex; justify-content:space-between; align-items:center;
            padding-bottom:22px; margin-bottom:26px; border-bottom:2px solid #d4af37; }}
  h1 {{ font-size:46px; font-weight:800; color:#e8c45a; }}
  .date {{ text-align:left; color:#a9a9a9; font-size:22px; line-height:1.4; }}
  .date b {{ display:block; color:#fff; font-size:28px; }}

  .sc {{ border-radius:18px; padding:24px 26px; margin-bottom:22px; }}
  .up   {{ background:#10291a; border:2px solid #1f6b3a; }}
  .down {{ background:#2d1213; border:2px solid #8a2a2c; }}
  .head {{ display:flex; justify-content:space-between; align-items:center; margin-bottom:20px; }}
  .head h2 {{ font-size:34px; font-weight:700; }}
  .up .head h2 {{ color:#4fd27f; }}
  .down .head h2 {{ color:#ff6b6b; }}
  .entry {{ font-size:26px; color:#ddd; background:rgba(255,255,255,.07);
            padding:6px 20px; border-radius:12px; }}
  .entry .n {{ font-size:36px; font-weight:800; color:#fff; margin-right:8px; }}

  .targets {{ display:grid; grid-template-columns:repeat(6,1fr); gap:12px; }}
  .t {{ background:rgba(0,0,0,.35); border-radius:12px; padding:10px 0; text-align:center; }}
  .t small {{ display:block; font-size:18px; color:#9a9a9a; }}
  .t .n {{ font-size:32px; font-weight:700; }}

  footer {{ text-align:center; color:#6f6f6f; font-size:18px; margin-top:6px; }}
</style></head><body><div id="card">
  <header>
    <h1>{title}</h1>
    <div class="date"><b class="n">{date}</b>3:00 فجراً بتوقيت الكويت</div>
  </header>
  <section class="sc up">
    <div class="head"><h2>▲ السيناريو الصاعد</h2><div class="entry">الثبات فوق<span class="n">{up_entry}</span></div></div>
    <div class="targets">{up_targets}</div>
  </section>
  <section class="sc down">
    <div class="head"><h2>▼ السيناريو الهابط</h2><div class="entry">الثبات تحت<span class="n">{down_entry}</span></div></div>
    <div class="targets">{down_targets}</div>
  </section>
  <footer>ليست توصية مالية — إدارة رأس المال مسؤوليتك</footer>
</div></body></html>"""


def _chips(nums: list[int]) -> str:
    return "".join(
        f'<div class="t"><small>هدف {i}</small><span class="n">{n}</span></div>'
        for i, n in enumerate(nums, 1)
    )


def build_html(levels: Levels, title: str, date: str) -> str:
    return TEMPLATE.format(
        title=html.escape(title),
        date=html.escape(date),
        up_entry=levels.up.entry,
        up_targets=_chips(levels.up.targets),
        down_entry=levels.down.entry,
        down_targets=_chips(levels.down.targets),
    )


def render_png(levels: Levels, out: Path, title: str, date: str) -> Path:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        exe = os.environ.get("CHROMIUM_PATH")
        browser = p.chromium.launch(executable_path=exe) if exe else p.chromium.launch()
        page = browser.new_page(device_scale_factor=2)
        page.set_content(build_html(levels, title, date), wait_until="networkidle")
        page.evaluate("document.fonts.ready")
        page.locator("#card").screenshot(path=str(out))
        browser.close()
    return out
