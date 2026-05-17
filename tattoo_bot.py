"""
VALHALLA Tattoo Bot — ВКонтакте
pip install vk_api
"""

import vk_api
from vk_api.longpoll import VkLongPoll, VkEventType
from vk_api.keyboard import VkKeyboard, VkKeyboardColor
import logging
import random
import os
import time
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
GROUP_TOKEN  = "vk1.a.qM8MOyWFdXqj449qmyEMVh8_2u6ldFE2ZOkNADpq8Tr55JRc0xrEluF3bZDlPm9rfuFLHGRh1Zpw8YK72S2DGRh2rzkvGJMZQ1rg7-0zb4pMBF8WxhPug3CEUBN_aw3zN36zH-7QVCbraGpctmUePoRQj_Mp2SRFUKJCFzY_vtc5LDrlVlWRlVTCVI91EclOuwwp13BINZaOHd0_1JQXiw"
GROUP_ID     = 238443976
MASTER_VK_ID = 401276566

# Положи welcome.jpg рядом со скриптом — оно отправляется при первом входе
WELCOME_PHOTO = "welcome.jpg"
# ══════════════════════════════════════

sessions:     dict = {}   # { user_id: { step, data } }
known_users:  set  = set()
master_state: dict = {"mode": "idle", "broadcast_text": ""}


# ─────────────────────────────────────
#  КЛАВИАТУРЫ
# ─────────────────────────────────────

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


# ─────────────────────────────────────
#  ОТПРАВКА
# ─────────────────────────────────────

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


# ─────────────────────────────────────
#  ВЛОЖЕНИЯ
# ─────────────────────────────────────

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


# ─────────────────────────────────────
#  ЗАГРУЗКА ПРИВЕТСТВЕННОГО ФОТО
# ─────────────────────────────────────

def upload_welcome_photo(vk_session) -> str:
    if not os.path.exists(WELCOME_PHOTO):
        log.warning("welcome.jpg не найден — бот работает без приветственного фото")
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


# ─────────────────────────────────────
#  ХЕЛПЕРЫ
# ─────────────────────────────────────

def get_first_name(vk, uid: int) -> str:
    try:
        return vk.users.get(user_ids=uid)[0]["first_name"]
    except Exception:
        return "Привет"

def get_full_name(vk, uid: int) -> str:
    try:
        u = vk.users.get(user_ids=uid)[0]
        return f"{u['first_name']} {u['last_name']}"
    except Exception:
        return f"id{uid}"

def make_summary(data: dict, name: str, uid: int) -> str:
    return "\n".join([
        "─────────────────────",
        "НОВАЯ АНКЕТА  |  VALHALLA",
        "─────────────────────",
        f"Клиент:        {name}",
        f"Страница:      vk.com/id{uid}",
        f"Дата:          {datetime.now().strftime('%d.%m.%Y %H:%M')}",
        "",
        f"Размер:        {data.get('size', '—')}",
        f"Возраст:       {data.get('age', '—')} лет",
        f"Время связи:   {data.get('contact_time', '—')}",
        "",
        f"Фото места:    {'есть' if data.get('photo_attach') else 'нет'}",
        f"Эскиз:         {'есть' if data.get('sketch_attach') else 'нет'}",
        "─────────────────────",
    ])


# ─────────────────────────────────────
#  СТАРТ АНКЕТЫ
# ─────────────────────────────────────

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


# ─────────────────────────────────────
#  РАССЫЛКА
# ─────────────────────────────────────

def broadcast(vk, text: str) -> int:
    sent = 0
    for uid in list(known_users):
        if uid == MASTER_VK_ID:
            continue
        try:
            send(vk, uid, text)
            sent += 1
            time.sleep(0.35)
        except Exception as e:
            log.warning("broadcast uid=%s: %s", uid, e)
    return sent


# ─────────────────────────────────────
#  ГЛАВНЫЙ ОБРАБОТЧИК
# ─────────────────────────────────────

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

    known_users.add(uid)

    # ════════════════════════════════
    # МАСТЕР — админ-панель
    # ════════════════════════════════
    if uid == MASTER_VK_ID:
        mode = master_state["mode"]

        if mode == "broadcast_wait_text":
            master_state["broadcast_text"] = raw_text
            master_state["mode"] = "broadcast_confirm"
            clients_count = len([u for u in known_users if u != MASTER_VK_ID])
            send(vk, uid,
                 f"Текст рассылки:\n\n{raw_text}\n\n"
                 f"Клиентов в базе: {clients_count}\n\n"
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
            clients = [u for u in known_users if u != MASTER_VK_ID]
            if clients:
                lines = []
                for cid in clients[:50]:
                    try:
                        info = vk.users.get(user_ids=cid)[0]
                        lines.append(f"• {info['first_name']} {info['last_name']} — vk.com/id{cid}")
                    except Exception:
                        lines.append(f"• vk.com/id{cid}")
                send(vk, uid,
                     f"Клиентов в базе: {len(clients)}\n\n" + "\n".join(lines),
                     keyboard=kb_admin())
            else:
                send(vk, uid, "Клиентов пока нет.", keyboard=kb_admin())
            return

        if "статистика" in text:
            clients = len([u for u in known_users if u != MASTER_VK_ID])
            active  = len(sessions)
            send(vk, uid,
                 f"Статистика:\n\n"
                 f"Всего клиентов: {clients}\n"
                 f"Анкет в процессе: {active}",
                 keyboard=kb_admin())
            return

        send(vk, uid, "Панель управления VALHALLA:", keyboard=kb_admin())
        return

    # ════════════════════════════════
    # КЛИЕНТ
    # ════════════════════════════════

    # Стартовая команда / кнопка «Заполнить анкету»
    if text in START_WORDS:
        start_form(vk, uid)
        return

    # Первый раз — приветствие с фото
    if uid not in sessions:
        name = get_first_name(vk, uid)
        send(vk, uid,
             f"👋 Привет, {name}!\n\n"
             "Добро пожаловать! Здесь ты можешь записаться на тату 🖤\n\n"
             "Нажми кнопку ниже, чтобы оставить заявку — мастер свяжется с тобой в ближайшее время.",
             keyboard=kb_start(),
             attachment=welcome_attach or None)
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
            sess["step"] = "contact_time"
            send(vk, uid,
                 f"✅ Возраст: {digits} лет\n\n"
                 "📍 Шаг 5 из 5\n"
                 "📞 Когда удобно получить сообщение или звонок от мастера?",
                 keyboard=kb_contact_time())
        else:
            send(vk, uid, "Введи возраст цифрами. Например: 24", keyboard=None)

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
            name    = get_full_name(vk, uid)
            summary = make_summary(data, name, uid)

            # 1. Текстовая сводка мастеру
            try:
                send(vk, MASTER_VK_ID, summary)
                log.info("Сводка отправлена. uid=%s name=%s", uid, name)
            except Exception as ex:
                log.error("Сводка не отправлена: %s", ex)

            # 2. Фото места нанесения
            if data.get("photo_attach"):
                try:
                    send(vk, MASTER_VK_ID,
                         f"📸 Фото места — {name} (vk.com/id{uid})",
                         attachment=data["photo_attach"])
                    log.info("Фото места переслано.")
                except Exception as ex:
                    log.error("Фото через attachment не сработало (%s), пробую forward_messages...", ex)
                    try:
                        vk.messages.send(
                            user_id=MASTER_VK_ID,
                            message=f"📸 Фото места — {name} (vk.com/id{uid})",
                            forward_messages=str(data["photo_msg_id"]),
                            random_id=random.randint(0, 2 ** 31),
                        )
                        log.info("Фото переслано через forward_messages.")
                    except Exception as ex2:
                        log.error("forward_messages тоже не сработал: %s", ex2)

            # 3. Эскиз
            if data.get("sketch_attach"):
                try:
                    send(vk, MASTER_VK_ID,
                         f"✏️ Эскиз — {name} (vk.com/id{uid})",
                         attachment=data["sketch_attach"])
                    log.info("Эскиз переслан.")
                except Exception as ex:
                    log.error("Эскиз через attachment не сработало (%s), пробую forward_messages...", ex)
                    try:
                        vk.messages.send(
                            user_id=MASTER_VK_ID,
                            message=f"✏️ Эскиз — {name} (vk.com/id{uid})",
                            forward_messages=str(data["sketch_msg_id"]),
                            random_id=random.randint(0, 2 ** 31),
                        )
                        log.info("Эскиз переслан через forward_messages.")
                    except Exception as ex2:
                        log.error("forward_messages для эскиза не сработал: %s", ex2)

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


# ─────────────────────────────────────
#  ЗАПУСК
# ─────────────────────────────────────

def main():
    vk_session = vk_api.VkApi(token=GROUP_TOKEN)
    vk         = vk_session.get_api()
    longpoll   = VkLongPoll(vk_session, group_id=GROUP_ID)

    welcome_attach = upload_welcome_photo(vk_session)

    log.info("VALHALLA Bot запущен. Ожидаю сообщения...")

    for event in longpoll.listen():
        if event.type == VkEventType.MESSAGE_NEW and event.to_me:
            try:
                handle(vk, event, welcome_attach)
            except Exception as e:
                log.exception("Ошибка (uid=%s): %s", getattr(event, "user_id", "?"), e)


if __name__ == "__main__":
    main()
