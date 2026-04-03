import os
import requests
from bs4 import BeautifulSoup
import time
import random
import re
from supabase import create_client, Client

# --- НАСТРОЙКИ (Берутся из Secrets GitHub) ---
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

FUNNY_PHRASES = [
    "🕵️‍♂️ Пссс, парень, хату нннада? Тут нашлось выгодное предложение!",
    "🔥 Опа! Кажется, кто-то выставил сочную хату! Беги смотреть, пока не увели!",
    "🚀 Бро, бросай всё! Мои датчики зафиксировали аномально дешевое жилье!",
    "👀 Глянь, че нашел! Похоже, это тот самый 'бабушатник' твоей мечты (или нет)!",
    "💎 Нашел настоящий алмаз в куче объявлений! Срочно чекай:",
    "⚡️ ВНИМАНИЕ! Детектор выгодных цен сработал!"
]

def sync_users():
    """Синхронизация настроек пользователей из Telegram"""
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
        response = requests.get(url, params={"limit": 100}, timeout=15).json()
        if response.get("ok"):
            updates = response.get("result", [])
            if not updates: return
            
            for update in updates:
                if "message" in update:
                    chat_id = str(update["message"]["chat"]["id"])
                    text = update.get("message", {}).get("text", "").strip()
                    
                    if text == "/start":
                        supabase.table("users").upsert({"chat_id": chat_id, "price_limit": 0, "rooms_filter": "all"}).execute()
                    elif text in ["/1", "/2", "/3", "/all"]:
                        val = text.replace("/", "")
                        supabase.table("users").update({"rooms_filter": val}).eq("chat_id", chat_id).execute()
                    elif text.startswith("/price"):
                        pm = re.search(r'\d+', text)
                        if pm:
                            price_val = int(pm.group())
                            supabase.table("users").update({"price_limit": price_val}).eq("chat_id", chat_id).execute()
            
            last_id = updates[-1]["update_id"]
            requests.get(url, params={"offset": last_id + 1})
    except Exception as e:
        print(f"Ошибка синхронизации: {e}")

def calculate_interest(price_str, rooms_str):
    try:
        if "договорная" in price_str.lower(): return 1
        p_num = re.sub(r'[^\d]', '', price_str)
        if not p_num: return 1
        price = float(p_num)
        r_match = re.search(r'\d+', rooms_str)
        rooms = int(r_match.group()) if r_match else 1
        if rooms == 0: rooms = 1
        ratio = price / rooms
        if ratio <= 200: return 5
        if ratio <= 300: return 4
        if ratio <= 400: return 3
        if ratio <= 500: return 2
        return 1
    except: return 1

def send_notifications(ad):
    """Отправка уведомлений с учетом фильтров по комнатам и цене за комнату (USD)"""
    rm = re.search(r'\d+', ad['rooms'])
    ad_rooms_count = int(rm.group()) if rm else 1
    if "студ" in ad['rooms'].lower(): ad_rooms_count = 1
    if ad_rooms_count == 0: ad_rooms_count = 1

    usd_clean = re.sub(r'[^\d]', '', ad['price_usd'])
    price_per_room = int(usd_clean) / ad_rooms_count if usd_clean else 0

    try:
        res = supabase.table("users").select("chat_id", "price_limit", "rooms_filter").execute()
        
        for user in res.data:
            # Проверка фильтра комнат
            rf = user.get('rooms_filter', 'all')
            if rf != 'all' and rf != str(ad_rooms_count):
                continue
            
            # Проверка лимита цены (если лимит установлен > 0)
            user_limit = user.get('price_limit', 0)
            if user_limit > 0:
                if price_per_room == 0 or price_per_room > user_limit:
                    continue
            
            # Если все проверки прошли — отправляем
            intro = random.choice(FUNNY_PHRASES)
            p_display = f"{ad['price']}" + (f" (~{ad['price_usd']})" if ad.get('price_usd') else "")
            
            message = (
                f"{intro}\n\n"
                f"⭐ *Рейтинг выгоды: {ad['interest']}/5*\n"
                f"───────────────────\n"
                f"💰 *Цена:* {p_display}\n"
                f"🏠 *Комнат:* {ad['rooms']}\n"
                f"📍 *Адрес:* {ad['address']}\n"
                f"───────────────────\n\n"
                f"🔗 [ОТКРЫТЬ НА KUFAR]({ad['url']})"
            )
            
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
            requests.post(url, json={
                "chat_id": user['chat_id'], 
                "text": message, 
                "parse_mode": "Markdown"
            }, timeout=10)
    except Exception as e:
        print(f"Ошибка отправки: {e}")

def run_parser():
    print("--- СТАРТ ПАРСИНГА ---")
    sync_users()
    
    base_url = "https://re.kufar.by"
    current_url = "https://re.kufar.by/l/minsk/snyat/kvartiru?cur=BYR"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    
    # В GitHub Actions лучше проверять 5-8 страниц за раз
    PAGE_LIMIT = 8 
    
    try:
        res = supabase.table("ads").select("url").execute()
        existing_urls = {item['url'] for item in res.data}
    except: existing_urls = set()

    new_ads_collected = []
    seen_locally = set()

    for page_num in range(1, PAGE_LIMIT + 1):
        print(f"Сканирую страницу {page_num}...")
        try:
            response = requests.get(current_url, headers=headers, timeout=15)
            soup = BeautifulSoup(response.text, 'html.parser')
            listings = soup.find_all('section')

            if not listings: break

            for ad in listings:
                link_tag = ad.find('a', href=True)
                url = link_tag['href'].split('?')[0] if link_tag else ""
                if url.startswith('/'): url = base_url + url
                if not url or url in existing_urls or url in seen_locally: continue

                price_tag = ad.find('span', class_=lambda x: x and 'price__byr' in x)
                price_usd_tag = ad.find('span', class_=lambda x: x and 'price__usd' in x)
                price_raw = price_tag.text.replace('\xa0', ' ').strip() if price_tag else "Договорная"
                price_usd = price_usd_tag.text.replace('\xa0', ' ').replace('*', '').strip() if price_usd_tag else ""
                
                params_tag = ad.find('div', class_=lambda x: x and 'parameters' in x)
                rooms_raw = params_tag.text.split(',')[0].strip() if params_tag else "1 комн."
                address_tag = ad.find('span', class_=lambda x: x and 'address' in x)
                address = address_tag.text.strip() if address_tag else "Минск"

                interest = calculate_interest(price_raw, rooms_raw)
                ad_data = {
                    "rooms": rooms_raw, "price": price_raw, "price_usd": price_usd, 
                    "address": address, "url": url, "interest": interest
                }

                # Уведомляем пользователей
                send_notifications(ad_data)
                
                new_ads_collected.append(ad_data)
                seen_locally.add(url)

            next_link = soup.find('a', {'data-testid': 'realty-pagination-next-link'})
            if next_link:
                current_url = base_url + next_link['href']
                time.sleep(random.uniform(1, 2))
            else: break
        except Exception as e:
            print(f"Ошибка на странице {page_num}: {e}")
            break

    if new_ads_collected:
        try:
            supabase.table("ads").upsert(new_ads_collected, on_conflict="url").execute()
            print(f"✅ Успешно добавлено объявлений: {len(new_ads_collected)}")
        except Exception as e:
            print(f"Ошибка записи в БД: {e}")
    else:
        print("Ничего нового не найдено.")

if __name__ == "__main__":
    run_parser()
