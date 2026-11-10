import asyncio
import json
import re
import sqlite3
import html
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.filters import Command
import aiohttp

# ================= НАСТРОЙКИ =================
BOT_TOKEN = "9071887061:AAF_eh-XTOzYSgVfzH4-Y2QeJUx-36qySV4"
ADMIN_CHAT_ID = 781413995  # Ваш числовой Telegram ID

# Скопируйте сюда вашу строку Cookie с kwork.ru/projects
KWORK_COOKIE = "_ym_uid=1776869265662196346; uad=2066455069e8e074164fb919344731; list_type_sdisplay=table; ref=531396; _ym_d=1793900968; referrer_url=https%3A%2F%2Fkwork.ru%2Fprojects; csrf_user_token=7b1811e934c768d4c73a3c3356b9ada2; RORSSQIHEK=852fec8b0d78eeee3e8a2ac7362fae5c; slrememberme=20664550_%242y%2412%24pmv5Nk2RozN.GfvkmtcY%2FeQTsBjQT8QqDGlBEPb9V7n%2FlnjwoaTcu; ref_redirect_save=531396; gclid=Cj0KCQiAnsvXBhCqARIsAHKgGNbT8atk8yM5q-Jz6OyTsmiSXIRDutpER_CTEPTx6RzJL0rP1ou17PcaAo-mEALw_wcB; landed_page=%2F%3Fgad_source%3D1%26gad_campaignid%3D24016514384%26gbraid%3D0AAAAA-e_KnqhtnT8WOwS8dHOUjMRUnWy6%26gclid%3DCj0KCQiAnsvXBhCqARIsAHKgGNbT8atk8yM5q-Jz6OyTsmiSXIRDutpER_CTEPTx6RzJL0rP1ou17PcaAo-mEALw_wcB; _ym_isad=1"

CHECK_INTERVAL = 45  # Интервал проверки новых проектов в секундах
EXCLUDED_CATEGORIES = {"Компьютерная и IT помощь"}
# =============================================

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Инициализация базы данных SQLite для сохранения состояния
conn = sqlite3.connect("kwork_projects.db")
cursor = conn.cursor()
cursor.execute("CREATE TABLE IF NOT EXISTS seen_projects (id INTEGER PRIMARY KEY)")
cursor.execute("""
    CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value INTEGER
    )
""")
cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('is_running', 1)")
cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('min_hired_percent', 0)")
conn.commit()


def get_setting(key: str) -> int:
    cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
    row = cursor.fetchone()
    return row[0] if row else 0


def set_setting(key: str, value: int):
    cursor.execute("REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
    conn.commit()


def is_project_seen(project_id: int) -> bool:
    cursor.execute("SELECT 1 FROM seen_projects WHERE id = ?", (project_id,))
    return cursor.fetchone() is not None


def mark_project_seen(project_id: int):
    cursor.execute("INSERT OR IGNORE INTO seen_projects (id) VALUES (?)", (project_id,))
    conn.commit()


async def fetch_projects() -> list:
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": "https://kwork.ru/projects",
        "Cookie": KWORK_COOKIE,
    }
    url = "https://kwork.ru/projects?a=1"

    async with aiohttp.ClientSession(headers=headers) as session:
        try:
            async with session.get(url, timeout=20) as resp:
                text = await resp.text()
                try:
                    data = json.loads(text)
                    if "data" in data and "wants" in data["data"]:
                        return data["data"]["wants"]
                    if "wants" in data:
                        return data["wants"]
                except json.JSONDecodeError:
                    pass

                match = re.search(r"window\.stateData\s*=\s*(\{.*?\});\s*</script>", text, re.S)
                if match:
                    state_data = json.loads(match.group(1))
                    return (
                        state_data.get("wantsListData", {}).get("wants")
                        or state_data.get("wants")
                        or []
                    )
        except Exception as e:
            print(f"[Ошибка запроса к Kwork]: {e}")
    return []


def format_project_card(item: dict) -> tuple[str, InlineKeyboardMarkup]:
    project_id = item.get("id", 0)
    title = html.escape(item.get("name", "Без названия"))

    raw_desc = re.sub(r"<br\s*/?>", "\n", item.get("description", ""))
    clean_desc = re.sub(r"<[^>]+>", "", raw_desc).strip()
    if len(clean_desc) > 650:
        clean_desc = clean_desc[:650] + "..."
    desc = html.escape(clean_desc)

    price_limit = item.get("priceLimit")
    possible_limit = item.get("possiblePriceLimit")
    price_str = f"{int(float(price_limit)):,} ₽".replace(",", " ") if price_limit else "Не указан"
    if possible_limit:
        pos_str = f"{int(float(possible_limit)):,} ₽".replace(",", " ")
        price_str += f" (допустимый: до {pos_str})"

    category = html.escape(item.get("categoryName") or "Разработка и IT")
    offers_count = item.get("kworkCount", 0)
    time_left = html.escape(str(item.get("timeLeft") or item.get("date_create") or "Только что"))

    user = item.get("user", {})
    username = html.escape(user.get("username", "Покупатель"))
    user_data = user.get("data", {})

    hired_pct = user_data.get("wants_hired_percent") or item.get("userHiredPercent")
    wants_count = user_data.get("wants_count") or item.get("userWantsCount")
    active_wants = user.get("active_wants") or user_data.get("active_wants")

    badge = "⚪️"
    if hired_pct is not None:
        hired_val = int(hired_pct)
        badge = "🟢" if hired_val >= 60 else ("🟡" if hired_val >= 30 else "🔴")

    buyer_lines = []
    if hired_pct is not None:
        buyer_lines.append(f"{badge} Нанято: <b>{hired_pct}%</b>")
    if wants_count is not None:
        buyer_lines.append(f"Проектов: <b>{wants_count}</b>")
    if active_wants is not None:
        buyer_lines.append(f"Активных: <b>{active_wants}</b>")

    buyer_stats_str = " | ".join(buyer_lines) if buyer_lines else "Новый покупатель (без истории)"

    text = (
        f"🔥 <b>{title}</b>\n"
        f"📂 Рубрика: <i>{category}</i>\n\n"
        f"📝 <b>Описание:</b>\n{desc}\n\n"
        f"💰 <b>Бюджет:</b> {price_str}\n"
        f"📨 <b>Предложений:</b> {offers_count} | ⏱ {time_left}\n"
        f"────────────────────\n"
        f"👤 <b>Покупатель:</b> <a href='https://kwork.ru/user/{username}'>{username}</a>\n"
        f"📊 {buyer_stats_str}"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🚀 Предложить услугу", url=f"https://kwork.ru/new_offer?project={project_id}"),
            InlineKeyboardButton(text="🔎 Проект", url=f"https://kwork.ru/projects/{project_id}/view"),
        ],
        [
            InlineKeyboardButton(text=f"👤 Профиль {username}", url=f"https://kwork.ru/user/{username}"),
        ]
    ])
    return text, kb


@dp.message(Command("start"))
async def cmd_start(message: Message):
    if message.from_user.id != ADMIN_CHAT_ID:
        return
    status = "🟢 Активен" if get_setting("is_running") else "🔴 На паузе"
    min_pct = get_setting("min_hired_percent")
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="▶️ Запустить / ⏸ Пауза", callback_data="toggle_run"),
        ],
        [
            InlineKeyboardButton(text="Фильтр найма: Все (0%)", callback_data="set_pct_0"),
            InlineKeyboardButton(text="От 30%", callback_data="set_pct_30"),
            InlineKeyboardButton(text="От 50%", callback_data="set_pct_50"),
        ]
    ])
    await message.answer(
        f"<b>Панель управления парсером Kwork</b>\n\n"
        f"Статус перехвата: <b>{status}</b>\n"
        f"Мин. рейтинг найма покупателя: <b>{min_pct}%</b>\n\n"
        f"Отслеживаемые рубрики (согласно вашему выбору)",
        parse_mode="HTML",
        reply_markup=kb
    )


@dp.callback_query(F.data == "toggle_run")
async def cb_toggle_run(call: CallbackQuery):
    current = get_setting("is_running")
    new_val = 0 if current else 1
    set_setting("is_running", new_val)
    status = "🟢 Запущен" if new_val else "🔴 Остановлен"
    await call.answer(f"Мониторинг {status}")
    await cmd_start(call.message)


@dp.callback_query(F.data.startswith("set_pct_"))
async def cb_set_pct(call: CallbackQuery):
    pct = int(call.data.split("_")[-1])
    set_setting("min_hired_percent", pct)
    await call.answer(f"Минимальный процент найма установлен на {pct}%")
    await cmd_start(call.message)


async def parser_loop():
    while True:
        if get_setting("is_running") == 1:
            projects = await fetch_projects()
            min_pct = get_setting("min_hired_percent")

            for item in reversed(projects):
                pid = int(item.get("id", 0))
                if not pid or is_project_seen(pid):
                    continue

                cat_name = item.get("categoryName", "")
                if cat_name in EXCLUDED_CATEGORIES:
                    mark_project_seen(pid)
                    continue

                user_data = item.get("user", {}).get("data", {})
                hired_pct = user_data.get("wants_hired_percent") or item.get("userHiredPercent") or 0
                if int(hired_pct) < min_pct:
                    mark_project_seen(pid)
                    continue

                text, kb = format_project_card(item)
                try:
                    await bot.send_message(
                        chat_id=ADMIN_CHAT_ID,
                        text=text,
                        parse_mode="HTML",
                        disable_web_page_preview=True,
                        reply_markup=kb
                    )
                    mark_project_seen(pid)
                    await asyncio.sleep(0.4)
                except Exception as e:
                    print(f"[Ошибка отправки в Telegram]: {e}")

        await asyncio.sleep(CHECK_INTERVAL)


async def main():
    asyncio.create_task(parser_loop())
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
