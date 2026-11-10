# Black-Week Deal-Bot

Schickt dir Deals per Telegram aufs Handy. Zwei Wege:

1. **Deal-Feeds aus ganz Europa** (alle 5 min): mydealz 🇩🇪, Preisjäger 🇦🇹, Dealabs 🇫🇷, Chollometro 🇪🇸, Pepper NL 🇳🇱, hotukdeals 🇬🇧.
   Der Bot sucht dabei nach **Kategorien mit €/TB-Grenze** statt nach festen Modellen. So fallen auch unbekannte Händler und Mehrfachpacks auf, etwa
   „2× Angelbird 1 TB für 423 € bei einem italienischen Händler“ (≈ 212 €/TB → 🚨). Mehrfachpacks
   (2x, 2er, Doppelpack, lot de 2, pack of 2 …) werden pro Stück gerechnet.
2. **Geizhals EU** (alle 30 min): feste Produktseiten mit Ziel- und Sofort-Kauf-Preis. Erfasst Händler aus DE, AT, PL und UK.

| Alarm | Bedeutung |
|---|---|
| 🚨 TOP-DEAL / SOFORT KAUFEN | unter `hot_eur_per_tb` bzw. `buy_now` |
| 🛒 Deal / 🔥 Zielpreis | unter `max_eur_per_tb` bzw. `target` |
| 📉 −X % | Geizhals-Preis mind. 12 % unter dem Startpreis |
| ❔ prüfen | CFexpress-Deal, aber Preis/Kapazität nicht im Titel erkennbar |
| ⚠️ | eine Produktseite lässt sich seit ~1,5 h nicht mehr abrufen |

Aktuelle Grenzen (in `config.toml` änderbar):

| Kategorie | 🛒 Deal | 🚨 Top |
|---|---|---|
| CFexpress Type B | ≤ 320 €/TB | ≤ 250 €/TB |
| Portable SSD | ≤ 150 €/TB | ≤ 115 €/TB |
| HDD (NAS/extern) | ≤ 28 €/TB | ≤ 22 €/TB |
| NAS-Gehäuse | ≤ 450 € | – |

## Einrichtung (ca. 10 min)

1. **Telegram-Bot anlegen:** Schreib in Telegram an `@BotFather`, dann `/newbot`. Du bekommst ein **Token**.
2. **Chat-ID holen:** Schick deinem Bot eine Nachricht. Öffne dann `https://api.telegram.org/bot<TOKEN>/getUpdates` und lies `"chat":{"id": …}` ab.
3. **Lokal testen:**
   ```bash
   TELEGRAM_BOT_TOKEN=xxx TELEGRAM_CHAT_ID=yyy python3 deal_bot.py --test
   ```
4. **Rund um die Uhr laufen lassen (GitHub Actions):**
   - Am besten als **öffentliches** Repo anlegen. Nur dort sind die Actions-Minuten unbegrenzt kostenlos.
     Ein privates Repo hat 2.000 min/Monat, und ein 5-Minuten-Takt verbraucht ~8.600.
     Öffentlich sichtbar wären nur Watchlist und Preise. Token und Chat-ID liegen geschützt als Secrets.
   - Unter *Settings → Secrets and variables → Actions* `TELEGRAM_BOT_TOKEN` und `TELEGRAM_CHAT_ID` anlegen.
   - Unter *Actions* den Workflow aktivieren und einmal manuell starten.
   - Beim ersten Lauf merkt sich der Bot nur die vorhandenen Deals. Gemeldet wird erst, was danach neu dazukommt.

## eBay einrichten (optional, ca. 15 min)
Der Bot durchsucht alle 15 min eBay DE, IT, FR und ES über die **offizielle Browse API**. Hier verkaufen auch Händler wie Virtual Foto.
Er meldet nur Neuware mit Sofortkauf und Versand nach DE, der Preis versteht sich inkl. Versand.
Verkäufer brauchen **≥ 98,5 % positive und ≥ 200 Bewertungen**. Das schützt vor gefälschten Karten.
Ein Angebot meldet er einmal und dann erneut, sobald es mindestens 3 % billiger wird.

1. Auf <https://developer.ebay.com> einen kostenlosen Account anlegen (mit deinem normalen eBay-Login).
2. Unter *Application Keys* ein **Production**-Keyset erzeugen.
3. eBay verlangt dabei eine Angabe zu „Marketplace Account Deletion“: Wähle die Ausnahme
   (*„I do not persist eBay data“*). Der Bot speichert nur Artikelnummern und Preise, keine Nutzerdaten.
4. **App ID (Client ID)** und **Cert ID (Client Secret)** als GitHub-Secrets `EBAY_CLIENT_ID` und `EBAY_CLIENT_SECRET` anlegen.

Ohne diese Secrets überspringt der Bot eBay einfach, alles andere läuft weiter.

## Bekannte Lücken
- **Amazon IT/FR/ES** wird nicht direkt durchsucht. Dafür eignen sich Keepa-Preisalarme.
- **Italienische Preisvergleiche:** pepper.it ist geschlossen, und trovaprezzi.it sowie idealo blockieren automatische Abrufe.
  Italienische Händler auf eBay.it sind über die API aber abgedeckt.
- Gefälschte Karten mit falscher Kapazität gibt es trotzdem. Prüfe neue Karten nach dem Kauf mit dem Tool *h2testw* oder *F3*.

## Watchlist ändern
- **Neues Produkt:** Die geizhals.eu-Produkt-URL ohne `?…` als neuen `[[product]]`-Block eintragen.
- **Neue Kategorie:** einen neuen `[[watch]]`-Block anlegen.
- **Neuer Deal-Feed:** einen neuen `[[feed]]`-Block anlegen.

`python3 deal_bot.py --dry-run` zeigt alles an, ohne etwas zu senden.

Fairness: Der Bot ruft nur Seiten auf, die laut robots.txt erlaubt sind (RSS und Produktseiten), mit Pausen dazwischen. Suchseiten und Bot-Sperren lässt er in Ruhe.
