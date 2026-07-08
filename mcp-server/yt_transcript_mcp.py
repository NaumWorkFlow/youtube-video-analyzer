#!/usr/bin/env python3
"""
Локальный MCP-сервер для YouTube: транскрипты + мониторинг каналов (режим 2).

Работает НА твоей машине с обычным интернетом (не через песочницу),
поэтому обходит блокировки, из-за которых Chrome-скрейпинг ненадёжен.

Инструменты:
  - get_youtube_transcript(url_or_id, languages) -> текст субтитров
  - list_youtube_transcripts(url_or_id)          -> какие дорожки доступны
  - resolve_channel_id(handle_or_url)            -> UC-идентификатор канала
  - list_channel_recent_videos(channel, max_results) -> свежие видео канала
  - send_telegram(text)                          -> отправка сводки в Telegram

Секреты (TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID) читаются из mcp-server/.env
(см. README-setup.md) — в коде не хардкодятся.

Проверка без Claude (в терминале):
  python yt_transcript_mcp.py --test "https://youtu.be/VIDEO_ID"
  python yt_transcript_mcp.py --list-channel "@handle_or_url"
  python yt_transcript_mcp.py --get-chat-id
  python yt_transcript_mcp.py --send-telegram "тестовое сообщение"
"""

import os
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

# На Windows консоль/пайп по умолчанию открывается в cp1252, что падает
# на кириллице. Принудительно переключаем stdout/stderr в UTF-8 — это
# нужно и для --test в терминале, и когда Claude Desktop запускает
# скрипт как MCP-подпроцесс.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8")

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent / ".env")
except Exception:
    pass  # секреты можно передать и обычными переменными окружения

try:
    import requests
except Exception as e:  # pragma: no cover
    print("Не установлен requests. Установи: pip install requests",
          file=sys.stderr)
    raise

try:
    from youtube_transcript_api import (
        YouTubeTranscriptApi,
        TranscriptsDisabled,
        NoTranscriptFound,
        VideoUnavailable,
    )
except Exception as e:  # pragma: no cover
    print("Не установлен youtube-transcript-api. Установи: "
          "pip install youtube-transcript-api", file=sys.stderr)
    raise


_ID_RE = re.compile(r"[A-Za-z0-9_-]{11}")
_URL_RE = re.compile(
    r"(?:v=|/shorts/|youtu\.be/|/embed/|/live/|/v/)([A-Za-z0-9_-]{11})"
)


def extract_id(s: str) -> str:
    """Достаёт 11-символьный video ID из ссылки или принимает готовый ID."""
    s = (s or "").strip()
    m = _URL_RE.search(s)
    if m:
        return m.group(1)
    if _ID_RE.fullmatch(s):
        return s
    raise ValueError(f"Не удалось извлечь YouTube video ID из: {s!r}")


def fetch_transcript(url_or_id: str, languages=None):
    """Возвращает (video_id, language_code, text). Кидает понятную ошибку."""
    if not languages:
        languages = ["ru", "en"]
    vid = extract_id(url_or_id)
    api = YouTubeTranscriptApi()

    # Основной путь: сразу пытаемся получить нужные языки по приоритету.
    try:
        fetched = api.fetch(vid, languages=languages)
    except NoTranscriptFound:
        # Фолбэк: берём список и выбираем что есть (ручные, затем авто).
        tl = api.list(vid)
        tr = None
        try:
            tr = tl.find_transcript(languages)
        except Exception:
            for t in tl:            # первая доступная дорожка любого языка
                tr = t
                break
        if tr is None:
            raise
        fetched = tr.fetch()

    text = " ".join(sn.text for sn in fetched).replace("\n", " ").strip()
    text = re.sub(r"\s+", " ", text)
    lang = getattr(fetched, "language_code", "?")
    return vid, lang, text


def list_tracks(url_or_id: str):
    vid = extract_id(url_or_id)
    tl = YouTubeTranscriptApi().list(vid)
    rows = []
    for t in tl:
        auto = " [авто]" if getattr(t, "is_generated", False) else ""
        rows.append(f"- {t.language} ({t.language_code}){auto}")
    return vid, rows


# ---------------------------------------------------------------------------
# Мониторинг каналов (режим 2)
# ---------------------------------------------------------------------------
_CHANNEL_ID_RE = re.compile(r"UC[A-Za-z0-9_-]{22}")
_UA_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"),
    "Accept-Language": "en-US,en;q=0.9,ru;q=0.8",
}


def _fetch_html(url: str) -> str:
    resp = requests.get(url, headers=_UA_HEADERS, timeout=15)
    resp.raise_for_status()
    return resp.text


def _extract_channel_id_from_html(html: str) -> str | None:
    m = re.search(r'<meta itemprop="channelId" content="(UC[A-Za-z0-9_-]{22})"', html)
    if m:
        return m.group(1)
    m = re.search(r'"channelId":"(UC[A-Za-z0-9_-]{22})"', html)
    if m:
        return m.group(1)
    m = re.search(r'"externalId":"(UC[A-Za-z0-9_-]{22})"', html)
    if m:
        return m.group(1)
    return None


def resolve_channel_id(handle_or_url: str) -> str:
    """Определяет UC-идентификатор канала по @handle, ссылке на канал или на видео."""
    s = (handle_or_url or "").strip()
    if not s:
        raise ValueError("Пустой handle/ссылка")

    if _CHANNEL_ID_RE.fullmatch(s):
        return s

    m = re.search(r"/channel/(UC[A-Za-z0-9_-]{22})", s)
    if m:
        return m.group(1)

    if s.startswith("http://") or s.startswith("https://"):
        url = s
    elif s.startswith("@"):
        url = f"https://www.youtube.com/{s}"
    else:
        url = f"https://www.youtube.com/@{s}"

    html = _fetch_html(url)
    channel_id = _extract_channel_id_from_html(html)
    if not channel_id:
        raise ValueError(f"Не удалось определить channelId для: {handle_or_url!r}")
    return channel_id


def get_recent_videos(channel: str, max_results: int = 5):
    """Возвращает (channel_id, [{video_id,title,published,url}, ...]) из RSS-ленты."""
    s = (channel or "").strip()
    channel_id = s if _CHANNEL_ID_RE.fullmatch(s) else resolve_channel_id(s)

    rss_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
    resp = requests.get(rss_url, headers=_UA_HEADERS, timeout=15)
    resp.raise_for_status()

    ns = {
        "atom": "http://www.w3.org/2005/Atom",
        "yt": "http://www.youtube.com/xml/schemas/2015",
    }
    root = ET.fromstring(resp.content)
    videos = []
    for entry in root.findall("atom:entry", ns)[:max_results]:
        vid_el = entry.find("yt:videoId", ns)
        title_el = entry.find("atom:title", ns)
        pub_el = entry.find("atom:published", ns)
        link_el = entry.find("atom:link", ns)
        vid = vid_el.text if vid_el is not None else None
        videos.append({
            "video_id": vid,
            "title": title_el.text if title_el is not None else "",
            "published": pub_el.text if pub_el is not None else "",
            "url": (link_el.get("href") if link_el is not None
                    else f"https://www.youtube.com/watch?v={vid}"),
        })
    return channel_id, videos


# ---------------------------------------------------------------------------
# Telegram
# ---------------------------------------------------------------------------
def _split_text(text: str, limit: int = 4000):
    if len(text) <= limit:
        return [text]
    parts = []
    while text:
        if len(text) <= limit:
            parts.append(text)
            break
        cut = text.rfind("\n", 0, limit)
        if cut <= 0:
            cut = limit
        parts.append(text[:cut])
        text = text[cut:].lstrip("\n")
    return parts


def send_telegram(text: str):
    """Отправляет текст в Telegram-чат, разбивая на части по лимиту 4096 символов.

    Возвращает список message_id отправленных частей.
    """
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID не заданы. "
            "Заполни mcp-server/.env (см. README-setup.md)."
        )

    message_ids = []
    for chunk in _split_text(text, 4000):
        resp = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data={"chat_id": chat_id, "text": chunk},
            timeout=15,
        )
        data = resp.json()
        if not data.get("ok"):
            raise RuntimeError(f"Telegram API вернул ошибку: {data}")
        message_ids.append(data["result"]["message_id"])
    return message_ids


def get_telegram_updates():
    """Вызывает getUpdates и возвращает список чатов, писавших боту."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN не задан. Заполни mcp-server/.env."
        )
    resp = requests.get(
        f"https://api.telegram.org/bot{token}/getUpdates", timeout=15
    )
    data = resp.json()
    if not data.get("ok"):
        raise RuntimeError(f"Telegram API вернул ошибку: {data}")

    chats = {}
    for upd in data.get("result", []):
        msg = upd.get("message") or upd.get("channel_post")
        if not msg:
            continue
        chat = msg.get("chat", {})
        if chat.get("id") is not None:
            chats[chat["id"]] = chat
    return list(chats.values())


# ---------------------------------------------------------------------------
# MCP server
# ---------------------------------------------------------------------------
def build_server():
    from mcp.server.fastmcp import FastMCP

    mcp = FastMCP("youtube-transcript")

    @mcp.tool()
    def get_youtube_transcript(url_or_id: str,
                               languages: list[str] | None = None) -> str:
        """Достаёт транскрипт (субтитры) YouTube-видео по ссылке или ID.

        url_or_id: ссылка на видео (youtu.be/..., watch?v=..., /shorts/...) или 11-символьный ID.
        languages: приоритет языков, по умолчанию ['ru','en'].
        Возвращает сплошной текст субтитров.
        """
        try:
            vid, lang, text = fetch_transcript(url_or_id, languages)
        except TranscriptsDisabled:
            return "У этого видео отключены субтитры."
        except VideoUnavailable:
            return "Видео недоступно."
        except NoTranscriptFound:
            return "Субтитры для запрошенных языков не найдены."
        except Exception as e:
            return f"Ошибка при извлечении субтитров: {e}"
        if not text:
            return "Субтитры пустые."
        return f"[video={vid} lang={lang} chars={len(text)}]\n\n{text}"

    @mcp.tool()
    def list_youtube_transcripts(url_or_id: str) -> str:
        """Показывает, какие дорожки субтитров доступны у видео."""
        try:
            vid, rows = list_tracks(url_or_id)
        except Exception as e:
            return f"Ошибка: {e}"
        if not rows:
            return "Субтитры не найдены."
        return f"Доступные субтитры для {vid}:\n" + "\n".join(rows)

    @mcp.tool(name="resolve_channel_id")
    def _tool_resolve_channel_id(handle_or_url: str) -> str:
        """Определяет UC-идентификатор канала YouTube.

        handle_or_url: @handle, ссылка /channel/UC..., /@handle или ссылка на видео канала.
        """
        try:
            return resolve_channel_id(handle_or_url)
        except Exception as e:
            return f"Ошибка: {e}"

    @mcp.tool(name="list_channel_recent_videos")
    def _tool_list_channel_recent_videos(channel: str, max_results: int = 5) -> str:
        """Список последних видео канала (через RSS-ленту YouTube).

        channel: UC-идентификатор, @handle или ссылка на канал/видео.
        max_results: сколько последних видео вернуть (по умолчанию 5).
        """
        try:
            channel_id, videos = get_recent_videos(channel, max_results)
        except Exception as e:
            return f"Ошибка: {e}"
        if not videos:
            return f"У канала {channel_id} нет видео в ленте."
        lines = [f"Свежие видео канала {channel_id}:"]
        for v in videos:
            lines.append(f"- {v['published']} | {v['title']} | {v['url']}")
        return "\n".join(lines)

    @mcp.tool(name="send_telegram")
    def _tool_send_telegram(text: str) -> str:
        """Отправляет текст в Telegram (бот и chat_id берутся из mcp-server/.env)."""
        try:
            message_ids = send_telegram(text)
        except Exception as e:
            return f"Ошибка отправки в Telegram: {e}"
        return f"Отправлено сообщений: {len(message_ids)} (message_id: {message_ids})"

    return mcp


def _cli_test(url):
    print(f"Извлекаю субтитры для: {url}\n")
    try:
        vid, rows = list_tracks(url)
        print(f"Video ID: {vid}\nДорожки:")
        print("\n".join(rows) if rows else "  (нет)")
    except Exception as e:
        print(f"Список дорожек недоступен: {e}")
    print("\n--- Транскрипт ---")
    try:
        vid, lang, text = fetch_transcript(url)
        print(f"[lang={lang} chars={len(text)}]\n")
        print(text[:2000] + ("..." if len(text) > 2000 else ""))
    except Exception as e:
        print(f"ОШИБКА: {e}")


def _cli_list_channel(channel):
    print(f"Ищу свежие видео канала: {channel}\n")
    try:
        channel_id, videos = get_recent_videos(channel, max_results=5)
    except Exception as e:
        print(f"ОШИБКА: {e}")
        return
    print(f"channel_id = {channel_id}")
    if not videos:
        print("Видео не найдены.")
        return
    for v in videos:
        print(f"- [{v['published']}] {v['title']}")
        print(f"  {v['url']}  (id={v['video_id']})")


def _cli_get_chat_id():
    print("Запрашиваю getUpdates у Telegram...\n")
    try:
        chats = get_telegram_updates()
    except Exception as e:
        print(f"ОШИБКА: {e}")
        return
    if not chats:
        print("Обновлений нет. Напиши боту любое сообщение в Telegram и повтори "
              "команду --get-chat-id.")
        return
    print("Найденные чаты:")
    for chat in chats:
        name = chat.get("username") or chat.get("title") or chat.get("first_name") or "?"
        print(f"  chat_id={chat.get('id')}  type={chat.get('type')}  name={name}")
    print("\nВпиши нужный chat_id в TELEGRAM_CHAT_ID в mcp-server/.env")


def _cli_send_telegram(text):
    print("Отправляю сообщение в Telegram...\n")
    try:
        message_ids = send_telegram(text)
    except Exception as e:
        print(f"ОШИБКА: {e}")
        return
    print(f"Отправлено успешно. message_id: {message_ids}")


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "--test":
        _cli_test(sys.argv[2])
    elif len(sys.argv) >= 3 and sys.argv[1] == "--list-channel":
        _cli_list_channel(sys.argv[2])
    elif len(sys.argv) >= 2 and sys.argv[1] == "--get-chat-id":
        _cli_get_chat_id()
    elif len(sys.argv) >= 3 and sys.argv[1] == "--send-telegram":
        _cli_send_telegram(sys.argv[2])
    else:
        build_server().run()
