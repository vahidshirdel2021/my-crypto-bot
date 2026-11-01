#!/usr/bin/env bash
# چک دیتای فیوچرز بایننس دقیقاً با منطق ربات v3.44.120
# اجرا:
#   bash check_futures_scan.sh                 # ۱۵ نماد پرحجم + BTC/ETH/SOL
#   bash check_futures_scan.sh 40              # ۴۰ نماد پرحجم
#   bash check_futures_scan.sh BTC PEPE ZK     # نمادهای دلخواه
# نیاز: curl و python3 (روی VPS هست)

HOST="${BINANCE_FUTURES_URL:-https://fapi.binance.com}"
TF="${TF:-15m}"

echo "=== 1) دسترسی به $HOST از این سرور ==="
for p in "/fapi/v1/ping" "/fapi/v1/time" "/fapi/v1/exchangeInfo"; do
  code=$(curl -s -o /dev/null -m 15 -w '%{http_code}' "$HOST$p")
  note=""
  case "$code" in
    451|403) note="  <-- بلاک جغرافیایی/IP" ;;
    418|429) note="  <-- rate limit / بن موقت IP" ;;
    000)     note="  <-- اتصال برقرار نشد (DNS/فایروال/تایم‌اوت)" ;;
  esac
  echo "$p -> HTTP $code$note"
done
echo

HOST="$HOST" TF="$TF" python3 - "$@" <<'PY'
import os, re, sys, json, time, urllib.request, urllib.error

HOST = os.environ["HOST"].rstrip("/")
TF = os.environ["TF"]
TIMEOUT = 15

def get(path, params=None):
    url = HOST + path
    if params:
        url += "?" + "&".join(f"{k}={v}" for k, v in params.items())
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, None
    except Exception as e:
        return 0, str(e)

# --- مثل _binance_futures_entries و _split_futures_base ربات ---
PREFIX = re.compile(r"^(\d+)([A-Z].*)$")
def split_base(raw):
    m = PREFIX.match(raw)
    return (int(m.group(1)), m.group(2)) if m else (1, raw)

st, info = get("/fapi/v1/exchangeInfo")
print(f"=== 2) exchangeInfo: HTTP {st} ===")
if st != 200 or not isinstance(info, dict):
    print("exchangeInfo نیامد؛ ربات هم نماد را رد می‌کند. جزئیات:", info)
    sys.exit(1)

mp, scale, total = {}, {}, 0
entries = []
for s in info.get("symbols", []):
    total += 1
    if s.get("quoteAsset") != "USDT" or s.get("contractType") != "PERPETUAL":
        continue
    if (s.get("status") or s.get("contractStatus")) != "TRADING":
        continue
    raw = str(s.get("baseAsset", "")).upper(); sym = s.get("symbol")
    if not raw or not sym:
        continue
    sc, base = split_base(raw)
    entries.append((base, sym, sc))
for base, sym, sc in sorted(entries, key=lambda e: e[2] == 1):
    mp[base] = sym; scale[base] = sc

print(f"کل قراردادها: {total} | PERPETUAL+USDT+TRADING که ربات قبول می‌کند: {len(mp)}")
pref = {b: (mp[b], scale[b]) for b in mp if scale[b] != 1}
print(f"نمادهای با پیشوند ×۱۰۰۰ (مثل 1000PEPE): {len(pref)}", list(pref.items())[:5])
print()

# --- انتخاب نمادها ---
args = [a.upper() for a in sys.argv[1:]]
if args and all(a.isdigit() for a in args):
    n = int(args[0]); args = []
elif not args:
    n = 15
else:
    n = 0
if not args:
    st2, tk = get("/fapi/v1/ticker/24hr")
    rows = []
    if st2 == 200 and isinstance(tk, list):
        by_sym = {v: k for k, v in mp.items()}
        for t in tk:
            b = by_sym.get(t.get("symbol"))
            if b:
                try: rows.append((float(t["quoteVolume"]), b))
                except Exception: pass
    rows.sort(reverse=True)
    args = [b for _, b in rows[:n]]
    for must in ("BTC", "ETH", "SOL"):
        if must not in args: args.append(must)

print(f"=== 3) کندل {TF} برای {len(args)} نماد (همان شرط‌های _klines_usable ربات) ===")
print(f"{'نماد':<10}{'فیوچرز':<14}{'scale':<6}{'HTTP':<6}{'کندل':<6}{'سن آخرین':<10}{'high<low':<9}{'flat30':<7}{'قیمت':<14}نتیجه")
bad = 0
for base in args:
    sym = mp.get(base)
    if not sym:
        print(f"{base:<10}{'-':<14}{'-':<6}{'-':<6}{'-':<6}{'-':<10}{'-':<9}{'-':<7}{'-':<14}REJECT: not_listed (روی فیوچرز PERPETUAL/TRADING نیست)")
        bad += 1; continue
    sc = scale.get(base, 1)
    st, k = get("/fapi/v1/klines", {"symbol": sym, "interval": TF, "limit": 300})
    if st != 200 or not isinstance(k, list) or not k:
        why = {451: "بلاک جغرافیایی", 403: "بلاک", 418: "بن IP", 429: "rate limit"}.get(st, "داده نیامد")
        print(f"{base:<10}{sym:<14}{sc:<6}{st:<6}{0:<6}{'-':<10}{'-':<9}{'-':<7}{'-':<14}REJECT: http_{st} ({why})")
        bad += 1; continue
    rows = [(float(r[0]), float(r[2]), float(r[3]), float(r[4])) for r in k if len(r) >= 6]
    tail = rows[-30:]
    hl = any(h < l for _, h, l, _ in tail)
    flat = all((h - l) <= 0 for _, h, l, _ in tail)
    age_min = (time.time() * 1000 - rows[-1][0]) / 60000.0
    last = rows[-1][3] / sc
    problems = []
    if len(rows) < 60: problems.append(f"rows<{60}")
    if hl: problems.append("high<low")
    if flat: problems.append("flat")
    tf_min = {"1m":1,"5m":5,"15m":15,"30m":30,"1h":60,"4h":240}.get(TF, 15)
    if age_min > tf_min * 2: problems.append("stale")
    res = "OK" if not problems else "REJECT: " + ",".join(problems)
    if problems: bad += 1
    print(f"{base:<10}{sym:<14}{sc:<6}{st:<6}{len(rows):<6}{age_min:<10.1f}{str(hl):<9}{str(flat):<7}{last:<14.6g}{res}")
    time.sleep(0.15)

print()
print(f"خلاصه: {len(args)-bad} نماد OK و {bad} نماد REJECT از {len(args)}")
if bad == 0:
    print("-> دیتا درست می‌آید؛ مشکل بی‌سیگنالی بعد از مرحله‌ی دیتا (فیلتر/سناریو/قیمت×scale) است، نه دریافت نماد.")
else:
    print("-> دلیل REJECT بالا مشخص است (not_listed / http_xxx / rows / stale ...).")
PY

echo
echo "=== 4) لاگ زنده‌ی ربات (۳۰ دقیقه‌ی اخیر) ==="
if command -v journalctl >/dev/null 2>&1; then
  journalctl -u traderbot --since "30 min ago" --no-pager 2>/dev/null \
    | grep -i -E "temporarily disabled|exchangeInfo|not_listed|empty_or_invalid|http_4|http_5|market data|klines|Traceback|Error" \
    | tail -n 40
  echo "(اگر خروجی خالی بود یعنی هیچ خطای دیتا در لاگ نیست)"
else
  echo "journalctl نیست؛ لاگ ربات را دستی ببین."
fi
