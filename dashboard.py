import streamlit as st
import pandas as pd
import psycopg2
import os
import plotly.express as px
from dotenv import load_dotenv
from datetime import date, timedelta

# पेज कॉन्फ़िगरेशन (सबसे पहले होना चाहिए)
st.set_page_config(page_title="ASR Library Admin", page_icon="📚", layout="wide")

load_dotenv()
DATABASE_URL = os.getenv("SUPABASE_URL")

# 🎨 Custom CSS (प्रोफेशनल लुक के लिए)
st.markdown("""
<style>
    /* मुख्य बैकग्राउंड */
    .stApp {
        background-color: #f4f6f9;
    }
    /* कार्ड्स का डिज़ाइन */
    div[data-testid="metric-container"] {
        background-color: white;
        border-radius: 12px;
        padding: 20px;
        box-shadow: 0 4px 12px rgba(0,0,0,0.05);
        border: 1px solid #e0e0e0;
    }
    /* साइडबार */
    [data-testid="stSidebar"] {
        background-color: #1e1e2d;
        color: white;
    }
    /* टेबल का डिज़ाइन */
    .stDataFrame {
        background-color: white;
        border-radius: 10px;
        box-shadow: 0 2px 8px rgba(0,0,0,0.05);
    }
    /* हेडर */
    h1, h2, h3 {
        color: #2c3e50;
        font-family: 'Helvetica Neue', sans-serif;
    }
    /* सीट ग्रिड के लिए */
    .seat-box {
        display: inline-block;
        width: 45px;
        height: 45px;
        margin: 4px;
        border-radius: 6px;
        text-align: center;
        line-height: 45px;
        font-weight: bold;
        color: white;
        font-size: 14px;
    }
    .seat-available { background-color: #2ecc71; }
    .seat-booked { background-color: #e74c3c; }
</style>
""", unsafe_allow_html=True)

# डेटाबेस से डेटा लाने का फंक्शन
@st.cache_data(ttl=60) # हर 1 मिनट में रिफ्रेश होगा
def get_data(query):
    conn = psycopg2.connect(DATABASE_URL)
    df = pd.read_sql(query, conn)
    conn.close()
    return df

# 🚨 लॉगिन सिस्टम
def check_password():
    def password_entered():
        if st.session_state["password"] == "admin123": # अपना पासवर्ड यहाँ बदलें
            st.session_state["password_correct"] = True
            del st.session_state["password"]  
        else:
            st.session_state["password_correct"] = False

    if "password_correct" not in st.session_state:
        st.title("🔒 ASR Library Admin Portal")
        st.text_input("कृपया पासवर्ड डालें", type="password", on_change=password_entered, key="password")
        return False
    elif not st.session_state["password_correct"]:
        st.text_input("कृपया पासवर्ड डालें", type="password", on_change=password_entered, key="password")
        st.error("😕 गलत पासवर्ड!")
        return False
    else:
        return True

if check_password():
    # --- साइडबार ---
    with st.sidebar:
        st.title("📚 ASR Library")
        st.markdown("---")
        menu = st.radio("नेविगेशन", ["📊 Dashboard", "🪑 Live Seats", "📝 Active Bookings", "👥 Users", "⏳ Waitlist"])
        st.markdown("---")
        st.info("💡 सिस्टम ऑटोमैटिक अपडेट हो रहा है।")

    # --- मुख्य डैशबोर्ड (Overview) ---
    if menu == "📊 Dashboard":
        st.title("Dashboard Overview")
        st.write("आपके लाइब्रेरी की आज की स्थिति।")
        
        # KPIs निकालें
        rev_df = get_data("SELECT SUM(amount) as total FROM bookings WHERE status = 'active'")
        total_revenue = rev_df['total'][0] if not pd.isna(rev_df['total'][0]) else 0
        
        active_df = get_data("SELECT COUNT(*) as count FROM bookings WHERE status = 'active'")
        active_seats = active_df['count'][0]
        
        users_df = get_data("SELECT COUNT(*) as count FROM users")
        total_users = users_df['count'][0]
        
        expiring_df = get_data("SELECT COUNT(*) as count FROM bookings WHERE status = 'active' AND CURRENT_DATE >= (booking_date + 27 * INTERVAL '1 day')")
        expiring_soon = expiring_df['count'][0]
        
        # KPI कार्ड्स
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("💰 Total Revenue", f"₹{total_revenue:,}")
        col2.metric("🪑 Assigned Seats", active_seats)
        col3.metric("👥 Total Users", total_users)
        col4.metric("⏳ Expiring Soon (3 Days)", expiring_soon, delta="-Urgent" if expiring_soon > 0 else None, delta_color="inverse")
        
        st.markdown("---")
        
        # चार्ट (पिछले 7 दिनों की कमाई)
        st.subheader("📈 Revenue Trend (Last 7 Days)")
        chart_query = """
            SELECT booking_date::text as date, SUM(amount) as revenue 
            FROM bookings 
            WHERE status = 'active' AND booking_date >= CURRENT_DATE - INTERVAL '7 days'
            GROUP BY booking_date 
            ORDER BY booking_date
        """
        chart_df = get_data(chart_query)
        if not chart_df.empty:
            fig = px.area(chart_df, x="date", y="revenue", title="", markers=True, color_discrete_sequence=['#2ecc71'])
            fig.update_layout(plot_bgcolor='white', paper_bgcolor='white')
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("पिछले 7 दिनों का कोई डेटा नहीं है।")

    # --- Live Seats (विजुअल ग्रिड) ---
    elif menu == "🪑 Live Seats":
        st.title("Live Seat Availability")
        st.write("आज की सभी शिफ्ट्स की सीटें (हरा = खाली, लाल = बुक)।")
        
        SHIFTS = {
            "1": "06:00 - 10:00", "2": "10:00 - 14:00", "3": "14:00 - 18:00", "4": "18:00 - 22:00",
            "5": "06:00 - 12:00", "6": "12:00 - 18:00", "7": "06:00 - 18:00", "8": "08:00 - 20:00", "9": "06:00 - 22:00"
        }
        
        selected_shift_key = st.selectbox("शिफ्ट चुनें:", list(SHIFTS.keys()), format_func=lambda x: f"Shift {x} ({SHIFTS[x]})")
        
        # उस शिफ्ट की बुक सीटें निकालें
        shift_times = SHIFTS[selected_shift_key].split(" - ")
        start_t, end_t = shift_times[0] + ":00", shift_times[1] + ":00"
        
        query = f"SELECT seat_id, status FROM bookings WHERE booking_date = CURRENT_DATE AND status IN ('active', 'pending') AND start_time = '{start_t}' AND end_time = '{end_t}'"
        booked_df = get_data(query)
        booked_seats = booked_df['seat_id'].tolist()
        
        # सीट ग्रिड बनाएं
        st.markdown("<div style='background: white; padding: 20px; border-radius: 10px;'>", unsafe_allow_html=True)
        html_grid = ""
        for seat in range(1, 31):
            if seat in booked_seats:
                html_grid += f"<div class='seat-box seat-booked'>{seat}</div>"
            else:
                html_grid += f"<div class='seat-box seat-available'>{seat}</div>"
        st.markdown(html_grid, unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)

    # --- Active Bookings ---
    elif menu == "📝 Active Bookings":
        st.title("Active Bookings & Expiry")
        
        query = """
            SELECT b.id as "Booking ID", u.name as "Name", u.phone as "Phone", 
                   b.seat_id as "Seat", b.booking_date as "Start Date", 
                   (b.booking_date + 30) as "Expiry Date", b.amount as "Amount"
            FROM bookings b
            JOIN users u ON b.telegram_id = u.telegram_id
            WHERE b.status = 'active'
            ORDER BY b.id DESC
        """
        df = get_data(query)
        if not df.empty:
            st.dataframe(df, use_container_width=True, hide_index=True)
            
            # CSV डाउनलोड
            csv = df.to_csv(index=False).encode('utf-8')
            st.download_button("📥 Download Active Bookings CSV", data=csv, file_name=f'bookings_{date.today()}.csv', mime='text/csv')
        else:
            st.info("कोई एक्टिव बुकिंग नहीं है।")

    # --- Users ---
    elif menu == "👥 Users":
        st.title("Registered Users")
        
        query = "SELECT telegram_id as 'ID', name as 'Name', phone as 'Phone', is_banned as 'Banned' FROM users ORDER BY telegram_id DESC"
        df = get_data(query)
        st.dataframe(df, use_container_width=True, hide_index=True)
        
        csv = df.to_csv(index=False).encode('utf-8')
        st.download_button("📥 Download Users CSV", data=csv, file_name=f'users_{date.today()}.csv', mime='text/csv')

    # --- Waitlist ---
    elif menu == "⏳ Waitlist":
        st.title("Waitlist Users")
        st.write("जो यूजर वेटिंग लिस्ट में हैं (सीट खाली होते ही उन्हें बॉट द्वारा मैसेज चला जाएगा)।")
        
        query = """
            SELECT w.id as 'WL ID', u.name as 'Name', u.phone as 'Phone', 
                   w.shift_key as 'Shift', w.created_at as 'Joined At'
            FROM waitlists w
            JOIN users u ON w.telegram_id = u.telegram_id
            ORDER BY w.id ASC
        """
        df = get_data(query)
        if not df.empty:
            st.dataframe(df, use_container_width=True, hide_index=True)
        else:
            st.success("वेटिंग लिस्ट खाली है।")