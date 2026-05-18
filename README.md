# Тату Бот (VK)

Бот для записи на тату в группе ВКонтакте. Long polling, SQLite.

## Запуск на Bothost

1. Загрузите этот код в **публичный** GitHub-репозиторий.
2. На [create-bot.php](https://bothost.ru/create-bot.php) укажите:
   - Платформа: **VK**
   - Язык: **Python 3.11**
   - Bot Token: токен сообщества VK
   - Git URL: `https://github.com/ВАШ_ЛОГИН/tattoo-bot.git`
   - Главный файл: `tattoo_bot.py`
   - Домен: **выключен** (бот на long polling)
3. Переменные окружения (опционально): `GROUP_ID`, `MASTER_VK_ID`

Токен задаётся полем **Bot Token** на Bothost (переменная `BOT_TOKEN` в контейнере).

## Локальные файлы (не в git)

- `welcome.jpg` — приветственное фото
- `razreshenie_roditeley.docx` — шаблон разрешения для несовершеннолетних
