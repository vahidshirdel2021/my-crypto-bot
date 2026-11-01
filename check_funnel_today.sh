#!/usr/bin/env bash
# مرحله‌ی دوم: بعد از اینکه دیتا OK بود، ببینیم سیگنال‌ها کجای قیف می‌میرند.
# اجرا:  cd /root/my-crypto-bot && bash check_funnel_today.sh
# اختیاری: bash check_funnel_today.sh /مسیر/funnel

DIR="${1:-}"
if [ -z "$DIR" ]; then
  DIR=$(find /root/my-crypto-bot -maxdepth 3 -type d -name funnel 2>/dev/null | head -n 1)
fi
if [ -z "$DIR" ] || [ ! -d "$DIR" ]; then
  echo "پوشه‌ی funnel پیدا نشد. با مسیر دستی اجرا کن:  bash check_funnel_today.sh /مسیر/funnel"
  exit 1
fi
echo "funnel dir: $DIR"
TODAY=$(date -u +%Y-%m-%d)
F="$DIR/funnel_$TODAY.jsonl"
ls -la "$DIR" | tail -n 5
[ -f "$F" ] || { echo "فایل امروز ($F) نیست."; exit 1; }

echo
echo "=== 1) تعداد رویدادها به تفکیک kind (امروز UTC) ==="
python3 - "$F" <<'PY'
import sys, json, collections, time
path = sys.argv[1]
kinds = collections.Counter(); ev = []
for line in open(path, encoding="utf-8", errors="ignore"):
    try: e = json.loads(line)
    except Exception: continue
    ev.append(e); kinds[e.get("kind")] += 1
for k, n in kinds.most_common(): print(f"{k:<14}{n}")
print()
print("=== 2) آخرین scan_summary ها (شمارنده‌های هر ~۱۵ دقیقه) ===")
sums = [e for e in ev if e.get("kind") == "scan_summary"][-6:]
for e in sums:
    t = time.strftime("%H:%M", time.gmtime(e.get("ts", 0)))
    print(t, "UTC", e.get("tf"), e.get("mode"), json.dumps(e.get("counts"), ensure_ascii=False)[:600])
if not sums:
    print("هیچ scan_summary ای نیست -> اسکن اصلاً چرخه‌ی کامل نمی‌زند یا نماد به مرحله‌ی بررسی نمی‌رسد.")
print()
print("=== 3) آخرین block ها (چرا ورود انجام نشد) ===")
for e in [e for e in ev if e.get("kind") == "block"][-8:]:
    print(json.dumps({k: e.get(k) for k in ("ts", "sym", "symbol", "gate", "why", "reason")}, ensure_ascii=False))
print()
print("=== 4) touch / pass_vote / entry امروز ===")
for k in ("touch", "pass_vote", "fav_queue", "entry"):
    print(k, kinds.get(k, 0))
PY

echo
echo "=== 5) لاگ: سقف/کف تاریخی (halving range) و خطاهای مربوط ==="
journalctl -u traderbot --since "2 hours ago" --no-pager 2>/dev/null \
  | grep -i -E "halving range|hist range|range .*None|no range|بدون سقف" | tail -n 25
echo "(اگر خالی بود: در ۲ ساعت اخیر هیچ سقف/کف جدیدی ساخته نشده، یعنی از کش می‌آید)"
