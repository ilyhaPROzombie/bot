import json, os, re, sys, time, html
import requests

BOT_TOKEN = "9071887061:AAF_eh-XTOzYSgVfzH4-Y2QeJUx-36qySV4"
CHAT_ID = "781413995"

# Вставьте сюда URL(ы) со страницы проектов с вашими фильтрами
URLS = [
    "https://kwork.ru/projects?a=1",
]

SEEN_FILE = "seen.json"
INTERVAL = 240  # секунд, только для локального режима (--loop)
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept-Language": "ru-RU,ru;q=0.9",
}
COOKIES = {}
# test
# for part in os.environ.get("KWORK_COOKIES", "").split(";"):
#     if "=" in part:
#         k, v = part.strip().split("=", 1)
#         COOKIES[k] = v
# test

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


from datetime import datetime
import html
import re

def format_time(timestamp):
    try:
        dt = datetime.fromtimestamp(int(timestamp))
        return dt.strftime("%d.%m.%Y в %H:%M")
    except Exception:
        return "Только что"

def fmt(w: dict) -> str:
    u = w.get("user") or {}
    ud = u.get("data") or {}
    esc = lambda s: html.escape(str(s if s not in (None, "") else "—"))

    price = w.get("priceLimit") or w.get("price_limit")
    price_max = w.get("possiblePriceLimit")
    desc = re.sub(r"\s+", " ", w.get("description") or "")[:600]
    
    # Обработка времени публикации (проверяем разные возможные ключи таймстампы или даты)
    raw_date = w.get("date") or w.get("date_publish") or w.get("created_at")
    pub_date = format_time(raw_date) if raw_date else "Не указано"

    return (
        f"🆕 <b>{esc(w.get('name'))}</b> 🆕\n\n"
        f"🕒 <b>Опубликовано:</b> {esc(pub_date)}\n"
        f"💰 Бюджет: {esc(price)} ₽ (допустимо до {esc(price_max)} ₽)\n"
        f"------------------------------------\n"
        f"📝 {esc(desc)}\n"
        f"------------------------------------\n"
        f"💬 Предложений: {esc(w.get('kwork_count'))}\n"
        f"⏳ Осталось: {esc(w.get('timeLeft') or w.get('date_expire'))}\n\n"
        f"👤 <b>Покупатель:</b> {esc(u.get('username'))}\n"
        f"📊 Размещено проектов: {esc(ud.get('wants_count'))}\n"
        f"✅ Процент найма: {esc(ud.get('wants_hired_percent'))}%\n"
        f"🔗 https://kwork.ru/projects/{w.get('id')}"
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


# Фильтр по ключевым словам (потом можно заменить на фильтр по рубрикам)
KEYWORDS = ("верстка", "сайт", "html", "css", "js", "php","хостинг", "домен",
            "wordpress", "доработка", "юзабилити", "сервер")


def allowed(w):
    title = (w.get("name") or "").lower()
    description = (w.get("description") or "").lower()
    full_text = f"{title} {description}"

    # Ваши ключевые слова (соответствуют вашим рубрикам: верстка, правки, WP, создание сайтов и т.д.)
    target_keywords = [
        # Верстка и фронтенд
        "верстк", "html", "css", "scss","php", "js", "javascript", "java", "flexbox", "grid", "макет", "figma", "фигм",
        # Правки и доработка
        "доработк", "правк", "ошибк", "баг", "исправ", "плагин", "тему", "темы", 
        "скорост", "оптимизац", "ускорен", "админку", "админ",
        # WordPress и конструкторы
        "wordpress", "вордпресс","wordpres","вордпрес", "wp", "acf", "elementor", "элементор",
        # Создание сайтов
        "сайт", "лендинг", "landing", "интернет-магазин", "магазин", "портфолио", "визитк", 
        "копи", "перенос",
        # Сервера и хостинг
        "хостинг", "хост", "домен", "сервер", "vps", "vds", "ssl"
    ]
    
    # Проверяем, есть ли хоть одно ключевое слово в тексте проекта
    has_keyword = any(kw in full_text for kw in target_keywords)
    
    # Если ключевое слово найдено — пропускаем (True), если нет — отклоняем (False)
    return has_keyword


def run_once():
    seen = load_seen()
    first_run = not seen
    new = []

    for url in URLS:
        for w in find_wants(fetch(url)):
            wid = str(w.get("id"))
            if wid in seen:
                continue          # Уже видели этот ID в прошлые разы, пропускаем
            
            # 1. ЗАПОМНИМ В ЛЮБОМ СЛУЧАЕ (даже если проект не подошел по фильтру)
            seen.add(wid)         
            
            # 2. Проверяем, подходит ли он под ваши критерии для отправки
            if allowed(w):
                new.append(w)     
        time.sleep(3)

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