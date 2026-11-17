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


def fmt(w: dict) -> str:
    u = w.get("user") or {}
    ud = u.get("data") or {}
    esc = lambda s: html.escape(str(s if s not in (None, "") else "—"))

    price = w.get("priceLimit") or w.get("price_limit")
    price_max = w.get("possiblePriceLimit")
    desc = re.sub(r"\s+", " ", w.get("description") or "")[:600]

    return (
        f"🆕 <b>{esc(w.get('name'))}</b>\n\n"
        f"💰 Бюджет: {esc(price)} ₽ (допустимо до {esc(price_max)} ₽)\n"
        f"📝 {esc(desc)}\n"
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


# def allowed(w: dict) -> bool:
#     text = ((w.get("name") or "") + " " + (w.get("description") or "")).lower()
#     return any(k in text for k in KEYWORDS)

    # ..
def allowed(w):
    return True
    # ,,


def run_once():
    seen = load_seen()
    # test
    first_run = False
    # first_run = not seen
    new = []

    for url in URLS:
        for w in find_wants(fetch(url)):
            wid = str(w.get("id"))
            if wid in seen:
                continue          
            
            if allowed(w):
                new.append(w)     # Сначала проверяем фильтр
                seen.add(wid)     # И только потом запоминаем, что увидели
        time.sleep(3)

    # при самом первом запуске не спамим старыми проектами
    if not first_run:
        print(f"Пытаюсь отправить в Telegram проектов: {len(new)}")
        for w in reversed(new):   # от старых к новым
            print(f"Отправляю заказ ID: {w.get('id')} - {w.get('name')}")
            send(fmt(w))
            time.sleep(1)
    else:
        print("Первый запуск: пропускаем отправку.")


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