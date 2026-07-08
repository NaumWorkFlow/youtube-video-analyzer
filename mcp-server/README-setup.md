# Подключение своего транскрипт-коннектора (Windows)

Локальный MCP-сервер достаёт субтитры YouTube напрямую с твоей машины —
без браузера и без хрупкого скрейпинга. Ниже — шаги настройки.

## Шаг 1. Python
Если Python не установлен — поставь с https://python.org (при установке
галочка **«Add Python to PATH»**). Проверка в PowerShell:
```
py --version
```

## Шаг 2. Зависимости
В PowerShell выполни (путь уже указан):
```
py -m pip install -r "C:\Users\ASUS\Claude\Projects\Автоматизация разных моментов\youtube-analyzer\mcp-server\requirements.txt"
```

## Шаг 3. Проверка ДО подключения к Claude
Убедимся, что субтитры достаются (подставь любую ссылку):
```
py "C:\Users\ASUS\Claude\Projects\Автоматизация разных моментов\youtube-analyzer\mcp-server\yt_transcript_mcp.py" --test "https://youtu.be/tsPmVoA2r94"
```
Должен вывестись список дорожек и текст субтитров. Если текст есть — коннектор рабочий.

## Шаг 4. Регистрация в Claude
Открой файл настроек (создай, если его нет):
```
%APPDATA%\Claude\claude_desktop_config.json
```
Добавь блок `youtube-transcript` в `mcpServers` (если файл пустой — вставь целиком):
```json
{
  "mcpServers": {
    "youtube-transcript": {
      "command": "py",
      "args": [
        "C:\\Users\\ASUS\\Claude\\Projects\\Автоматизация разных моментов\\youtube-analyzer\\mcp-server\\yt_transcript_mcp.py"
      ]
    }
  }
}
```
Если `py` не найдётся — замени на полный путь к python.exe
(узнать: `py -c "import sys; print(sys.executable)"`).

## Шаг 5. Перезапуск и проверка
Полностью закрой и снова открой приложение Claude. Затем спроси:
«какие у тебя есть инструменты для youtube?» — должны появиться
`get_youtube_transcript` и `list_youtube_transcripts`.

> Примечание: то, что Cowork подхватывает пользовательские MCP из этого файла —
> нужно подтвердить на практике (шаг 5). Если не подхватит — сообщи, подберём
> способ регистрации коннектора именно для Cowork.

## Как это использует система
После подключения режим 1 работает так: ты кидаешь ссылку → Claude вызывает
`get_youtube_transcript` → применяет `../PROMPT-general.md` → выдаёт разбор.

## Режим 2: мониторинг каналов + Telegram

Добавлены инструменты:
- `resolve_channel_id(handle_or_url)` — определяет UC-идентификатор канала
  по `@handle`, ссылке `/channel/UC...`, `/@handle` или ссылке на видео канала.
- `list_channel_recent_videos(channel, max_results=5)` — свежие видео канала
  через RSS-ленту YouTube (`feeds/videos.xml?channel_id=UC...`).
- `send_telegram(text)` — отправка текста в Telegram (лимит 4096 символов —
  длинные сводки режутся на части автоматически).

### Шаг 1. Секреты Telegram
Создай бота через [@BotFather](https://t.me/BotFather) (команда `/newbot`),
получишь токен вида `123456789:AA...`. Впиши его в `mcp-server/.env`:
```
TELEGRAM_BOT_TOKEN=твой_токен
TELEGRAM_CHAT_ID=
```
Файл `.env` уже в `.gitignore` — в репозиторий не попадёт.

### Шаг 2. Узнать chat_id
1. Напиши своему боту в Telegram любое сообщение (например «привет»).
2. Выполни:
   ```
   py "C:\Users\ASUS\Claude\Projects\Автоматизация разных моментов\youtube-analyzer\mcp-server\yt_transcript_mcp.py" --get-chat-id
   ```
3. Скопируй нужный `chat_id` в `TELEGRAM_CHAT_ID` в `.env`.

### Шаг 3. Проверка отправки
```
py "C:\Users\ASUS\Claude\Projects\Автоматизация разных моментов\youtube-analyzer\mcp-server\yt_transcript_mcp.py" --send-telegram "тестовое сообщение"
```
Должно прийти сообщение в Telegram от бота.

### Проверка мониторинга канала (без Telegram)
```
py "C:\Users\ASUS\Claude\Projects\Автоматизация разных моментов\youtube-analyzer\mcp-server\yt_transcript_mcp.py" --list-channel "@handle_или_ссылка"
```

### Проверено на практике (2026-07-08)
- `resolve_channel_id` протестирован на 4 форматах входа для одного канала
  (`@handle`, `/channel/UC...`, «голый» `UC...`, ссылка на видео канала) —
  все дают одинаковый `channel_id` и одинаковый список свежих видео.
- RSS-парсинг сделан через `xml.etree.ElementTree` (без `feedparser`, чтобы
  не тянуть лишнюю зависимость) — namespace `yt:videoId` / `atom:title` и
  т.д. читаются штатно.
- `--get-chat-id` при пустом `TELEGRAM_BOT_TOKEN` даёт понятную ошибку, а не
  трейсбек — проверено.
- Секреты подхватываются через `python-dotenv` (`load_dotenv` на файл
  `mcp-server/.env` рядом со скриптом); если `python-dotenv` вдруг не
  установлен, сервер не падает — переменные тогда нужно выставлять вручную
  в окружении процесса.

## Надёжность
`youtube-transcript-api` — поддерживаемая библиотека, которая корректно решает
токены и preconditions YouTube. Это самый надёжный доступный путь, но не «вечный»:
при изменениях на стороне YouTube иногда нужно обновить библиотеку
(`py -m pip install -U youtube-transcript-api`).

## Проверено на практике (2026-07-07)
- Python 3.12.10, `youtube-transcript-api==1.2.4`, `mcp==1.28.1` — установились
  штатно через `requirements.txt`, API (`.fetch()` / `.list()` на экземпляре
  `YouTubeTranscriptApi()`) совпал с тем, что уже было в коде — правок логики
  извлечения не понадобилось.
- **Единственный найденный баг:** Windows-консоль по умолчанию открывает
  stdout/stderr в `cp1252`, что роняет вывод кириллицы (`UnicodeEncodeError`).
  Исправлено принудительным `reconfigure(encoding="utf-8")` для stdout/stderr
  в начале `yt_transcript_mcp.py` — нужно и для `--test` в терминале, и для
  работы как MCP-подпроцесса под Claude Desktop.
- Протестировано на 4 видео: обычное (ru avto-субтитры), длинный TED-доклад
  (60+ языков, включая ручной ru), видео без русских субтитров (фолбэк на en
  сработал корректно), и `/shorts/` формат ссылки.
- `%APPDATA%\Claude\claude_desktop_config.json` на этой машине изначально
  **не существовал** (ни файла, ни папки `Claude`) — похоже, приложение Claude
  Desktop ещё не запускалось. Папка и файл созданы с нуля, блок `mcpServers`
  добавлен без потери других настроек.
- Важно при ручном редактировании JSON с кириллическим путём в PowerShell:
  Windows PowerShell 5.1 (`Get-Content -Raw`) может НЕПРАВИЛЬНО отобразить
  (но не испортить) UTF-8 файл без BOM — показывает кракозябры при чтении,
  хотя байты на диске корректны. Проверяй через
  `[System.Text.Encoding]::UTF8.GetString([System.IO.File]::ReadAllBytes($path))`,
  а не напрямую через `Get-Content`.
