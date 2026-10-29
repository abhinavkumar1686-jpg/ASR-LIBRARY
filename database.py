import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()

# 🚨 यहाँ हार्डकोड URL हटाकर .env से उठाएं
DATABASE_URL = os.getenv("SUPABASE_URL")

def get_db_connection():
    if not DATABASE_URL:
        raise ValueError("🚨 SUPABASE_URL .env फाइल में नहीं मिला! कृपया चेक करें।")
    return psycopg2.connect(DATABASE_URL)

# ... (नीचे का बाकी सारा कोड वैसा ही रहने दें) ...

def create_tables():
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                telegram_id BIGINT PRIMARY KEY,
                name VARCHAR(100),
                phone VARCHAR(15),
                is_banned BOOLEAN DEFAULT FALSE
            );
        """)
        
        cur.execute("""
            CREATE TABLE IF NOT EXISTS bookings (
                id SERIAL PRIMARY KEY,
                telegram_id BIGINT,
                seat_id INT,
                booking_date DATE,
                start_time TIME,
                end_time TIME,
                amount INT,
                status VARCHAR(20),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                grace_period INT DEFAULT 3
            );
        """)
        
        cur.execute("""
            CREATE TABLE IF NOT EXISTS waitlists (
                id SERIAL PRIMARY KEY,
                telegram_id BIGINT,
                shift_key VARCHAR(10),
                booking_date DATE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        conn.commit()
        cur.close()
        conn.close()
        print("✅ Supabase से कनेक्शन सफल! टेबल्स बन गईं।")
    except Exception as e:
        print(f"🚨 Database Error: {e}")

def get_user_phone(user_id):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT phone FROM users WHERE telegram_id = %s", (user_id,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row[0] if row else None

def save_user_phone(user_id, name, phone):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO users (telegram_id, name, phone) 
        VALUES (%s, %s, %s) 
        ON CONFLICT (telegram_id) DO UPDATE SET phone = EXCLUDED.phone, name = EXCLUDED.name
    """, (user_id, name, phone))
    conn.commit()
    cur.close()
    conn.close()

# 🚨 नए फंक्शन्स (Ban/Blacklist के लिए)
def is_user_banned(user_id):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT is_banned FROM users WHERE telegram_id = %s", (user_id,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row[0] if row else False

def ban_user(user_id):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("UPDATE users SET is_banned = TRUE WHERE telegram_id = %s", (user_id,))
    conn.commit()
    cur.close()
    conn.close()

def unban_user(user_id):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("UPDATE users SET is_banned = FALSE WHERE telegram_id = %s", (user_id,))
    conn.commit()
    cur.close()
    conn.close()

def get_all_users():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT telegram_id FROM users WHERE is_banned = FALSE")
    users = cur.fetchall()
    cur.close()
    conn.close()
    return [u[0] for u in users]