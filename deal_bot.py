#!/usr/bin/env python3
"""Black-Week Preiswächter → Telegram.

Quellen:
  * Geizhals-Produktseiten (nur die konkreten Produkt-URLs aus config.toml,
    keine Suche – die ist laut robots.txt gesperrt)
  * Pepper-Deal-Feeds (mydealz & Co., EU), lokal nach Kategorie + €/TB gefiltert
  * eBay Browse API (DE/IT/FR/ES/AT), nur Neuware, nur Händler mit guten Bewertungen

Aufruf:
  python3 deal_bot.py            # prüfen + Telegram-Alarme senden
  python3 deal_bot.py --dry-run  # nur ausgeben, nichts senden, State nicht speichern
  python3 deal_bot.py --test     # Testnachricht an Telegram

Umgebungsvariablen: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, EBAY_CLIENT_ID, EBAY_CLIENT_SECRET
"""
from __future__ import annotations

import html
import json
import os
import re
import sys
import time
import tomllib
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
CONFIG = HERE / "config.toml"
STATE = HERE / "state.json"
UA = "Mozilla/5.0 (compatible; personal-price-watch/1.0)"
MYDEALZ_FEED = "https://www.mydealz.de/rss/alles"
PEPPER_NS = "{http://www.pepper.com/rss}"


# ---------------------------------------------------------------- helpers
def fetch(url: str, timeout: int = 25) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "de-DE"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="replace")


GBP_TO_EUR = 1.15


def parse_eur(text: str) -> float | None:
    """'€ 1.234,56' / '54.999€' / '1 299,99€' / '£1,299.99' -> Euro (float)"""
    t = re.sub(r"(?<=\d)[\s\xa0 ](?=\d)", "", text or "")
    m = re.search(r"\d[\d.,]*", t)
    if not m:
        return None
    n = m.group(0).rstrip(".,")
    if "," in n and "." in n:  # letztes Trennzeichen = Dezimal
        dec = "," if n.rfind(",") > n.rfind(".") else "."
        n = n.replace("." if dec == "," else ",", "").replace(dec, ".")
    elif re.search(r"[.,]\d{1,2}$", n):  # 429,00 / 12.99
        n = n.replace(",", ".")
        n = n[: n.rfind(".")].replace(".", "") + n[n.rfind(".") :]
    else:  # 54.999 / 1,299 → Tausender
        n = n.replace(".", "").replace(",", "")
    v = float(n)
    return round(v * GBP_TO_EUR, 2) if "£" in t else v


CAP_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s?(tb|to|gb|go)\b")
PACK_RE = re.compile(
    r"\b(\d)\s?(?:x|er|-?pack|stück|stk|pz|pcs)\b|\b(?:pack|lot|set) (?:of |de |da |van )?(\d)\b|\b(?:doppelpack|twin ?pack)\b"
)


def capacity_tb(title: str) -> float | None:
    """größte Kapazitätsangabe im Titel in TB (12TB, 1 To, 512GB …)"""
    caps = []
    for num, unit in CAP_RE.findall(title.lower()):
        v = float(num.replace(",", "."))
        caps.append(v if unit in ("tb", "to") else v / 1000)
    return max(caps) if caps else None


def pack_size(title: str) -> int:
    m = PACK_RE.search(title.lower())
    if not m:
        return 1
    n = m.group(1) or m.group(2)
    return int(n) if n and 1 < int(n) <= 8 else (2 if not n else 1)


def eur(v: float) -> str:
    return f"{v:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_state() -> dict:
    if STATE.exists():
        return json.loads(STATE.read_text())
    return {"products": {}, "mydealz_seen": [], "errors": {}}


def save_state(state: dict) -> None:
    state["mydealz_seen"] = state["mydealz_seen"][-1500:]
    STATE.write_text(json.dumps(state, indent=1, ensure_ascii=False))


def telegram(text: str, dry: bool) -> None:
    if dry:
        print("\n[TELEGRAM]\n" + re.sub(r"<[^>]+>", "", text) + "\n")
        return
    token, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat:
        sys.exit("TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID fehlen")
    data = urllib.parse.urlencode(
        {"chat_id": chat, "text": text, "parse_mode": "HTML", "disable_web_page_preview": "false"}
    ).encode()
    urllib.request.urlopen(f"https://api.telegram.org/bot{token}/sendMessage", data=data, timeout=20)


# --------------------------------------------------------------- geizhals
def geizhals_price(page: str) -> tuple[float | None, str]:
    """Bestpreis + Produktname von einer Geizhals-Produktseite."""
    title = html.unescape(re.search(r"<title>([^<]*)", page).group(1)) if "<title>" in page else ""
    name = re.split(r" ab €| \| Preisvergleich", title)[0].strip()
    # Geizhals' eigener Bestpreis steht im Seitentitel ("… ab € 469,90 (2026)").
    # Fehlt er, gibt es aktuell kein lieferbares Angebot.
    m = re.search(r"ab €\s*([\d.,]+)", title.replace("\xa0", " "))
    return (parse_eur(m.group(1)) if m else None), name


def check_products(cfg: dict, state: dict, dry: bool) -> list[str]:
    alerts, report = [], []
    drop = cfg["settings"].get("drop_alert_pct", 12) / 100
    for p in cfg.get("product", []):
        key = p["url"]
        st = state["products"].setdefault(key, {})
        try:
            price, name = geizhals_price(fetch(p["url"]))
            state["errors"].pop(key, None)
        except Exception as e:  # noqa: BLE001
            state["errors"][key] = state["errors"].get(key, 0) + 1
            report.append(f"FEHLER {p['name']}: {e}")
            if state["errors"][key] == 6:  # ~1,5 h am Stück kaputt → einmal melden
                alerts.append(f"⚠️ Abruf klappt nicht mehr: <a href=\"{p['url']}\">{html.escape(p['name'])}</a> ({html.escape(str(e))[:120]})")
            time.sleep(cfg["settings"].get("delay_s", 4))
            continue
        time.sleep(cfg["settings"].get("delay_s", 4))
        if price is None:
            report.append(f"{'kein Angebot':>12}  {p['name']}")
            continue
        ref = p.get("target") or st.get("baseline")
        if ref and price < ref * 0.4:  # unplausibel billig → Parser/Fake, nicht alarmieren
            report.append(f"VERDÄCHTIG {eur(price)}  {p['name']}")
            continue

        st.setdefault("baseline", price)
        st.setdefault("first_seen", now_iso())
        st["lowest"] = min(st.get("lowest", price), price)
        st["last"] = price
        st["checked"] = now_iso()
        target, buy = p.get("target"), p.get("buy_now")
        report.append(f"{eur(price):>12}  Ziel {eur(target) if target else '-':>10}  {p['name']}")

        level = None
        if buy and price <= buy:
            level = "🚨 SOFORT KAUFEN"
        elif target and price <= target:
            level = "🔥 Zielpreis erreicht"
        elif price <= st["baseline"] * (1 - drop):
            level = f"📉 −{(1 - price / st['baseline']) * 100:.0f} % vs. Start"
        # nur melden, wenn neuer Tiefpunkt seit letztem Alarm (kein Spam)
        if level and price < st.get("alerted_at", float("inf")):
            st["alerted_at"] = price
            alerts.append(
                f"{level} [{p.get('prio', '')}]\n<b>{html.escape(p['name'])}</b>\n"
                f"Jetzt: <b>{eur(price)}</b> (Start {eur(st['baseline'])}"
                + (f", Ziel {eur(target)}" if target else "")
                + f")\n<a href=\"{p['url']}\">→ Geizhals</a>"
            )
        elif not level and st.get("alerted_at") and price > st["alerted_at"] * 1.05:
            st.pop("alerted_at")  # Deal vorbei → nächstes Mal wieder melden
    print("\n".join(report))
    return alerts


# ------------------------------------------------- Deal-Feeds (Pepper-Netzwerk)
def rule_matches(w: dict, low: str) -> bool:
    if w.get("all") and not all(t.lower() in low for t in w["all"]):
        return False
    if w.get("any") and not any(t.lower() in low for t in w["any"]):
        return False
    return not any(t.lower() in low for t in w.get("none", []))


def evaluate(w: dict, title: str, price: float | None) -> tuple[str, str] | None:
    """→ (Stufe, Detailtext) oder None, wenn der Deal die Regel nicht erfüllt."""
    if w.get("max_price") and price and price > w["max_price"]:
        return None
    detail = ""
    if w.get("max_eur_per_tb"):
        cap, pack = capacity_tb(title), pack_size(title)
        if not (price and cap):
            return ("❔ prüfen", "Preis/Kapazität nicht erkannt") if w.get("alert_unknown") else None
        per_tb = price / (cap * pack)
        if per_tb > w["max_eur_per_tb"]:
            return None
        detail = f"≈ {eur(per_tb)}/TB" + (f" · {pack} Stück à {eur(price / pack)}" if pack > 1 else "")
        if w.get("hot_eur_per_tb") and per_tb <= w["hot_eur_per_tb"]:
            return ("🚨 TOP-DEAL", detail)
    return ("🛒 Deal", detail)


def check_feeds(cfg: dict, state: dict, dry: bool) -> list[str]:
    seen = set(state["mydealz_seen"])
    boot = state.setdefault("feeds_bootstrapped", [])
    alerts = []
    for f in cfg.get("feed", []):
        try:
            root = ET.fromstring(fetch(f["url"]))
        except Exception as e:  # noqa: BLE001
            print(f"FEHLER {f['name']}: {e}")
            continue
        bootstrap = f["url"] not in boot  # erster Lauf je Feed: nur merken
        hits = 0
        for item in root.iter("item"):
            guid = (item.findtext("guid") or item.findtext("link") or "").strip()
            if not guid or guid in seen:
                continue
            state["mydealz_seen"].append(guid)
            seen.add(guid)
            title = (item.findtext("title") or "").strip()
            merchant = item.find(f"{PEPPER_NS}merchant")
            price = parse_eur(merchant.get("price", "")) if merchant is not None else None
            shop = merchant.get("name", "") if merchant is not None else ""
            low = title.lower()
            for w in cfg.get("watch", []):
                if not rule_matches(w, low):
                    continue
                res = evaluate(w, title, price)
                if res is None:
                    break
                level, detail = res
                hits += 1
                msg = (
                    f"{level} · {html.escape(w['label'])} · {f['flag']} {html.escape(f['name'])}\n"
                    f"<b>{html.escape(title)}</b>\n{eur(price) if price else '?'} – {html.escape(shop)}"
                    + (f"\n{detail}" if detail else "")
                    + (f"\n⚠️ {html.escape(f['note'])}" if f.get("note") else "")
                    + f"\n<a href=\"{html.escape(item.findtext('link') or guid)}\">→ Deal</a>"
                )
                if bootstrap or dry:
                    print(("(bootstrap) " if bootstrap else "") + re.sub(r"<[^>]+>", "", msg).replace("\n", " | "))
                if not bootstrap:
                    alerts.append(msg)
                break
        if bootstrap:
            boot.append(f["url"])
        print(f"{f['flag']} {f['name']}: ok, {hits} Treffer")
    return alerts


# ------------------------------------------------------------- eBay (API)
# Offizielle eBay Browse API (kein Scraping). Braucht EBAY_CLIENT_ID + EBAY_CLIENT_SECRET.
EBAY_API = "https://api.ebay.com"
EBAY_FLAGS = {"EBAY_DE": "🇩🇪", "EBAY_IT": "🇮🇹", "EBAY_FR": "🇫🇷", "EBAY_ES": "🇪🇸", "EBAY_AT": "🇦🇹", "EBAY_NL": "🇳🇱"}


def ebay_token() -> str | None:
    cid, sec = os.environ.get("EBAY_CLIENT_ID"), os.environ.get("EBAY_CLIENT_SECRET")
    if not cid or not sec:
        return None
    import base64

    req = urllib.request.Request(
        f"{EBAY_API}/identity/v1/oauth2/token",
        data=urllib.parse.urlencode(
            {"grant_type": "client_credentials", "scope": "https://api.ebay.com/oauth/api_scope"}
        ).encode(),
        headers={
            "Authorization": "Basic " + base64.b64encode(f"{cid}:{sec}".encode()).decode(),
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read())["access_token"]


def ebay_search(token: str, marketplace: str, q: str, s: dict, deliver_to: str) -> list[dict]:
    flt = [
        "buyingOptions:{FIXED_PRICE}",
        "conditionIds:{1000}",  # neu
        f"price:[{s.get('min_price', 20)}..{s.get('max_price', 2000)}]",
        "priceCurrency:EUR",
        f"deliveryCountry:{deliver_to}",
    ]
    qs = urllib.parse.urlencode({"q": q, "filter": ",".join(flt), "sort": "price", "limit": 50})
    req = urllib.request.Request(
        f"{EBAY_API}/buy/browse/v1/item_summary/search?{qs}",
        headers={
            "Authorization": f"Bearer {token}",
            "X-EBAY-C-MARKETPLACE-ID": marketplace,
            "X-EBAY-C-ENDUSERCTX": f"contextualLocation=country={deliver_to}",
        },
    )
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.loads(r.read()).get("itemSummaries", [])


def ebay_total(it: dict) -> float | None:
    try:
        price = float(it["price"]["value"])
    except (KeyError, ValueError):
        return None
    ship = (it.get("shippingOptions") or [{}])[0].get("shippingCost", {}).get("value")
    return price + float(ship or 0)


def ebay_evaluate(cfg: dict, s: dict, it: dict) -> tuple[str, str, float] | None:
    """Regel-Prüfung + Händler-Check für ein eBay-Angebot."""
    rules = {w["label"]: w for w in cfg.get("watch", [])}
    w = rules[s["rule"]]
    title = it.get("title", "")
    if not rule_matches(w, title.lower()):
        return None
    eb = cfg.get("ebay", {})
    seller = it.get("seller", {})
    try:
        fb_pct, fb_n = float(seller.get("feedbackPercentage", 0)), int(seller.get("feedbackScore", 0))
    except ValueError:
        fb_pct, fb_n = 0.0, 0
    if fb_pct < eb.get("min_feedback_pct", 98.5) or fb_n < eb.get("min_feedback_count", 200):
        return None  # Schutz vor Fake-Karten von Neu-Accounts
    total = ebay_total(it)
    res = evaluate(w, title, total)
    if res is None or res[0].startswith("❔"):
        return None
    return res[0], res[1], total


def check_ebay(cfg: dict, state: dict, dry: bool) -> list[str]:
    eb = cfg.get("ebay", {})
    if not eb.get("search"):
        return []
    try:
        token = ebay_token()
    except Exception as e:  # noqa: BLE001
        print(f"FEHLER eBay-Login: {e}")
        return []
    if not token:
        print("eBay: übersprungen (EBAY_CLIENT_ID / EBAY_CLIENT_SECRET fehlen)")
        return []
    seen: dict = state.setdefault("ebay_seen", {})  # itemId -> zuletzt gemeldeter Preis
    alerts = []
    for s in eb["search"]:
        found = []
        for mp in s.get("marketplaces", eb.get("marketplaces", ["EBAY_DE"])):
            try:
                items = ebay_search(token, mp, s["q"], s, eb.get("deliver_to", "DE"))
            except Exception as e:  # noqa: BLE001
                print(f"FEHLER eBay {mp} '{s['q']}': {e}")
                continue
            for it in items:
                res = ebay_evaluate(cfg, s, it)
                if res:
                    found.append((res, mp, it))
        found.sort(key=lambda x: x[0][2])
        n_new = 0
        for (level, detail, total), mp, it in found:
            iid = it.get("legacyItemId") or it.get("itemId")
            last = seen.get(iid)
            if last is not None and total >= last * 0.97:  # schon gemeldet, nicht billiger
                continue
            seen[iid] = total
            if n_new >= eb.get("max_alerts_per_search", 5):
                continue
            n_new += 1
            seller = it.get("seller", {})
            loc = it.get("itemLocation", {}).get("country", "?")
            alerts.append(
                f"{level} · {html.escape(s['rule'])} · {EBAY_FLAGS.get(mp, '')} eBay"
                + (" (billiger geworden)" if last else "")
                + f"\n<b>{html.escape(it.get('title', ''))}</b>\n"
                f"{eur(total)} inkl. Versand – {html.escape(seller.get('username', '?'))} "
                f"({seller.get('feedbackPercentage', '?')} %, {seller.get('feedbackScore', '?')} Bew.) · Standort {loc}"
                + (f"\n{detail}" if detail else "")
                + f"\n<a href=\"{html.escape(it.get('itemWebUrl', ''))}\">→ eBay</a>"
            )
        print(f"eBay '{s['q']}': {len(found)} passende, {n_new} neu gemeldet")
    return alerts


# ------------------------------------------------------------------- main
def main() -> None:
    dry = "--dry-run" in sys.argv
    if "--test" in sys.argv:
        telegram("✅ Black-Week-Bot ist verbunden.", dry=False)
        return
    cfg = tomllib.loads(CONFIG.read_text())
    state = load_state()
    alerts = check_feeds(cfg, state, dry)
    minute = datetime.now(timezone.utc).minute  # Geizhals seltener abfragen
    every = cfg["settings"].get("geizhals_every_min", 30)
    step = cfg["settings"].get("run_every_min", 10)
    if dry or "--all" in sys.argv or minute % every < step:
        alerts += check_products(cfg, state, dry)
    if dry or "--all" in sys.argv or minute % cfg["settings"].get("ebay_every_min", 15) < step:
        alerts += check_ebay(cfg, state, dry)
    for a in alerts:
        telegram(a, dry)
    if not dry:
        save_state(state)
    print(f"{len(alerts)} Alarm(e)")


if __name__ == "__main__":
    main()
