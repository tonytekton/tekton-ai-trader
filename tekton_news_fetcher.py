import os
import requests
import xml.etree.ElementTree as ET
import psycopg2
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

DB_PARAMS = {
    "host": "172.16.64.3",
    "database": "tekton-trader",
    "user": "postgres",
    "password": os.getenv("CLOUD_SQL_DB_PASSWORD")
}

# The Direct "Fair Economy" XML Feed (Official Forex Factory Data Source)
FF_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.xml"

def fetch_and_store_news():
    print(f"📡 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | Starting News Sync via Fair Economy...")
    
    try:
        response = requests.get(FF_URL, timeout=20)
        
        if response.status_code != 200:
            print(f"❌ Feed Error. Status: {response.status_code}")
            return

        # Parse XML Content
        root = ET.fromstring(response.content)
        
        conn = psycopg2.connect(**DB_PARAMS)
        cur = conn.cursor()
        
        new_events = 0
        skipped = 0

        for event in root.findall('event'):
            # Filtering for HIGH impact
            impact = event.find('impact').text.lower()
            
            if 'high' in impact:
                currency = event.find('country').text
                title = event.find('title').text
                date_str = event.find('date').text # Format: 03-01-2026
                time_str = event.find('time').text # Format: 9:00am
                
                try:
                    # Combine Date and Time for a clean Timestamp
                    # Note: Fair Economy usually provides GMT/UTC
                    full_dt_str = f"{date_str} {time_str}"
                    event_dt = datetime.strptime(full_dt_str, "%m-%d-%Y %I:%M%p")
                except (ValueError, AttributeError, TypeError):
                    # Handle "All Day" or tentative events
                    try:
                        event_dt = datetime.strptime(date_str, "%m-%d-%Y")
                    except:
                        continue

                cur.execute("""
                    INSERT INTO economic_events (event_date, currency, indicator_name, impact_level)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (event_date, currency, indicator_name) DO NOTHING;
                """, (event_dt, currency, title, 'high'))
                
                if cur.rowcount > 0:
                    new_events += 1
                else:
                    skipped += 1
        
        conn.commit()
        cur.close()
        conn.close()
        
        print(f"✅ News Sync Complete.")
        print(f"📊 New High-Impact Events: {new_events}")
        print(f"📊 Existing Events Skipped: {skipped}")

    except requests.exceptions.RequestException as e:
        print(f"❌ Network Error: {e}")
    except Exception as e:
        print(f"❌ System Error: {e}")

if __name__ == "__main__":
    fetch_and_store_news()
