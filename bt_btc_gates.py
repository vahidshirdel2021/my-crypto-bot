# -*- coding: utf-8 -*-
"""
گیت‌های ورودیِ BTC برای بک‌تست (V3.44.127)
==========================================
همان منطق ربات زنده، ولی روی کندل‌های تاریخیِ BTC/ETH و فقط با کندل‌های «بسته‌شده» تا لحظه‌ی سیگنال (بدون نشت آینده):
  aligned   : رژیم BTC و ETH هر دو صعودی یا هر دو نزولی (gate_btceth_aligned_enabled)
  undecided : BTC وسطِ راهروی دو سطح و دور از هر دو (gate_btc_undecided_enabled)
  chop      : کلاف دور سطح (gate_btc_chop_enabled)
  front     : سمت درستِ سطح + فاصله‌ی معقول تا سطح جلویی (gate_btc_front_level_enabled)
  daily     : رژیم روزانه‌ی BTC (gate_btc_daily_regime_enabled، V3.44.131): خرید وقتی رژیم روزانه نزولی است و فروش وقتی صعودی است رد می‌شود؛ رنج = آزاد.
              مثل ربات زنده از آخرین کندل «بسته‌شده»ی روزانه‌ی UTC با معیار دقیق (advanced) سنجیده می‌شود و در طول روز ثابت است؛ نبود داده = آزاد (fail-open).
  candle    : کندل BTC هم‌جهت معامله (gate_btc_candle_enabled) — تقریب: در ربات زنده «کندل در حال تشکیل» سنجیده می‌شود
              که در بک‌تست (ورود روی open کندل بعد) هنوز بدنه ندارد؛ پس بدنه‌ی «آخرین کندل بسته‌شده‌ی BTC» جایگزین است.
توابع وابسته به ربات (اندیکاتور، سطوح، رژیم) از بیرون تزریق می‌شوند تا این ماژول مستقل و قابل تست باشد.
اگر سیگنال رد شود، همان قدم رد می‌شود و کندل بعدی دوباره سنجیده می‌شود (صف تاییدِ ۳۰ دقیقه‌ای شبیه‌سازی نمی‌شود).
"""
from __future__ import annotations

import math
from typing import Dict, Optional, Tuple

import numpy as np
import pandas as pd

FRONT_WINDOW = 649      # live: get_klines(BTC, tf, 650) -> 649 بسته + ۱ در حال تشکیل
REGIME_WINDOW = 159     # live: get_klines(sym, tf, 160)
DAILY_WINDOW = 199      # live: get_klines(BTC, '1day', 200) -> 199 بسته + ۱ در حال تشکیل
DAY_MS = 86_400_000
GATE_KEYS = ('aligned', 'undecided', 'chop', 'front', 'candle', 'daily')


class BtcGates:
    def __init__(self, btc_df: Optional[pd.DataFrame], eth_df: Optional[pd.DataFrame], cfg: dict, flags: Dict[str, bool],
                 helpers: dict, btc_halving_range=None, grid_levels=None, daily_df: Optional[pd.DataFrame] = None,
                 tf_ms: int = 900_000):
        self.h = helpers
        self.tf_ms = int(tf_ms)                                # طول کندل نماد بک‌تست؛ زمان ورود = بسته‌شدن کندل سیگنال + یک کندل
        self.daily = self._prep(daily_df)
        self._daily_cache: Dict[int, Optional[str]] = {}
        self.flags = {k: bool(flags.get(k)) for k in GATE_KEYS}
        self.btc = self._prep(btc_df)
        self.eth = self._prep(eth_df)
        cfg0 = {**(helpers.get('defaults') or {}), **(cfg or {})}
        self.cfg0 = cfg0
        if cfg0.get('halving_model_enabled'):
            self.cfg_btc = helpers['with_halving_cfg'](cfg0, btc_halving_range) if btc_halving_range else None
        else:
            self.cfg_btc = cfg0
        self.grid = grid_levels or []
        self._ind_cache: Dict[int, Optional[pd.DataFrame]] = {}
        self._front_cache: Dict[Tuple[int, bool], Optional[dict]] = {}
        self._reg_cache: Dict[Tuple[int, int], Optional[str]] = {}

        def _ci(key, default, lo=0):
            v = cfg0.get(key)
            try:
                return default if v is None else max(lo, int(float(v)))
            except Exception:
                return default

        def _cf(key, default):
            v = cfg0.get(key)
            try:
                return default if v is None else max(0.0, float(v))
            except Exception:
                return default
        ch = helpers['chop']                                   # (flips, window, clear_closes, clear_atr)
        v = cfg0.get('btc_front_min_atr')
        self.min_atr = helpers['front_min_atr'] if v is None else max(0.0, float(v))
        self.chop_flips = _ci('btc_chop_flips', ch[0])
        self.chop_win = _ci('btc_chop_window', ch[1], 4)
        self.chop_k = _ci('btc_chop_clear_closes', ch[2], 1)
        self.chop_x = _cf('btc_chop_clear_atr', ch[3])
        v = cfg0.get('btc_undecided_far_atr')
        self.far_atr = helpers['far_atr'] if v is None else max(0.5, float(v))
        v = cfg0.get('btc_undecided_far_gap')
        self.far_gap = helpers['far_gap'] if v is None else min(0.5, max(0.05, float(v)))

    @property
    def active(self):
        return [k for k in GATE_KEYS if self.flags[k]]

    @staticmethod
    def _prep(df):
        if df is None or len(df) == 0:
            return None
        d = df.sort_values('timestamp').reset_index(drop=True).copy()
        for c in ('open', 'high', 'low', 'close', 'volume'):
            d[c] = pd.to_numeric(d[c], errors='coerce')
        d['timestamp'] = pd.to_numeric(d['timestamp'], errors='coerce').astype('int64')
        return {'df': d, 'ts': d['timestamp'].values}

    @staticmethod
    def _idx(ref, ts_ms):
        """اندیس کندل بسته‌شده با timestamp برابر؛ باید کندل بعدی (برای open) هم وجود داشته باشد."""
        if ref is None:
            return None
        k = int(np.searchsorted(ref['ts'], int(ts_ms)))
        if k + 1 >= len(ref['ts']) or int(ref['ts'][k]) != int(ts_ms):
            return None
        return k

    @staticmethod
    def _window(ref, k, n_closed):
        d = ref['df']
        w = d.iloc[max(0, k - n_closed + 1):k + 2].copy().reset_index(drop=True)
        o = float(w['open'].iloc[-1]); last = len(w) - 1
        for c in ('open', 'high', 'low', 'close'):
            w.loc[last, c] = o
        w.loc[last, 'volume'] = 0.0                          # کندل در حال تشکیل = فقط open کندل بعد
        return w

    # ---------------- رژیم ----------------
    def _regime(self, ref, k):
        key = (id(ref), k)
        if key in self._reg_cache:
            return self._reg_cache[key]
        r = None
        try:
            w = self._window(ref, k, REGIME_WINDOW)
            if len(w) >= 60:
                r = self.h['regime'](self.h['calculate_indicators'](w))
        except Exception:
            r = None
        self._reg_cache[key] = r
        return r

    # ---------------- رژیم روزانه‌ی BTC (V3.44.131) ----------------
    def daily_regime(self, entry_ms: int) -> Optional[str]:
        """رژیم روزانه‌ی BTC در لحظه‌ی ورود: آخرین کندل روزانه‌ای که تا آن لحظه کامل بسته شده (دیروزِ UTC).
        کندل «امروز» فقط یک ردیف ساختگی است (مثل کندل در حال تشکیل در ربات زنده؛ رژیم روی iloc[-2] سنجیده می‌شود) تا نشت آینده نباشد.
        None = داده‌ی ناکافی یا شکاف در داده (گیت آزاد می‌ماند)."""
        ref = self.daily
        if ref is None:
            return None
        ts = ref['ts']
        k = int(np.searchsorted(ts + DAY_MS, int(entry_ms), side='right')) - 1
        if k < 0 or int(entry_ms) - (int(ts[k]) + DAY_MS) >= DAY_MS:
            return None                                       # دیروز در داده نیست (شکاف یا بعد از پایان داده)
        if k in self._daily_cache:
            return self._daily_cache[k]
        r = None
        try:
            d = ref['df']
            w = d.iloc[max(0, k - DAILY_WINDOW + 1):k + 1].copy().reset_index(drop=True)
            if len(w) + 1 >= 60:
                last = float(w['close'].iloc[-1])
                row = pd.DataFrame([{'timestamp': int(ts[k]) + DAY_MS, 'open': last, 'high': last, 'low': last, 'close': last, 'volume': 0.0}])
                w = pd.concat([w, row], ignore_index=True)
                ind = self.h['calculate_indicators'](w)
                try:
                    r = self.h['regime'](ind, advanced=True)
                except TypeError:
                    r = self.h['regime'](ind)
        except Exception:
            r = None
        if len(self._daily_cache) > 512:
            self._daily_cache.clear()
        self._daily_cache[k] = r
        return r

    # ---------------- سطح جلویی / کلاف ----------------
    def _ind(self, k):
        if k in self._ind_cache:
            return self._ind_cache[k]
        ind = None
        try:
            w = self._window(self.btc, k, FRONT_WINDOW)
            if len(w) >= 62:
                ind = self.h['calculate_indicators'](w)
        except Exception:
            ind = None
        if len(self._ind_cache) > 64:
            self._ind_cache.clear()
        self._ind_cache[k] = ind
        return ind

    def front_info(self, k, is_long):
        key = (k, bool(is_long))
        if key in self._front_cache:
            return self._front_cache[key]
        info = self._front_info(k, bool(is_long))
        if len(self._front_cache) > 256:
            self._front_cache.clear()
        self._front_cache[key] = info
        return info

    def _front_info(self, k, is_long):
        ind = self._ind(k)
        if ind is None or self.cfg_btc is None:
            return None
        closed = ind.iloc[-2]
        close = float(closed['close']); atr = float(closed.get('atr') or 0)
        if not (math.isfinite(close) and close > 0 and math.isfinite(atr) and atr > 0):
            return None
        ql = self.h['quick_levels']
        levels = ql(ind, close, is_long, self.grid, self.cfg_btc)
        info = {'ok': True, 'close': close, 'atr': atr, 'front_price': None, 'dist': None, 'dist_atr': None, 'side_ok': True,
                'ref_price': None, 'ref_above': None, 'chop': False}
        if levels:
            fp, _fl = min(levels, key=lambda t: abs(t[0] - close))
            dist = abs(float(fp) - close)
            info.update(front_price=float(fp), dist=dist, dist_atr=dist / atr, ok=(dist / atr) >= self.min_atr)
        try:
            other = ql(ind, close, not is_long, self.grid, self.cfg_btc)
        except Exception:
            other = []
        allv = list(levels or []) + list(other or [])
        if allv:
            rp, _rl = min(allv, key=lambda t: abs(t[0] - close))
            above = float(rp) > close
            info.update(ref_price=float(rp), ref_above=above, side_ok=((not above) if is_long else above))
            if self.chop_flips > 0:
                try:
                    cl = [float(x) for x in ind['close'].iloc[-(self.chop_win + 1):-1] if math.isfinite(float(x))]
                    sg = [1 if c_ > float(rp) else -1 for c_ in cl if c_ != float(rp)]
                    flips = sum(1 for a_, b_ in zip(sg, sg[1:]) if a_ != b_)
                    tail = sg[-self.chop_k:]
                    decisive = (len(tail) == self.chop_k and len(set(tail)) == 1 and abs(close - float(rp)) / atr >= self.chop_x)
                    info.update(chop=(flips >= self.chop_flips and not decisive))
                except Exception:
                    pass
        return info

    def _undecided(self, k):
        """True = بلاتکلیف (ورود بسته)."""
        fu, fd = self.front_info(k, True), self.front_info(k, False)
        base = fu or fd
        if base is None:
            return True
        close, atr = float(base['close']), float(base['atr'])
        up = (fu or {}).get('front_price'); dn = (fd or {}).get('front_price')
        up = float(up) if up is not None and float(up) > close else None
        dn = float(dn) if dn is not None and float(dn) < close else None
        if up is None and dn is None:
            return True
        d_up = (up - close) if up is not None else None
        d_dn = (close - dn) if dn is not None else None
        nearest = min(x for x in (d_up, d_dn) if x is not None)
        far_atr_ok = (nearest / atr) > self.far_atr
        far_gap_ok = ((nearest / (up - dn)) > self.far_gap) if (up is not None and dn is not None) else True
        return bool(far_atr_ok and far_gap_ok)

    # ---------------- ورودیِ اصلی ----------------
    def check(self, closed_ts_ms: int, sig: str) -> Tuple[bool, str]:
        """(ok, tag). tag یکی از GATE_KEYS یا 'nodata'. closed_ts_ms = timestamp آخرین کندل بسته‌شده‌ی نماد."""
        f = self.flags
        if not any(f.values()):
            return True, ''
        is_long = (sig == 'BUY')
        if f['daily']:
            reg_d = self.daily_regime(int(closed_ts_ms) + self.tf_ms)
            if (reg_d == 'BEARISH' and is_long) or (reg_d == 'BULLISH' and not is_long):
                return False, 'daily'
        kb = self._idx(self.btc, closed_ts_ms)
        if f['aligned']:
            ke = self._idx(self.eth, closed_ts_ms)
            rb = self._regime(self.btc, kb) if kb is not None else None
            re_ = self._regime(self.eth, ke) if ke is not None else None
            if not (rb and re_) or rb != re_ or rb not in ('BULLISH', 'BEARISH'):
                return False, 'aligned'
        if any(f[k] for k in ('undecided', 'chop', 'front', 'candle')) and kb is None:
            return False, 'nodata'
        if f['undecided'] and self._undecided(kb):
            return False, 'undecided'
        if f['chop'] or f['front']:
            info = self.front_info(kb, is_long)
            if info is None:
                return False, 'nodata'
            if f['chop'] and info.get('chop'):
                return False, 'chop'
            if f['front']:
                if not info.get('side_ok', True):
                    return False, 'front'
                if not info.get('ok', True):
                    return False, 'front'
        if f['candle']:
            row = self.btc['df'].iloc[kb]
            o, c = float(row['open']), float(row['close'])
            pct = (c - o) / o * 100.0 if o > 0 else 0.0
            if abs(pct) <= float(self.h.get('candle_min_body', 0.0)):
                return False, 'candle'
            if (pct > 0) != is_long:
                return False, 'candle'
        return True, ''
