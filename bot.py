import json, os, re, sys, time, html
import requests

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODELS = [
    "gemini-flash-lite-latest",
    "gemini-flash-latest",
]

SYSTEM_PROMPT = """Ты ассистент фрилансера-веб-разработчика (стек: HTML, CSS, JS, PHP, WordPress, ACF, Elementor, WooCommerce; услуги: верстка по Figma, доработки, сайты под ключ).
Кратко оцени заказ с Kwork строго в 4 строки, БЕЗ Markdown (без **, *, #), максимум 450 символов:
💰 Цена: адекватна / занижена / хорошая (коротко почему с учётом объёма)
📋 ТЗ и сроки: понятность задачи, скрытые риски, срочность (если есть сроки)
👤 Заказчик: новичок или опытный, оценка процента найма
🎯 Вердикт: стоит брать / сомнительно / лучше пропустить"""

SEEN_FILE = "seen.json"
INTERVAL = 240  # секунд, только для локального режима (--loop)
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept-Language": "ru-RU,ru;q=0.9",
}
COOKIES = {}


def load_seen():
    try:
        return set(json.load(open(SEEN_FILE)))
    except Exception:
        return set()


def save_seen(seen):
    json.dump(sorted(seen)[-3000:], open(SEEN_FILE, "w"))


def extract_state(page: str) -> dict:
    """Kwork кладёт данные страницы в window.stateData = {...};"""
    m = re.search(r"window\.stateData\s*=\s*(\{.*?\});\s*(?:window\.|</script>)", page, re.S)
    if not m:
        raise RuntimeError("stateData не найден: возможно, блокировка или смена верстки")
    return json.loads(m.group(1))


def find_wants(state: dict) -> list:
    data = state.get("wantsListData", {})
    pag = data.get("pagination", {})
    return pag.get("data") or data.get("wants") or []


def fetch(url):
    r = requests.get(url, headers=HEADERS, cookies=COOKIES, timeout=30)
    r.raise_for_status()
    return extract_state(r.text)


from datetime import datetime, timezone, timedelta

MSK = timezone(timedelta(hours=3))

def format_time(val) -> str:
    if not val:
        return "Не указано"
    s = str(val).strip()

    # Если пришёл Unix timestamp (например, 1763800000)
    if s.isdigit():
        dt = datetime.fromtimestamp(int(s), tz=MSK)
        return dt.strftime("%d.%m.%Y в %H:%M МСК")

    # Если пришла строка вида "2026-11-22 14:35:10" (Kwork отдаёт её уже по МСК)
    for pattern in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            dt = datetime.strptime(s[:19], pattern)
            return dt.strftime("%d.%m.%Y в %H:%M МСК")
        except ValueError:
            continue

    return s

def get_pub_date(w: dict) -> str:
    for key in ("date_active", "date_create"):
        if w.get(key):
            return format_time(w[key])
    return "Не указано"

def analyze_project(w: dict) -> str:
    if not GEMINI_API_KEY:
        return ""

    u = w.get("user") or {}
    ud = u.get("data") or {}

    user_content = (
        f"Название: {w.get('name')}\n"
        f"Бюджет: {w.get('priceLimit') or w.get('price_limit')} ₽ "
        f"(допустимо до {w.get('possiblePriceLimit')} ₽)\n"
        f"Осталось на приём откликов: {w.get('timeLeft') or w.get('date_expire')}\n"
        f"Откликов: {w.get('kwork_count')}\n"
        f"Заказчик: размещено проектов {ud.get('wants_count')}, "
        f"процент найма {ud.get('wants_hired_percent')}%\n"
        f"Полное описание:\n{w.get('description') or 'Нет описания'}"
    )

    payload = {
        "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": [{"parts": [{"text": user_content}]}],
        "generationConfig": {
            "temperature": 0.3,
            "maxOutputTokens": 2048,
        },
    }

    for model in GEMINI_MODELS:
        attempts = [
        ("gemini-flash-lite-latest", 15),
        ("gemini-flash-lite-latest", 15),
        ("gemini-flash-latest", 25),
    ]

    for i, (model, req_timeout) in enumerate(attempts, 1):
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        try:
            r = requests.post(
                url,
                headers={
                    "x-goog-api-key": GEMINI_API_KEY,
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=req_timeout,
            )

            if r.ok:
                data = r.json()
                cand = data["candidates"][0]
                finish_reason = cand.get("finishReason")
                if finish_reason and finish_reason != "STOP":
                    print(f"Gemini ({model}) завершил с причиной: {finish_reason}")
                parts = cand.get("content", {}).get("parts", [])
                text = "".join(
                    p.get("text", "") for p in parts if not p.get("thought")
                ).strip()
                return text

            print(f"Попытка {i} ({model}) вернула {r.status_code}...")
            if r.status_code in (429, 500, 503):
                time.sleep(3)
                continue

            print(f"Ответ Gemini ({model}): {r.text}")
            return ""
        except requests.exceptions.Timeout:
            print(f"Попытка {i} ({model}): таймаут...")
            time.sleep(2)
            continue
        except Exception as e:
            print(f"Ошибка Gemini API ({model}): {e}")
            return ""

    return ""

def fmt(w: dict) -> str:
    u = w.get("user") or {}
    ud = u.get("data") or {}
    esc = lambda s: html.escape(str(s if s not in (None, "") else "—"))

    price = w.get("priceLimit") or w.get("price_limit")
    price_max = w.get("possiblePriceLimit")
    desc = re.sub(r"\s+", " ", w.get("description") or "")[:600]
    
    # поиск времени
    pub_date = get_pub_date(w)

    ai_text = analyze_project(w)
    ai_block = (
        f"\n\n<blockquote expandable>🤖 <b>Анализ заказа:</b>\n{esc(ai_text)}</blockquote>"
        if ai_text else ""
    )

    return (
        f"🆕 <b>{esc(w.get('name'))}</b>\n\n"
        f"💰 Бюджет: {esc(price)} ₽ (допустимо до {esc(price_max)} ₽)\n"
        f"-------------------\n"
        f"📝 {esc(desc)}\n"
        f"-------------------\n"
        f"💬 Предложений: {esc(w.get('kwork_count'))}\n"
        f"🕒 <b>Опубликовано:</b> {esc(pub_date)}\n"
        f"⏳ Осталось: {esc(w.get('timeLeft') or w.get('date_expire'))}\n"
        f"👤 <b>Покупатель:</b> {esc(u.get('username'))}\n"
        f"📊 Размещено проектов: {esc(ud.get('wants_count'))}\n"
        f"✅ Процент найма: {esc(ud.get('wants_hired_percent'))}%\n"
        f"-------------------\n"
        f"📎 https://kwork.ru/projects/{w.get('id')}{ai_block}"
    )


def send(text):
    r = requests.post(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
        json={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML",
              "disable_web_page_preview": True},
        timeout=30,
    )
    if not r.ok:
        # Выведем ошибку и сразу остановим скрипт, чтобы увидеть её в логах GitHub
        raise RuntimeError(f"Telegram error: {r.text}")


import time

FILTER_URLS = [
    "https://kwork.ru/projects?fc=37",
    "https://kwork.ru/projects?fc=38",
    "https://kwork.ru/projects?fc=79",
    "https://kwork.ru/projects?fc=81",
    "https://kwork.ru/projects?fc=255",
    # сюда добавьте остальные нужные ссылки с сайта (например, доработка, сайт под ключ)
]

def load_all_projects() -> list[dict]:
    unique = {}  # убирает дубли, если заказ попал сразу в две подрубрики

    for url in FILTER_URLS:
        for w in fetch_projects(url):  # ваша текущая функция запроса к Kwork
            pid = str(w.get("id") or "")
            if pid:
                unique[pid] = w
        time.sleep(1)  # пауза, чтобы Kwork не резал частые запросы

    return list(unique.values())


def run_once():
    seen = load_seen()
    first_run = not seen
    new = []

    for url in FILTER_URLS:
        projects = find_wants(fetch(url))

        for w in projects:
            wid = str(w.get("id"))
            if wid in seen:
                continue          # Уже видели этот ID в прошлые разы (или в другой рубрике), пропускаем

            # 1. ЗАПОМНИМ В ЛЮБОМ СЛУЧАЕ
            seen.add(wid)

            # 2. Добавляем в очередь на отправку (фильтрация уже сделана через FILTER_URLS)
            new.append(w)
        time.sleep(2)

    # Отправка в Telegram (если это не самый первый пустой запуск)
    if not first_run:
        print(f"Пытаюсь отправить в Telegram проектов: {len(new)}")
        for w in reversed(new):   # От старых к новым
            print(f"Отправляю заказ ID: {w.get('id')}")
            send(fmt(w))
            time.sleep(1)
    else:
        print("Первый запуск: база инициализирована, спам пропущен.")

    # 3. Гарантированно сохраняем обновленный массив на диск
    save_seen(seen)
    print(f"Сохранено. Всего ID в базе seen.json: {len(seen)}")

if __name__ == "__main__":
    if "--dump" in sys.argv:  # посмотреть реальную структуру данных
        wants = find_wants(fetch(URLS[0]))
        print(json.dumps(wants[:1], ensure_ascii=False, indent=2))
    elif "--loop" in sys.argv:
        while True:
            try:
                run_once()
            except Exception as e:
                print("Ошибка:", e)
            time.sleep(INTERVAL)
    else:
        run_once()