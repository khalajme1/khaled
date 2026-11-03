"""رسم الصورة بنفس تصميم الجدول (عنوان + سطر أخضر + سطر أحمر)."""
import html
import os
from pathlib import Path

from .levels import Levels

TEMPLATE = """<!doctype html>
<html lang="ar" dir="rtl"><head><meta charset="utf-8">
<link href="https://fonts.googleapis.com/css2?family=Noto+Sans+Arabic:wght@500;600&display=swap" rel="stylesheet">
<style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ background:#000; font-family:'Noto Sans Arabic', sans-serif; color:#fff; }}
  #card {{ display:inline-block; background:#000; padding:24px 4px 70px; }}
  .row {{ border:1px solid #2a2a2a; padding:10px 18px; font-size:30px; font-weight:500;
          white-space:nowrap; text-align:center; }}
  .title {{ background:#181818; }}
  .title small {{ color:#9a9a9a; font-size:20px; margin-right:12px; }}
  .up {{ background:#11331a; }}
  .down {{ background:#3c1717; }}
  .n {{ unicode-bidi:isolate; direction:ltr; }}
</style></head><body><div id="card">
  <div class="row title">{title}<small class="n">{date}</small></div>
  <div class="row up">السناريو الصاعد: الثبات فوق <span class="n">{up_entry}</span> | الأهداف: <span class="n">{up_targets}</span></div>
  <div class="row down">السناريو الهابط: الثبات تحت <span class="n">{down_entry}</span> | الأهداف: <span class="n">{down_targets}</span></div>
</div></body></html>"""


def _join(nums: list[int]) -> str:
    # من اليمين لليسار في الصورة الأصلية يظهر الأقرب أولاً → نعكس داخل span باتجاه LTR
    return " - ".join(str(n) for n in reversed(nums))


def build_html(levels: Levels, title: str, date: str) -> str:
    return TEMPLATE.format(
        title=html.escape(title),
        date=html.escape(date),
        up_entry=levels.up.entry,
        up_targets=_join(levels.up.targets),
        down_entry=levels.down.entry,
        down_targets=_join(levels.down.targets),
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
