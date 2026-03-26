#!/usr/bin/env python3
"""
tekton_calendar.py
──────────────────
Fetches the ForexFactory weekly XML calendar feed, parses medium + high impact
events, and upserts them into the economic_events SQL table.

Designed to run as a cron job every 6 hours:
  0 */6 * * * /home/tony/tekton-ai-trader/venv/bin/python /home/tony/tekton-ai-trader/tekton_calendar.py >> /home/tony/tekton-ai-trader/combined_trades.log 2>&1

Also runs at system startup via the tekton-calendar.service systemd unit.

SQL table required (run once):
  CREATE TABLE IF NOT EXISTS economic_events (
      id              SERIAL PRIMARY KEY,
      event_date      TIMESTAMPTZ NOT NULL,
      currency        VARCHAR(10) NOT NULL,
      indicator_name  TEXT NOT NULL,
      impact_level    VARCHAR(10) NOT NULL,
      source          VARCHAR(50) DEFAULT 'forexfactory',
      created_at      TIMESTAMPTZ DEFAULT NOW(),
      UNIQUE (event_date, currency, indicator_name)
  );
"""

import os
import re
import logging
import psycopg2
from datetime import datetime, timezone, timedelta
from urllib.request import urlopen, Request
from dotenv import load_dotenv

# Load .env from the same directory as this script (same pattern as executor/bridge)
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env'))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [CALENDAR] %(levelname)s %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
log = logging.getLogger('tekton_calendar')

FF_CALENDAR_URL = 'https://nfs.faireconomy.media/ff_calendar_thisweek.xml'

CURRENCY_MAP = {
    'USD': 'USD', 'EUR': 'EUR', 'GBP': 'GBP', 'JPY': 'JPY',
    'AUD': 'AUD', 'CAD': 'CAD', 'CHF': 'CHF', 'NZD': 'NZD', 'CNY': 'CNY',
}

def get_db_conn():
    return psycopg2.connect(
        host=os.getenv('CLOUD_SQL_HOST', '172.16.64.3'),
        database=os.getenv('CLOUD_SQL_DB_NAME', 'tekton-trader'),
        user=os.getenv('CLOUD_SQL_DB_USER'),
        password=os.getenv('CLOUD_SQL_DB_PASSWORD'),
    )

def fetch_xml() -> str:
    req = Request(FF_CALENDAR_URL, headers={
        'User-Agent': 'Mozilla/5.0 (compatible; TektonTrader/4.7)',
        'Accept': 'application/xml, text/xml, */*',
    })
    with urlopen(req, timeout=15) as resp:
        return resp.read().decode('utf-8')

def parse_events(xml: str) -> list[dict]:
    events = []
    for event_xml in re.findall(r'<event>([\s\S]*?)<\/event>', xml, re.IGNORECASE):
        title_m   = re.search(r'<title>(.*?)<\/title>', event_xml, re.DOTALL)
        country_m = re.search(r'<country>(.*?)<\/country>', event_xml, re.DOTALL)
        date_m    = re.search(r'<date><!\[CDATA\[(.*?)\]\]><\/date>', event_xml)
        time_m    = re.search(r'<time><!\[CDATA\[(.*?)\]\]><\/time>', event_xml)
        impact_m  = re.search(r'<impact><!\[CDATA\[(.*?)\]\]><\/impact>', event_xml)

        if not (title_m and country_m and date_m and impact_m):
            continue

        impact = impact_m.group(1).strip().lower()
        if impact not in ('medium', 'high'):
            continue

        country  = country_m.group(1).strip()
        currency = CURRENCY_MAP.get(country, country)
        title    = title_m.group(1).strip()
        date_str = date_m.group(1).strip()   # e.g. "03-18-2026"
        time_str = time_m.group(1).strip() if time_m else 'All Day'

        try:
            month, day, year = map(int, date_str.split('-'))
            hour, minute = 0, 0
            if time_str not in ('All Day', 'Tentative', ''):
                t = re.match(r'(\d+):(\d+)(am|pm)', time_str, re.IGNORECASE)
                if t:
                    hour, minute = int(t.group(1)), int(t.group(2))
                    if t.group(3).lower() == 'pm' and hour != 12:
                        hour += 12
                    if t.group(3).lower() == 'am' and hour == 12:
                        hour = 0
            event_dt = datetime(year, month, day, hour, minute, tzinfo=timezone.utc)
        except Exception as e:
            log.warning(f'Date parse failed for "{title}": {e}')
            continue

        # Skip events more than 1 hour in the past
        if event_dt < datetime.now(timezone.utc) - timedelta(hours=1):
            continue

        events.append({
            'event_date':     event_dt,
            'currency':       currency,
            'indicator_name': title,
            'impact_level':   impact,
            'source':         'forexfactory',
        })

    return events

def upsert_events(events: list[dict]) -> tuple[int, int]:
    """Returns (inserted, skipped)."""
    inserted, skipped = 0, 0
    conn = get_db_conn()
    try:
        cur = conn.cursor()
        for ev in events:
            cur.execute("""
                INSERT INTO economic_events (event_date, currency, indicator_name, impact_level, source)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (event_date, currency, indicator_name) DO UPDATE
                    SET impact_level = EXCLUDED.impact_level,
                        source = EXCLUDED.source
                RETURNING (xmax = 0) AS was_inserted
            """, (
                ev['event_date'], ev['currency'],
                ev['indicator_name'], ev['impact_level'], ev['source'],
            ))
            row = cur.fetchone()
            if row and row[0]:
                inserted += 1
            else:
                skipped += 1
        conn.commit()
        cur.close()
    finally:
        conn.close()
    return inserted, skipped

def main():
    log.info('📅 Starting calendar refresh from ForexFactory...')
    try:
        xml = fetch_xml()
        log.info(f'📄 Fetched {len(xml)} bytes from ForexFactory')
    except Exception as e:
        log.error(f'❌ Failed to fetch calendar XML: {e}')
        return

    events = parse_events(xml)
    log.info(f'✅ Parsed {len(events)} medium/high impact events')

    if not events:
        log.warning('⚠️  No events parsed — check feed format')
        return

    high  = sum(1 for e in events if e['impact_level'] == 'high')
    med   = sum(1 for e in events if e['impact_level'] == 'medium')
    log.info(f'   → High: {high}  Medium: {med}')

    try:
        inserted, skipped = upsert_events(events)
        log.info(f'💾 DB upsert complete — inserted: {inserted}, already existed: {skipped}')
    except Exception as e:
        log.error(f'❌ DB upsert failed: {e}')

if __name__ == '__main__':
    main()
