#!/usr/bin/env bash
# Verbindet den Deal-Bot mit Telegram (und optional eBay).
# - fragt das Bot-Token verdeckt ab und prüft es
# - holt deine Chat-ID automatisch, sobald du dem Bot "Start" drückst
# - speichert alles verschlüsselt als GitHub-Secrets und schickt eine Testnachricht
# Die Werte werden nicht angezeigt und nirgends lokal gespeichert.
set -euo pipefail
cd "$(dirname "$0")"

api() { curl -fsS "https://api.telegram.org/bot${TOKEN}/$1" "${@:2}"; }

echo "== 1/3 Telegram-Bot =="
echo "Kopiere das Token (oder die ganze BotFather-Nachricht) und drück dann einfach Enter."
echo "(Du kannst es auch hier einfügen, die Eingabe ist unsichtbar.)"
read -r -s RAW || true; echo
[[ -z "$RAW" ]] && RAW="$(pbpaste 2>/dev/null || true)" && echo "→ nehme Token aus der Zwischenablage"
TOKEN="$(printf '%s' "$RAW" | grep -oE '[0-9]{8,12}:[A-Za-z0-9_-]{30,}' | head -1 || true)"
unset RAW
if [[ -z "$TOKEN" ]]; then
  echo "✗ Kein Token gefunden. Es sieht aus wie 1234567890:AAH… (Zahl, Doppelpunkt, lange Zeichenkette)."
  echo "  Tipp: In Telegram auf das orange Token klicken, das kopiert es. Dann Skript neu starten und nur Enter drücken."
  exit 1
fi
ME="$(api getMe 2>/dev/null || true)"
USERNAME="$(printf '%s' "$ME" | python3 -c 'import sys,json;print(json.load(sys.stdin)["result"]["username"])' 2>/dev/null || true)"
if [[ -z "$USERNAME" ]]; then
  echo "✗ Token ungültig. Kopiere es nochmal komplett aus dem BotFather-Chat (inkl. Zahl vor dem Doppelpunkt)."; exit 1
fi
echo "✓ Bot gefunden: @$USERNAME"
api deleteWebhook >/dev/null || true

echo
echo "== 2/3 Chat verbinden =="
echo "Öffne jetzt auf dem Handy: https://t.me/$USERNAME"
echo "und tippe unten auf START (oder schreib ihm irgendwas). Ich warte bis zu 3 Minuten …"
open "https://t.me/$USERNAME" 2>/dev/null || true
CHAT=""
for _ in $(seq 1 36); do
  CHAT="$( (api getUpdates || true) | python3 -c '
import sys,json
try:
    r=json.load(sys.stdin).get("result",[])
except Exception:
    r=[]
ids=[u[k]["chat"]["id"] for u in r for k in ("message","my_chat_member") if k in u]
print(ids[-1] if ids else "")' )"
  [[ -n "$CHAT" ]] && break
  sleep 5
done
if [[ -z "$CHAT" ]]; then
  echo "✗ Keine Nachricht angekommen. Hast du beim richtigen Bot (@$USERNAME) auf START getippt? Skript einfach nochmal starten."; exit 1
fi
api sendMessage --data-urlencode "chat_id=$CHAT" --data-urlencode "text=✅ Black-Week-Bot ist verbunden. Ab jetzt kommen hier die Deals." >/dev/null
echo "✓ Chat verbunden, Testnachricht gesendet. Schau aufs Handy!"
printf '%s' "$TOKEN" | gh secret set TELEGRAM_BOT_TOKEN
printf '%s' "$CHAT"  | gh secret set TELEGRAM_CHAT_ID
echo "✓ In GitHub gespeichert"

echo
echo "== 3/3 eBay (optional, Enter = überspringen) =="
read -r -s -p "eBay App ID / Client ID: " EID; echo
if [[ -n "$EID" ]]; then
  read -r -s -p "eBay Cert ID / Client Secret: " ESEC; echo
  printf '%s' "$EID"  | gh secret set EBAY_CLIENT_ID
  printf '%s' "$ESEC" | gh secret set EBAY_CLIENT_SECRET
  echo "✓ eBay gespeichert"
else
  echo "→ eBay übersprungen (später einfach Skript nochmal starten)"
fi

echo
echo "Starte den Bot auf GitHub neu …"
for id in $(gh run list --workflow deal-bot.yml --status in_progress --json databaseId -q '.[].databaseId'); do gh run cancel "$id" >/dev/null || true; done
gh workflow run deal-bot.yml && echo "✓ Fertig. Der Bot läuft und meldet sich, sobald ein Deal auftaucht."
