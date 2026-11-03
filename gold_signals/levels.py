"""حساب مستويات السيناريو الصاعد والهابط.

⚠️ هذا الملف هو المكان الوحيد الذي يجب تعديله ليطابق منطق مؤشرك.
المعادلة الحالية مستنتجة من الصورة المرسلة فقط:
  - الفرق بين الثبات فوق والثبات تحت = 6 نقاط
  - الأهداف تبعد عن نقطة الثبات بنفس المسافات في الاتجاهين:
    16, 30, 47, 69, 95, 125
استبدل دالة compute_levels بمنطق المؤشر الحقيقي (أرسل كود المؤشر ونحوّله).
"""
from dataclasses import dataclass

TARGET_OFFSETS = [16, 30, 47, 69, 95, 125]
ENTRY_GAP = 6


@dataclass
class Scenario:
    entry: int
    targets: list[int]


@dataclass
class Levels:
    up: Scenario
    down: Scenario


def compute_levels(price: float) -> Levels:
    pivot = round(price)
    up_entry = pivot + ENTRY_GAP // 2
    down_entry = up_entry - ENTRY_GAP
    return Levels(
        up=Scenario(up_entry, [up_entry + o for o in TARGET_OFFSETS]),
        down=Scenario(down_entry, [down_entry - o for o in TARGET_OFFSETS]),
    )
