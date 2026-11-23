#!/usr/bin/env bash
# Speichert die eBay-Keys (Production) als GitHub-Secrets.
# Werte werden aus der Zwischenablage gelesen (oder unsichtbar eingefügt), geprüft und nicht angezeigt.
set -euo pipefail
cd "$(dirname "$0")"

grab() {  # $1 = Beschreibung, $2 = Regex
  local raw val
  echo "Kopiere die $1 auf developer.ebay.com (Kopier-Symbol daneben) und drück dann Enter:" >&2
  read -r -s raw || true; echo >&2
  [[ -z "$raw" ]] && raw="$(pbpaste 2>/dev/null || true)"
  val="$(printf '%s' "$raw" | grep -oE "$2" | head -1 || true)"
  [[ -z "$val" ]] && { echo "✗ Keine gültige $1 gefunden. Skript bitte neu starten." >&2; exit 1; }
  printf '%s' "$val"
}

echo "== eBay-Keys (Production) =="
EID="$(grab "App ID (Client ID)" '[A-Za-z0-9]+-[A-Za-z0-9]+-PRD-[A-Za-z0-9-]+')"
echo "✓ App ID erkannt"
ESEC="$(grab "Cert ID (Client Secret)" 'PRD-[A-Za-z0-9-]{10,}')"
echo "✓ Cert ID erkannt"

echo "Prüfe die Keys bei eBay …"
echo "  (App ID: ${#EID} Zeichen, Cert ID: ${#ESEC} Zeichen, Anfang Cert ID: ${ESEC:0:4}…)"
RESP="$(curl -sS -u "$EID:$ESEC" -d grant_type=client_credentials \
     --data-urlencode scope=https://api.ebay.com/oauth/api_scope \
     -w '\n%{http_code}' https://api.ebay.com/identity/v1/oauth2/token || true)"
CODE="$(printf '%s' "$RESP" | tail -1)"
if [[ "$CODE" == "200" ]]; then
  echo "✓ eBay akzeptiert die Keys"
else
  echo "✗ eBay lehnt die Keys ab (HTTP $CODE):"
  printf '%s' "$RESP" | sed '$d' | python3 -c 'import sys,json
try:
  d=json.load(sys.stdin); print("  ", d.get("error"), "-", d.get("error_description"))
except Exception: print("   (keine Details)")'
  echo "  Mögliche Gründe: Keyset noch nicht freigeschaltet (kann nach der Ausnahme etwas dauern),"
  echo "  oder App ID und Cert ID nicht aus demselben Production-Keyset."
  exit 1
fi
unset RESP
printf '%s' "$EID"  | gh secret set EBAY_CLIENT_ID
printf '%s' "$ESEC" | gh secret set EBAY_CLIENT_SECRET
unset EID ESEC
echo "✓ In GitHub gespeichert"

echo "Starte den Bot neu …"
for id in $(gh run list --workflow deal-bot.yml --status in_progress --json databaseId -q '.[].databaseId'); do gh run cancel "$id" >/dev/null || true; done
gh workflow run deal-bot.yml && echo "✓ Fertig. eBay wird ab jetzt alle 15 Minuten durchsucht."
