"""
VALHALLA Tattoo Bot — ВКонтакте
pip install vk_api

База данных SQLite — встроена в Python, ничего устанавливать не нужно.
Файл базы: tattoo.db (создаётся автоматически рядом со скриптом)
"""

import vk_api
from vk_api.longpoll import VkLongPoll, VkEventType
from vk_api.keyboard import VkKeyboard, VkKeyboardColor
import logging
import random
import os
import time
import sqlite3
from datetime import datetime

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()]
)
log = logging.getLogger(__name__)

# ══════════════════════════════════════
#  НАСТРОЙКИ
# ══════════════════════════════════════
GROUP_TOKEN  = os.environ.get("BOT_TOKEN") or os.environ.get("GROUP_TOKEN", "")
GROUP_ID     = int(os.environ.get("GROUP_ID", "238443976"))
MASTER_VK_ID = int(os.environ.get("MASTER_VK_ID", "401276566"))

WELCOME_PHOTO = "welcome.jpg"
DB_FILE       = os.environ.get("DB_FILE", "data/tattoo.db")
# ══════════════════════════════════════

# В памяти храним только активные незавершённые анкеты
sessions:          dict = {}
master_state:      dict = {"mode": "idle", "broadcast_text": ""}
vk_session_global       = None   # инициализируется в main()


# ══════════════════════════════════════
#  БАЗА ДАННЫХ
# ══════════════════════════════════════

def db_connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def db_init():
    """Создаёт таблицы при первом запуске."""
    os.makedirs(os.path.dirname(DB_FILE) or ".", exist_ok=True)
    with db_connect() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS clients (
                vk_id       INTEGER PRIMARY KEY,
                first_name  TEXT,
                last_name   TEXT,
                created_at  TEXT DEFAULT (datetime('now','localtime'))
            );

            CREATE TABLE IF NOT EXISTS applications (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                vk_id        INTEGER,
                size         TEXT,
                age          TEXT,
                contact_time TEXT,
                has_photo    INTEGER DEFAULT 0,
                has_sketch   INTEGER DEFAULT 0,
                created_at   TEXT DEFAULT (datetime('now','localtime'))
            );
        """)
    log.info("БД инициализирована: %s", DB_FILE)

def db_add_client(vk_id: int, first_name: str, last_name: str):
    """Добавляет клиента если его ещё нет."""
    with db_connect() as conn:
        conn.execute("""
            INSERT OR IGNORE INTO clients (vk_id, first_name, last_name)
            VALUES (?, ?, ?)
        """, (vk_id, first_name, last_name))

def db_client_exists(vk_id: int) -> bool:
    with db_connect() as conn:
        row = conn.execute("SELECT 1 FROM clients WHERE vk_id = ?", (vk_id,)).fetchone()
        return row is not None

def db_save_application(vk_id: int, data: dict):
    """Сохраняет заявку в базу."""
    with db_connect() as conn:
        conn.execute("""
            INSERT INTO applications (vk_id, size, age, contact_time, has_photo, has_sketch)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            vk_id,
            data.get("size", ""),
            data.get("age", ""),
            data.get("contact_time", ""),
            1 if data.get("photo_attach") else 0,
            1 if data.get("sketch_attach") else 0,
        ))

def db_get_all_clients() -> list:
    with db_connect() as conn:
        return conn.execute(
            "SELECT vk_id, first_name, last_name, created_at FROM clients ORDER BY created_at DESC"
        ).fetchall()

def db_get_clients_count() -> int:
    with db_connect() as conn:
        return conn.execute("SELECT COUNT(*) FROM clients").fetchone()[0]

def db_get_apps_count() -> int:
    with db_connect() as conn:
        return conn.execute("SELECT COUNT(*) FROM applications").fetchone()[0]

def db_get_all_vk_ids() -> list:
    """Возвращает список всех vk_id для рассылки."""
    with db_connect() as conn:
        rows = conn.execute("SELECT vk_id FROM clients").fetchall()
        return [r["vk_id"] for r in rows]


# ══════════════════════════════════════
#  КЛАВИАТУРЫ
# ══════════════════════════════════════

def kb_start():
    kb = VkKeyboard(one_time=True)
    kb.add_button("Заполнить анкету", color=VkKeyboardColor.POSITIVE)
    return kb.get_keyboard()

def kb_sketch():
    kb = VkKeyboard(one_time=True)
    kb.add_button("Пропустить — эскиза нет", color=VkKeyboardColor.SECONDARY)
    return kb.get_keyboard()

def kb_size():
    kb = VkKeyboard(one_time=True)
    kb.add_button("до 5 см",     color=VkKeyboardColor.PRIMARY)
    kb.add_line()
    kb.add_button("5 - 10 см",   color=VkKeyboardColor.PRIMARY)
    kb.add_line()
    kb.add_button("10 - 15 см",  color=VkKeyboardColor.PRIMARY)
    kb.add_line()
    kb.add_button("15 - 20 см",  color=VkKeyboardColor.PRIMARY)
    kb.add_line()
    kb.add_button("более 20 см", color=VkKeyboardColor.SECONDARY)
    return kb.get_keyboard()

def kb_contact_time():
    kb = VkKeyboard(one_time=True)
    kb.add_button("9:00 - 12:00",  color=VkKeyboardColor.PRIMARY)
    kb.add_line()
    kb.add_button("12:00 - 15:00", color=VkKeyboardColor.PRIMARY)
    kb.add_line()
    kb.add_button("15:00 - 18:00", color=VkKeyboardColor.PRIMARY)
    kb.add_line()
    kb.add_button("18:00 - 21:00", color=VkKeyboardColor.PRIMARY)
    kb.add_line()
    kb.add_button("Любое время",   color=VkKeyboardColor.SECONDARY)
    return kb.get_keyboard()

def kb_confirm():
    kb = VkKeyboard(one_time=True)
    kb.add_button("Отправить заявку", color=VkKeyboardColor.POSITIVE)
    kb.add_line()
    kb.add_button("Начать заново",    color=VkKeyboardColor.NEGATIVE)
    return kb.get_keyboard()

def kb_admin():
    kb = VkKeyboard(one_time=False)
    kb.add_button("Рассылка клиентам", color=VkKeyboardColor.POSITIVE)
    kb.add_line()
    kb.add_button("Список клиентов",   color=VkKeyboardColor.PRIMARY)
    kb.add_line()
    kb.add_button("Статистика",        color=VkKeyboardColor.SECONDARY)
    return kb.get_keyboard()

def kb_yes_no():
    kb = VkKeyboard(one_time=True)
    kb.add_button("Отправить",  color=VkKeyboardColor.POSITIVE)
    kb.add_line()
    kb.add_button("Отмена",     color=VkKeyboardColor.NEGATIVE)
    return kb.get_keyboard()

def kb_permission():
    kb = VkKeyboard(one_time=True)
    kb.add_button("Да, разрешение есть",  color=VkKeyboardColor.POSITIVE)
    kb.add_line()
    kb.add_button("Нет, нужен шаблон",    color=VkKeyboardColor.NEGATIVE)
    return kb.get_keyboard()

def kb_form_done():
    kb = VkKeyboard(one_time=True)
    kb.add_button("Анкета заполнена",     color=VkKeyboardColor.POSITIVE)
    return kb.get_keyboard()


# ══════════════════════════════════════
#  ОТПРАВКА
# ══════════════════════════════════════

def send(vk, user_id: int, text: str, keyboard=None, attachment: str = None):
    params = dict(
        user_id=user_id,
        message=text,
        random_id=random.randint(0, 2 ** 31),
    )
    if keyboard is not None:
        params["keyboard"] = keyboard
    if attachment:
        params["attachment"] = attachment
    vk.messages.send(**params)


# ══════════════════════════════════════
#  ВЛОЖЕНИЯ
# ══════════════════════════════════════

def get_attach_string(vk, message_id: int) -> str:
    try:
        resp  = vk.messages.getById(message_ids=message_id)
        items = resp.get("items", [])
        if not items:
            return ""
        parts = []
        for att in items[0].get("attachments", []):
            if att.get("type") == "photo":
                p  = att["photo"]
                o  = p["owner_id"]
                i  = p["id"]
                ak = p.get("access_key", "")
                parts.append(f"photo{o}_{i}_{ak}" if ak else f"photo{o}_{i}")
        return ",".join(parts)
    except Exception as ex:
        log.error("get_attach_string(msg_id=%s): %s", message_id, ex)
        return ""

def has_photo_in_event(event) -> bool:
    raw = event.attachments or {}
    return any(raw.get(f"attach{i}_type") == "photo" for i in range(1, 11))


# ══════════════════════════════════════
#  ЗАГРУЗКА ПРИВЕТСТВЕННОГО ФОТО
# ══════════════════════════════════════

def upload_welcome_photo(vk_session) -> str:
    if not os.path.exists(WELCOME_PHOTO):
        log.warning("welcome.jpg не найден — бот работает без фото")
        return ""
    try:
        uploader = vk_api.VkUpload(vk_session)
        photo    = uploader.photo_messages(WELCOME_PHOTO)
        p        = photo[0]
        ak       = p.get("access_key", "")
        att      = f"photo{p['owner_id']}_{p['id']}_{ak}" if ak else f"photo{p['owner_id']}_{p['id']}"
        log.info("Приветственное фото загружено: %s", att)
        return att
    except Exception as e:
        log.error("Не удалось загрузить welcome.jpg: %s", e)
        return ""


# ══════════════════════════════════════
#  ХЕЛПЕРЫ
# ══════════════════════════════════════

def get_first_name(vk, uid: int) -> str:
    try:
        return vk.users.get(user_ids=uid)[0]["first_name"]
    except Exception:
        return "Привет"

def get_full_name(vk, uid: int) -> tuple:
    """Возвращает (first_name, last_name)."""
    try:
        u = vk.users.get(user_ids=uid)[0]
        return u["first_name"], u["last_name"]
    except Exception:
        return "id" + str(uid), ""

def make_summary(data: dict, first: str, last: str, uid: int) -> str:
    return "\n".join([
        "─────────────────────",
        "НОВАЯ АНКЕТА  |  VALHALLA",
        "─────────────────────",
        f"Клиент:        {first} {last}",
        f"Страница:      vk.com/id{uid}",
        f"Дата:          {datetime.now().strftime('%d.%m.%Y %H:%M')}",
        "",
        f"Размер:        {data.get('size', '—')}",
        f"Возраст:       {data.get('age', '—')} лет",
        f"Время связи:   {data.get('contact_time', '—')}",
        "",
        f"Фото места:    {'есть ✅' if data.get('photo_attach') else 'нет'}",
        f"Эскиз:         {'есть ✅' if data.get('sketch_attach') else 'нет'}",
        f"Разрешение:    {'есть ✅' if data.get('permission_attach') else ('нужно у мастера ⚠️' if int(data.get('age','99')) < 18 else '—')}",
        "─────────────────────",
    ])


# ══════════════════════════════════════
#  СТАРТ АНКЕТЫ
# ══════════════════════════════════════

def start_form(vk, uid: int):
    sessions[uid] = {"step": "photo", "data": {}}
    name = get_first_name(vk, uid)
    send(vk, uid,
         f"Отлично, {name}! Давай оформим заявку — это займёт пару минут 🖤\n\n"
         "📍 Шаг 1 из 5\n"
         "📸 Пришли фото места, куда хочешь набить тату\n\n"
         "Сфотографируй именно ту зону — мастер наложит эскиз прямо туда "
         "и подгонит размер, чтобы ты заранее увидел(а), как всё будет смотреться на коже ✨",
         keyboard=None)


# ══════════════════════════════════════
#  РАССЫЛКА
# ══════════════════════════════════════

def broadcast(vk, text: str) -> int:
    ids  = db_get_all_vk_ids()
    sent = 0
    for uid in ids:
        if uid == MASTER_VK_ID:
            continue
        try:
            send(vk, uid, text)
            sent += 1
            time.sleep(0.35)
        except Exception as e:
            log.warning("broadcast uid=%s: %s", uid, e)
    return sent


# ══════════════════════════════════════
#  ГЛАВНЫЙ ОБРАБОТЧИК
# ══════════════════════════════════════

START_WORDS = {
    "начать", "старт", "start", "/start",
    "анкета", "привет", "hello", "hi",
    "запись", "записаться", "заявка", "хочу записаться",
    "заполнить анкету",
}

def handle(vk, event, welcome_attach: str):
    uid       = event.user_id
    raw_text  = (event.text or "").strip()
    text      = raw_text.lower()
    msg_id    = event.message_id
    got_photo = has_photo_in_event(event)

    # ════════════════════════════════
    # МАСТЕР — админ-панель
    # ════════════════════════════════
    if uid == MASTER_VK_ID:
        mode = master_state["mode"]

        if mode == "broadcast_wait_text":
            master_state["broadcast_text"] = raw_text
            master_state["mode"] = "broadcast_confirm"
            count = db_get_clients_count()
            send(vk, uid,
                 f"Текст рассылки:\n\n{raw_text}\n\n"
                 f"Клиентов в базе: {count}\n\n"
                 "Отправить?",
                 keyboard=kb_yes_no())
            return

        if mode == "broadcast_confirm":
            if "отправ" in text:
                master_state["mode"] = "idle"
                n = broadcast(vk, master_state["broadcast_text"])
                send(vk, uid, f"Готово! Сообщение отправлено {n} клиентам.", keyboard=kb_admin())
            else:
                master_state["mode"] = "idle"
                send(vk, uid, "Рассылка отменена.", keyboard=kb_admin())
            return

        if "рассылка" in text:
            master_state["mode"] = "broadcast_wait_text"
            send(vk, uid, "Введи текст рассылки:")
            return

        if "список" in text:
            clients = db_get_all_clients()
            if clients:
                lines = []
                for c in clients[:50]:
                    lines.append(
                        f"• {c['first_name']} {c['last_name']} — "
                        f"vk.com/id{c['vk_id']} (с {c['created_at'][:10]})"
                    )
                send(vk, uid,
                     f"Клиентов в базе: {len(clients)}\n\n" + "\n".join(lines),
                     keyboard=kb_admin())
            else:
                send(vk, uid, "Клиентов пока нет.", keyboard=kb_admin())
            return

        if "статистика" in text:
            clients = db_get_clients_count()
            apps    = db_get_apps_count()
            active  = len(sessions)
            send(vk, uid,
                 f"📊 Статистика:\n\n"
                 f"👥 Всего клиентов: {clients}\n"
                 f"📋 Всего заявок: {apps}\n"
                 f"⏳ Анкет в процессе: {active}",
                 keyboard=kb_admin())
            return

        send(vk, uid, "Панель управления VALHALLA:", keyboard=kb_admin())
        return

    # ════════════════════════════════
    # КЛИЕНТ
    # ════════════════════════════════

    # Стартовые команды / кнопка «Заполнить анкету»
    if text in START_WORDS:
        # Регистрируем клиента в БД если ещё нет
        if not db_client_exists(uid):
            fn, ln = get_full_name(vk, uid)
            db_add_client(uid, fn, ln)
        start_form(vk, uid)
        return

    # Первый раз — приветствие с фото
    if uid not in sessions and not db_client_exists(uid):
        fn, ln = get_full_name(vk, uid)
        db_add_client(uid, fn, ln)
        send(vk, uid,
             f"👋 Привет, {fn}!\n\n"
             "Добро пожаловать! Здесь ты можешь записаться на тату 🖤\n\n"
             "Нажми кнопку ниже, чтобы оставить заявку — мастер свяжется с тобой в ближайшее время.",
             keyboard=kb_start(),
             attachment=welcome_attach or None)
        return

    # Клиент уже знакомый, но не в активной сессии
    if uid not in sessions:
        send(vk, uid,
             "Нажми «Заполнить анкету», чтобы оставить заявку 🖤",
             keyboard=kb_start())
        return

    sess = sessions[uid]
    step = sess["step"]
    data = sess["data"]

    # ── ШАГ 1: фото места нанесения ──────────────────────────
    if step == "photo":
        if got_photo:
            attach = get_attach_string(vk, msg_id)
            data["photo_attach"] = attach
            data["photo_msg_id"] = msg_id
            sess["step"] = "sketch"
            send(vk, uid,
                 "✅ Фото получено!\n\n"
                 "📍 Шаг 2 из 5\n"
                 "🎨 Есть эскиз или референс?\n\n"
                 "Пришли любую картинку, которая тебе нравится — мастер возьмёт её за основу, "
                 "подгонит под нужный размер и форму, а потом пришлёт как это будет смотреться именно на тебе.\n\n"
                 "Если ничего нет — нажми «Пропустить».",
                 keyboard=kb_sketch())
        else:
            send(vk, uid,
                 "Прикрепи фото места нанесения и отправь 📷\n\n"
                 "Просто выбери картинку из галереи и пришли её сюда.",
                 keyboard=None)

    # ── ШАГ 2: эскиз ─────────────────────────────────────────
    elif step == "sketch":
        if got_photo:
            attach = get_attach_string(vk, msg_id)
            data["sketch_attach"] = attach
            data["sketch_msg_id"] = msg_id
            sess["step"] = "size"
            send(vk, uid,
                 "✅ Эскиз сохранён!\n\n"
                 "📍 Шаг 3 из 5\n"
                 "📏 Выбери примерный размер тату:",
                 keyboard=kb_size())
        elif any(w in text for w in ("пропуст", "нет", "эскиза нет")):
            data["sketch_attach"] = None
            sess["step"] = "size"
            send(vk, uid,
                 "👌 Хорошо, продолжаем без эскиза.\n\n"
                 "📍 Шаг 3 из 5\n"
                 "📏 Выбери примерный размер тату:",
                 keyboard=kb_size())
        else:
            send(vk, uid,
                 "Пришли фото эскиза или нажми «Пропустить» 👇",
                 keyboard=kb_sketch())

    # ── ШАГ 3: размер ────────────────────────────────────────
    elif step == "size":
        SIZES = {
            "до 5":      "до 5 см",
            "5 - 10":    "5–10 см",
            "5-10":      "5–10 см",
            "10 - 15":   "10–15 см",
            "10-15":     "10–15 см",
            "15 - 20":   "15–20 см",
            "15-20":     "15–20 см",
            "более 20":  "более 20 см",
            "больше 20": "более 20 см",
        }
        matched = next((v for k, v in SIZES.items() if k in text), None)
        if matched:
            data["size"] = matched
            sess["step"] = "age"
            send(vk, uid,
                 f"✅ Размер: {matched}\n\n"
                 "📍 Шаг 4 из 5\n"
                 "🎂 Сколько тебе полных лет?\n\n"
                 "Напиши цифрами 👇",
                 keyboard=None)
        else:
            send(vk, uid, "Нажми одну из кнопок с размером 👇", keyboard=kb_size())

    # ── ШАГ 4: возраст ───────────────────────────────────────
    elif step == "age":
        digits = "".join(c for c in text if c.isdigit())
        if digits and 10 <= int(digits) <= 100:
            data["age"] = digits
            age_int = int(digits)
            if age_int < 18:
                # Несовершеннолетний — спрашиваем про разрешение
                sess["step"] = "minor_permission"
                send(vk, uid,
                     f"✅ Возраст: {digits} лет\n\n"
                     "⚠️ Так как тебе нет 18 лет, для записи необходимо письменное "
                     "разрешение от родителя или опекуна.\n\n"
                     "У тебя уже есть подписанное разрешение?",
                     keyboard=kb_permission())
            else:
                sess["step"] = "contact_time"
                send(vk, uid,
                     f"✅ Возраст: {digits} лет\n\n"
                     "📍 Шаг 5 из 5\n"
                     "📞 Когда удобно получить сообщение или звонок от мастера?",
                     keyboard=kb_contact_time())
        else:
            send(vk, uid, "Введи возраст цифрами. Например: 24", keyboard=None)

    # ── ШАГ 4б: разрешение родителей (несовершеннолетние) ────
    elif step == "minor_permission":
        if "нет" in text or "шаблон" in text:
            # Загружаем и отправляем документ-шаблон
            doc_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "razreshenie_roditeley.docx")
            att_str = None
            if os.path.exists(doc_path):
                try:
                    # Получаем upload server для документа
                    vk_raw = vk_session_global.get_api()
                    upload_data = vk_raw.docs.getMessagesUploadServer(type="doc", peer_id=uid)
                    upload_url  = upload_data["upload_url"]

                    import requests as _req
                    with open(doc_path, "rb") as docf:
                        resp = _req.post(upload_url, files={"file": ("razreshenie_roditeley.docx", docf)})
                    file_data = resp.json().get("file", "")

                    saved = vk_raw.docs.save(file=file_data, title="Разрешение родителей на тату")
                    d = saved["doc"]
                    att_str = f"doc{d['owner_id']}_{d['id']}"
                    log.info("Документ загружен: %s", att_str)
                except Exception as e:
                    log.error("Ошибка загрузки документа: %s", e)
            else:
                log.warning("Файл razreshenie_roditeley.docx не найден по пути: %s", doc_path)

            sess["step"] = "minor_doc"
            msg = (
                "📄 Держи шаблон разрешения!\n\n"
                "Что нужно сделать:\n"
                "1. Распечатай документ\n"
                "2. Родитель заполняет и подписывает\n"
                "3. Ты тоже подписываешь\n"
                "4. Оригинал обязательно принеси на сеанс\n\n"
                "Когда всё будет готово — нажми кнопку ниже 👇"
            )
            send(vk, uid, msg, keyboard=kb_form_done(), attachment=att_str)

        elif "да" in text or "есть" in text:
            # Разрешение уже есть — просим прислать скан/фото
            sess["step"] = "minor_doc"
            send(vk, uid,
                 "✅ Отлично!\n\n"
                 "📎 Пришли фото или скан заполненного разрешения прямо сюда — "
                 "мастер проверит его заранее.\n\n"
                 "Оригинал также обязательно принеси с собой на сеанс 🖤",
                 keyboard=None)
        else:
            send(vk, uid, "Нажми одну из кнопок 👇", keyboard=kb_permission())

    # ── ШАГ 4в: получение скана разрешения ───────────────────
    elif step == "minor_doc":
        if got_photo or "заполнена" in text or "готово" in text or "готов" in text:
            if got_photo:
                attach = get_attach_string(vk, msg_id)
                data["permission_attach"] = attach
                data["permission_msg_id"] = msg_id
                msg_ok = (
                    "✅ Скан получен! Мастер проверит его перед сеансом.\n\n"
                    "‼️ Оригинал разрешения обязательно возьми с собой на сеанс — "
                    "без него процедура не проводится.\n\n"
                    "📍 Шаг 5 из 5\n"
                    "📞 Когда удобно получить сообщение или звонок от мастера?"
                )
            else:
                # Нажал «Анкета заполнена» без фото
                data["permission_attach"] = None
                msg_ok = (
                    "👍 Принято!\n\n"
                    "‼️ Обязательно принеси оригинал разрешения с собой на сеанс — "
                    "без него процедура не проводится.\n\n"
                    "📍 Шаг 5 из 5\n"
                    "📞 Когда удобно получить сообщение или звонок от мастера?"
                )
            sess["step"] = "contact_time"
            send(vk, uid, msg_ok, keyboard=kb_contact_time())
        else:
            send(vk, uid,
                 "Пришли фото или скан заполненного разрешения, "
                 "или нажми «Анкета заполнена» если принесёшь оригинал на сеанс 👇",
                 keyboard=kb_form_done())

    # ── ШАГ 5: время для связи ───────────────────────────────
    elif step == "contact_time":
        TIMES = ["9:00 - 12:00", "12:00 - 15:00", "15:00 - 18:00", "18:00 - 21:00"]
        matched = next((t for t in TIMES if t in text), None)
        if not matched and "люб" in text:
            matched = "Любое время"
        if matched:
            data["contact_time"] = matched
            sess["step"] = "confirm"
            preview = (
                "📋 Твоя заявка:\n\n"
                f"📏 Размер: {data['size']}\n"
                f"🎂 Возраст: {data['age']} лет\n"
                f"📞 Время связи: {data['contact_time']}\n"
                f"📸 Фото места: {'есть ✅' if data.get('photo_attach') else 'нет'}\n"
                f"🎨 Эскиз: {'есть ✅' if data.get('sketch_attach') else 'нет'}\n\n"
                "Всё верно? 👇"
            )
            send(vk, uid, preview, keyboard=kb_confirm())
        else:
            send(vk, uid, "Нажми одну из кнопок с временем 👇", keyboard=kb_contact_time())

    # ── ПОДТВЕРЖДЕНИЕ ────────────────────────────────────────
    elif step == "confirm":
        if "заново" in text or "начать" in text:
            sessions.pop(uid, None)
            start_form(vk, uid)
            return

        if "отправ" in text or "верно" in text:
            fn, ln = get_full_name(vk, uid)
            summary = make_summary(data, fn, ln, uid)

            # Сохраняем заявку в БД
            db_save_application(uid, data)
            log.info("Заявка сохранена в БД. uid=%s", uid)

            # 1. Текстовая сводка мастеру
            try:
                send(vk, MASTER_VK_ID, summary)
            except Exception as ex:
                log.error("Сводка не отправлена: %s", ex)

            # 2. Фото места нанесения
            if data.get("photo_attach"):
                try:
                    send(vk, MASTER_VK_ID,
                         f"📸 Фото места — {fn} {ln} (vk.com/id{uid})",
                         attachment=data["photo_attach"])
                except Exception as ex:
                    log.error("Фото через attachment (%s), пробую forward...", ex)
                    try:
                        vk.messages.send(
                            user_id=MASTER_VK_ID,
                            message=f"📸 Фото места — {fn} {ln} (vk.com/id{uid})",
                            forward_messages=str(data["photo_msg_id"]),
                            random_id=random.randint(0, 2 ** 31),
                        )
                    except Exception as ex2:
                        log.error("forward_messages тоже не сработал: %s", ex2)

            # 3. Эскиз
            if data.get("sketch_attach"):
                try:
                    send(vk, MASTER_VK_ID,
                         f"✏️ Эскиз — {fn} {ln} (vk.com/id{uid})",
                         attachment=data["sketch_attach"])
                except Exception as ex:
                    log.error("Эскиз через attachment (%s), пробую forward...", ex)
                    try:
                        vk.messages.send(
                            user_id=MASTER_VK_ID,
                            message=f"✏️ Эскиз — {fn} {ln} (vk.com/id{uid})",
                            forward_messages=str(data["sketch_msg_id"]),
                            random_id=random.randint(0, 2 ** 31),
                        )
                    except Exception as ex2:
                        log.error("forward_messages для эскиза не сработал: %s", ex2)

            # 3б. Скан разрешения родителей (если есть)
            if data.get("permission_attach"):
                try:
                    send(vk, MASTER_VK_ID,
                         f"📋 Разрешение родителей — {fn} {ln} (vk.com/id{uid})",
                         attachment=data["permission_attach"])
                except Exception as ex:
                    log.error("Скан разрешения через attachment (%s), пробую forward...", ex)
                    try:
                        vk.messages.send(
                            user_id=MASTER_VK_ID,
                            message=f"📋 Разрешение родителей — {fn} {ln} (vk.com/id{uid})",
                            forward_messages=str(data["permission_msg_id"]),
                            random_id=random.randint(0, 2 ** 31),
                        )
                    except Exception as ex2:
                        log.error("forward_messages для разрешения не сработал: %s", ex2)

            # 4. Финальное сообщение клиенту
            send(vk, uid,
                 "🔥 Заявка успешно отправлена!\n\n"
                 "Мастер уже получил твою анкету ✨\n"
                 "С тобой свяжутся в ближайшее время.\n\n"
                 "💬 Чтобы оставить новую заявку — напиши «Начать».",
                 keyboard=kb_start())

            sessions.pop(uid, None)

        else:
            send(vk, uid,
                 "Нажми «Отправить заявку» или «Начать заново» 👇",
                 keyboard=kb_confirm())

    else:
        sessions.pop(uid, None)
        start_form(vk, uid)


# ══════════════════════════════════════
#  ЗАПУСК
# ══════════════════════════════════════

def main():
    global vk_session_global
    if not GROUP_TOKEN:
        raise SystemExit("Укажите BOT_TOKEN (токен группы VK) в переменных окружения.")
    db_init()  # создаёт tattoo.db при первом запуске

    vk_session        = vk_api.VkApi(token=GROUP_TOKEN)
    vk_session_global = vk_session   # нужен для загрузки документов внутри handle()
    vk                = vk_session.get_api()
    longpoll          = VkLongPoll(vk_session, group_id=GROUP_ID)

    welcome_attach = upload_welcome_photo(vk_session)

    log.info("VALHALLA Bot запущен. БД: %s", os.path.abspath(DB_FILE))

    for event in longpoll.listen():
        if event.type == VkEventType.MESSAGE_NEW and event.to_me:
            try:
                handle(vk, event, welcome_attach)
            except Exception as e:
                log.exception("Ошибка (uid=%s): %s", getattr(event, "user_id", "?"), e)


if __name__ == "__main__":
    main()
