import os
import requests
from bs4 import BeautifulSoup
import time
import random
from supabase import create_client, Client

SUPABASE_URL =  os.environ.get("SUPABASE_URL")
SUPABASE_KEY =  os.environ.get("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("Необходимо установить SUPABASE_URL и SUPABASE_KEY в секретах GitHub!")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
def get_existing_urls():
    """Получает список всех URL из базы, чтобы не добавлять дубликаты"""
    try:
        # Запрашиваем только колонку url
        response = supabase.table("ads").select("url").execute()
        return {item['url'] for item in response.data}
    except Exception as e:
        print(f"Ошибка при получении данных из БД: {e}")
        return set()

def scrape_to_supabase(max_pages=5):
    base_url = "https://re.kufar.by"
    current_url = "https://re.kufar.by/l/minsk/snyat/kvartiru?cur=BYR"

    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}

    # 1. Получаем список того, что уже есть в базе
    existing_urls = get_existing_urls()
    print(f"В базе уже есть {len(existing_urls)} объявлений.")

    new_ads_to_insert = []
    seen_locally = set() # Чтобы не дублировать внутри одного запуска

    for page_num in range(1, max_pages + 1):
        print(f"Сканируем страницу {page_num}...")
        try:
            response = requests.get(current_url, headers=headers, timeout=10)
            soup = BeautifulSoup(response.text, 'html.parser')
            listings = soup.find_all('section')

            print(response.status_code)

            added_on_page = 0
            for ad in listings:
                link_tag = ad.find('a', href=True)
                url = link_tag['href'].split('?')[0] if link_tag else ""
                if url.startswith('/'): url = base_url + url

                # ПРОВЕРКА: Если ссылка пустая, уже есть в БД или уже найдена на этой странице - пропускаем
                if not url or url in existing_urls or url in seen_locally:
                    continue

                # Собираем данные
                price_tag = ad.find('span', class_=lambda x: x and 'price__byr' in x)
                price = price_tag.text.replace('\xa0', ' ').strip() if price_tag else "Договорная"

                params_tag = ad.find('div', class_=lambda x: x and 'parameters' in x)
                rooms = params_tag.text.split(',')[0].strip() if params_tag else "Не указано"

                address_tag = ad.find('span', class_=lambda x: x and 'address' in x)
                address = address_tag.text.strip() if address_tag else "Нет адреса"

                # Добавляем в список для вставки
                new_ads_to_insert.append({
                    "rooms": rooms,
                    "price": price,
                    "address": address,
                    "url": url,
                    "interest": 1,   # Значение по умолчанию
                    "comment": ""    # Пустое поле
                })

                seen_locally.add(url)
                added_on_page += 1

            print(f"Найдено новых на странице: {added_on_page}")

            # Ищем ссылку на следующую страницу
            next_link = soup.find('a', {'data-testid': 'realty-pagination-next-link'})
            if next_link:
                current_url = base_url + next_link['href']
                time.sleep(random.uniform(1.5, 3))
            else:
                break

        except Exception as e:
            print(f"Ошибка при парсинге страницы {page_num}: {e}")
            break

    # 2. Отправляем всё новое в Supabase одним батчем (пачкой)
    if new_ads_to_insert:
        print(f"\nОтправка {len(new_ads_to_insert)} новых записей в базу...")
        try:
            result = supabase.table("ads").insert(new_ads_to_insert).execute()
            print("Успешно! База обновлена.")
        except Exception as e:
            print(f"Ошибка при вставке в БД: {e}")
    else:
        print("\nНовых объявлений не найдено. База в актуальном состоянии.")

# ЗАПУСК: укажите сколько страниц проверять
scrape_to_supabase(max_pages=11)