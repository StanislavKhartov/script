import os
import requests
from bs4 import BeautifulSoup
import time
import random
import re
from supabase import create_client, Client

# --- НАСТРОЙКИ ---
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
    "⚡️ ВНИМАНИЕ! Детектор выгодных цен сработал! Кто-то явно ошибся кнопкой при вводе цены!"
]

def sync_users():
    """Синхронизация пользователей и их фильтров (без ответных сообщений)"""
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
        response = requests.get(url, timeout=10).json()
        if response.get("ok"):
            for update in response.get("result", []):
                if "message" in update:
                    chat_id = str(update["message"]["chat"]["id"])
                    text = update.get("message", {}).get("text", "")
                    
                    if text == "/start":
                        # При старте создаем пользователя
                        supabase.table("users").upsert({"chat_id": chat_id, "rooms_filter": "all"}).execute()
                    elif text in ["/1", "/2", "/3", "/all"]:
                        # Просто обновляем базу данных без ответа пользователю
                        filter_val = text.replace("/", "")
                        supabase.table("users").update({"rooms_filter": filter_val}).eq("chat_id", chat_id).execute()
    except Exception as e:
        print(f"Ошибка синхронизации пользователей: {e}")

def send_telegram_notifications(ad):
    """Отправка уведомлений согласно фильтрам"""
    ad_rooms_digit = re.search(r'\d+', ad['rooms'])
    ad_rooms_val = ad_rooms_digit.group() if ad_rooms_digit else "1"
    if "студ" in ad['rooms'].lower(): ad_rooms_val = "1"

    try:
        response = supabase.table("users").select("chat_id").or_(f"rooms_filter.eq.all,rooms_filter.eq.{ad_rooms_val}").execute()
        subscribers = [item['chat_id'] for item in response.data]
    except Exception as e:
        print(f"Ошибка фильтрации подписчиков: {e}")
        return

    if not subscribers: return
    intro = random.choice(FUNNY_PHRASES)
    
    price_display = f"{ad['price']}"
    if ad.get('price_usd'):
        price_display += f" (~{ad['price_usd']})"

    message = (
        f"{intro}\n\n"
        f"⭐ *Рейтинг выгоды: {ad['interest']}/5*\n"
        f"───────────────────\n"
        f"💰 *Цена:* {price_display}\n"
        f"🏠 *Комнат:* {ad['rooms']}\n"
        f"📍 *Адрес:* {ad['address']}\n"
        f"───────────────────\n\n"
        f"🔗 [СКОРЕЕ ЖМИ СЮДА, ПОКА НЕ ЗАБРАЛИ]({ad['url']})"
    )
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    for chat_id in subscribers:
        try:
            requests.post(url, json={"chat_id": chat_id, "text": message, "parse_mode": "Markdown", "disable_web_page_preview": False}, timeout=10)
        except: pass

def calculate_interest(price_str, rooms_str):
    try:
        if "договорная" in price_str.lower(): return 1
        p = price_str.replace('\xa0', '').replace(' ', '').replace(',', '.')
        match = re.search(r'(\d+\.?\d*)', p)
        if not match: return 1
        price = float(match.group(1))
        if "студ" in rooms_str.lower():
            rooms = 1
        else:
            rooms_match = re.search(r'\d+', rooms_str)
            rooms = int(rooms_match.group()) if rooms_match else 1
        if rooms <= 0: rooms = 1
        ratio = price / rooms
        if ratio <= 200: return 5
        if ratio <= 300: return 4
        if ratio <= 400: return 3
        if ratio <= 500: return 2
        return 1
    except: return 1

def run_parser():
    sync_users()
    base_url = "https://re.kufar.by"
    current_url = "https://re.kufar.by/l/minsk/snyat/kvartiru?cur=BYR"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
    
    page_limit = 10
    
    try:
        response = supabase.table("ads").select("url").execute()
        existing_urls = {item['url'] for item in response.data}
    except: existing_urls = set()

    new_ads_to_insert = []
    seen_locally = set()

    for page_num in range(1, page_limit + 1):
        print(f"Сканирую страницу {page_num}...")
        try:
            response = requests.get(current_url, headers=headers, timeout=15)
            soup = BeautifulSoup(response.text, 'html.parser')
            listings = soup.find_all('section')

            for ad in listings:
                link_tag = ad.find('a', href=True)
                url = link_tag['href'].split('?')[0] if link_tag else ""
                if url.startswith('/'): url = base_url + url
                if not url or url in existing_urls or url in seen_locally: continue

                price_tag = ad.find('span', class_=lambda x: x and 'price__byr' in x)
                price_usd_tag = ad.find('span', class_=lambda x: x and 'price__usd' in x)
                
                price_raw = price_tag.get_text(strip=True).replace('\xa0', ' ') if price_tag else "Договорная"
                price_usd = ""
                if price_usd_tag:
                    price_usd = price_usd_tag.get_text(strip=True).replace('\xa0', ' ').replace('*', '').strip()

                params_tag = ad.find('div', class_=lambda x: x and 'parameters' in x)
                rooms_raw = params_tag.text.split(',')[0].strip() if params_tag else "1 комн."
                address_tag = ad.find('span', class_=lambda x: x and 'address' in x)
                address = address_tag.text.strip() if address_tag else "Минск"

                interest_level = calculate_interest(price_raw, rooms_raw)
                
                ad_data = {
                    "rooms": rooms_raw, 
                    "price": price_raw, 
                    "price_usd": price_usd,
                    "address": address, 
                    "url": url, 
                    "interest": interest_level, 
                    "comment": f"Авто-оценка: {interest_level}"
                }

                if interest_level >= 3:
                    print(f"🎯 Выгодное объявление ({interest_level}*)! Маякую в ТГ...")
                    send_telegram_notifications(ad_data)

                new_ads_to_insert.append(ad_data)
                seen_locally.add(url)

            next_link = soup.find('a', {'data-testid': 'realty-pagination-next-link'})
            if next_link:
                current_url = base_url + next_link['href']
                time.sleep(random.uniform(1, 2))
            else: break
        except Exception as e:
            print(f"Ошибка: {e}")
            break

    if new_ads_to_insert:
        try:
            supabase.table("ads").insert(new_ads_to_insert).execute()
            print(f"✅ Добавлено новых: {len(new_ads_to_insert)}")
        except Exception as e: 
            print(f"Ошибка записи: {e}")
    else:
        print("Нового ничего нет.")

if __name__ == "__main__":
    run_parser()
