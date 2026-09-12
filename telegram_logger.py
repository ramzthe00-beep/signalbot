# -*- coding: utf-8 -*-
"""
telegram_logger.py
=====================================================================
هر چیزی که به «ارسال لاگ/پیام به تلگرام» و لاگِ خودِ برنامه مربوط است:
ارسال پیام (با مدیریت Rate-Limit و پیام‌های بلند)، ارسال فایل، و
راه‌اندازی logging استاندارد پایتون + کمک‌تابع‌های زمانِ ایران.
"""

import logging
import time
import os

import requests
import pandas as pd
from datetime import datetime, timezone, timedelta

IRAN_TZ = timezone(timedelta(hours=3, minutes=30))


def setup_logging(level=logging.INFO):
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[logging.StreamHandler()],
    )
    return logging.getLogger("dtm_bot")


def format_iran_time(dt=None) -> str:
    if dt is None:
        dt = datetime.now(IRAN_TZ)
    else:
        if isinstance(dt, pd.Timestamp):
            dt = dt.to_pydatetime()
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        dt = dt.astimezone(IRAN_TZ)
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def format_iran_date(dt=None) -> str:
    if dt is None:
        dt = datetime.now(IRAN_TZ)
    return dt.strftime("%Y-%m-%d")


class TelegramNotifier:
    def __init__(self, bot_token: str, chat_id: str, logger=None):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.logger = logger or logging.getLogger("telegram")

    def _send_single(self, text: str, max_attempts: int = 3) -> bool:
        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        for attempt in range(max_attempts):
            try:
                r = requests.post(url, json={"chat_id": self.chat_id, "text": str(text),
                                              "parse_mode": "Markdown"}, timeout=30)
                if r.status_code == 200:
                    return True
                if r.status_code == 429:
                    retry_after = 10
                    try:
                        retry_after = r.json().get("parameters", {}).get("retry_after", 10)
                    except Exception:
                        pass
                    if attempt == max_attempts - 1:
                        self.logger.error(f"[TELEGRAM] rate-limit پس از {max_attempts} تلاش: {r.text[:200]}")
                        return False
                    time.sleep(min(retry_after + 2, 30))
                    continue
                if r.status_code == 400 and attempt == 0:
                    r2 = requests.post(url, json={"chat_id": self.chat_id, "text": str(text)}, timeout=30)
                    if r2.status_code == 200:
                        return True
                self.logger.error(f"[TELEGRAM] ارسال ناموفق: {r.status_code} {r.text[:200]}")
                return False
            except Exception as e:
                self.logger.error(f"[TELEGRAM] Exception: {e}")
                if attempt == max_attempts - 1:
                    return False
                time.sleep(2 ** attempt)
        return False

    def send(self, message: str) -> bool:
        text = str(message)
        if len(text) <= 4000:
            return self._send_single(text)
        parts = [text[i:i + 4000] for i in range(0, len(text), 4000)]
        ok = True
        for part in parts:
            ok = self._send_single(part) and ok
            time.sleep(1.0)
        return ok

    def send_document(self, filepath: str, caption: str = "") -> bool:
        url = f"https://api.telegram.org/bot{self.bot_token}/sendDocument"
        try:
            with open(filepath, "rb") as f:
                files = {"document": (os.path.basename(filepath), f, "text/plain")}
                data = {"chat_id": self.chat_id, "caption": caption}
                r = requests.post(url, files=files, data=data, timeout=60)
            return r.status_code == 200
        except Exception as e:
            self.logger.error(f"[TELEGRAM-FILE] {e}")
            return False
