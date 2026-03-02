#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════╗
║         SSR / Cloaking Checker  +  Visual Comparison            ║
║                                                                  ║
║  Как работает:                                                   ║
║   1. Вводите URL                                                 ║
║   2. Playwright загружает страницу КАК БОТ автоматически        ║
║   3. Вы вставляете HTML КАК ПОЛЬЗОВАТЕЛЬ (скопировав в браузере) ║
║   4. Программа сравнивает и строит отчёт                        ║
╚══════════════════════════════════════════════════════════════════╝
"""

import os
import sys
import time
import json
import hashlib
import re
import glob
import threading
import webbrowser
import http.server
import socketserver
from collections import Counter
from difflib import SequenceMatcher

try:
    import readline
except ImportError:
    pass

from dotenv import load_dotenv
from bs4 import BeautifulSoup

load_dotenv()

# ═══════════════════════════════════════════════════════════════
# НАСТРОЙКИ
# ═══════════════════════════════════════════════════════════════

DEFAULTS = {
    "BOT_MODE":             os.getenv("BOT_MODE",             "google_smartphone"),
    "ANTIBOT_HEADER_NAME":  os.getenv("ANTIBOT_HEADER_NAME",  ""),
    "ANTIBOT_HEADER_VALUE": os.getenv("ANTIBOT_HEADER_VALUE", ""),
    "GOTO_TIMEOUT":         int(os.getenv("GOTO_TIMEOUT",     "60000")),
    "SELECTOR_TIMEOUT":     int(os.getenv("SELECTOR_TIMEOUT", "15000")),
    "DYNAMIC_EXTRA_SLEEP":  float(os.getenv("DYNAMIC_EXTRA_SLEEP", "3")),
}

DYNAMIC_SELECTORS = [
    '[data-qa="product-card-title"]',
    '[data-qa="cart-button-container"]',
    '[itemprop="price"]',
]

USER_AGENTS = {
    "google_smartphone": (
        "Mozilla/5.0 (Linux; Android 10; Pixel 5) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Mobile Safari/537.36 "
        "(compatible; Googlebot/2.1; +http://www.google.com/bot.html)"
    ),
    "google_desktop": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36 "
        "(compatible; Googlebot/2.1; +http://www.google.com/bot.html)"
    ),
    "chrome_desktop": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "chrome_mobile": (
        "Mozilla/5.0 (Linux; Android 10; Pixel 5) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Mobile Safari/537.36"
    ),
    "fake_bot": (
        "Mozilla/5.0 (compatible; AhrefsBot/7.0; +http://ahrefs.com/robot)"
    ),
}

SKIP_TAGS = {
    'script','style','link','meta','noscript','head',
    'next-route-announcer','svg','path','circle','rect',
    'defs','g','use','polyline','polygon','line','title',
    'stop','lineargradient','radialgradient','filter','clippath',
}

ELEMENT_GROUPS = {
    "🗂 Layout":     ["div","section","article","main","aside","header","footer","nav","figure","figcaption"],
    "✍️ Text":        ["p","span","h1","h2","h3","h4","h5","h6","strong","em","b","i","label","blockquote","pre","code","small","sup","sub"],
    "🖼 Media":       ["img","video","audio","picture","source","iframe","canvas","object","embed"],
    "🖱 Interactive": ["button","a","input","select","textarea","form","fieldset","legend","option","optgroup"],
    "📜 Meta/Head":   ["script","style","link","meta","noscript","title","base"],
    "🔷 SVG":         ["svg","path","circle","rect","g","use","defs","polyline","polygon","line","text","tspan","clippath","mask","symbol","ellipse"],
    "📋 Lists":       ["ul","ol","li","dl","dt","dd"],
    "📊 Table":       ["table","thead","tbody","tfoot","tr","th","td","caption","col","colgroup"],
}

url_history: list[str] = []


# ═══════════════════════════════════════════════════════════════
# UI-ПОМОЩНИКИ
# ═══════════════════════════════════════════════════════════════

def line(char="═", n=64):
    print(char * n)

def section(title: str):
    line()
    print(f"  {title}")
    line()

def inp(prompt: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    try:
        v = input(f"  {prompt}{suffix}: ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        raise
    return v or default

def yn(prompt: str, default: bool = True) -> bool:
    hint = "Y/n" if default else "y/N"
    try:
        v = input(f"  {prompt} [{hint}]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        raise
    return (v in ("y", "yes", "да", "д")) if v else default

def add_to_history(url: str):
    if url and url not in url_history:
        url_history.insert(0, url)
        del url_history[50:]


# ═══════════════════════════════════════════════════════════════
# ВВОД URL
# ═══════════════════════════════════════════════════════════════

def prompt_url(current: str = "") -> str:
    print()
    line("─")
    print("  🌐  Введите URL для проверки")
    line("─")

    if url_history:
        print("  Недавние URL:")
        for i, u in enumerate(url_history, 1):
            mark = "  ◀ активный" if u == current else ""
            print(f"    {i:>2}. {u}{mark}")
        print()

    hint = "Номер из истории или новый URL"
    if current:
        hint += " (Enter — оставить текущий)"

    while True:
        try:
            raw = input(f"  {hint}: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return current

        if not raw:
            if current:
                print(f"  ↩  Оставляем: {current}")
                return current
            print("  ⚠  Введите URL или номер из истории")
            continue

        if raw.isdigit():
            idx = int(raw) - 1
            if 0 <= idx < len(url_history):
                chosen = url_history[idx]
                print(f"  ✅ Выбран: {chosen}")
                return chosen
            print(f"  ⚠  Нет пункта #{raw}")
            continue

        if not raw.startswith(("http://", "https://")):
            raw = "https://" + raw
            print(f"  ℹ  Добавлен протокол → {raw}")

        return raw


# ═══════════════════════════════════════════════════════════════
# МЕНЮ НАСТРОЕК
# ═══════════════════════════════════════════════════════════════

def settings_menu(cfg: dict) -> dict:
    while True:
        section("⚙  Настройки")
        hv = f": {cfg['ANTIBOT_HEADER_VALUE'][:30]}…" if cfg['ANTIBOT_HEADER_VALUE'] else ""
        print(f"    1. Bot Mode         : {cfg['BOT_MODE']}")
        print(f"    2. AntiBot Header   : {cfg['ANTIBOT_HEADER_NAME'] or '—'}{hv}")
        print(f"    3. GOTO timeout     : {cfg['GOTO_TIMEOUT']} мс")
        print(f"    4. Selector timeout : {cfg['SELECTOR_TIMEOUT']} мс")
        print(f"    5. Extra sleep      : {cfg['DYNAMIC_EXTRA_SLEEP']} с")
        print(f"    0. ← Назад")
        line("─")

        ch = inp("Что изменить", "0")

        if ch == "0":
            break
        elif ch == "1":
            modes = list(USER_AGENTS.keys())
            print("\n  Режимы бота:")
            for i, m in enumerate(modes, 1):
                mark = " ◀" if m == cfg["BOT_MODE"] else ""
                print(f"    {i}. {m}{mark}")
            sel = inp("Номер или название", cfg["BOT_MODE"])
            if sel.isdigit():
                i = int(sel) - 1
                if 0 <= i < len(modes):
                    cfg["BOT_MODE"] = modes[i]
            elif sel in USER_AGENTS:
                cfg["BOT_MODE"] = sel
            else:
                print("  ⚠  Неизвестный режим")
        elif ch == "2":
            cfg["ANTIBOT_HEADER_NAME"]  = inp("Имя заголовка",      cfg["ANTIBOT_HEADER_NAME"])
            cfg["ANTIBOT_HEADER_VALUE"] = inp("Значение заголовка",  cfg["ANTIBOT_HEADER_VALUE"])
        elif ch == "3":
            raw = inp("GOTO timeout (мс)", str(cfg["GOTO_TIMEOUT"]))
            try:    cfg["GOTO_TIMEOUT"] = int(raw)
            except: print("  ⚠  Нужно целое число")
        elif ch == "4":
            raw = inp("Selector timeout (мс)", str(cfg["SELECTOR_TIMEOUT"]))
            try:    cfg["SELECTOR_TIMEOUT"] = int(raw)
            except: print("  ⚠  Нужно целое число")
        elif ch == "5":
            raw = inp("Extra sleep (сек)", str(cfg["DYNAMIC_EXTRA_SLEEP"]))
            try:    cfg["DYNAMIC_EXTRA_SLEEP"] = float(raw)
            except: print("  ⚠  Нужно число")
        else:
            print("  ⚠  Неизвестный пункт")

    return cfg


# ═══════════════════════════════════════════════════════════════
# ЗАГРУЗКА СТРАНИЦЫ ЧЕРЕЗ PLAYWRIGHT (BOT — автоматически)
# ═══════════════════════════════════════════════════════════════

def fetch_bot_html(url: str, cfg: dict) -> tuple[str, str]:
    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
    except ImportError:
        print("  ❌ playwright не установлен.")
        print("     Установите: pip install playwright && playwright install chromium")
        return "", ""

    bot_mode = cfg["BOT_MODE"]
    bot_ua   = USER_AGENTS.get(bot_mode)
    if not bot_ua:
        print(f"  ❌ Неизвестный BOT_MODE: {bot_mode}")
        return "", ""

    extra = {}
    if cfg["ANTIBOT_HEADER_NAME"] and cfg["ANTIBOT_HEADER_VALUE"]:
        extra[cfg["ANTIBOT_HEADER_NAME"]] = cfg["ANTIBOT_HEADER_VALUE"]

    is_mobile = "smartphone" in bot_mode or "mobile" in bot_mode

    print(f"\n  🤖 Загружаю страницу как БОТ ({bot_mode})…")
    print(f"     UA: {bot_ua[:80]}…")
    if extra:
        print(f"     Доп. заголовки: {list(extra.keys())}")

    html = ""
    with sync_playwright() as pw:
        browser = None
        try:
            browser = pw.chromium.launch(
                headless=True,
                args=["--disable-blink-features=AutomationControlled"],
            )
            ctx = browser.new_context(
                user_agent=bot_ua,
                locale="ru-RU",
                viewport={"width": 390, "height": 844} if is_mobile
                         else {"width": 1920, "height": 1080},
                extra_http_headers=extra,
            )
            page = ctx.new_page()

            def on_request(req):
                if req.url == url:
                    for key in extra:
                        present = key.lower() in {h.lower() for h in req.headers}
                        print(f"     {'✅' if present else '❌'} Заголовок '{key}' передан")

            page.on("request", on_request)

            print(f"  ⏳ Открываю страницу (timeout={cfg['GOTO_TIMEOUT']} мс)…")
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=cfg["GOTO_TIMEOUT"])
                print("  ✅ DOM загружен")
            except PlaywrightTimeoutError:
                print("  ⚠  Таймаут — продолжаем")
            except Exception as e:
                print(f"  ⚠  {e} — продолжаем")

            print(f"  ⏳ Жду динамические элементы (timeout={cfg['SELECTOR_TIMEOUT']} мс)…")
            found = 0
            for sel in DYNAMIC_SELECTORS:
                try:
                    page.wait_for_selector(sel, timeout=cfg["SELECTOR_TIMEOUT"])
                    print(f"  ✅ {sel}")
                    found += 1
                except PlaywrightTimeoutError:
                    print(f"  ⚠  Не найден: {sel}")
                except Exception as e:
                    print(f"  ⚠  {e}")
            print(f"  {'✅' if found else '⚠ '} Гидратация: {found}/{len(DYNAMIC_SELECTORS)}")

            print(f"  ⏳ Пауза {cfg['DYNAMIC_EXTRA_SLEEP']} с…")
            time.sleep(cfg["DYNAMIC_EXTRA_SLEEP"])

            try:
                page.wait_for_load_state("networkidle", timeout=15_000)
                print("  ✅ Network idle")
            except PlaywrightTimeoutError:
                print("  ⚠  Networkidle таймаут")
            except Exception as e:
                print(f"  ⚠  {e}")

            html = page.content()
            ctx.close()

        except Exception as e:
            print(f"  ❌ Критическая ошибка Playwright: {e}")
        finally:
            if browser:
                try: browser.close()
                except: pass

    if html:
        print(f"  ✅ HTML бота получен  ({len(html.encode())/1024:.1f} KB)")
    else:
        print("  ❌ Не удалось получить HTML бота")

    return html, bot_mode


# ═══════════════════════════════════════════════════════════════
# РУЧНОЙ ВВОД HTML ПОЛЬЗОВАТЕЛЯ
# ═══════════════════════════════════════════════════════════════

def read_user_html(url: str, user_mode: str) -> str:
    """
    Просит пользователя вставить HTML из браузера.
    Ввод завершается пустой строкой после последней строки HTML.
    """
    line("─")
    print(f"\n  👤 Теперь нужен HTML ГЛАЗАМИ ПОЛЬЗОВАТЕЛЯ")
    line("─")
    print()
    print(f"  Откройте в обычном браузере: {url}")
    print()
    print("  ┌─ Как скопировать HTML ──────────────────────────────────┐")
    print("  │                                                          │")
    print("  │  Способ 1 — исходный код (до JS, быстрее):              │")
    print("  │    Ctrl+U  →  Ctrl+A  →  Ctrl+C                         │")
    print("  │                                                          │")
    print("  │  Способ 2 — DOM после JS (точнее):                      │")
    print("  │    F12  →  Elements  →  правый клик на <html>           │")
    print("  │    →  Copy  →  Copy outerHTML                           │")
    print("  │                                                          │")
    print("  └──────────────────────────────────────────────────────────┘")
    print()
    print("  Вставьте HTML сюда и нажмите Enter на пустой строке:")
    print()

    lines = []
    try:
        while True:
            row = input()
            if row == "" and lines:
                break
            lines.append(row)
    except EOFError:
        pass
    except KeyboardInterrupt:
        print("\n  ⏹  Отменено")
        return ""

    html = "\n".join(lines).strip()

    if not html:
        print("  ⚠  Вы не вставили HTML!")
        return ""

    size_kb = len(html.encode()) / 1024
    print(f"\n  ✅ Получено {len(html):,} симв. ({size_kb:.1f} KB)")

    return html


# ═══════════════════════════════════════════════════════════════
# АНАЛИЗ HTML
# ═══════════════════════════════════════════════════════════════

def get_text_hash(text: str) -> str:
    return hashlib.md5(text.encode("utf-8")).hexdigest()


def extract_content_metrics(soup: BeautifulSoup) -> dict:
    body      = soup.body
    body_text = body.get_text(strip=True) if body else ""

    metrics = {
        "title":             soup.title.string.strip() if soup.title else "",
        "body_text_length":  len(body_text),
        "body_text_hash":    get_text_hash(body_text),
        "h1_count":          len(soup.find_all("h1")),
        "h2_count":          len(soup.find_all("h2")),
        "h3_count":          len(soup.find_all("h3")),
        "p_count":           len(soup.find_all("p")),
        "img_count":         len(soup.find_all("img")),
        "a_count":           len(soup.find_all("a")),
        "json_ld_count":     len(soup.find_all("script", type="application/ld+json")),
        "body_text_preview": body_text[:500],
    }

    desc = soup.find("meta", {"name": "description"})
    metrics["description"] = desc["content"][:160] if desc and desc.get("content") else ""

    canonical = soup.find("link", rel="canonical")
    metrics["canonical"] = canonical["href"] if canonical and canonical.get("href") else ""

    root = soup.find(id=["root", "__next", "app"])
    if root:
        root_text = root.get_text(strip=True)
        metrics["spa_root_found"]       = True
        metrics["spa_root_text_length"] = len(root_text)
        metrics["spa_root_text_hash"]   = get_text_hash(root_text)
    else:
        metrics["spa_root_found"]       = False
        metrics["spa_root_text_length"] = 0
        metrics["spa_root_text_hash"]   = ""

    price_el = soup.find(attrs={"itemprop": "price"})
    metrics["price"] = price_el.get("content", "") if price_el else ""

    sticker_els = soup.find_all(attrs={"data-qa": lambda v: v and "sticker" in v.lower()})
    metrics["stickers"] = [s.get_text(strip=True) for s in sticker_els if s.get_text(strip=True)]

    rating_el = soup.find(attrs={"data-qa": lambda v: v and "rating" in v.lower()})
    metrics["rating"] = rating_el.get_text(strip=True) if rating_el else ""

    review_el = soup.find(attrs={"data-qa": lambda v: v and "review" in v.lower()})
    metrics["reviews"] = review_el.get_text(strip=True) if review_el else ""

    cart_btn = soup.find(attrs={"data-qa": "cart-button-add-button"})
    metrics["cart_button_present"] = bool(cart_btn)

    metrics["loyalty_points"] = ""
    metrics["promo_label"]    = ""
    metrics["stock_limit"]    = ""
    next_data_el = soup.find("script", id="__NEXT_DATA__")
    if next_data_el:
        try:
            nd = json.loads(next_data_el.string)
            ps = nd.get("props", {}).get("pageProps", {}).get("props", {}).get("productStore", "{}")
            if isinstance(ps, str):
                ps = json.loads(ps)
            product = ps.get("product", {})
            metrics["loyalty_points"] = product.get("orange_loyalty_points", "")
            metrics["promo_label"]    = str(product.get("promo", ""))
            metrics["stock_limit"]    = product.get("stock_limit", "")
        except Exception:
            pass

    return metrics


def analyze_html(html: str, label: str):
    if not html:
        print(f"\n  ❌ [{label}]: HTML пуст!")
        return None, None
    try:
        soup = BeautifulSoup(html, "html.parser")
    except Exception as e:
        print(f"\n  ❌ [{label}]: Парсинг не удался — {e}")
        return None, None

    print(f"\n  {'─'*58}")
    print(f"  АНАЛИЗ [{label}]")
    print(f"  {'─'*58}")

    m = extract_content_metrics(soup)

    print(f"  Title      : {m['title']       or '❌ нет'}")
    print(f"  Description: {m['description'] or '❌ нет'}")
    print(f"  Canonical  : {m['canonical']   or '❌ нет'}")
    print(f"  H1:{m['h1_count']}  H2:{m['h2_count']}  H3:{m['h3_count']}  "
          f"P:{m['p_count']}  IMG:{m['img_count']}  A:{m['a_count']}  "
          f"JSON-LD:{m['json_ld_count']}")
    print(f"  Текст body : {m['body_text_length']} симв.")

    if m["spa_root_found"]:
        n   = m["spa_root_text_length"]
        tag = "⚠  CSR (пустой root)" if n < 100 else "✅ SSR / prerender"
        print(f"  SPA root   : {n} симв. → {tag}")
    else:
        print("  SPA root   : не найден")

    print(f"\n  📦 Динамика:")
    print(f"     Цена       : {m['price']          or '—'}")
    print(f"     Лояльность : {m['loyalty_points'] or '—'}")
    print(f"     Промо      : {m['promo_label']    or '—'}")
    print(f"     Остаток    : {m['stock_limit']    or '—'}")
    print(f"     Рейтинг    : {m['rating']         or '—'}")
    print(f"     Отзывы     : {m['reviews']        or '—'}")
    print(f"     Стикеры    : {m['stickers']       or '—'}")
    print(f"     Корзина    : {'✅ найдена' if m['cart_button_present'] else '❌ не найдена'}")

    return soup, m


# ═══════════════════════════════════════════════════════════════
# СРАВНЕНИЕ МЕТРИК
# ═══════════════════════════════════════════════════════════════

def compare_metrics(bm: dict, um: dict) -> bool:
    if not bm or not um:
        print("  ❌ Нет метрик для сравнения")
        return False

    line()
    print("  СРАВНЕНИЕ: БОТ vs ПОЛЬЗОВАТЕЛЬ")
    line()

    try:
        sim = SequenceMatcher(None,
                              bm["body_text_preview"],
                              um["body_text_preview"]).ratio() * 100
    except Exception:
        sim = 0

    print(f"\n  📊 Схожесть текста : {sim:.1f}%")
    if bm["body_text_hash"] == um["body_text_hash"]:
        print("  ✅ Контент ИДЕНТИЧЕН (хеши совпадают)")
    else:
        print("  ⚠  Контент РАЗЛИЧАЕТСЯ")

    bl, ul = bm["body_text_length"], um["body_text_length"]
    diff   = abs(bl - ul)
    pct    = diff / max(bl, ul) * 100 if max(bl, ul) else 0
    print(f"\n  📏 Текст   : бот={bl}  польз.={ul}  Δ={diff} ({pct:.1f}%)")

    print(f"\n  🏗  Структура:")
    for k, lbl in [("h1_count","H1"),("h2_count","H2"),("p_count","P"),
                   ("img_count","IMG"),("a_count","A")]:
        b, u = bm[k], um[k]
        print(f"     {'✅' if b==u else '⚠ '} {lbl}: бот={b}  польз.={u}")

    print(f"\n  📦 Динамика:")
    for k, lbl in [("price","Цена"),("loyalty_points","Лояльность"),
                   ("promo_label","Промо"),("stock_limit","Остаток"),
                   ("rating","Рейтинг"),("reviews","Отзывы"),
                   ("cart_button_present","Корзина")]:
        b, u = bm.get(k,""), um.get(k,"")
        print(f"     {'✅' if b==u else '⚠ '} {lbl}: бот={b!r}  польз.={u!r}")

    sb, su = bm.get("stickers",[]), um.get("stickers",[])
    print(f"     {'✅' if sb==su else '⚠ '} Стикеры: бот={sb}  польз.={su}")

    line()
    print("  ЗАКЛЮЧЕНИЕ")
    line()
    if sim > 95 and pct < 5:
        print("  ✅ ПОЛНОЦЕННЫЙ SSR — одинаковый контент для ботов и пользователей")
    elif sim > 70:
        print("  ⚠  ГИБРИДНЫЙ SSR — контент похож, но есть различия")
        print("     (персонализация, A/B-тесты, частичная гидратация)")
    else:
        print("  ❌ CLOAKING / РАЗНЫЙ КОНТЕНТ")
        print("     Dynamic Rendering или настоящий cloaking")

    if bm["spa_root_found"] and um["spa_root_found"]:
        if bm["spa_root_text_length"] > 100 and um["spa_root_text_length"] < 100:
            print("\n  ⚠  SSR только для ботов! Root бота заполнен, у польз. — пуст.")

    return True


# ═══════════════════════════════════════════════════════════════
# VISUAL COMPARISON — АНАЛИЗ ЭЛЕМЕНТОВ
# ═══════════════════════════════════════════════════════════════

def get_basic_metrics(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    title = str(soup.title.string).strip() if soup.title else "No title"
    body_text = soup.body.get_text(strip=True) if soup.body else ""
    return {
        "title":    title[:50],
        "size":     f"{len(html)/1024:.1f} KB",
        "elements": len(soup.find_all()),
        "text":     len(body_text),
    }


def get_element_details(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    all_els = soup.find_all()
    tag_counts = Counter(el.name for el in all_els)
    group_counts = {g: sum(tag_counts.get(t,0) for t in tags) for g, tags in ELEMENT_GROUPS.items()}
    group_counts["⚙️ Other"] = sum(tag_counts.values()) - sum(group_counts.values())
    data_qa = [el.get("data-qa") for el in soup.find_all(attrs={"data-qa": True})]
    class_counter: Counter = Counter()
    for el in all_els:
        for cls in (el.get("class") or []):
            class_counter[cls] += 1
    css_top = class_counter.most_common(20)
    emotion = len(soup.find_all("style", attrs={"data-emotion": True}))
    inline_styles = len(soup.find_all(attrs={"style": True}))
    all_scripts = soup.find_all("script")
    ext_scripts = [s for s in all_scripts if s.get("src")]
    inl_scripts = [s for s in all_scripts if not s.get("src")]
    all_links  = soup.find_all("a")
    ext_links  = [a for a in all_links if str(a.get("href","")).startswith("http")]
    all_imgs   = soup.find_all("img")
    STANDARD_TAGS = {
        "a","abbr","address","area","article","aside","audio","b","base","bdi","bdo",
        "blockquote","body","br","button","canvas","caption","cite","code","col","colgroup",
        "data","datalist","dd","del","details","dfn","dialog","div","dl","dt","em","embed",
        "fieldset","figcaption","figure","footer","form","h1","h2","h3","h4","h5","h6",
        "head","header","hgroup","hr","html","i","iframe","img","input","ins","kbd","label",
        "legend","li","link","main","map","mark","menu","meta","meter","nav","noscript",
        "object","ol","optgroup","option","output","p","picture","pre","progress","q",
        "rp","rt","ruby","s","samp","script","section","select","slot","small","source",
        "span","strong","style","sub","summary","sup","table","tbody","td","template",
        "textarea","tfoot","th","thead","time","title","tr","track","u","ul","var","video","wbr",
        "svg","path","circle","rect","g","use","defs","polyline","polygon","line",
        "text","tspan","clippath","mask","symbol","ellipse","lineargradient","radialgradient",
        "stop","filter","fedropshadow",
    }
    custom_tags = sorted({t for t in tag_counts if t not in STANDARD_TAGS})
    return {
        "tag_counts":       dict(sorted(tag_counts.items(), key=lambda x: -x[1])),
        "group_counts":     group_counts,
        "data_qa_list":     data_qa,
        "css_classes_top":  css_top,
        "emotion_blocks":   emotion,
        "inline_styles":    inline_styles,
        "scripts_total":    len(all_scripts),
        "scripts_external": len(ext_scripts),
        "scripts_inline":   len(inl_scripts),
        "links_total":      len(all_links),
        "links_external":   len(ext_links),
        "images_total":     len(all_imgs),
        "images_with_alt":  len([i for i in all_imgs if i.get("alt")]),
        "images_no_alt":    len([i for i in all_imgs if not i.get("alt")]),
        "custom_tags":      custom_tags,
    }


# ═══════════════════════════════════════════════════════════════
# VISUAL COMPARISON — ПРОТОТИП
# ═══════════════════════════════════════════════════════════════

def extract_proto_blocks(html: str) -> list:
    soup    = BeautifulSoup(html, "html.parser")
    blocks  = []
    visited = set()

    def classify(el):
        tag      = el.name
        cls_list = el.get("class", [])
        cls_str  = " ".join(cls_list).lower()
        dqa      = el.get("data-qa", "")
        text     = el.get_text(strip=True)[:80]

        if tag == "img":
            return {"type":"image","label":el.get("alt","")[:40] or "Image","size":"image"}
        if tag == "h1" or "product-card-title" in dqa:
            return {"type":"h1","label":text,"size":"h1"}
        if tag == "h2":
            return {"type":"h2","label":text,"size":"h2"}
        if tag in ("h3","h4","h5","h6"):
            return {"type":"h3","label":text,"size":"h3"}
        if tag == "p":
            return {"type":"text","label":text,"size":"text"}
        if tag == "ol" or "breadcrumb" in cls_str:
            return {"type":"breadcrumb","label":text,"size":"breadcrumb"}
        if tag == "input":
            return {"type":"input","label":el.get("placeholder","input")[:30],"size":"input"}
        if tag == "button":
            is_p = any(k in cls_str for k in ("primary","green","emerald","cart","add"))
            return {"type":"button_primary" if is_p else "button",
                    "label":text[:30] or "Button","size":"button"}
        if tag == "a" and text:
            return {"type":"link","label":text[:30],"size":"link"}
        if dqa:
            if "header" in dqa:          return {"type":"header","label":"Header / Nav","size":"header"}
            if "search" in dqa:          return {"type":"search","label":"Search bar","size":"search"}
            if "tab-bar" in dqa:         return {"type":"tabbar","label":"Tab bar","size":"tabbar"}
            if "tab-item" in dqa:        return {"type":"tab","label":text or dqa,"size":"tab"}
            if "cart-button-add" in dqa: return {"type":"button_primary","label":text or "В корзину","size":"button"}
            if "cart-button" in dqa:     return {"type":"button_primary","label":text or "Cart","size":"button_wide"}
            if "product-slider" in dqa or "slider" in dqa:
                                         return {"type":"image_carousel","label":"Слайдер товара","size":"carousel"}
            if "price" in dqa:           return {"type":"price","label":text or "Price","size":"price"}
            if any(k in dqa for k in ("sticker","badge","label","promo","cpd")):
                                         return {"type":"badge","label":text or dqa,"size":"badge"}
            if "rating" in dqa:          return {"type":"rating","label":text or "★★★★☆","size":"rating"}
        if "footer_main" in cls_str or tag == "footer":
            return {"type":"footer","label":"Footer","size":"footer"}
        if "footer" in cls_str and any(k in cls_str for k in ("accordion","container","mobile")):
            return {"type":"footer_block","label":text[:40] or "Footer section","size":"footer_block"}
        if "tabbar_main" in cls_str or "tabbar_item" in cls_str:
            return {"type":"tabbar","label":"Tab bar","size":"tabbar"}
        if "carousel" in cls_str or "swiper" in cls_str:
            return {"type":"carousel","label":"Carousel","size":"carousel"}
        if "badge" in cls_str or "sticker" in cls_str:
            return {"type":"badge","label":text[:20],"size":"badge"}
        if "price" in cls_str and text:
            return {"type":"price","label":text[:20],"size":"price"}
        if "chakra-image" in cls_str:
            return {"type":"image","label":el.get("alt","Image"),"size":"image"}
        return None

    def walk(el, depth=0):
        if not hasattr(el, "name") or not el.name: return
        if el.name in SKIP_TAGS: return
        eid = id(el)
        if eid in visited: return
        block    = classify(el)
        children = [c for c in el.children
                    if hasattr(c,"name") and c.name and c.name not in SKIP_TAGS]
        if block:
            visited.add(eid)
            block["depth"]    = depth
            block["dqa"]      = el.get("data-qa","")
            block["tag"]      = el.name
            block["children"] = len(children)
            blocks.append(block)
            if block["type"] in ("header","tabbar","footer_block","footer","image_carousel"):
                for c in children: walk(c, depth+1)
            return
        for c in children: walk(c, depth+1)

    walk(soup.body)
    return blocks


def diff_proto_blocks(bot: list, user: list) -> tuple:
    def key(b): return f"{b['type']}::{b['label'][:25]}"
    bk = {key(b) for b in bot}
    uk = {key(u) for u in user}
    for b in bot:  b["status"] = "same" if key(b) in uk else "only_bot"
    for u in user: u["status"] = "same" if key(u) in bk else "only_user"
    return bot, user


# ═══════════════════════════════════════════════════════════════
# HTML ОТЧЁТ
# ═══════════════════════════════════════════════════════════════

def create_report(
    bot_metrics, user_metrics,
    bot_details, user_details,
    bot_proto, user_proto,
    output_filename,
) -> str:

    bd_json  = json.dumps(bot_details,  ensure_ascii=False)
    ud_json  = json.dumps(user_details, ensure_ascii=False)
    bp_json  = json.dumps(bot_proto,    ensure_ascii=False)
    up_json  = json.dumps(user_proto,   ensure_ascii=False)
    grp_json = json.dumps({k:v for k,v in ELEMENT_GROUPS.items()}, ensure_ascii=False)

    ed  = bot_metrics["elements"] - user_metrics["elements"]
    es  = f"+{ed}" if ed > 0 else str(ed)
    ec  = "#e53935" if ed != 0 else "#43a047"
    obn = os.path.basename(output_filename)

    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Visual Comparison — BOT vs USER</title>
<style>
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;background:#f0f2f5;color:#1a1a2e}}
.header{{background:linear-gradient(135deg,#667eea,#764ba2);color:#fff;padding:26px 30px;text-align:center;box-shadow:0 2px 12px rgba(0,0,0,.15)}}
.header h1{{font-size:1.9em;margin-bottom:4px}}.header p{{opacity:.88}}
.warn{{background:#fff8e1;color:#795548;padding:10px 20px;margin:12px 20px 0;border-radius:6px;border-left:4px solid #ffc107;font-size:.87em}}
.warn code{{background:#ffeecb;padding:1px 5px;border-radius:3px}}
.tabs{{display:flex;background:#fff;border-bottom:3px solid #667eea}}
.tab-btn{{flex:1;padding:13px 8px;background:none;border:none;cursor:pointer;font-size:.88em;font-weight:700;color:#777;transition:all .2s}}
.tab-btn:hover{{background:#f5f5f5;color:#333}}
.tab-btn.active{{color:#667eea;background:#f0f2ff;border-bottom:4px solid #667eea;margin-bottom:-3px}}
.content{{display:none;padding:18px}}.content.active{{display:block}}
.two-col{{display:grid;grid-template-columns:1fr 1fr;gap:18px}}
@media(max-width:900px){{.two-col{{grid-template-columns:1fr}}}}
.panel{{background:#fff;border-radius:10px;box-shadow:0 2px 10px rgba(0,0,0,.08);overflow:hidden;display:flex;flex-direction:column}}
.ph{{padding:12px 16px;font-weight:700;font-size:.9em}}.ph.bot{{background:#e8f5e9;color:#2e7d32;border-bottom:2px solid #4caf50}}
.ph.user{{background:#ffebee;color:#c62828;border-bottom:2px solid #f44336}}
.pb{{flex:1;overflow:auto}}
#visual .panel,#screenshots .panel{{height:calc(100vh - 270px)}}
.code-box{{flex:1;overflow:auto;padding:14px;background:#1e1e2e;color:#cdd6f4;font-family:Consolas,monospace;font-size:.77em;line-height:1.5;white-space:pre-wrap;word-break:break-all}}
#htmlcode .two-col{{height:calc(100vh - 270px)}}
.sg{{display:grid;grid-template-columns:1fr 1fr;gap:9px;padding:14px}}
.st{{background:#f8f9ff;padding:10px 12px;border-radius:6px;border-left:3px solid #667eea}}
.stl{{font-size:.7em;color:#999;text-transform:uppercase;font-weight:700}}.stv{{font-size:1.1em;font-weight:800;margin-top:2px}}
.sc{{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:10px;margin-bottom:16px}}
.scard{{background:#fff;border-radius:9px;box-shadow:0 2px 8px rgba(0,0,0,.07);padding:12px 14px}}
.sclbl{{font-size:.69em;text-transform:uppercase;color:#999;font-weight:700}}.scvals{{display:flex;gap:9px;margin-top:5px;align-items:baseline}}
.scb{{font-size:1.2em;font-weight:800;color:#2e7d32}}.scu{{font-size:1.2em;font-weight:800;color:#c62828}}
.scd{{font-size:.8em;font-weight:700;padding:2px 6px;border-radius:10px}}
.dp{{background:#fce4ec;color:#b71c1c}}.dn{{background:#e8f5e9;color:#1b5e20}}.dz{{background:#f5f5f5;color:#888}}
.itabs{{display:flex;border-bottom:2px solid #eee;margin-bottom:12px}}
.itab{{padding:7px 13px;cursor:pointer;font-size:.84em;font-weight:700;color:#999;border-bottom:3px solid transparent;margin-bottom:-2px;transition:all .15s;border-radius:4px 4px 0 0}}
.itab.active{{color:#667eea;border-bottom-color:#667eea}}.itab:hover{{color:#333;background:#f5f5f5}}
.ipane{{display:none}}.ipane.active{{display:block}}
.etab{{width:100%;border-collapse:collapse;font-size:.85em}}
.etab th{{text-align:left;padding:7px 10px;background:#f5f7ff;border-bottom:2px solid #dde1ff;font-size:.74em;text-transform:uppercase;color:#667eea}}
.etab td{{padding:6px 10px;border-bottom:1px solid #f0f0f0}}.etab tr:hover td{{background:#fafbff}}
.pos{{color:#e53935;font-weight:800}}.neg{{color:#43a047;font-weight:800}}.zero{{color:#bbb}}
.el{{display:grid;grid-template-columns:290px 1fr;gap:18px}}
@media(max-width:1100px){{.el{{grid-template-columns:1fr}}}}
.gsb{{background:#fff;border-radius:10px;box-shadow:0 2px 10px rgba(0,0,0,.08);padding:14px}}
.gsb h3{{font-size:.78em;text-transform:uppercase;color:#999;letter-spacing:.06em;margin-bottom:8px}}
.gbn{{display:flex;align-items:center;justify-content:space-between;width:100%;padding:8px 10px;margin-bottom:4px;background:#f5f5f5;border:none;border-radius:7px;cursor:pointer;font-size:.86em;font-weight:700;transition:background .15s;text-align:left}}
.gbn:hover{{background:#e8eaff}}.gbn.active{{background:#667eea;color:#fff}}
.gp{{font-size:.72em;font-weight:800;padding:2px 6px;border-radius:11px}}
.gpb{{background:#c8e6c9;color:#2e7d32}}.gpu{{background:#ffcdd2;color:#c62828}}
.gbn.active .gpb{{background:#a5d6a7}}.gbn.active .gpu{{background:#ef9a9a}}
.dp2{{background:#fff;border-radius:10px;box-shadow:0 2px 10px rgba(0,0,0,.08);padding:17px;min-height:440px}}
.dt{{font-size:1.05em;font-weight:800;margin-bottom:12px;padding-bottom:9px;border-bottom:2px solid #eee;display:flex;align-items:center;gap:8px;flex-wrap:wrap}}
.chip{{padding:3px 9px;border-radius:11px;font-size:.8em;font-weight:700}}
.cb{{background:#e8f5e9;color:#2e7d32}}.cu{{background:#ffebee;color:#c62828}}
.cdp{{background:#fce4ec;color:#b71c1c;font-weight:900}}.cdn{{background:#e8f5e9;color:#1b5e20;font-weight:900}}.cdz{{background:#f5f5f5;color:#666}}
.qa-list{{display:flex;flex-wrap:wrap;gap:5px;margin-top:7px}}
.qa-tag{{padding:3px 8px;border-radius:11px;font-size:.74em;font-weight:700}}
.qa-both{{background:#e8f0fe;color:#1a73e8}}.qa-bot{{background:#e8f5e9;color:#2e7d32;border:1px dashed #81c784}}
.qa-user{{background:#ffebee;color:#c62828;border:1px dashed #e57373}}
.proto-wrap{{display:grid;grid-template-columns:1fr 1fr;gap:28px;align-items:start}}
@media(max-width:900px){{.proto-wrap{{grid-template-columns:1fr}}}}
.pleg{{display:flex;gap:12px;align-items:center;padding:9px 13px;background:#fff;border-radius:8px;box-shadow:0 1px 6px rgba(0,0,0,.08);margin-bottom:12px;font-size:.8em;flex-wrap:wrap}}
.pleg-item{{display:flex;align-items:center;gap:5px;font-weight:700}}
.lbox{{width:18px;height:12px;border-radius:2px}}
.lb-s{{background:#e0e0e0}}.lb-b{{background:rgba(76,175,80,.2);border:2px dashed #4caf50}}.lb-u{{background:rgba(244,67,54,.2);border:2px dashed #f44336}}
.db{{display:inline-flex;align-items:center;gap:5px;padding:4px 10px;border-radius:20px;font-size:.78em;font-weight:800}}
.dbe{{background:#e8f5e9;color:#2e7d32}}.dbd{{background:#fff3e0;color:#e65100}}
.phone-col{{display:flex;flex-direction:column;align-items:center}}
.plbl{{font-weight:800;font-size:.92em;margin-bottom:9px;display:flex;align-items:center;gap:7px}}
.plbl-b{{color:#2e7d32}}.plbl-u{{color:#c62828}}
.phone{{width:360px;max-width:100%;background:#fff;border-radius:38px;box-shadow:0 0 0 9px #1a1a2e,0 18px 55px rgba(0,0,0,.32);overflow:hidden;position:relative}}
.pnotch{{width:110px;height:26px;background:#1a1a2e;border-radius:0 0 16px 16px;margin:0 auto;position:relative;z-index:10}}
.pscreen{{overflow-y:auto;max-height:660px;padding:0 0 70px;scrollbar-width:thin;scrollbar-color:#ddd transparent;background:#f7f8fa}}
.pb2{{margin:0 8px 3px;border-radius:7px;font-size:11px;font-weight:700;overflow:hidden;position:relative;cursor:default;transition:transform .1s,box-shadow .1s}}
.pb2:hover{{transform:scale(1.015);box-shadow:0 3px 12px rgba(0,0,0,.15);z-index:5}}
.pb2.ob{{outline:2.5px dashed #4caf50;background-color:rgba(76,175,80,.09)!important}}
.pb2.ou{{outline:2.5px dashed #f44336;background-color:rgba(244,67,54,.09)!important}}
.pbi{{display:flex;align-items:center;gap:6px;padding:5px 8px;min-height:22px;overflow:hidden}}
.pbi-icon{{font-size:11px;flex-shrink:0}}.pbi-text{{overflow:hidden;white-space:nowrap;text-overflow:ellipsis;flex:1;color:#333}}
.pbi-dqa{{font-size:9px;color:#aaa;overflow:hidden;white-space:nowrap;text-overflow:ellipsis;flex-shrink:0;max-width:80px}}
.t-header{{background:#e3f2fd;border-top:3px solid #1976d2;margin:0 0 3px;border-radius:0;height:42px}}
.t-header .pbi-text{{color:#1565c0;font-weight:800;font-size:12px}}
.t-search{{background:#fff;border:1.5px solid #bdbdbd;border-radius:22px;margin:4px 10px;height:35px}}
.t-search .pbi-text{{color:#9e9e9e}}
.t-breadcrumb{{background:#f5f5f5;margin:2px 8px;height:21px;border-radius:4px}}
.t-breadcrumb .pbi-text{{color:#888;font-size:10px}}
.t-image_carousel{{background:linear-gradient(135deg,#bbdefb,#e3f2fd);border-radius:10px;margin:4px 8px;height:210px;display:flex;align-items:center;justify-content:center;position:relative;overflow:hidden}}
.t-image_carousel .pbi{{flex-direction:column;gap:4px;position:relative;z-index:1;height:100%;justify-content:center}}
.t-image_carousel .pbi-text{{color:#1565c0;font-size:13px;font-weight:800;text-align:center;white-space:normal}}
.t-image{{background:linear-gradient(135deg,#e8eaf6,#c5cae9);border-radius:8px;margin:4px 8px;height:170px;display:flex;align-items:center;justify-content:center}}
.t-image .pbi{{flex-direction:column;gap:3px}}.t-image .pbi-text{{color:#3949ab;font-size:11px;text-align:center}}
.t-carousel{{background:linear-gradient(135deg,#fce4ec,#f8bbd0);border-radius:9px;margin:4px 8px;height:130px;display:flex;align-items:center;justify-content:center}}
.t-carousel .pbi-text{{color:#880e4f;font-size:11px}}
.t-h1{{background:#fff3e0;border-left:4px solid #ff6f00;margin:4px 8px;padding:4px 8px;min-height:38px;border-radius:6px}}
.t-h1 .pbi-text{{color:#e65100;font-size:12px;font-weight:900;line-height:1.3;white-space:normal}}
.t-h2{{background:#fff8e1;border-left:3px solid #f9a825;margin:3px 8px;height:27px;border-radius:5px}}
.t-h2 .pbi-text{{color:#f57f17;font-weight:800;font-size:11px}}
.t-h3{{background:#f3e5f5;border-left:2px solid #ab47bc;margin:2px 8px;height:23px;border-radius:4px}}
.t-h3 .pbi-text{{color:#7b1fa2;font-size:10px}}
.t-text{{background:#fafafa;margin:2px 8px;height:21px;border-radius:4px}}.t-text .pbi-text{{color:#666;font-size:10px}}
.t-button_primary{{background:linear-gradient(135deg,#43a047,#2e7d32);border-radius:22px;margin:5px 8px;height:43px;box-shadow:0 3px 8px rgba(67,160,71,.3)}}
.t-button_primary .pbi-text{{color:#fff;font-size:12px;font-weight:800;text-align:center}}
.t-button_wide{{background:linear-gradient(135deg,#43a047,#2e7d32);border-radius:8px;margin:5px 8px;height:48px}}
.t-button_wide .pbi-text{{color:#fff;font-size:12px;font-weight:800}}
.t-button{{background:#f5f5f5;border:1.5px solid #ddd;border-radius:20px;margin:4px 8px;height:35px}}
.t-button .pbi-text{{color:#555;font-size:11px}}
.t-price{{background:#e8f5e9;border-radius:7px;margin:3px 8px;height:31px}}.t-price .pbi-text{{color:#1b5e20;font-size:13px;font-weight:900}}
.t-badge{{display:inline-flex;align-items:center;background:#ff5722;border-radius:4px;margin:2px 4px;height:19px;padding:0 6px;font-size:10px;color:#fff;font-weight:800}}
.t-rating{{background:#fffde7;border-radius:6px;margin:3px 8px;height:23px}}.t-rating .pbi-text{{color:#f57f17;font-size:10px}}
.t-link{{background:transparent;margin:1px 8px;height:17px}}.t-link .pbi-text{{color:#1976d2;font-size:10px;text-decoration:underline}}
.t-input{{background:#fff;border:1.5px solid #bdbdbd;border-radius:6px;margin:3px 8px;height:33px}}.t-input .pbi-text{{color:#9e9e9e}}
.t-footer_block{{background:#eceff1;border-top:1.5px solid #90a4ae;margin:2px 0;border-radius:0;padding:5px 10px;min-height:28px}}
.t-footer_block .pbi-text{{color:#546e7a;font-size:10px;white-space:normal}}
.t-footer{{background:#263238;margin:3px 0 0;border-radius:0;min-height:55px}}.t-footer .pbi-text{{color:#b0bec5;font-size:10px}}
.t-tabbar{{position:sticky;bottom:0;z-index:20;background:#fff;border-top:1px solid #e0e0e0;display:flex;justify-content:space-around;align-items:center;height:54px;margin:0;border-radius:0;box-shadow:0 -2px 10px rgba(0,0,0,.08)}}
.t-tab{{background:transparent;margin:0;height:48px;border-radius:0;flex:1}}
.t-tab .pbi{{justify-content:center}}.t-tab .pbi-text{{color:#9e9e9e;font-size:9px;text-align:center}}
.t-unknown{{background:#f5f5f5;border:1px dashed #ccc;margin:2px 8px;height:19px;border-radius:4px}}.t-unknown .pbi-text{{color:#bbb;font-size:10px}}
.blkcnt{{font-size:.73em;color:#999;font-weight:600;margin-bottom:6px;text-align:center}}
</style>
</head>
<body>
<div class="header">
  <h1>🎨 Visual Comparison</h1>
  <p>BOT vs USER — Side-by-Side</p>
</div>
<div class="warn">
  ⚠️ CORS: <code>python -m http.server 8000</code> → <b>http://localhost:8000/{obn}</b>
</div>
<div class="tabs">
  <button class="tab-btn active" onclick="showTab('analysis',this)">📊 Analysis</button>
  <button class="tab-btn"        onclick="showTab('elements',this)">🔬 Elements</button>
  <button class="tab-btn"        onclick="showTab('prototype',this)">📱 Prototype</button>
</div>
<div id="analysis" class="content active">
  <div class="two-col">
    <div class="panel"><div class="ph bot">🤖 BOT Statistics</div>
      <div class="sg">
        <div class="st"><div class="stl">Title</div><div class="stv" style="font-size:.83em">{bot_metrics['title']}</div></div>
        <div class="st"><div class="stl">File Size</div><div class="stv">{bot_metrics['size']}</div></div>
        <div class="st"><div class="stl">Elements</div><div class="stv">{bot_metrics['elements']}</div></div>
        <div class="st"><div class="stl">Text</div><div class="stv">{bot_metrics['text']:,}</div></div>
        <div class="st"><div class="stl">Scripts</div><div class="stv">{bot_details['scripts_total']}</div></div>
        <div class="st"><div class="stl">Images</div><div class="stv">{bot_details['images_total']}</div></div>
        <div class="st"><div class="stl">Links</div><div class="stv">{bot_details['links_total']}</div></div>
        <div class="st"><div class="stl">CSS blocks</div><div class="stv">{bot_details['emotion_blocks']}</div></div>
      </div></div>
    <div class="panel"><div class="ph user">👤 USER Statistics</div>
      <div class="sg">
        <div class="st"><div class="stl">Title</div><div class="stv" style="font-size:.83em">{user_metrics['title']}</div></div>
        <div class="st"><div class="stl">File Size</div><div class="stv">{user_metrics['size']}</div></div>
        <div class="st"><div class="stl">Elements</div><div class="stv">{user_metrics['elements']} <span style="font-size:.68em;color:{ec}">({es})</span></div></div>
        <div class="st"><div class="stl">Text</div><div class="stv">{user_metrics['text']:,}</div></div>
        <div class="st"><div class="stl">Scripts</div><div class="stv">{user_details['scripts_total']}</div></div>
        <div class="st"><div class="stl">Images</div><div class="stv">{user_details['images_total']}</div></div>
        <div class="st"><div class="stl">Links</div><div class="stv">{user_details['links_total']}</div></div>
        <div class="st"><div class="stl">CSS blocks</div><div class="stv">{user_details['emotion_blocks']}</div></div>
      </div></div>
  </div>
</div>
<div id="elements" class="content">
  <div class="sc" id="sc"></div>
  <div class="el">
    <div class="gsb"><h3>Группы</h3><div id="gbtns"></div></div>
    <div class="dp2">
      <div class="dt" id="dt">Выберите группу</div>
      <div class="itabs">
        <div class="itab active" onclick="si('pt',this)">📋 Теги</div>
        <div class="itab" onclick="si('pb2',this)">📊 Диаграмма</div>
        <div class="itab" onclick="si('pq',this)">🏷 data-qa</div>
        <div class="itab" onclick="si('pc',this)">🎨 CSS</div>
        <div class="itab" onclick="si('pm',this)">⚙️ Прочее</div>
      </div>
      <div class="ipane active" id="pt"></div>
      <div class="ipane" id="pb2"></div>
      <div class="ipane" id="pq"></div>
      <div class="ipane" id="pc"></div>
      <div class="ipane" id="pm"></div>
    </div>
  </div>
</div>
<div id="prototype" class="content">
  <div style="display:flex;align-items:center;gap:12px;margin-bottom:12px;flex-wrap:wrap">
    <div class="pleg">
      <div class="pleg-item"><div class="lbox lb-s"></div>Одинаковый</div>
      <div class="pleg-item"><div class="lbox lb-b"></div>Только в BOT</div>
      <div class="pleg-item"><div class="lbox lb-u"></div>Только в USER</div>
    </div>
    <div id="pstats" style="display:flex;gap:8px;flex-wrap:wrap"></div>
  </div>
  <div class="proto-wrap">
    <div class="phone-col">
      <div class="plbl plbl-b">🤖 BOT <span id="bcnt" class="blkcnt"></span></div>
      <div class="phone"><div class="pnotch"></div><div class="pscreen" id="bproto"></div></div>
    </div>
    <div class="phone-col">
      <div class="plbl plbl-u">👤 USER <span id="ucnt" class="blkcnt"></span></div>
      <div class="phone"><div class="pnotch"></div><div class="pscreen" id="uproto"></div></div>
    </div>
  </div>
</div>
<script>
const bD={bd_json},uD={ud_json};
const GRPS={grp_json};
const bP={bp_json},uP={up_json};
let elInit=0,prInit=0;
function showTab(n,btn){{
  document.querySelectorAll('.content').forEach(e=>e.classList.remove('active'));
  document.querySelectorAll('.tab-btn').forEach(b=>b.classList.remove('active'));
  document.getElementById(n).classList.add('active');btn.classList.add('active');
  if(n==='elements'&&!elInit){{initEl();elInit=1}}
  if(n==='prototype'&&!prInit){{initProto();prInit=1}}
}}
function si(id,el){{
  document.querySelectorAll('.ipane').forEach(p=>p.classList.remove('active'));
  document.querySelectorAll('.itab').forEach(t=>t.classList.remove('active'));
  document.getElementById(id).classList.add('active');el.classList.add('active');
}}
function osum(o){{return Object.values(o).reduce((a,b)=>a+b,0)}}
function initEl(){{bldSC();bldGB();document.querySelector('#gbtns .gbn')?.click()}}
function bldSC(){{
  const items=[
    {{l:'Total Tags',b:osum(bD.tag_counts),u:osum(uD.tag_counts)}},
    {{l:'Scripts',b:bD.scripts_total,u:uD.scripts_total}},
    {{l:'Ext Scripts',b:bD.scripts_external,u:uD.scripts_external}},
    {{l:'Images',b:bD.images_total,u:uD.images_total}},
    {{l:'Links',b:bD.links_total,u:uD.links_total}},
    {{l:'CSS Blocks',b:bD.emotion_blocks,u:uD.emotion_blocks}},
    {{l:'Inline Style',b:bD.inline_styles,u:uD.inline_styles}},
    {{l:'data-qa',b:bD.data_qa_list.length,u:uD.data_qa_list.length}},
  ];
  document.getElementById('sc').innerHTML=items.map(it=>{{
    const d=it.b-it.u;const dc=d>0?'dp':d<0?'dn':'dz';const ds=d>0?'+'+d:d===0?'=':d;
    return `<div class="scard"><div class="sclbl">${{it.l}}</div><div class="scvals">
      <span class="scb">${{it.b}}</span><span class="scu">${{it.u}}</span>
      <span class="scd ${{dc}}">${{ds}}</span></div></div>`;
  }}).join('');
}}
function bldGB(){{
  const all={{'🗃 All':null,...GRPS}};
  document.getElementById('gbtns').innerHTML=Object.entries(all).map(([n,t])=>{{
    const bc=t?t.reduce((s,x)=>s+(bD.tag_counts[x]||0),0):osum(bD.tag_counts);
    const uc=t?t.reduce((s,x)=>s+(uD.tag_counts[x]||0),0):osum(uD.tag_counts);
    const d=bc-uc;const dh=d!==0?`<span style="font-size:.7em;font-weight:800;color:${{d>0?'#e57373':'#81c784'}}">${{d>0?'+':''}}${{d}}</span>`:'';
    return `<button class="gbn" onclick="selG('${{n}}',this)"><span>${{n}}</span>
      <span style="display:flex;gap:4px;align-items:center">
        <span class="gp gpb">${{bc}}</span><span class="gp gpu">${{uc}}</span>${{dh}}</span></button>`;
  }}).join('');
}}
function selG(gn,btn){{
  document.querySelectorAll('.gbn').forEach(b=>b.classList.remove('active'));btn.classList.add('active');
  const t=gn==='🗃 All'?null:GRPS[gn];
  const tl=t?t.slice().sort((a,b)=>(bD.tag_counts[b]||0)+(uD.tag_counts[b]||0)-(bD.tag_counts[a]||0)-(uD.tag_counts[a]||0))
    :Object.keys({{...bD.tag_counts,...uD.tag_counts}}).sort((a,b)=>(bD.tag_counts[b]||0)+(uD.tag_counts[b]||0)-(bD.tag_counts[a]||0)-(uD.tag_counts[a]||0));
  const bt=tl.reduce((s,x)=>s+(bD.tag_counts[x]||0),0),ut=tl.reduce((s,x)=>s+(uD.tag_counts[x]||0),0);
  const d=bt-ut;const dc=d>0?'cdp':d<0?'cdn':'cdz';
  document.getElementById('dt').innerHTML=`<span>${{gn}}</span><span style="display:flex;gap:6px">
    <span class="chip cb">🤖 ${{bt}}</span><span class="chip cu">👤 ${{ut}}</span>
    <span class="chip ${{dc}}">${{d>0?'+':''}}${{d===0?'0':d}}</span></span>`;
  rTable(tl);rBars(tl);rQA();rCSS();rMisc();
}}
function rTable(tl){{
  document.getElementById('pt').innerHTML=`<table class="etab"><thead><tr>
    <th>Тег</th><th style="text-align:right">🤖 BOT</th><th style="text-align:right">👤 USER</th><th style="text-align:right">Δ</th>
    </tr></thead><tbody>${{tl.map(t=>{{
      const b=bD.tag_counts[t]||0,u=uD.tag_counts[t]||0,d=b-u;
      const dc=d>0?'pos':d<0?'neg':'zero';const ds=d>0?'+'+d:d===0?'—':d;
      const hl=d!==0?'style="background:#fffde7"':'';
      return `<tr ${{hl}}><td style="font-family:monospace;font-weight:700">&lt;${{t}}&gt;</td>
        <td style="color:#2e7d32;font-weight:700;text-align:right">${{b}}</td>
        <td style="color:#c62828;font-weight:700;text-align:right">${{u}}</td>
        <td class="${{dc}}" style="text-align:right">${{ds}}</td></tr>`;
    }}).join('')}}</tbody></table>`;
}}
function rBars(tl){{
  const mx=Math.max(...tl.map(t=>Math.max(bD.tag_counts[t]||0,uD.tag_counts[t]||0)),1);
  document.getElementById('pb2').innerHTML=`
    <div style="display:flex;gap:12px;margin-bottom:9px;font-size:.79em">
      <span><span style="display:inline-block;width:11px;height:11px;background:#81c784;border-radius:2px;margin-right:3px"></span>🤖</span>
      <span><span style="display:inline-block;width:11px;height:11px;background:#e57373;border-radius:2px;margin-right:3px"></span>👤</span>
    </div>
    ${{tl.map(t=>{{const b=bD.tag_counts[t]||0,u=uD.tag_counts[t]||0;
      const bw=Math.max(Math.round(b/mx*190),b>0?4:0),uw=Math.max(Math.round(u/mx*190),u>0?4:0);
      const hl=b!==u?'style="background:#fffde7;border-radius:4px"':'';
      return `<div ${{hl}} style="display:grid;grid-template-columns:85px 1fr;gap:7px;align-items:center;padding:4px 5px;font-size:.82em">
        <span style="font-family:monospace;font-weight:700;color:#444">&lt;${{t}}&gt;</span><div>
          <div style="display:flex;align-items:center;gap:5px;margin-bottom:2px">
            <div style="height:8px;border-radius:4px;background:#81c784;min-width:2px;width:${{bw}}px"></div>
            <span style="color:#2e7d32;font-weight:700;min-width:24px">${{b}}</span></div>
          <div style="display:flex;align-items:center;gap:5px">
            <div style="height:8px;border-radius:4px;background:#e57373;min-width:2px;width:${{uw}}px"></div>
            <span style="color:#c62828;font-weight:700;min-width:24px">${{u}}</span></div>
        </div></div>`;
    }}).join('')}}`;
}}
function rQA(){{
  const bs=new Set(bD.data_qa_list.filter(Boolean)),us=new Set(uD.data_qa_list.filter(Boolean));
  const all=[...new Set([...bs,...us])].sort();
  const ob=[...bs].filter(v=>!us.has(v)),ou=[...us].filter(v=>!bs.has(v));
  document.getElementById('pq').innerHTML=`
    <div style="margin-bottom:10px;font-size:.82em;display:flex;gap:12px;flex-wrap:wrap">
      <span>Всего: <b>${{all.length}}</b></span>
      <span style="color:#1a73e8">🟦 Общие: <b>${{all.length-ob.length-ou.length}}</b></span>
      <span style="color:#2e7d32">🤖 BOT: <b>${{ob.length}}</b></span>
      <span style="color:#c62828">👤 USER: <b>${{ou.length}}</b></span></div>
    ${{ob.length?`<div style="margin-bottom:7px"><b style="color:#2e7d32">🤖 Только BOT:</b><div class="qa-list">${{ob.map(v=>`<span class="qa-tag qa-bot">${{v}}</span>`).join('')}}</div></div>`:''}}
    ${{ou.length?`<div style="margin-bottom:7px"><b style="color:#c62828">👤 Только USER:</b><div class="qa-list">${{ou.map(v=>`<span class="qa-tag qa-user">${{v}}</span>`).join('')}}</div></div>`:''}}
    <div><b>Все:</b><div class="qa-list">${{all.map(v=>{{
      const ib=bs.has(v),iu=us.has(v);const c=ib&&iu?'qa-both':ib?'qa-bot':'qa-user';
      return `<span class="qa-tag ${{c}}">${{ib&&iu?'':ib?'🤖 ':'👤 '}}${{v}}</span>`;
    }}).join('')}}</div></div>`;
}}
function rCSS(){{
  const bm=Object.fromEntries(bD.css_classes_top),um=Object.fromEntries(uD.css_classes_top);
  const items=[...new Set([...Object.keys(bm),...Object.keys(um)])]
    .map(function(c){{return {{c:c,b:bm[c]||0,u:um[c]||0}};}}).sort((a,b)=>(b.b+b.u)-(a.b+a.u)).slice(0,30);
  document.getElementById('pc').innerHTML=items.map(it=>{{
    const d=it.b-it.u;
    return `<div style="display:flex;justify-content:space-between;padding:4px 6px;border-radius:3px;font-size:.8em;${{d!==0?'background:#fffde7':''}}">
      <span style="font-family:monospace;color:#444;word-break:break-all;flex:1">.${{it.c}}</span>
      <div style="display:flex;gap:7px;flex-shrink:0;margin-left:7px">
        <span style="color:#2e7d32;font-weight:700;min-width:24px;text-align:right">${{it.b}}</span>
        <span style="color:#c62828;font-weight:700;min-width:24px;text-align:right">${{it.u}}</span>
        <span class="${{d>0?'pos':d<0?'neg':'zero'}}" style="min-width:32px;text-align:right">${{d>0?'+'+d:d===0?'—':d}}</span>
      </div></div>`;
  }}).join('');
}}
function rMisc(){{
  const row=(l,b,u)=>{{const d=b-u;const dc=d>0?'color:#e53935':d<0?'color:#43a047':'color:#aaa';
    return `<tr><td style="padding:6px 9px;border-bottom:1px solid #f0f0f0">${{l}}</td>
      <td style="padding:6px 9px;border-bottom:1px solid #f0f0f0;color:#2e7d32;font-weight:700;text-align:right">${{b}}</td>
      <td style="padding:6px 9px;border-bottom:1px solid #f0f0f0;color:#c62828;font-weight:700;text-align:right">${{u}}</td>
      <td style="padding:6px 9px;border-bottom:1px solid #f0f0f0;${{dc}};font-weight:700;text-align:right">${{d>0?'+'+d:d===0?'—':d}}</td></tr>`}};
  document.getElementById('pm').innerHTML=`
    <table class="etab" style="margin-bottom:14px"><thead><tr>
      <th>Метрика</th><th style="text-align:right">🤖</th><th style="text-align:right">👤</th><th style="text-align:right">Δ</th>
      </tr></thead><tbody>
      ${{row('Всего тегов',osum(bD.tag_counts),osum(uD.tag_counts))}}
      ${{row('Скриптов',bD.scripts_total,uD.scripts_total)}}
      ${{row('Скрипты внеш.',bD.scripts_external,uD.scripts_external)}}
      ${{row('Скрипты inline',bD.scripts_inline,uD.scripts_inline)}}
      ${{row('Изображений',bD.images_total,uD.images_total)}}
      ${{row('Img с alt',bD.images_with_alt,uD.images_with_alt)}}
      ${{row('Img без alt',bD.images_no_alt,uD.images_no_alt)}}
      ${{row('Ссылок',bD.links_total,uD.links_total)}}
      ${{row('Внеш. ссылок',bD.links_external,uD.links_external)}}
      ${{row('CSS-in-JS',bD.emotion_blocks,uD.emotion_blocks)}}
      ${{row('Inline style',bD.inline_styles,uD.inline_styles)}}
      ${{row('data-qa',bD.data_qa_list.length,uD.data_qa_list.length)}}
    </tbody></table>
    <div style="font-size:.81em">
      <b>Нестандартные BOT:</b> <code>${{bD.custom_tags.join(', ')||'—'}}</code><br>
      <b>Нестандартные USER:</b> <code>${{uD.custom_tags.join(', ')||'—'}}</code>
    </div>`;
}}
const ICONS={{
  header:'🔙',search:'🔍',breadcrumb:'›',image_carousel:'🖼',
  image:'🖼',carousel:'↔',h1:'H1',h2:'H2',h3:'H3',
  text:'¶',button_primary:'🛒',button:'[ ]',button_wide:'[ ]',
  price:'₽',badge:'🏷',rating:'★',link:'🔗',input:'✏',
  footer_block:'≡',footer:'©',tabbar:'⬛',tab:'•',unknown:'?'
}};
function initProto(){{
  rProto(bP,'bproto','bcnt');
  rProto(uP,'uproto','ucnt');
  updPStats();
}}
function updPStats(){{
  const bo=bP.filter(b=>b.status==='only_bot').length;
  const uo=uP.filter(b=>b.status==='only_user').length;
  const sm=bP.filter(b=>b.status==='same').length;
  const isDiff=bo>0||uo>0;
  document.getElementById('pstats').innerHTML=`
    <div class="db ${{isDiff?'dbd':'dbe'}}">${{isDiff?'⚠️':'✅'}} ${{isDiff?`${{bo+uo}} отличий`:'Структура одинакова'}}</div>
    <div style="font-size:.79em;color:#888;display:flex;gap:9px;align-items:center">
      <span>🟰 Общих: <b>${{sm}}</b></span>
      ${{bo>0?`<span style="color:#4caf50">🤖 BOT: <b>${{bo}}</b></span>`:''}}
      ${{uo>0?`<span style="color:#f44336">👤 USER: <b>${{uo}}</b></span>`:''}}
    </div>`;
}}
function rProto(blocks,cid,countId){{
  const dc=blocks.filter(b=>b.status!=='same').length;
  document.getElementById(countId).textContent=`${{blocks.length}} блоков${{dc>0?' · '+dc+' отличий':''}}`;
  document.getElementById(cid).innerHTML=blocks.map(rBlock).join('');
}}
function rBlock(b){{
  const type=b.type||'unknown';
  const lbl=(b.label||'').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  const icon=ICONS[type]||'□';
  const dqaHtml=b.dqa?`<span class="pbi-dqa">#${{b.dqa}}</span>`:'';
  const stCls=b.status==='only_bot'?'ob':b.status==='only_user'?'ou':'';
  const title=`title="${{type}}: ${{lbl}}"`;
  if(type==='tabbar'){{
    return `<div class="pb2 t-tabbar ${{stCls}}" ${{title}}>
      ${{['Главная','Каталог','Связь','Профиль'].map(n=>`
        <div style="flex:1;display:flex;flex-direction:column;align-items:center;gap:2px;padding:3px 0">
          <div style="width:20px;height:20px;background:#e0e0e0;border-radius:50%"></div>
          <span style="font-size:9px;color:#9e9e9e">${{n}}</span>
        </div>`).join('')}}
    </div>`;
  }}
  if(type==='image_carousel'){{
    return `<div class="pb2 t-image_carousel ${{stCls}}" ${{title}}>
      <div class="pbi">
        <div style="font-size:26px">🖼</div>
        <div class="pbi-text">${{lbl||'Image Carousel'}}</div>
        <div style="display:flex;gap:4px;margin-top:5px">
          ${{[0,1,2,3,4].map(i=>`<div style="width:${{i===2?'9px':'5px'}};height:${{i===2?'9px':'5px'}};border-radius:50%;background:${{i===2?'#1976d2':'rgba(25,118,210,.25)'}}"></div>`).join('')}}
        </div>
      </div>
    </div>`;
  }}
  if(type==='badge'){{
    return `<span class="pb2 t-badge ${{stCls}}" ${{title}}>${{icon}} ${{lbl}}</span>`;
  }}
  return `<div class="pb2 t-${{type.replace(/_/g,'-')}} ${{stCls}}" ${{title}}>
    <div class="pbi">
      <span class="pbi-icon">${{icon}}</span>
      <span class="pbi-text">${{lbl}}</span>
      ${{dqaHtml}}
    </div>
  </div>`;
}}
</script>
</body>
</html>
"""


# ═══════════════════════════════════════════════════════════════
# ОСНОВНОЙ СЦЕНАРИЙ
# ═══════════════════════════════════════════════════════════════

def run_check(url: str, cfg: dict):
    """
    ШАГ 1 — Playwright загружает страницу как БОТ (авто)
    ШАГ 2 — Пользователь вставляет HTML как USER (вручную)
    ШАГ 3 — Сравнение метрик
    ШАГ 4 — Генерация отчёта
    """
    bot_mode  = cfg["BOT_MODE"]
    user_mode = ("chrome_mobile" if "smartphone" in bot_mode or "mobile" in bot_mode
                 else "chrome_desktop")

    line()
    print(f"  🚀 ЗАПУСК ПРОВЕРКИ")
    line()
    print(f"  URL      : {url}")
    print(f"  Бот      : {bot_mode}  (Playwright загрузит автоматически)")
    print(f"  Польз.   : {user_mode}  (HTML вставите вручную из браузера)")
    line()

    # ШАГ 1
    print("\n  ── ШАГ 1: загрузка как БОТ ────────────────────────────")
    bot_html, _ = fetch_bot_html(url, cfg)
    if not bot_html:
        print("  ❌ Не удалось получить HTML бота. Прерываем.")
        return
    _, bot_m = analyze_html(bot_html, f"БОТ ({bot_mode})")
    if not bot_m:
        return

    # ШАГ 2
    print("\n  ── ШАГ 2: HTML глазами ПОЛЬЗОВАТЕЛЯ ───────────────────")
    usr_html = read_user_html(url, user_mode)
    if not usr_html:
        print("  ❌ HTML пользователя не получен. Прерываем.")
        return
    _, usr_m = analyze_html(usr_html, f"ПОЛЬЗОВАТЕЛЬ ({user_mode})")
    if not usr_m:
        return

    # ШАГ 3
    print("\n  ── ШАГ 3: сравнение ────────────────────────────────────")
    compare_metrics(bot_m, usr_m)

    # ШАГ 4
    print("\n  ── ШАГ 4: генерация отчёта ─────────────────────────────")
    safe_url  = re.sub(r"[^\w]", "_", url)[:40]
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    out       = f"report_{timestamp}_{safe_url}.html"

    print("  🔍 Считаю метрики…")
    bot_bm = get_basic_metrics(bot_html)
    usr_bm = get_basic_metrics(usr_html)
    bot_d  = get_element_details(bot_html)
    usr_d  = get_element_details(usr_html)

    print("  📱 Строю прототип…")
    bot_p = extract_proto_blocks(bot_html)
    usr_p = extract_proto_blocks(usr_html)
    bot_p, usr_p = diff_proto_blocks(bot_p, usr_p)

    html_report = create_report(
        bot_metrics=bot_bm,      user_metrics=usr_bm,
        bot_details=bot_d,       user_details=usr_d,
        bot_proto=bot_p,         user_proto=usr_p,
        output_filename=out,
    )

    with open(out, "w", encoding="utf-8") as f:
        f.write(html_report)

    line()
    print(f"  ✅ Отчёт сохранён  : {out}  ({len(html_report)//1024} KB)")
    print(f"  🌐 Запустите сервер: python -m http.server 8000")
    print(f"     Откройте        : http://localhost:8000/{os.path.basename(out)}")
    line()

    # Предложим открыть сразу
    if yn("  Открыть отчёт в браузере прямо сейчас?"):
        start_web_server(8000)
        if _server_instance:
            url = f"http://localhost:{_server_port}/{os.path.basename(out)}"
            print(f"  🔗 Открываю: {url}")
            webbrowser.open(url)


# ═══════════════════════════════════════════════════════════════
# WEB-СЕРВЕР ДЛЯ ПРОСМОТРА ОТЧЁТОВ
# ═══════════════════════════════════════════════════════════════

_server_instance = None
_server_thread   = None
_server_port     = 8000


def find_reports() -> list[str]:
    """Возвращает список report_*.html в текущей папке, свежие — первыми."""
    files = glob.glob("report_*.html")
    files.sort(key=os.path.getmtime, reverse=True)
    return files


def start_web_server(port: int = 8000):
    """Запускает http.server в фоновом потоке. Если уже запущен — ничего не делает."""
    global _server_instance, _server_thread, _server_port

    if _server_instance is not None:
        print(f"\n  ℹ  Сервер уже работает на порту {_server_port}")
        return

    cwd = os.getcwd()

    class QuietHandler(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *args): pass   # молчим в консоли

    try:
        _server_instance = socketserver.TCPServer(("", port), QuietHandler)
        _server_instance.allow_reuse_address = True
        _server_port = port
    except OSError:
        print(f"\n  ⚠  Порт {port} занят, пробую {port + 1}…")
        port += 1
        try:
            _server_instance = socketserver.TCPServer(("", port), QuietHandler)
            _server_instance.allow_reuse_address = True
            _server_port = port
        except OSError as e:
            print(f"  ❌ Не удалось запустить сервер: {e}")
            _server_instance = None
            return

    _server_thread = threading.Thread(target=_server_instance.serve_forever, daemon=True)
    _server_thread.start()
    print(f"\n  ✅ Сервер запущен: http://localhost:{_server_port}/")
    print(f"     Директория    : {cwd}")


def stop_web_server():
    global _server_instance, _server_thread
    if _server_instance is None:
        print("\n  ℹ  Сервер не запущен")
        return
    _server_instance.shutdown()
    _server_instance = None
    _server_thread   = None
    print(f"\n  ✅ Сервер остановлен")


def server_menu():
    """Подменю управления сервером и открытия отчётов."""
    global _server_instance, _server_port

    while True:
        reports = find_reports()

        line()
        print("  🌐  Web-сервер для просмотра отчётов")
        line()

        # Статус сервера
        if _server_instance:
            print(f"  ✅ Сервер работает  →  http://localhost:{_server_port}/")
        else:
            print(f"  ⛔ Сервер не запущен")

        # Список отчётов
        print()
        if reports:
            print("  📄 Доступные отчёты:")
            for i, f in enumerate(reports, 1):
                size_kb = os.path.getsize(f) // 1024
                mtime   = time.strftime("%d.%m %H:%M", time.localtime(os.path.getmtime(f)))
                mark    = "  ◀ последний" if i == 1 else ""
                print(f"    {i:>2}. {f}  ({size_kb} KB, {mtime}){mark}")
        else:
            print("  📄 Отчётов пока нет (запустите проверку)")

        print()
        line("─")
        if _server_instance:
            print("  1. 🔗 Открыть отчёт в браузере (выбрать)")
            print("  2. 🔗 Открыть последний отчёт")
            print("  3. ⛔ Остановить сервер")
        else:
            print("  1. ▶  Запустить сервер (порт 8000)")
            print("  2. ▶  Запустить сервер (другой порт)")
        print("  0. ← Назад")
        line("─")

        ch = inp("Выбор", "0")

        if ch == "0":
            break

        elif ch == "1":
            if _server_instance:
                # Открыть выбранный отчёт
                if not reports:
                    print("  ⚠  Нет отчётов для открытия")
                elif len(reports) == 1:
                    url = f"http://localhost:{_server_port}/{reports[0]}"
                    print(f"  🔗 Открываю: {url}")
                    webbrowser.open(url)
                else:
                    raw = inp(f"Номер отчёта (1–{len(reports)})", "1")
                    try:
                        idx = int(raw) - 1
                        if 0 <= idx < len(reports):
                            url = f"http://localhost:{_server_port}/{reports[idx]}"
                            print(f"  🔗 Открываю: {url}")
                            webbrowser.open(url)
                        else:
                            print("  ⚠  Неверный номер")
                    except ValueError:
                        print("  ⚠  Введите число")
            else:
                # Запустить на порту 8000
                start_web_server(8000)
                if _server_instance and reports:
                    url = f"http://localhost:{_server_port}/{reports[0]}"
                    print(f"  🔗 Открываю последний отчёт: {url}")
                    webbrowser.open(url)

        elif ch == "2":
            if _server_instance:
                # Открыть последний отчёт
                if not reports:
                    print("  ⚠  Нет отчётов для открытия")
                else:
                    url = f"http://localhost:{_server_port}/{reports[0]}"
                    print(f"  🔗 Открываю: {url}")
                    webbrowser.open(url)
            else:
                # Запустить на пользовательском порту
                raw = inp("Порт", "8000")
                try:
                    port = int(raw)
                    start_web_server(port)
                    if _server_instance and reports:
                        url = f"http://localhost:{_server_port}/{reports[0]}"
                        print(f"  🔗 Открываю последний отчёт: {url}")
                        webbrowser.open(url)
                except ValueError:
                    print("  ⚠  Введите число")

        elif ch == "3" and _server_instance:
            stop_web_server()

        else:
            print("  ⚠  Неизвестная команда")


# ═══════════════════════════════════════════════════════════════
# ГЛАВНОЕ МЕНЮ
# ═══════════════════════════════════════════════════════════════

def main():
    cfg     = dict(DEFAULTS)
    current = os.getenv("TARGET_URL", "")

    for arg in sys.argv[1:]:
        if arg in ("--help", "-h"):
            print("Использование: python checker.py [URL]")
            sys.exit(0)
        if arg.startswith(("http://", "https://", "www.")):
            current = arg if arg.startswith("http") else "https://" + arg
            break

    if current:
        add_to_history(current)

    while True:
        line()
        print("  🔍  SSR / Cloaking Checker")
        line()
        print(f"  URL      : {current or '(не задан)'}")
        print(f"  Bot Mode : {cfg['BOT_MODE']}")
        # статус сервера в меню
        srv_status = f"✅ работает на :{_server_port}" if _server_instance else "⛔ не запущен"
        line("─")
        print("  1. 🚀 Запустить проверку")
        print("  2. 🌐 Изменить URL")
        print("  3. 📋 История URL")
        print("  4. ⚙  Настройки")
        print(f"  5. 🖥  Web-сервер / отчёты  [{srv_status}]")
        print("  0. ❌ Выход")
        line("─")

        ch = inp("Выбор", "1" if current else "2")

        if ch == "1":
            if not current:
                print("  ⚠  Сначала введите URL (пункт 2)")
                continue
            try:
                run_check(current, cfg)
            except KeyboardInterrupt:
                print("\n  ⏹  Прервано")
            input("\n  Enter чтобы вернуться в меню…")

        elif ch == "2":
            new = prompt_url(current)
            if new:
                current = new
                add_to_history(current)
            if current and yn("\n  Запустить проверку сразу?"):
                try:
                    run_check(current, cfg)
                except KeyboardInterrupt:
                    print("\n  ⏹  Прервано")
                input("\n  Enter чтобы вернуться в меню…")

        elif ch == "3":
            line("─")
            if not url_history:
                print("  (история пуста)")
            else:
                print("  📋 История URL:")
                for i, u in enumerate(url_history, 1):
                    mark = "  ◀ активный" if u == current else ""
                    print(f"    {i:>2}. {u}{mark}")
                line("─")
                raw = inp("Выбрать номер (Enter — пропустить)", "")
                if raw.isdigit():
                    idx = int(raw) - 1
                    if 0 <= idx < len(url_history):
                        current = url_history[idx]
                        print(f"  ✅ Активен: {current}")

        elif ch == "4":
            cfg = settings_menu(cfg)

        elif ch == "5":
            server_menu()

        elif ch == "0":
            print("\n  До свидания! 👋\n")
            break

        else:
            print("  ⚠  Неизвестная команда")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n  ❌ Прервано\n")
    except Exception as e:
        print(f"\n\n  ❌ Критическая ошибка: {e}")
        import traceback
        traceback.print_exc()
