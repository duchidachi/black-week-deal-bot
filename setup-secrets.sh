#!/usr/bin/env bash
# Trägt Telegram- und eBay-Zugangsdaten als GitHub-Secrets ein.
# Die Eingaben werden nicht angezeigt und nirgends gespeichert, außer verschlüsselt bei GitHub.
set -euo pipefail
cd "$(dirname "$0")"

ask() {  # $1 = Secret-Name, $2 = Beschreibung, $3 = optional?
  local val
  read -r -s -p "$2${3:+ (Enter = überspringen)}: " val; echo
  if [[ -z "$val" ]]; then
    [[ -n "${3:-}" ]] && { echo "  → $1 übersprungen"; return; }
    echo "  → $1 ist Pflicht"; exit 1
  fi
  printf '%s' "$val" | gh secret set "$1" && echo "  ✓ $1 gesetzt"
}

echo "== Telegram =="
ask TELEGRAM_BOT_TOKEN "Bot-Token von @BotFather"
ask TELEGRAM_CHAT_ID   "Chat-ID (aus getUpdates)"
echo "== eBay (optional) =="
ask EBAY_CLIENT_ID     "eBay App ID / Client ID" opt
ask EBAY_CLIENT_SECRET "eBay Cert ID / Client Secret" opt

echo
echo "Starte Testlauf auf GitHub …"
gh workflow run deal-bot.yml && echo "✓ Läuft. Status: gh run list --workflow deal-bot.yml"
