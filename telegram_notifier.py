from __future__ import annotations

import html

import requests


class TelegramNotifier:
    def __init__(self, bot_token: str | None, chat_id: str | None) -> None:
        self.bot_token = bot_token
        self.chat_id = chat_id

    @property
    def enabled(self) -> bool:
        return bool(self.bot_token)

    def _request(self, method: str, payload: dict, timeout: int = 15) -> dict:
        if not self.bot_token:
            raise RuntimeError("Telegram bot token is not configured.")
        url = f"https://api.telegram.org/bot{self.bot_token}/{method}"
        response = requests.post(url, json=payload, timeout=timeout)
        response.raise_for_status()
        data = response.json()
        if not data.get("ok"):
            raise RuntimeError(f"Telegram API error on {method}: {data}")
        return data

    def _split_text(self, text: str, max_len: int = 3900) -> list[str]:
        if len(text) <= max_len:
            return [text]

        chunks: list[str] = []
        current = ""
        for line in text.splitlines(keepends=True):
            if len(current) + len(line) > max_len and current:
                chunks.append(current.rstrip())
                current = line
            else:
                current += line
        if current:
            chunks.append(current.rstrip())
        return chunks

    def send(self, text: str, chat_id: str | None = None, parse_mode: str | None = None) -> None:
        target_chat_id = chat_id or self.chat_id
        if not self.enabled or not target_chat_id:
            return
        for chunk in self._split_text(text):
            payload = {
                "chat_id": str(target_chat_id),
                "text": chunk,
                "disable_web_page_preview": True,
            }
            if parse_mode:
                payload["parse_mode"] = parse_mode
            self._request("sendMessage", payload)

    def send_preformatted(self, text: str, chat_id: str | None = None) -> None:
        for chunk in self._split_text(text, max_len=3500):
            self.send(f"<pre>{html.escape(chunk)}</pre>", chat_id=chat_id, parse_mode="HTML")

    def get_updates(self, offset: int | None = None, timeout: int = 15) -> list[dict]:
        payload: dict = {
            "timeout": timeout,
            "allowed_updates": ["message"],
        }
        if offset is not None:
            payload["offset"] = offset
        data = self._request("getUpdates", payload, timeout=timeout + 5)
        result = data.get("result", [])
        return result if isinstance(result, list) else []
