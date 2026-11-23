#!/usr/bin/env python3
"""Baut Black-Week-Funde.xlsx aus den Bot-Protokollen.

Quellen (alle optional): market.csv (eBay-Marktaufnahmen), alerts.csv (gesendete Alarme),
prices.csv (Geizhals-Messungen), state.json (gemeldete eBay-Angebote) und – als Nachtrag
für die Zeit vor dem CSV-Protokoll – heruntergeladene GitHub-Run-Logs (--logs ORDNER).

Aufruf:  python3 build_excel.py [--logs ORDNER] [--out Black-Week-Funde.xlsx]
"""
from __future__ import annotations

import csv
import json
import re
import sys
import tomllib
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.table import Table, TableStyleInfo

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import deal_bot as bot  # noqa: E402

FONT = "Arial"
F = Font(name=FONT, size=10)
B = Font(name=FONT, size=10, bold=True)
H1 = Font(name=FONT, size=14, bold=True)
BLUE = Font(name=FONT, size=10, color="0000FF")
LINK = Font(name=FONT, size=10, color="0563C1", underline="single")
HEAD_FILL = PatternFill("solid", fgColor="1F3864")
HEAD_FONT = Font(name=FONT, size=10, bold=True, color="FFFFFF")
GOOD = PatternFill("solid", fgColor="E2EFDA")
BAD = PatternFill("solid", fgColor="FCE4D6")
EUR = '#,##0.00 "€";-#,##0.00 "€";"-"'
EUR0 = '#,##0 "€";-#,##0 "€";"-"'

STORAGE = ["CFexpress Type B", "Portable SSD", "HDD Archiv/NAS"]


def arg(name: str, default: str | None = None) -> str | None:
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


def num(x) -> float | None:
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def read_csv(name: str) -> list[dict]:
    p = HERE / name
    return list(csv.DictReader(p.open(encoding="utf-8"))) if p.exists() else []


def item_id(url: str) -> str:
    return url.rstrip("/").split("/")[-1].split("?")[0]


def header(ws, row: int, cols: list[str], widths: list[int]) -> None:
    for i, (c, w) in enumerate(zip(cols, widths), 1):
        cell = ws.cell(row=row, column=i, value=c)
        cell.font, cell.fill = HEAD_FONT, HEAD_FILL
        cell.alignment = Alignment(vertical="center", wrap_text=True)
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = ws.cell(row=row + 1, column=1)


def add_table(ws, ref: str, name: str) -> None:
    t = Table(displayName=name, ref=ref)
    t.tableStyleInfo = TableStyleInfo(name="TableStyleLight9", showRowStripes=True)
    ws.add_table(t)


def link(cell, url: str, text: str = "öffnen") -> None:
    if url:
        cell.value, cell.hyperlink, cell.font = text, url, LINK


# ------------------------------------------------------------------ Daten
cfg = tomllib.loads((HERE / "config.toml").read_text())
rules = {w["label"]: w for w in cfg.get("watch", [])}
market = read_csv("market.csv")
latest = max((r["snapshot_utc"] for r in market), default="")
snap = [r for r in market if r["snapshot_utc"] == latest]
state = json.loads((HERE / "state.json").read_text()) if (HERE / "state.json").exists() else {}

# Geizhals-Verlauf: prices.csv + (optional) alte Run-Logs
prices = [(r["zeit_utc"][:19].replace("T", " "), r["produkt"], num(r["preis_eur"]), num(r["ziel_eur"]), num(r["sofort_eur"]))
          for r in read_csv("prices.csv")]
targets = {p["name"]: (p.get("target"), p.get("buy_now")) for p in cfg.get("product", [])}
logs = arg("--logs")
log_alarms: list[tuple[str, str, str, str]] = []
if logs:
    line_re = re.compile(r"(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)\.\d+Z\s+([\d.,]+) €\s+Ziel\s+\S+ €\s+(.+)$")
    for f in sorted(Path(logs).glob("*.log")):
        lines = f.read_text(errors="ignore").splitlines()
        for i, ln in enumerate(lines):
            if m := line_re.search(ln):
                name = m.group(3).strip()
                t, b = targets.get(name, (None, None))
                prices.append((m.group(1).replace("T", " "), name, bot.parse_eur(m.group(2)), t, b))
            if "[ALARM" in ln:
                block = [re.sub(r"^.*?Z ", "", x).strip() for x in lines[i + 1:i + 6]]
                ts = re.search(r"(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)", ln)
                log_alarms.append((ts.group(1).replace("T", " ") if ts else "", block[0], block[1], block[2]))
prices = sorted({(t, n): (t, n, p, z, s) for t, n, p, z, s in prices if p}.values())

# ------------------------------------------------------------------ Workbook
wb = Workbook()

# ---- Top-Deals Speicher (seriöse Händler, eindeutige Kapazität, nicht Fernost)
ws = wb.active
ws.title = "Top-Deals Speicher"
ws["A1"], ws["A1"].font = f"Beste Speicher-Angebote auf eBay (Marktaufnahme {latest[:16].replace('T', ' ')} UTC)", H1
ws["A2"] = ("Filter: Händler ≥ 98,5 % positiv und ≥ 200 Bewertungen, Standort nicht CN/HK, Kapazität eindeutig "
            "(keine Sammelangebote). €/TB = Preis inkl. Versand ÷ (TB × Stück).")
ws["A2"].font = F
cols = ["Kategorie", "Titel", "Preis inkl. Versand", "TB", "Stück", "€/TB", "Bot-Bewertung", "Händler",
        "Bewertung %", "Bewertungen", "Standort", "eBay", "Link"]
header(ws, 4, cols, [16, 60, 13, 7, 6, 10, 14, 22, 11, 11, 9, 8, 9])
r0 = row = 5
eb = cfg.get("ebay", {})
for cat in STORAGE:
    cand = []
    for r in snap:
        if r["kategorie"] != cat:
            continue
        it = {"title": r["titel"], "price": {"value": r["preis_inkl_versand"]},
              "seller": {"feedbackPercentage": r["bewertung_pct"], "feedbackScore": int(num(r["bewertungen"]) or 0)},
              "itemLocation": {"country": r["standort"]}}
        if (num(r["bewertung_pct"]) or 0) < eb.get("min_feedback_pct", 98.5) or (num(r["bewertungen"]) or 0) < eb.get("min_feedback_count", 200):
            continue
        if r["standort"] in eb.get("exclude_locations", []):
            continue
        w = rules[cat]
        if not bot.rule_matches(w, r["titel"].lower()):
            continue
        low = r["titel"].lower()
        if len(set(bot.CAP_RE.findall(low))) >= 3 or re.search(r"\d+\s?/\s?\d+\s?(tb|gb)\b|\d+\s?(gb|tb)\s?[-–]\s?\d+\s?(gb|tb)\b", low):
            continue
        cap, pack, price = bot.capacity_tb(r["titel"]), bot.pack_size(r["titel"]), num(r["preis_inkl_versand"])
        if not (cap and price):
            continue
        res = bot.ebay_evaluate(cfg, {"rule": cat}, it)
        cand.append((price / (cap * pack), cap, pack, price, res[0] if res else "", r))
    for per_tb, cap, pack, price, lvl, r in sorted(cand, key=lambda x: x[0])[:15]:
        vals = [cat, r["titel"], price, cap, pack, None, lvl or "über Grenze", r["verkaeufer"],
                num(r["bewertung_pct"]), int(num(r["bewertungen"]) or 0), r["standort"], r["marktplatz"][5:], None]
        for c, v in enumerate(vals, 1):
            cell = ws.cell(row=row, column=c, value=v)
            cell.font = F
        ws.cell(row=row, column=6, value=f"=C{row}/(D{row}*E{row})")
        link(ws.cell(row=row, column=13), r["url"])
        ws.cell(row=row, column=3).number_format = EUR
        ws.cell(row=row, column=6).number_format = EUR
        ws.cell(row=row, column=4).number_format = "0.###"
        fill = GOOD if lvl else None
        if fill:
            for c in range(1, 14):
                ws.cell(row=row, column=c).fill = fill
        row += 1
if row > r0:
    add_table(ws, f"A4:M{row - 1}", "TopDeals")
top_last = row - 1

# ---- Geizhals-Verlauf
gv = wb.create_sheet("Geizhals-Verlauf")
gv["A1"], gv["A1"].font = "Geizhals-EU-Bestpreise je Messung (alle 30 min)", H1
header(gv, 3, ["Zeit (UTC)", "Produkt", "Preis", "Ziel", "Sofort", "Abstand zum Ziel"], [18, 36, 11, 10, 10, 15])
for i, (t, n, p, z, s) in enumerate(prices, 4):
    gv.cell(row=i, column=1, value=datetime.strptime(t, "%Y-%m-%d %H:%M:%S")).number_format = "dd.mm.yy hh:mm"
    gv.cell(row=i, column=2, value=n)
    gv.cell(row=i, column=3, value=p).number_format = EUR
    gv.cell(row=i, column=4, value=z).number_format = EUR0
    gv.cell(row=i, column=5, value=s).number_format = EUR0
    gv.cell(row=i, column=6, value=f'=IF(D{i}="","",C{i}-D{i})').number_format = EUR
    for c in range(1, 7):
        gv.cell(row=i, column=c).font = F
g_last = max(4, 3 + len(prices))
if prices:
    add_table(gv, f"A3:F{g_last}", "GeizhalsVerlauf")

# ---- Übersicht (Formeln auf die anderen Blätter)
ov = wb.create_sheet("Übersicht", 0)
ov["A1"], ov["A1"].font = "Black Week 2026 – Lage auf einen Blick", H1
ov["A2"] = f"Stand: {datetime.now().strftime('%d.%m.%Y %H:%M')} · Black Friday 27.11. · Cyber Monday 30.11."
ov["A2"].font = F
ov["A4"], ov["A4"].font = "Speicher: bestes seriöses eBay-Angebot (€/TB)", B
header(ov, 5, ["Kategorie", "Bestes €/TB", "Deal-Grenze €/TB", "Top-Grenze €/TB", "Status"], [34, 14, 16, 16, 30])
for i, cat in enumerate(STORAGE, 6):
    w = rules[cat]
    ov.cell(row=i, column=1, value=cat).font = F
    ov.cell(row=i, column=2, value=f"=IFERROR(_xlfn.MINIFS('Top-Deals Speicher'!$F$5:$F${max(5, top_last)},'Top-Deals Speicher'!$A$5:$A${max(5, top_last)},A{i}),\"\")").number_format = EUR
    ov.cell(row=i, column=3, value=w.get("max_eur_per_tb")).font = BLUE
    ov.cell(row=i, column=4, value=w.get("hot_eur_per_tb")).font = BLUE
    ov.cell(row=i, column=5, value=f'=IF(B{i}="","keine Daten",IF(B{i}<=D{i},"🚨 Top-Deal da",IF(B{i}<=C{i},"🛒 Deal da","noch über Grenze")))')
    for c in (3, 4):
        ov.cell(row=i, column=c).number_format = EUR0
r = 6 + len(STORAGE) + 1
ov.cell(row=r, column=1, value="Geizhals: Start · aktuell · Tiefstwert · Ziel").font = B
header(ov, r + 1, ["Produkt", "Start", "Aktuell", "Tief", "Ziel", "Aktuell vs. Ziel"], [34, 14, 16, 16, 12, 16])
ov.freeze_panes = None
names = list(dict.fromkeys(n for _, n, *_ in prices))
gl = f"'Geizhals-Verlauf'!$A$4:$A${g_last}"
gn = f"'Geizhals-Verlauf'!$B$4:$B${g_last}"
gp = f"'Geizhals-Verlauf'!$C$4:$C${g_last}"
for j, n in enumerate(names, r + 2):
    ov.cell(row=j, column=1, value=n).font = F
    ov.cell(row=j, column=2, value=f"=SUMIFS({gp},{gn},A{j},{gl},_xlfn.MINIFS({gl},{gn},A{j}))")
    ov.cell(row=j, column=3, value=f"=SUMIFS({gp},{gn},A{j},{gl},_xlfn.MAXIFS({gl},{gn},A{j}))")
    ov.cell(row=j, column=4, value=f"=_xlfn.MINIFS({gp},{gn},A{j})")
    ov.cell(row=j, column=5, value=targets.get(n, (None, None))[0]).font = BLUE
    ov.cell(row=j, column=6, value=f'=IF(E{j}="","",C{j}-E{j})')
    for c in range(2, 7):
        ov.cell(row=j, column=c).number_format = EUR
note = r + 3 + len(names)
ov.cell(row=note, column=1, value="Blau = Grenzwerte aus config.toml (dort ändern, dann neu bauen). Grün in 'Top-Deals Speicher' = unter Deal-Grenze.").font = F

# ---- Gemeldete Funde
gf = wb.create_sheet("Gemeldete Funde")
gf["A1"], gf["A1"].font = "Alles, was der Bot per Telegram gemeldet hat", H1
header(gf, 3, ["Zeit (UTC)", "Prio", "Alarm", "Titel", "Preis / Detail", "Heute noch Deal?", "Link"], [17, 16, 40, 60, 34, 26, 9])
seen = state.get("ebay_seen", {})
by_id = {item_id(r["url"]): r for r in market}
rows = []
for iid, price in seen.items():
    r = by_id.get(iid)
    if not r:
        continue
    it = {"title": r["titel"], "price": {"value": price},
          "seller": {"feedbackPercentage": r["bewertung_pct"], "feedbackScore": int(num(r["bewertungen"]) or 0)},
          "itemLocation": {"country": r["standort"]}}
    now_ok = bot.ebay_evaluate(cfg, {"rule": r["kategorie"]}, it) if r["kategorie"] in rules else None
    low = r["titel"].lower()
    bogus = (r["standort"] in cfg.get("ebay", {}).get("exclude_locations", [])
             or len(set(bot.CAP_RE.findall(low))) >= 3
             or re.search(r"\d+\s?/\s?\d+\s?(tb|gb)\b|\d+\s?(gb|tb)\s?[-–]\s?\d+\s?(gb|tb)\b|compatib", low))
    verdict = "ja" if now_ok else ("nein – Fehlalarm (Sammelangebot/No-Name)" if bogus else "nein – über deinen neuen Grenzen")
    rows.append(("2026-11-23 20:26", rules.get(r["kategorie"], {}).get("prio", ""), f"eBay · {r['kategorie']}", r["titel"],
                 f"{bot.eur(price)} inkl. Versand – {r['verkaeufer']} ({r['standort']})", verdict, r["url"]))
known = {r[3] for r in rows}
for t, head, title, detail in log_alarms:
    if title in known:  # schon aus state.json/market.csv rekonstruiert
        continue
    known.add(title)
    rows.append((t[:16], "", head, title, detail, "", ""))
for a in read_csv("alerts.csv"):
    rows.append((a["zeit_utc"][:16].replace("T", " "), a["prio"], a["kopf"], a["titel"], a["preis_info"], "", a["link"]))
for i, v in enumerate(sorted(rows, key=lambda x: x[0], reverse=True), 4):
    for c, val in enumerate(v[:6], 1):
        gf.cell(row=i, column=c, value=val).font = F
    link(gf.cell(row=i, column=7), v[6])
    gf.cell(row=i, column=6).fill = GOOD if v[5] == "ja" else (BAD if v[5].startswith("nein") else PatternFill())
if rows:
    add_table(gf, f"A3:G{3 + len(rows)}", "Funde")

# ---- eBay-Markt (komplett)
em = wb.create_sheet("eBay-Markt (alle)")
mcols = ["snapshot_utc", "kategorie", "marktplatz", "titel", "preis_inkl_versand", "kapazitaet_tb", "stueck",
         "eur_pro_tb", "verkaeufer", "bewertung_pct", "bewertungen", "standort", "bot_bewertung", "url"]
header(em, 1, ["Snapshot", "Kategorie", "eBay", "Titel", "Preis inkl. Versand", "TB", "Stück", "€/TB (Titel)",
               "Händler", "Bewertung %", "Bewertungen", "Standort", "Bot (damals)", "Link"],
       [17, 16, 8, 60, 12, 7, 6, 11, 22, 11, 11, 9, 13, 9])
for i, r in enumerate(market, 2):
    for c, k in enumerate(mcols, 1):
        v = r.get(k, "")
        if k in ("preis_inkl_versand", "kapazitaet_tb", "eur_pro_tb", "bewertung_pct", "bewertungen", "stueck"):
            v = num(v)
        if k == "url":
            link(em.cell(row=i, column=c), v)
            continue
        em.cell(row=i, column=c, value=v).font = F
    em.cell(row=i, column=5).number_format = EUR
    em.cell(row=i, column=8).number_format = EUR
if market:
    add_table(em, f"A1:N{1 + len(market)}", "Markt")

out = HERE / (arg("--out") or "Black-Week-Funde.xlsx")
wb.save(out)
print(f"gespeichert: {out} · {len(snap)} Angebote im letzten Snapshot, {len(prices)} Geizhals-Messungen, {len(rows)} Funde")
