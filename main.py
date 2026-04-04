import os
import requests
from bs4 import BeautifulSoup
import time
import random
import re
from supabase import create_client, Client

# --- НАСТРОЙКИ (Берутся из GitHub Secrets) ---
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

FUNNY_PHRASES = [
    "🕵️‍♂️ Пссс, парень, хату нннада?",
    "🔥 Опа! Кажется, кто-то выставил сочную хату!",
    "🚀 Бро, бросай всё! Нашел жилье!",
    "👀 Глянь, че нашел!",
    "💎 Нашел настоящий алмаз!",
    "⚡️ ВНИМАНИЕ! Детектор цен сработал!"
]

def write_log(message):
    """Замена логирования Tkinter на консольный вывод"""
    timestamp = time.strftime("%H:%M:%S")
    print(f"[{timestamp}] {message}")

def sync_users():
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
        response = requests.get(url, params={"limit": 100}, timeout=15).json()
        if response.get("ok"):
            updates = response.get("result", [])
            if not updates: return
            user_settings = {}
            for update in updates:
                if "message" in update:
                    chat_id = str(update["message"]["chat"]["id"])
                    text = update.get("message", {}).get("text", "").strip()
                    if chat_id not in user_settings:
                        user_settings[chat_id] = {"rooms": None, "price": None, "start": False}
                    if text == "/start": user_settings[chat_id]["start"] = True
                    elif text in ["/1", "/2", "/3", "/all"]: user_settings[chat_id]["rooms"] = text.replace("/", "")
                    elif text.startswith("/price"):
                        pm = re.search(r'\d+', text)
                        if pm: user_settings[chat_id]["price"] = int(pm.group())
            
            for chat_id, data in user_settings.items():
                if data["start"]: supabase.table("users").upsert({"chat_id": chat_id, "price_limit": 0}).execute()
                if data["rooms"]: supabase.table("users").update({"rooms_filter": data["rooms"]}).eq("chat_id", chat_id).execute()
                if data["price"]: supabase.table("users").update({"price_limit": data["price"]}).eq("chat_id", chat_id).execute()
            
            last_id = updates[-1]["update_id"]
            requests.get(url, params={"offset": last_id + 1})
    except Exception as e:
        write_log(f"Ошибка синхронизации: {e}")

def send_message(chat_id, ad):
    intro = random.choice(FUNNY_PHRASES)
    p_display = f"{ad['price']}" + (f" (~{ad['price_usd']})" if ad.get('price_usd') else "")

    def h_esc(text):
        return text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

    message = (
        f"<b>{h_esc(intro)}</b>\n\n"
        f"⭐ <b>Рейтинг выгоды: {ad['interest']}/5</b>\n"
        f"───────────────────\n"
        f"💰 <b>Цена:</b> {h_esc(p_display)}\n"
        f"🏠 <b>Комнат:</b> {h_esc(ad['rooms'])}\n"
        f"📍 <b>Адрес:</b> {h_esc(ad['address'])}\n"
        f"───────────────────\n\n"
        f"🔗 <a href='{ad['url']}'>ОТКРЫТЬ НА KUFAR</a>"
    )
    
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": message, "parse_mode": "HTML"}
    try: 
        time.sleep(0.5) 
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code == 200:
            write_log(f"[{chat_id}] Отправлено: {ad['url']}")
    except: pass

def process_notifications(ad, users_list):
    rm = re.search(r'\d+', ad['rooms'])
    ad_rooms_count = int(rm.group()) if rm else 1
    if "студ" in ad['rooms'].lower(): ad_rooms_count = 1
    ad_rooms_count = max(ad_rooms_count, 1)

    usd_clean = ad['price_usd'].split('.')[0] 
    usd_val = int(re.sub(r'[^\d]', '', usd_clean)) if usd_clean else 0
    price_per_room = usd_val / ad_rooms_count

    for user in users_list:
        chat_id = user.get('chat_id')
        user_limit = user.get('price_limit', 0)
        user_rooms_filter = str(user.get('rooms_filter', 'all'))

        rooms_ok = (user_rooms_filter == 'all') or (user_rooms_filter == str(ad_rooms_count))
        price_ok = (user_limit == 0) or (price_per_room <= user_limit)

        if rooms_ok and price_ok:
            send_message(chat_id, ad)
        elif rooms_ok and not price_ok:
            write_log(f"DEBUG: {chat_id} пропустил {ad['url']} (Цена {price_per_room} > {user_limit})")

def calculate_interest(price_str, rooms_str):
    try:
        if "договорная" in price_str.lower(): return 1
        p_num = re.sub(r'[^\d]', '', price_str)
        if not p_num: return 1
        price = float(p_num)
        r_match = re.search(r'\d+', rooms_str)
        rooms = max(int(r_match.group()) if r_match else 1, 1)
        ratio = price / rooms
        if ratio <= 200: return 5
        if ratio <= 300: return 4
        if ratio <= 400: return 3
        if ratio <= 500: return 2
        return 1
    except: return 1

def run_parser():
    write_log("🚀 Старт парсинга...")
    sync_users()
    try:
        res_users = supabase.table("users").select("*").execute()
        raw_data = res_users.data if res_users.data else []
        active_users = list({str(u['chat_id']): u for u in raw_data}.values())
    except Exception as e:
        write_log(f"Ошибка получения юзеров: {e}")
        active_users = []

    base_url = "https://re.kufar.by"
    current_url = "https://re.kufar.by/l/minsk/snyat/kvartiru?cur=BYR"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    
    # Для GitHub Actions ставим фиксированную глубину (например, 5 страниц)
    page_limit = 5 
    
    try:
        res_ads = supabase.table("ads").select("url").execute()
        existing_urls = {item['url'] for item in res_ads.data}
    except: 
        existing_urls = set()

    new_ads_collected = []
    seen_locally = set()

    for page_num in range(1, page_limit + 1):
        write_log(f"Сканирую страницу {page_num}...")
        try:
            response = requests.get(current_url, headers=headers, timeout=15)
            if response.status_code != 200: break
            soup = BeautifulSoup(response.text, 'html.parser')
            listings = soup.find_all('section')

            for ad_node in listings:
                link_tag = ad_node.find('a', href=True)
                if not link_tag: continue
                url = link_tag['href'].split('?')[0]
                if url.startswith('/'): url = base_url + url
                
                if not url or url in existing_urls or url in seen_locally: 
                    continue

                price_tag = ad_node.find('span', class_=lambda x: x and 'price__byr' in x)
                price_usd_tag = ad_node.find('span', class_=lambda x: x and 'price__usd' in x)
                params_tag = ad_node.find('div', class_=lambda x: x and 'parameters' in x)
                address_tag = ad_node.find('span', class_=lambda x: x and 'address' in x)

                p_raw = price_tag.get_text(strip=True).replace('\xa0', ' ') if price_tag else "Договорная"
                p_usd = price_usd_tag.get_text(strip=True).replace('\xa0', ' ').replace('*', '').strip() if price_usd_tag else ""
                r_raw = params_tag.get_text(strip=True).split(',')[0] if params_tag else "1 комн."
                addr = address_tag.get_text(strip=True) if address_tag else "Минск"

                interest = calculate_interest(p_raw, r_raw)
                ad_data = {"rooms": r_raw, "price": p_raw, "price_usd": p_usd, "address": addr, "url": url, "interest": interest}

                if active_users:
                    process_notifications(ad_data, active_users)

                new_ads_collected.append(ad_data)
                seen_locally.add(url)

            next_link = soup.find('a', {'data-testid': 'realty-pagination-next-link'})
            if next_link and next_link.get('href'):
                current_url = base_url + next_link['href']
                time.sleep(2)
            else: break
        except Exception as e:
            write_log(f"Ошибка на странице {page_num}: {e}")
            break

    if new_ads_collected:
        try:
            supabase.table("ads").upsert(new_ads_collected, on_conflict="url").execute()
            write_log(f"✅ Обработано объявлений: {len(new_ads_collected)}")
        except Exception as e:
            write_log(f"Ошибка записи БД: {e}")
    else:
        write_log("Ничего нового.")

if __name__ == "__main__":
    run_parser()
