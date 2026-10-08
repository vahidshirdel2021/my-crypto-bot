"""سطوح نصف‌کردن پی‌درپی (Halving Levels)

از بالاترین و پایین‌ترین قیمت تاریخی نماد شروع می‌کنیم، وسط (EQ) را می‌گیریم، دوباره
بین EQ و سقف و بین کف و EQ نصف می‌کنیم و همین‌طور تا عمق دلخواه. نصف‌کردن «خطی» است
(میانگین ساده‌ی دو سطح مجاور).

برای عمق D، سطوح همان نقاط  low + k * (high - low) / 2**D  هستند (k = 0..2**D).
عمقِ هر سطح = کوچک‌ترین عمقی که آن سطح برای اولین بار در آن ساخته می‌شود:
کف و سقف عمق ۰، EQ عمق ۱، چارک‌ها عمق ۲ و ...  (سطح کم‌عمق = مهم‌تر).

این ماژول فقط ریاضی است؛ هیچ وابستگی‌ای به بات یا پانداس ندارد و قابل تست مستقل است.
"""
import math

DEFAULT_K_ATR = 4.0       # حداقل فاصله‌ی دو سطح مجاور = k × ATR
DEFAULT_MIN_DEPTH = 3
DEFAULT_MAX_DEPTH = 10


def _valid(x):
    try:
        return x is not None and math.isfinite(float(x))
    except (TypeError, ValueError):
        return False


def level_depth(k, D):
    """عمق سطح شماره‌ی k از 2**D بازه (k=0 یا k=2**D یعنی کف/سقف → عمق ۰)."""
    n = 2 ** D
    if k <= 0 or k >= n:
        return 0
    tz = (k & -k).bit_length() - 1      # تعداد صفرهای انتهایی k در مبنای ۲
    return D - tz


def choose_depth(high, low, atr, k_atr=DEFAULT_K_ATR,
                 min_depth=DEFAULT_MIN_DEPTH, max_depth=DEFAULT_MAX_DEPTH):
    """عمیق‌ترین عمقی که فاصله‌ی سطوح مجاور هنوز ≥ k_atr × atr است (بین min و max).
    اگر ATR معتبر نباشد، min_depth برگردانده می‌شود (محتاطانه: سطوح کم و اصلی)."""
    if not (_valid(high) and _valid(low) and _valid(atr)) or high <= low or atr <= 0:
        return int(min_depth)
    rng = float(high) - float(low)
    need = max(1e-12, float(k_atr) * float(atr))
    ratio = rng / need
    if ratio < 1:
        return int(min_depth)
    d = int(math.floor(math.log2(ratio)))
    return int(max(min_depth, min(max_depth, d)))


def spacing_at(high, low, depth):
    return (float(high) - float(low)) / (2 ** int(depth))


def levels_near(high, low, depth, price_min, price_max):
    """همه‌ی سطوح عمق `depth` که در بازه‌ی [price_min, price_max] می‌افتند، مرتب‌شده و
    با عمق هر سطح: لیست دیکشنری {'price', 'depth'}. فقط همین پنجره ساخته می‌شود (ارزان)."""
    if not (_valid(high) and _valid(low)) or high <= low:
        return []
    D = int(depth)
    n = 2 ** D
    step = (float(high) - float(low)) / n
    k0 = max(0, int(math.ceil((float(price_min) - float(low)) / step)))
    k1 = min(n, int(math.floor((float(price_max) - float(low)) / step)))
    out = []
    for k in range(k0, k1 + 1):
        out.append({"price": float(low) + k * step, "depth": level_depth(k, D)})
    return out


def cells_around(levels, ref_price):
    """سلول‌های (سقف، کف) اطراف قیمت مرجع از روی لیست مرتب سطوح.

    سلولی که ref در آن است + یک سلول بالاتر + یک سلول پایین‌تر (تا شکستِ تازه‌ی یک سطح
    هم از سمت دیگرش دیده شود). هر سلول: {'hi': {...}, 'lo': {...}} و بر حسب اهمیت
    (کم‌عمق‌ترین لبه) مرتب می‌شود.
    """
    if not levels or len(levels) < 2 or not _valid(ref_price):
        return []
    below = [i for i, lv in enumerate(levels) if lv["price"] <= ref_price]
    if not below:
        return []
    i = below[-1]
    if i >= len(levels) - 1:
        i = len(levels) - 2
    cells = []
    for j in (i, i + 1, i - 1):
        if 0 <= j < len(levels) - 1:
            cells.append({"hi": levels[j + 1], "lo": levels[j]})
    cells.sort(key=lambda c: min(c["hi"]["depth"], c["lo"]["depth"]))
    return cells


def depth_label_fa(depth):
    return "کف/سقف تاریخی" if int(depth) == 0 else ("EQ کل" if int(depth) == 1 else f"عمق {int(depth)}")
