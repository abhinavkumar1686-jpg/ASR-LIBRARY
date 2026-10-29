from database import get_db_connection
from datetime import datetime, time, timedelta

SHIFTS = {
    "1": {"hours": "4H", "start": "06:00", "end": "10:00", "price": 300},
    "2": {"hours": "4H", "start": "10:00", "end": "14:00", "price": 400},
    "3": {"hours": "4H", "start": "14:00", "end": "18:00", "price": 400},
    "4": {"hours": "4H", "start": "18:00", "end": "22:00", "price": 350},
    "5": {"hours": "6H", "start": "06:00", "end": "12:00", "price": 600},
    "6": {"hours": "6H", "start": "12:00", "end": "18:00", "price": 600},
    "7": {"hours": "12H", "start": "06:00", "end": "18:00", "price": 1000},
    "8": {"hours": "12H", "start": "08:00", "end": "20:00", "price": 1000},
    "9": {"hours": "16H", "start": "06:00", "end": "22:00", "price": 1200},
}

def clean_expired_bookings():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("UPDATE bookings SET status = 'expired' WHERE status = 'pending' AND created_at < (CURRENT_TIMESTAMP - INTERVAL '15 minutes')")
    cur.execute("UPDATE bookings SET status = 'expired' WHERE status = 'active' AND CURRENT_DATE > (booking_date + (30 + grace_period) * INTERVAL '1 day')")
    conn.commit()
    cur.close()
    conn.close()

def get_available_seats(booking_date, req_start_str, req_end_str):
    # सीट चेक करने से पहले पुरानी एक्सपायर बुकिंग्स साफ करें
    clean_expired_bookings()
    
    conn = get_db_connection()
    cur = conn.cursor()
    
    # 🚨 यहाँ सबसे बड़ा फिक्स किया गया है
    # अब यह सिर्फ आज की तारीख नहीं, बल्कि पूरे 30 दिन + ग्रेस पीरियड का रेंज चेक करेगा
    cur.execute("""
        SELECT seat_id, start_time, end_time FROM bookings 
        WHERE status IN ('active', 'pending')
        AND %s BETWEEN booking_date AND (booking_date + (30 + COALESCE(grace_period, 3)) * INTERVAL '1 day')
    """, (booking_date,))
    booked_slots = cur.fetchall()
    
    total_seats = 30 
    available_seats = []

    req_start = datetime.strptime(req_start_str, "%H:%M").time()
    req_end = datetime.strptime(req_end_str, "%H:%M").time()

    for seat in range(1, total_seats + 1):
        is_available = True
        for b_seat, b_start, b_end in booked_slots:
            if seat == b_seat:
                b_s = b_start if isinstance(b_start, time) else datetime.strptime(str(b_start), "%H:%M:%S").time()
                b_e = b_end if isinstance(b_end, time) else datetime.strptime(str(b_end), "%H:%M:%S").time()
                
                # टाइम ओवरलैप चेक
                if (req_start < b_e) and (req_end > b_s):
                    is_available = False
                    break
        if is_available:
            available_seats.append(seat)
            
    cur.close()
    conn.close()
    return available_seats
def save_pending_booking(user_id, seat_id, booking_date, start_time, end_time, amount):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("INSERT INTO bookings (telegram_id, seat_id, booking_date, start_time, end_time, amount, status, grace_period) VALUES (%s, %s, %s, %s, %s, %s, 'pending', 3) RETURNING id", (user_id, seat_id, booking_date, start_time, end_time, amount))
    booking_id = cur.fetchone()[0]
    conn.commit()
    cur.close()
    conn.close()
    return booking_id

def create_renewal_booking(user_id, old_booking_id):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT seat_id, booking_date, start_time, end_time, amount FROM bookings WHERE id = %s", (old_booking_id,))
    old = cur.fetchone()
    if old:
        seat_id, b_date, start_time, end_time, amount = old
        new_b_date = b_date + timedelta(days=30)
        cur.execute("INSERT INTO bookings (telegram_id, seat_id, booking_date, start_time, end_time, amount, status, grace_period) VALUES (%s, %s, %s, %s, %s, %s, 'pending', 3) RETURNING id", (user_id, seat_id, new_b_date, start_time, end_time, amount))
        new_id = cur.fetchone()[0]
        conn.commit()
        cur.close()
        conn.close()
        return new_id, new_b_date, amount
    cur.close()
    conn.close()
    return None, None, None

def update_booking_status(booking_id, new_status):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("UPDATE bookings SET status = %s WHERE id = %s", (new_status, booking_id))
    conn.commit()
    cur.close()
    conn.close()

def get_booking_details_by_id(booking_id):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT seat_id, amount, status, telegram_id FROM bookings WHERE id = %s", (booking_id,))
    res = cur.fetchone()
    cur.close()
    conn.close()
    return res

def get_user_bookings(user_id):
    conn = get_db_connection()
    cur = conn.cursor()
    clean_expired_bookings()
    cur.execute("SELECT id, seat_id, start_time, end_time, amount, booking_date, status, grace_period FROM bookings WHERE telegram_id = %s AND status IN ('active', 'pending') ORDER BY status ASC, id DESC", (user_id,))
    bookings = cur.fetchall()
    cur.close()
    conn.close()
    return bookings

# 🚨 नए फंक्शन्स (Waitlist और Admin के लिए)

# 🚨 अपडेटेड फंक्शन: अब यह पसंदीदा सीटें भी सेव करेगा
def join_waitlist(user_id, shift_key, booking_date, preferred_seats):
    conn = get_db_connection()
    cur = conn.cursor()
    # चेक करें कि कहीं पहले से वेटिंग लिस्ट में तो नहीं है
    cur.execute("SELECT id FROM waitlists WHERE telegram_id = %s AND shift_key = %s AND booking_date = %s", (user_id, shift_key, booking_date))
    if not cur.fetchone():
        cur.execute("""
            INSERT INTO waitlists (telegram_id, shift_key, booking_date, preferred_seats) 
            VALUES (%s, %s, %s, %s)
        """, (user_id, shift_key, booking_date, preferred_seats))
    conn.commit()
    cur.close()
    conn.close()

# 🚨 अपडेटेड फंक्शन: अब यह चेक करेगा कि खाली हुई सीट उसकी पसंदीदा सीटों में है या नहीं
def get_next_waitlist_user(shift_key, booking_date, vacant_seat_id):
    conn = get_db_connection()
    cur = conn.cursor()
    # उस शिफ्ट की सारी वेटिंग लिस्ट निकालें (जो पहले आया है, वो पहले)
    cur.execute("""
        SELECT id, telegram_id, preferred_seats 
        FROM waitlists 
        WHERE shift_key = %s AND booking_date = %s 
        ORDER BY id ASC
    """, (shift_key, booking_date))
    rows = cur.fetchall()
    cur.close()
    conn.close()

    # हर यूजर को चेक करें
    for row in rows:
        w_id, user_id, prefs = row
        # अगर preferred_seats खाली है (पुराना डेटा) या उसमें यह सीट है, तो उसे रिटर्न करें
        if not prefs or str(vacant_seat_id) in prefs.split(','):
            return w_id, user_id
            
    return None

def remove_from_waitlist(waitlist_id):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM waitlists WHERE id = %s", (waitlist_id,))
    conn.commit()
    cur.close()
    conn.close()

def get_revenue():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT SUM(amount) FROM bookings WHERE status = 'active'")
    total = cur.fetchone()[0]
    cur.close()
    conn.close()
    return total if total else 0

def get_user_profile(user_id):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT name, phone, is_banned FROM users WHERE telegram_id = %s", (user_id,))
    user = cur.fetchone()
    cur.execute("SELECT COUNT(*) FROM bookings WHERE telegram_id = %s AND status = 'active'", (user_id,))
    active_bookings = cur.fetchone()[0]
    cur.close()
    conn.close()
    return user, active_bookings

def admin_manual_booking(user_id, seat_id, shift_key, booking_date):
    shift = SHIFTS[shift_key]
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("INSERT INTO bookings (telegram_id, seat_id, booking_date, start_time, end_time, amount, status, grace_period) VALUES (%s, %s, %s, %s, %s, %s, 'active', 3) RETURNING id", (user_id, seat_id, booking_date, shift['start'], shift['end'], shift['price']))
    b_id = cur.fetchone()[0]
    conn.commit()
    cur.close()
    conn.close()
    return b_id