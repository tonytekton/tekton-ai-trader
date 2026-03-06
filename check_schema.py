import psycopg2
import os
from dotenv import load_dotenv

load_dotenv()

try:
    conn = psycopg2.connect(
        host='172.16.64.3', 
        database='tekton-trader', 
        user='postgres', 
        password=os.getenv('CLOUD_SQL_DB_PASSWORD')
    )
    cur = conn.cursor()
    cur.execute("SELECT column_name, data_type FROM information_schema.columns WHERE table_name = 'signals' ORDER BY ordinal_position;")
    
    print("\n" + "="*40)
    print("      ACTUAL DATABASE SCHEMA: SIGNALS")
    print("="*40)
    for col in cur.fetchall():
        print(f"{col[0]:<20} | {col[1]}")
    print("="*40 + "\n")
    
    cur.close()
    conn.close()
except Exception as e:
    print(f"❌ Connection Error: {e}")
