# -*- coding: utf-8 -*-
"""ذخیره‌ی رمزشده‌ی کلید API کاربران برای معامله‌ی REAL (V3.44.57).

- کلید و secret با Fernet (AES-128-CBC + HMAC) رمز می‌شوند و فقط متن رمزشده در sqlite می‌رود.
- کلید رمزنگاری: متغیر محیطی CREDENTIALS_ENC_KEY (خروجی Fernet.generate_key())؛ اگر نبود، یک‌بار ساخته و در فایل
  credentials.key کنار دیتابیس (دسترسی 600) ذخیره می‌شود. این فایل را جدا از بکاپ دیتابیس و امن نگه دارید.
- هیچ‌وقت secret را لاگ نکنید؛ فقط ۴ حرف آخر کلید (key_hint) برای نمایش ذخیره می‌شود."""
import logging
import os
import sqlite3
import threading
import time

logger = logging.getLogger(__name__)

try:
    from cryptography.fernet import Fernet, InvalidToken
except Exception:                                   # pragma: no cover
    Fernet = None; InvalidToken = Exception


class CredentialsError(Exception):
    pass


class CredentialsStore:
    def __init__(self, db_path, connect=None, lock=None, env_key=None, key_path=None):
        self.db_path = db_path
        self._connect = connect or (lambda: sqlite3.connect(db_path, timeout=15))
        self._lock = lock or threading.RLock()
        self._env_key = env_key if env_key is not None else os.environ.get('CREDENTIALS_ENC_KEY', '').strip()
        self._key_path = key_path or os.path.join(os.path.dirname(os.path.abspath(db_path)), 'credentials.key')
        self._fernet_obj = None

    # ---- رمزنگاری ----
    def _fernet(self):
        if self._fernet_obj is not None:
            return self._fernet_obj
        if Fernet is None:
            raise CredentialsError('کتابخانه‌ی cryptography نصب نیست؛ ذخیره‌ی امن کلید ممکن نیست.')
        key = self._env_key
        if not key:
            if os.path.exists(self._key_path):
                with open(self._key_path, 'rb') as fh:
                    key = fh.read().strip().decode('ascii')
            else:
                key = Fernet.generate_key().decode('ascii')
                fd = os.open(self._key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, 'wb') as fh:
                    fh.write(key.encode('ascii'))
                logger.warning('کلید رمزنگاری کلیدهای API ساخته شد: %s (از بکاپ دیتابیس جدا نگه دارید)', self._key_path)
        try:
            self._fernet_obj = Fernet(key.encode('ascii') if isinstance(key, str) else key)
        except Exception as exc:
            raise CredentialsError('CREDENTIALS_ENC_KEY معتبر نیست (باید خروجی Fernet.generate_key() باشد).') from exc
        return self._fernet_obj

    def _enc(self, text):
        return self._fernet().encrypt(text.encode('utf-8')).decode('ascii')

    def _dec(self, token):
        try:
            return self._fernet().decrypt(token.encode('ascii')).decode('utf-8')
        except InvalidToken as exc:
            raise CredentialsError('رمزگشایی کلید ذخیره‌شده ممکن نیست (کلید رمزنگاری عوض شده؟).') from exc

    # ---- جدول ----
    def init_table(self):
        with self._lock:
            conn = self._connect()
            try:
                conn.execute('''CREATE TABLE IF NOT EXISTS exchange_accounts(
                    chat_id INTEGER NOT NULL, exchange TEXT NOT NULL,
                    api_key_enc TEXT NOT NULL, api_secret_enc TEXT NOT NULL, key_hint TEXT,
                    created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL,
                    PRIMARY KEY(chat_id, exchange))''')
                conn.commit()
            finally:
                conn.close()

    def save(self, chat_id, exchange, api_key, api_secret):
        api_key = (api_key or '').strip(); api_secret = (api_secret or '').strip()
        if not api_key or not api_secret:
            raise CredentialsError('کلید یا secret خالی است.')
        k_enc, s_enc = self._enc(api_key), self._enc(api_secret); now = int(time.time())
        with self._lock:
            conn = self._connect()
            try:
                conn.execute('''INSERT INTO exchange_accounts(chat_id,exchange,api_key_enc,api_secret_enc,key_hint,created_at,updated_at)
                                VALUES(?,?,?,?,?,?,?)
                                ON CONFLICT(chat_id,exchange) DO UPDATE SET api_key_enc=excluded.api_key_enc,
                                api_secret_enc=excluded.api_secret_enc, key_hint=excluded.key_hint, updated_at=excluded.updated_at''',
                             (int(chat_id), str(exchange), k_enc, s_enc, api_key[-4:], now, now))
                conn.commit()
            finally:
                conn.close()

    def load(self, chat_id, exchange):
        """(api_key, api_secret) یا None."""
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute('SELECT api_key_enc, api_secret_enc FROM exchange_accounts WHERE chat_id=? AND exchange=?',
                                   (int(chat_id), str(exchange))).fetchone()
            finally:
                conn.close()
        if not row:
            return None
        return self._dec(row[0]), self._dec(row[1])

    def hint(self, chat_id, exchange):
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute('SELECT key_hint FROM exchange_accounts WHERE chat_id=? AND exchange=?', (int(chat_id), str(exchange))).fetchone()
            finally:
                conn.close()
        return row[0] if row else None

    def has(self, chat_id, exchange):
        return self.hint(chat_id, exchange) is not None

    def delete(self, chat_id, exchange=None):
        with self._lock:
            conn = self._connect()
            try:
                if exchange:
                    cur = conn.execute('DELETE FROM exchange_accounts WHERE chat_id=? AND exchange=?', (int(chat_id), str(exchange)))
                else:
                    cur = conn.execute('DELETE FROM exchange_accounts WHERE chat_id=?', (int(chat_id),))
                conn.commit(); return cur.rowcount
            finally:
                conn.close()
