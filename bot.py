import os
from datetime import date, datetime, timezone, timedelta, time
from pathlib import Path
from decimal import Decimal, InvalidOperation
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, 
    ContextTypes, ConversationHandler, MessageHandler, filters
)
from telegram.error import TelegramError
from dotenv import load_dotenv
from database import (
    create_tables, get_db_connection, get_user_phone, save_user_phone,
    is_user_banned, ban_user, unban_user, get_all_users
)
from booking_logic import (
    SHIFTS, get_available_seats, save_pending_booking, 
    update_booking_status, get_booking_details_by_id, get_user_bookings, 
    create_renewal_booking, join_waitlist, get_next_waitlist_user, 
    remove_from_waitlist, get_revenue, get_user_profile, admin_manual_booking
)
import qrcode
from io import BytesIO

# 🚨 ReportLab Imports (PDF के लिए)
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A5
from reportlab.lib.colors import HexColor, white, black
from reportlab.pdfbase.pdfmetrics import stringWidth

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("Admin_id", "0"))  
UPI_ID = os.getenv("UPI_ID", "yourupi@paytm")

LIBRARY_IMAGE_URL = "https://i.ibb.co/tpYHhxND/IMG-4448.jpg"


WAITING_FOR_CONTACT, CHOOSING_SHIFT, CHOOSING_SEAT, WAITING_FOR_PROOF, WAITLIST_SEAT = range(5)
# ==========================================
# 🚨 PDF GENERATION LOGIC (From asr_receipt.py)
# ==========================================
LIBRARY_NAME = "ASR LIBRARY"
TAGLINE = "Study Today  |  Build Tomorrow"
OWNER_NAME = "Vishwa Ranjan"
OWNER_ROLE = "Owner"
PHONE = "9504786511"
ADDRESS_LINES = [
    "Back Gate of College of Commerce,",
    "C/31, Patna-20, Kankarbagh,",
    "Patrakar Nagar, Patna, Bihar 800020, India",
]

NAVY = HexColor("#123B68")
BLUE = HexColor("#1768B2")
MID_BLUE = HexColor("#2B78BE")
PALE_BLUE = HexColor("#E8F1FA")
PALEST_BLUE = HexColor("#F5F9FD")
GRID = HexColor("#B8D2ED")
TEXT = HexColor("#16345B")
MUTED = HexColor("#536B86")
STAMP_BLUE = HexColor("#165BC1")
PAGE_W, PAGE_H = A5

def fmt_date(value):
    if value is None or value == "": return date.today().strftime("%d-%b-%Y")
    if isinstance(value, datetime): return value.strftime("%d-%b-%Y")
    if isinstance(value, date): return value.strftime("%d-%b-%Y")
    raw = str(value).strip()
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%d-%b-%Y", "%d/%m/%Y"):
        try: return datetime.strptime(raw[:len(fmt) + 8] if "T" in raw else raw, fmt).strftime("%d-%b-%Y")
        except: pass
    return raw

def money(value):
    try:
        amount = Decimal(str(value or 0))
        return f"Rs. {amount:,.0f}/-" if amount == amount.to_integral() else f"Rs. {amount:,.2f}"
    except: return f"Rs. {value}/-"

def val(row, key, default="—"):
    value = row.get(key)
    return default if value is None or value == "" else str(value)

def fit_text(c, text, x, y, max_width, font="Helvetica", size=8, color=TEXT):
    text = str(text)
    while size > 5 and stringWidth(text, font, size) > max_width: size -= 0.25
    c.setFillColor(color)
    c.setFont(font, size)
    c.drawString(x, y, text)

def draw_book_logo(c, cx, cy, scale=1.0, color=white):
    c.saveState()
    c.setFillColor(color)
    c.setStrokeColor(color)
    c.setLineWidth(1.3 * scale)
    p = c.beginPath()
    p.moveTo(cx, cy - 8 * scale)
    p.curveTo(cx - 8 * scale, cy - 2 * scale, cx - 15 * scale, cy - 2 * scale, cx - 20 * scale, cy)
    p.lineTo(cx - 20 * scale, cy + 17 * scale)
    p.curveTo(cx - 12 * scale, cy + 19 * scale, cx - 5 * scale, cy + 15 * scale, cx, cy + 11 * scale)
    p.close()
    c.drawPath(p, fill=1, stroke=0)
    p = c.beginPath()
    p.moveTo(cx, cy - 8 * scale)
    p.curveTo(cx + 8 * scale, cy - 2 * scale, cx + 15 * scale, cy - 2 * scale, cx + 20 * scale, cy)
    p.lineTo(cx + 20 * scale, cy + 17 * scale)
    p.curveTo(cx + 12 * scale, cy + 19 * scale, cx + 5 * scale, cy + 15 * scale, cx, cy + 11 * scale)
    p.close()
    c.drawPath(p, fill=1, stroke=0)
    c.setStrokeColor(color)
    c.setLineWidth(1 * scale)
    c.line(cx, cy + 10 * scale, cx, cy - 8 * scale)
    c.restoreState()

def draw_header(c, left, top, width):
    c.setFillColor(NAVY)
    c.roundRect(left + 10, top - 61, 50, 43, 5, fill=1, stroke=0)
    draw_book_logo(c, left + 35, top - 44, 0.85, white)

    c.setFillColor(NAVY)
    c.setFont("Helvetica-Bold", 19)
    c.drawString(left + 70, top - 35, LIBRARY_NAME)
    c.setFillColor(MUTED)
    c.setFont("Helvetica-Oblique", 8.3)
    c.drawString(left + 73, top - 49, TAGLINE)

    sep_x = left + width * 0.625
    c.setStrokeColor(GRID)
    c.setLineWidth(0.8)
    c.line(sep_x, top - 62, sep_x, top - 8)

    tx = sep_x + 10
    y = top - 18
    c.setFillColor(BLUE)
    c.circle(tx + 2, y + 2, 2.1, fill=1, stroke=0)
    for line in ADDRESS_LINES:
        fit_text(c, line, tx + 9, y, left + width - tx - 11, size=6.3)
        y -= 9
    c.setFillColor(BLUE)
    c.circle(tx + 2, y + 2, 2, fill=1, stroke=0)
    c.setFillColor(TEXT)
    c.setFont("Helvetica", 7)
    c.drawString(tx + 9, y, f"Mobile: {PHONE}")
    y -= 12
    c.setFillColor(BLUE)
    c.circle(tx + 2, y + 2, 2, fill=1, stroke=0)
    c.setFillColor(TEXT)
    c.setFont("Helvetica", 7)
    c.drawString(tx + 9, y, f"Owner: {OWNER_NAME}")

    c.setStrokeColor(BLUE)
    c.setLineWidth(1.2)
    c.line(left + 10, top - 72, left + width - 10, top - 72)

def draw_watermark(c, cx, cy):
    c.saveState()
    c.setFillColor(HexColor("#F0F5FA"))
    draw_book_logo(c, cx, cy, 3.3, HexColor("#F0F5FA"))
    c.restoreState()

def draw_stamp(c, cx, cy, radius=31, angle=-35):
    c.saveState()
    c.translate(cx, cy)
    c.rotate(angle)
    c.setStrokeColor(STAMP_BLUE)
    c.setFillColor(STAMP_BLUE)
    c.setLineWidth(1.35)
    c.circle(0, 0, radius, stroke=1, fill=0)
    c.setLineWidth(0.65)
    c.circle(0, 0, radius - 4, stroke=1, fill=0)
    c.circle(0, 0, radius * 0.57, stroke=1, fill=0)

    c.setFont("Helvetica-Bold", 7.6)
    c.drawCentredString(0, radius - 13, "ASR LIBRARY")
    c.setFont("Helvetica-Bold", 7.2)
    c.drawCentredString(0, -radius + 8, "PATNA")
    c.setFont("Helvetica-Bold", 8)
    c.drawCentredString(0, -2, "ASR")
    c.setFont("Helvetica", 5.4)
    c.drawCentredString(0, -10, "LIBRARY")
    c.setFont("Helvetica-Bold", 7)
    c.drawCentredString(-radius + 10, -1, "★")
    c.drawCentredString(radius - 10, -1, "★")
    c.restoreState()

def draw_signature(c, x, y):
    c.saveState()
    c.setStrokeColor(HexColor("#171717"))
    c.setFillColor(HexColor("#171717"))
    c.setLineWidth(0.9)
    p = c.beginPath()
    p.moveTo(x, y)
    p.curveTo(x + 5, y + 15, x + 7, y - 4, x + 12, y + 8)
    p.curveTo(x + 17, y + 17, x + 16, y - 7, x + 22, y + 4)
    p.curveTo(x + 28, y + 11, x + 29, y + 3, x + 34, y + 7)
    p.curveTo(x + 39, y + 12, x + 43, y - 2, x + 48, y + 5)
    p.curveTo(x + 55, y + 11, x + 57, y + 4, x + 63, y + 7)
    p.curveTo(x + 69, y + 12, x + 74, y + 2, x + 81, y + 7)
    c.drawPath(p, stroke=1, fill=0)
    c.setLineWidth(0.55)
    c.line(x - 2, y - 4, x + 84, y - 4)
    c.restoreState()

def build_receipt(row, output_path):
    c = canvas.Canvas(str(output_path), pagesize=A5, pageCompression=1)
    c.setTitle(f"ASR Library Receipt - {val(row, 'receipt_no', str(row.get('id', '')))}")
    c.setAuthor(LIBRARY_NAME)

    margin = 19
    left, bottom = margin, margin
    width, height = PAGE_W - 2 * margin, PAGE_H - 2 * margin
    c.setFillColor(white)
    c.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)
    c.setStrokeColor(BLUE)
    c.setLineWidth(1.25)
    c.roundRect(left, bottom, width, height, 4, fill=0, stroke=1)

    top = PAGE_H - margin - 9
    
   # --- 1. HEADER ---
    # 🚨 लोगो (Logo)
    try: 
        c.drawImage("logo.png", left + 10, top - 55, width=40, height=40, mask='auto', preserveAspectRatio=True)
    except Exception as e: 
        print(f"Logo error: {e}")

    # 🚨 वर्टिकल लाइन 1 (लोगो के बाद)
    c.setStrokeColor(HexColor("#B8D2ED"))
    c.setLineWidth(1)
    c.line(left + 55, top - 15, left + 55, top - 52)

    # लाइब्रेरी का नाम (फॉन्ट साइज़ 20 किया ताकि एड्रेस से न टकराए)
    c.setFillColor(NAVY)
    c.setFont("Helvetica-Bold", 20) 
    c.drawString(left + 65, top - 32, LIBRARY_NAME)
    
    # टैगलाइन
    c.setFillColor(MUTED)
    c.setFont("Helvetica-Oblique", 8.5)
    c.drawString(left + 65, top - 46, TAGLINE)

    # 🚨 वर्टिकल लाइन 2 (नाम के बाद)
    c.setStrokeColor(HexColor("#B8D2ED"))
    c.setLineWidth(1)
    c.line(left + 210, top - 15, left + 210, top - 52) # लाइन को दाएं खिसकाया

    # 🚨 कांटेक्ट सेक्शन (आइकन्स के साथ)
    tx = left + 220 # एड्रेस शुरू होने की जगह
    y = top - 18

    # Address (Location Icon)
    try: c.drawImage("location.png", tx, y - 2, width=8, height=8, mask='auto')
    except: pass
    for line in ADDRESS_LINES:
        # width - 230 ताकि टेक्स्ट पेज से बाहर न जाए
        fit_text(c, line, tx + 12, y, width - 235, size=6.5)
        y -= 8
        
    # Mobile (Phone Icon)
    y += 1
    try: c.drawImage("phone.png", tx, y - 10, width=8, height=8, mask='auto')
    except: pass
    c.setFillColor(TEXT)
    c.setFont("Helvetica", 7)
    c.drawString(tx + 12, y - 9, f"Mobile: {PHONE}")
    
    # Owner (User Icon)
    y -= 12
    try: c.drawImage("student_icon.png", tx, y - 10, width=8, height=8, mask='auto')
    except: pass
    c.setFillColor(TEXT)
    c.setFont("Helvetica", 7)
    c.drawString(tx + 12, y - 9, f"Owner: {OWNER_NAME}")

    # 🚨 डबल डिवाइडर लाइन
    c.setStrokeColor(NAVY)
    c.setLineWidth(1.2)
    c.line(left + 10, top - 65, left + width - 10, top - 65)
    
    c.setStrokeColor(GRID)
    c.setLineWidth(0.5)
    c.line(left + 10, top - 67, left + width - 10, top - 67)

  

# # --- 2. META (Receipt No & Date) ---
    y_meta = top - 85
    
    # 1. Receipt No (लेबल और वैल्यू)
    c.setFillColor(MUTED)
    c.setFont("Helvetica", 8) # लेबल का साइज़
    c.drawString(left + 12, y_meta, "Receipt No :")
    
    c.setFillColor(NAVY)
    c.setFont("Helvetica", 8.5) # 🚨 वैल्यू का साइज़ छोटा किया (8.5)
    c.drawString(left + 60, y_meta, val(row, "receipt_no", "ASR-000"))

    # 2. Date (कैलेंडर + डेट)
    date_text = fmt_date(row.get("payment_date"))
    
    c.setFillColor(NAVY)
    c.setFont("Helvetica", 8.5) # 🚨 डेट का साइज़ छोटा किया (8.5)
    c.drawRightString(left + width - 12, y_meta, date_text)
    
    # "Date :" लेबल
    c.setFillColor(MUTED)
    c.setFont("Helvetica", 8)
    date_width = c.stringWidth(date_text, "Helvetica-Bold", 8.5) # यहाँ भी 8.5 किया ताकि आइकन सही जगह रहे
    c.drawRightString(left + width - 12 - date_width - 4, y_meta, "Date :")
    
    # कैलेंडर आइकन
    try: 
        label_width = c.stringWidth("Date :", "Helvetica", 8)
        icon_x = left + width - 12 - date_width - 4 - label_width - 10
        c.drawImage("calendar.png", icon_x, y_meta - 1, width=8, height=8, mask='auto')
    except Exception as e: 
        print(f"Calendar error: {e}")

    # --- 3. BANNER (PAYMENT RECEIPT) ---
    banner_y = y_meta - 35
    c.setFillColor(NAVY)
    c.roundRect(left + 11, banner_y, width - 22, 30, 4, fill=1, stroke=0)
    
    # बैनर में दाईं तरफ तिरछी पट्टी (Diagonal Design)
    c.setFillColor(HexColor("#2465A8"))
    p = c.beginPath()
    p.moveTo(left + width - 70, banner_y)
    p.lineTo(left + width - 11, banner_y)
    p.lineTo(left + width - 11, banner_y + 30)
    p.lineTo(left + width - 40, banner_y + 30)
    p.close()
    c.drawPath(p, fill=1, stroke=0)

    # बैंक आइकन
    try: 
        c.drawImage("bank.png", left + 18, banner_y + 7, width=15, height=15, mask='auto')
    except: pass

    # बैंक आइकन के बाद सफेद वर्टिकल लाइन
    c.setStrokeColor(white)
    c.setLineWidth(1)
    c.line(left + 40, banner_y + 7, left + 40, banner_y + 23)

    # टेक्स्ट
    c.setFillColor(white)
    c.setFont("Helvetica-Bold", 15)
    c.drawString(left + 50, banner_y + 9, "PAYMENT RECEIPT")
    # --- 4. STUDENT CARD ---
    card_x, card_w = left + 11, width - 22
    card_top = banner_y - 12
    card_h = 67
    card_y = card_top - card_h
    c.setFillColor(PALEST_BLUE)
    c.roundRect(card_x, card_y, card_w, card_h, 5, fill=1, stroke=0)
    c.setFillColor(PALE_BLUE)
    c.roundRect(card_x, card_y + card_h - 23, card_w, 23, 5, fill=1, stroke=0)
    c.rect(card_x, card_y + card_h - 23, card_w, 5, fill=1, stroke=0)
    
    try: 
        c.drawImage("student_icon.png", card_x + 12, card_y + card_h - 18, width=10, height=10, mask='auto', preserveAspectRatio=True)
    except Exception as e: 
        print(f"Student icon error: {e}")

    c.setFillColor(NAVY)
    c.setFont("Helvetica-Bold", 9)
    c.drawString(card_x + 26, card_y + card_h - 15, "STUDENT DETAILS")

    divider_x = card_x + card_w * 0.5
    c.setStrokeColor(GRID)
    c.setLineWidth(0.7)
    c.line(divider_x, card_y + 9, divider_x, card_y + card_h - 29)
    c.setFillColor(MUTED)
    c.setFont("Helvetica", 8)
    c.drawString(card_x + 13, card_y + 29, "Name")
    c.drawString(divider_x + 13, card_y + 29, "Phone Number")
    c.setFillColor(TEXT)
    c.setFont("Helvetica-Bold", 10)
    fit_text(c, val(row, "student_name"), card_x + 13, card_y + 13, card_w * 0.46, "Helvetica-Bold", 10)
    fit_text(c, val(row, "student_phone"), divider_x + 13, card_y + 13, card_w * 0.45, "Helvetica-Bold", 9.2)

    # --- 5. TABLE ---
    # 🚨 टेबल को थोड़ा नीचे किया ताकि टेक्स्ट कटे नहीं
    table_top = card_y - 25 
    table_x, table_w = card_x, card_w
    row_h = 29
    header_h = 23
    table_h = header_h + row_h * 3
    table_y = table_top - table_h

    c.setFillColor(PALE_BLUE)
    c.roundRect(table_x, table_y, table_w, table_h, 5, fill=1, stroke=0)
    c.setFillColor(HexColor("#D9E8F7"))
    c.roundRect(table_x, table_y + table_h - header_h, table_w, header_h, 5, fill=1, stroke=0)
    c.rect(table_x, table_y + table_h - header_h, table_w, 5, fill=1, stroke=0)

    split = table_x + table_w * 0.5
    c.setStrokeColor(GRID)
    c.setLineWidth(0.65)
    c.line(split, table_y, split, table_y + table_h)
    for i in range(1, 4):
        yy = table_y + table_h - header_h - row_h * (i - 1)
        if i > 1: c.line(table_x, yy, table_x + table_w, yy)

    c.setFillColor(NAVY)
    c.setFont("Helvetica-Bold", 8.5)
    c.drawString(table_x + 12, table_y + table_h - 15, "DESCRIPTION")
    c.drawString(split + 12, table_y + table_h - 15, "DETAILS")

    rows = [
        ("chair.png", "Seat Number", str(val(row, "seat_number"))), 
        ("clock.png", "Library Timing", val(row, "shift_timing", "6:00 AM to 10:00 PM")),
        ("calendar.png", "Valid Till", fmt_date(row.get("valid_till"))),
    ]
    
    for i, (icon_url, label, detail) in enumerate(rows):
        baseline = table_y + table_h - header_h - row_h * i - 18
        
        try:
            c.drawImage(icon_url, table_x + 12, baseline - 3, width=10, height=10, mask='auto', preserveAspectRatio=True)
            text_x = table_x + 28
        except Exception as e:
            text_x = table_x + 12
            
        c.setFillColor(TEXT)
        c.setFont("Helvetica", 8.5)
        c.drawString(text_x, baseline, label)
        fit_text(c, detail, split + 12, baseline, table_w * 0.47, "Helvetica-Bold", 8.5)

    # --- 6. TOTAL PAID ---
    total_top = table_y - 12
    total_h = 39
    total_y = total_top - total_h
    c.setFillColor(PALE_BLUE)
    c.roundRect(card_x, total_y, card_w, total_h, 5, fill=1, stroke=0)
    
    # नीला गोला
    c.setFillColor(BLUE)
    c.circle(card_x + 22, total_y + 19.5, 12, fill=1, stroke=0)
    
    # 🚨 रुपये का चिन्ह (Image)
    try:
        # इमेज को गोले के ठीक बीच में सेट किया है (width=12, height=12)
        c.drawImage("rupee.png", card_x + 16, total_y + 13.5, width=12, height=12, mask='auto', preserveAspectRatio=True)
    except Exception as e:
        print(f"Rupee icon error: {e}")
        # अगर इमेज लोड न हो, तो बैकअप के लिए "Rs." लिख देगा
        c.setFillColor(white)
        c.setFont("Helvetica-Bold", 12)
        c.drawCentredString(card_x + 22, total_y + 15, "Rs.")

    c.setFillColor(NAVY)
    c.setFont("Helvetica-Bold", 9.6)
    c.drawString(card_x + 43, total_y + 16, "Total Amount Paid")
    
    c.setStrokeColor(GRID)
    c.line(card_x + card_w - 105, total_y + 8, card_x + card_w - 105, total_y + total_h - 8)
    
    amount = money(row.get("amount_paid"))
    c.setFont("Helvetica-Bold", 15)
    c.drawRightString(card_x + card_w - 10, total_y + 14, amount)

    # --- 7. SIGNATURE & STAMP ---
    sig_cx = left + width - 75  
    sig_y = bottom + 90  # लाइन की ऊंचाई

    # 1. सिग्नेचर लाइन बनाएं (लंबी और साफ)
    c.setStrokeColor(HexColor("#9BB7D4")) 
    c.setLineWidth(1.5) # लाइन को थोड़ा मोटा किया ताकि साफ दिखे
    c.line(sig_cx - 35, sig_y, sig_cx + 35, sig_y) # लाइन 150 पॉइंट लंबी कर दी

    # 2. सिग्नेचर इमेज (लाइन के ठीक ऊपर)
    try:
        c.saveState()
        c.translate(sig_cx, sig_y) 
        c.rotate(5) # हल्का सा तिरछापन
        
        # y-कोआर्डिनेट 2 रखा है ताकि सिग्नेचर लाइन को न काटे, बल्कि उसके ऊपर रहे
        c.drawImage("signature.png", -45, 2, width=90, height=30, mask='auto', preserveAspectRatio=True)
        c.restoreState()
    except Exception as e: 
        print(f"Signature error: {e}")

    # 3. स्टाम्प इमेज (सिग्नेचर के ऊपर, +35 डिग्री)
    try:
        c.saveState()
        c.translate(sig_cx + 7, sig_y + 12) # स्टाम्प को थोड़ा दाएं और ऊपर लाए
        c.rotate(33) 
        c.drawImage("stamp.png", -24, -24, width=50, height=50, mask='auto', preserveAspectRatio=True)
        c.restoreState()
    except Exception as e: 
        print(f"Stamp error: {e}")

    # 4. डायरेक्टर का नाम और पद (लाइन के नीचे)
    c.setFillColor(NAVY)
    c.setFont("Helvetica-Bold", 9.5) 
    c.drawCentredString(sig_cx, sig_y - 18, OWNER_NAME) # नाम थोड़ा और नीचे किया

    c.setFillColor(MUTED)
    c.setFont("Helvetica", 7.5)
    c.drawCentredString(sig_cx, sig_y - 28, OWNER_ROLE)
    c.drawCentredString(sig_cx, sig_y - 38, LIBRARY_NAME.title())

    
    
    # --- 8. FOOTER ---
    c.setFillColor(BLUE)
    c.setStrokeColor(BLUE)
    c.setLineWidth(1.3)
    c.line(left + 12, bottom + 28, left + 12, bottom + 52)
    c.setFillColor(MUTED)
    c.setFont("Helvetica-Oblique", 7.5)
    c.drawString(left + 20, bottom + 43, "Thank you for choosing ASR Library.")
    c.drawString(left + 20, bottom + 31, "Keep this receipt for your records.")

    c.showPage()
    c.save()
    return output_path

# ==========================================
# 🚨 TELEGRAM BOT LOGIC
# ==========================================
def format_time(t_str):
    t = datetime.strptime(t_str, "%H:%M")
    return t.strftime("%I:%M %p").lstrip("0")

def get_today_date_ist():
    ist = timezone(timedelta(hours=5, minutes=30))
    return datetime.now(ist).strftime("%Y-%m-%d")

async def is_banned_guard(update: Update) -> bool:
    user_id = update.effective_user.id
    if is_user_banned(user_id):
        msg = "🚫 **आपको एडमिन द्वारा बैन कर दिया गया है।**\nआप इस बॉट का उपयोग नहीं कर सकते।"
        if update.message: await update.message.reply_text(msg, parse_mode="Markdown")
        elif update.callback_query: await update.callback_query.answer("🚫 आप बैन हैं!", show_alert=True)
        return True
    return False

async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, is_new=False):
    context.user_data.clear()
    user_id = update.effective_user.id
    
    # 🚨 चेक करें कि यूजर के पास एक्टिव बुकिंग है या नहीं
    bookings = get_user_bookings(user_id)
    has_active_booking = any(b[6] == 'active' for b in bookings)
    
    reply_keyboard = [
        [KeyboardButton("🪑 View Available Seats"), KeyboardButton("📅 Book a Seat")],
        [KeyboardButton("💳 Pay Fees"), KeyboardButton("📄 My Booking")]
    ]
    
    # 🚨 अगर एक्टिव बुकिंग है, तो दोनों बटन दिखाएं, वरना सिर्फ Help & FAQ
    if has_active_booking:
        reply_keyboard.append([KeyboardButton("⏳ Join Waitlist"), KeyboardButton("❓ Help & FAQ")])
    else:
        reply_keyboard.append([KeyboardButton("❓ Help & FAQ")])
        
    reply_markup = ReplyKeyboardMarkup(reply_keyboard, resize_keyboard=True, one_time_keyboard=False)
    
    first_name = update.effective_user.first_name
    welcome_msg = "✅ **रजिस्ट्रेशन सफल!**\n\n" if is_new else ""
    msg = (
        f"{welcome_msg}"
        f"✨ **WELCOME TO ASR LIBRARY** ✨\n\n"
        f"नमस्कार, {first_name}! 👋\n"
        f"आपका स्वागत है। 📚\n\n"
        f"Your Study Space. Your Success Journey.\n\n"
        f"Focus • Learn • Achieve 💫."
    )
    await update.message.reply_text(msg, reply_markup=reply_markup, parse_mode="Markdown")
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await is_banned_guard(update): return ConversationHandler.END
    user_id = update.message.from_user.id
    if get_user_phone(user_id):
        await show_main_menu(update, context)
        return ConversationHandler.END
    else:
        contact_keyboard = [[KeyboardButton("📱 Share Phone Number", request_contact=True)]]
        reply_markup = ReplyKeyboardMarkup(contact_keyboard, resize_keyboard=True, one_time_keyboard=True)
        msg = f"👋 **Hello {update.message.from_user.first_name}!**\n\nASR Library में आपका स्वागत है।\nसुरक्षा के लिए कृपया अपना फोन नंबर शेयर करें।"
        await update.message.reply_text(msg, reply_markup=reply_markup, parse_mode="Markdown")
        return WAITING_FOR_CONTACT

async def contact_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    contact = update.message.contact
    user_id = update.message.from_user.id
    if contact.user_id and contact.user_id != user_id:
        await update.message.reply_text("❌ कृपया अपना ही फोन नंबर शेयर करें।")
        return WAITING_FOR_CONTACT
    save_user_phone(user_id, update.message.from_user.first_name, contact.phone_number)
    await show_main_menu(update, context, is_new=True)
    return ConversationHandler.END

async def book_seat_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await is_banned_guard(update): return ConversationHandler.END
    context.user_data.clear()
    keyboard = []
    for key, shift in SHIFTS.items():
        start_fmt = format_time(shift['start'])
        end_fmt = format_time(shift['end'])
        btn_text = f"Time ({shift['hours']}) - {start_fmt} to {end_fmt} | ₹{shift['price']}"
        keyboard.append([InlineKeyboardButton(btn_text, callback_data=f"shift_{key}")])
    keyboard.append([InlineKeyboardButton("❌ Cancel", callback_data="cancel")])
    await update.message.reply_text("🕒 Please Select Your Shift :", reply_markup=InlineKeyboardMarkup(keyboard))
    return CHOOSING_SHIFT

async def shift_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "cancel":
        await query.message.reply_text("❌ **बुकिंग रद्द कर दी गई है।**", parse_mode="Markdown")
        return ConversationHandler.END
    
    shift_key = query.data.replace("shift_", "") 
    shift_data = SHIFTS[shift_key]
    context.user_data['selected_shift'] = shift_data
    context.user_data['shift_key'] = shift_key
    context.user_data['booking_date'] = get_today_date_ist()
    
    available = get_available_seats(context.user_data['booking_date'], shift_data['start'], shift_data['end'])
    if not available:
        keyboard = [[InlineKeyboardButton("⏳ Join Waitlist", callback_data=f"waitlist_{shift_key}")]]
        await query.message.reply_text("😔 **माफी हो, इस शिफ्ट में सभी सीटें बुक हो चुकी हैं।**\n\nआप वेटिंग लिस्ट में जुड़ सकते हैं।", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        return ConversationHandler.END
        
    keyboard = []
    boys_avail = [s for s in available if s <= 20]
    if boys_avail:
        keyboard.append([InlineKeyboardButton("👦 Boys Seats (1-20)", callback_data="ignore")])
        row = []
        for seat in boys_avail:
            row.append(InlineKeyboardButton(f"{seat}", callback_data=f"seat_{seat}"))
            if len(row) == 5: keyboard.append(row); row = []
        if row: keyboard.append(row)

    girls_avail = [s for s in available if s > 20]
    if girls_avail:
        keyboard.append([InlineKeyboardButton("👧 Girls Seats (21-30)", callback_data="ignore")])
        row = []
        for seat in girls_avail:
            row.append(InlineKeyboardButton(f"{seat}", callback_data=f"seat_{seat}"))
            if len(row) == 5: keyboard.append(row); row = []
        if row: keyboard.append(row)

    keyboard.append([InlineKeyboardButton("❌ Cancel", callback_data="cancel")])
    start_fmt = format_time(shift_data['start'])
    end_fmt = format_time(shift_data['end'])
    # ✅ नया कोड
    caption = (
        f"🪑 **SHIFT & PRICING DETAILS**\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🕒 **Selected Shift**\n"
        f"{start_fmt} – {end_fmt}\n\n"
        f"💳 **Shift Fee: ₹{shift_data['price']}**\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"👇 **Please select your preferred seat below.**"
    )
    await query.message.reply_photo(photo=LIBRARY_IMAGE_URL, caption=caption, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    return CHOOSING_SEAT

async def handle_waitlist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    shift_key = query.data.replace("waitlist_", "")
    context.user_data['wl_shift_key'] = shift_key
    context.user_data['wl_seats'] = [] 
    
    await show_waitlist_seat_grid(query, context)
    return WAITLIST_SEAT # 🚨 यहाँ रिटर्न बदलना है

async def show_waitlist_seat_grid(query, context):
    selected_seats = context.user_data.get('wl_seats', [])
    keyboard = []
    row = []
    for seat in range(1, 31):
        btn_text = f"✅ {seat}" if seat in selected_seats else str(seat)
        row.append(InlineKeyboardButton(btn_text, callback_data=f"wlseat_{seat}"))
        if len(row) == 5:
            keyboard.append(row)
            row = []
    if row: keyboard.append(row)
    
    keyboard.append([InlineKeyboardButton("✔️ Confirm Selection", callback_data="wlconfirm")])
    keyboard.append([InlineKeyboardButton("❌ Cancel", callback_data="cancel_wl")])
    
    await query.edit_message_text(
        "👇 **Please select up to 2 preferred seats:**\n_(You will be notified instantly if any of these seats become vacant)_",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )

async def wl_seat_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    seat = int(query.data.replace("wlseat_", ""))
    selected_seats = context.user_data.get('wl_seats', [])
    
    if seat in selected_seats:
        selected_seats.remove(seat)
    else:
        if len(selected_seats) >= 2:
            await query.answer("⚠️ You can select a maximum of 2 seats.", show_alert=True)
            return
        selected_seats.append(seat)
        
    context.user_data['wl_seats'] = selected_seats
    await show_waitlist_seat_grid(query, context)

async def wl_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    shift_key = context.user_data.get('wl_shift_key')
    selected_seats = context.user_data.get('wl_seats', [])
    booking_date = get_today_date_ist()
    
    if not selected_seats:
        await query.answer("⚠️ Please select at least 1 seat.", show_alert=True)
        return
        
    preferred_str = ",".join(map(str, selected_seats))
    join_waitlist(user_id, shift_key, booking_date, preferred_str)
    
    await query.edit_message_text(
        f"✅ **You have been added to the waitlist!**\n\n"
        f"You will be notified immediately if seat(s) **{', '.join(map(str, selected_seats))}** become available.\n\n"
        f"🏛️ **ASR Library**",
        parse_mode="Markdown"
    )
    return ConversationHandler.END
async def seat_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.data == "ignore": await query.answer(); return CHOOSING_SEAT
    await query.answer()
    
    seat_id = int(query.data.replace("seat_", ""))
    shift_data = context.user_data['selected_shift']
    booking_date = context.user_data['booking_date']
    
    context.user_data['selected_seat'] = seat_id
    booking_id = save_pending_booking(query.from_user.id, seat_id, booking_date, shift_data['start'], shift_data['end'], shift_data['price'])
    context.user_data['booking_id'] = booking_id
    amount = shift_data['price']
    
    upi_string = f"upi://pay?pa={UPI_ID}&pn=ASR%20Library&am={amount}&cu=INR"
    qr = qrcode.QRCode(version=1, box_size=10, border=5)
    qr.add_data(upi_string)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    bio = BytesIO()
    img.save(bio, 'PNG')
    bio.seek(0)
    
    # 🚨 नया अपडेटेड कैप्शन (English Format)
    caption_text = (
        f"✅ **Seat No. {seat_id} — Temporarily Reserved**\n\n"
        f"💰 Amount: ₹{amount}\n"
        f"⏳ Reservation valid for 15 minutes.\n\n"
        f"📸 After payment,\n"
        f"Please send your payment screenshot with the 12-digit UTR/transaction reference number\n\n"
        f"⚠️ Booking is confirmed after payment verification.\n\n"
        f"🏛️ **ASR Library**"
    )
    await context.bot.send_photo(chat_id=query.message.chat_id, photo=bio, caption=caption_text, parse_mode="Markdown")
    return WAITING_FOR_PROOF

async def pay_fees_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await is_banned_guard(update): return
    user_id = update.message.from_user.id
    bookings = get_user_bookings(user_id)
    active_bookings = [b for b in bookings if b[6] == 'active']
    
    if not active_bookings:
        await update.message.reply_text("❌ **आपकी कोई एक्टिव बुकिंग नहीं है।**", parse_mode="Markdown")
        return
        
    keyboard = []
    eligible_for_renewal = False
    min_days_left = 999
    
    for b in active_bookings:
        b_id, seat_id, start_time, end_time, amount, b_date, status, grace = b
        expiry_date = b_date + timedelta(days=30)
        days_left = (expiry_date - date.today()).days
        if days_left < min_days_left: min_days_left = days_left
        if days_left <= 2:
            eligible_for_renewal = True
            start_fmt = format_time(str(start_time)[:5])
            end_fmt = format_time(str(end_time)[:5])
            btn_text = f"🔄 Renew Seat {seat_id} ({start_fmt} to {end_fmt}) - ₹{amount}"
            keyboard.append([InlineKeyboardButton(btn_text, callback_data=f"renew_{b_id}")])
            
    if not eligible_for_renewal:
        await update.message.reply_text(f"⏳ **अभी रिन्यू करने का समय नहीं आया है।**\n\nआपकी वैलिडिटी खत्म होने में अभी **{min_days_left} दिन** बचे हैं।", parse_mode="Markdown")
        return
    await update.message.reply_text("⚠️ **कृपया रिन्यू करें:**", reply_markup=InlineKeyboardMarkup(keyboard))

async def renew_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    old_booking_id = int(query.data.replace("renew_", ""))
    user_id = query.from_user.id
    new_id, new_b_date, amount = create_renewal_booking(user_id, old_booking_id)
    
    if not new_id:
        await query.message.reply_text("रिन्यूअल में समस्या आई।")
        return
    context.user_data['booking_id'] = new_id
    await query.message.reply_text(f"🔄 **रिन्यूअल!**\n\nनई वैलिडिटी: {new_b_date}\nकुल देय राशि: ₹{amount}\n\nकृपया QR स्कैन करके पेमेंट करें।")
    
    upi_string = f"upi://pay?pa={UPI_ID}&pn=ASR%20Library&am={amount}&cu=INR"
    qr = qrcode.QRCode(version=1, box_size=10, border=5)
    qr.add_data(upi_string); qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    bio = BytesIO(); img.save(bio, 'PNG'); bio.seek(0)
    await context.bot.send_photo(chat_id=query.message.chat_id, photo=bio, caption=f"कुल देय राशि: ₹{amount}\n\nकृपया **स्क्रीनशॉट** भेजें और **UTR** लिखें।", parse_mode="Markdown")
    return WAITING_FOR_PROOF

async def proof_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.photo:
        photo_file_id = update.message.photo[-1].file_id
        caption = update.message.caption
        
        if not caption or not caption.strip().isdigit() or len(caption.strip()) != 12:
            error_msg = (
                f"⚠️ **Payment Screenshot Required**\n\n"
                f"Please send your payment screenshot as a photo and enter the 12-digit UTR number in the photo caption.\n\n"
                f"📌 **Example:**\n\n"
                f"* Photo: Your payment confirmation screenshot\n"
                f"* Caption ( फोटो के साथ ): 762309178912\n\n"
                f"✅ Both are required for payment verification.\n\n"
                f"🏛️ **ASR Library**"
            )
            await update.message.reply_text(error_msg, parse_mode="Markdown")
            return WAITING_FOR_PROOF
        
        utr = caption.strip()
        user = update.message.from_user
        booking_id = context.user_data.get('booking_id')
        booking_details = get_booking_details_by_id(booking_id)
        
        if not booking_details:
            await update.message.reply_text("बुकिंग डिटेल्स नहीं मिलीं।")
            return ConversationHandler.END
            
        seat_id, amount, status, user_id = booking_details
        if status != 'pending':
            await update.message.reply_text("❌ यह बुकिंग एक्सपायर हो चुकी है।")
            return ConversationHandler.END
        
        success_msg = (
            f"✅ **Payment Details Submitted Successfully**\n\n"
            f"📩 Your payment screenshot and UTR number have been forwarded to the admin for verification.\n\n"
            f"⏳ Please wait for payment verification and booking confirmation.\n\n"
            f"🏛️ **ASR Library**"
        )
        await update.message.reply_text(success_msg, parse_mode="Markdown")
        
        admin_text = (
            f"🚨 **NEW BOOKING RECEIVED** 🚨\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 **User Details:**\n"
            f"Name: {user.first_name}\n"
            f"Username: @{user.username if user.username else 'None'}\n"
            f"ID: `{user.id}`\n\n"
            f"📝 **Booking Details:**\n"
            f"Seat No: `{seat_id}`\n"
            f"Amount: `₹{amount}`\n"
            f"UTR No: `{utr}`\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"👇 _कृपया पेमेंट की जाँच करके अप्रूव करें:_"
        )
        keyboard = [[InlineKeyboardButton("✅ Approve", callback_data=f"approve_{booking_id}"), InlineKeyboardButton("❌ Reject", callback_data=f"reject_{booking_id}")]]
        
        try:
            await context.bot.send_photo(
                chat_id=ADMIN_ID, 
                photo=photo_file_id, 
                caption=admin_text, 
                parse_mode="Markdown", 
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        except Exception as e:
            print(f"Admin error: {e}")
            
        return ConversationHandler.END
        
    else:
        error_msg = (
            f"⚠️ **Payment Screenshot Required**\n\n"
            f"Please send your payment screenshot as a photo and enter the 12-digit UTR number in the photo caption.\n\n"
            f"📌 **Example:**\n\n"
            f"* Photo: Your payment confirmation screenshot\n"
            f"* Caption ( फोटो के साथ ): 762309178912\n\n"
            f"✅ Both are required for payment verification.\n\n"
            f"🏛️ **ASR Library**"
        )
        await update.message.reply_text(error_msg, parse_mode="Markdown")
        return WAITING_FOR_PROOF

async def admin_approve(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    action, booking_id = query.data.split("_")
    booking_id = int(booking_id)
    
    booking_details = get_booking_details_by_id(booking_id)
    if not booking_details: return
    seat_id, amount, status, user_id = booking_details
    
    if action == "reject":
        update_booking_status(booking_id, 'rejected')
        
        # 1. एडमिन (आपके) पुराने मैसेज को एडिट करें (बटन हटा दें)
        try:
            await query.edit_message_caption(
                caption=query.message.caption + "\n\n❌ **BOOKING REJECTED**", 
                reply_markup=None, 
                parse_mode="Markdown"
            )
        except: pass
        
        # 2. यूजर को नया इंग्लिश मैसेज भेजें
        try: 
            reject_msg = (
                f"❌ **Booking Not Confirmed**\n\n"
                f"Your seat booking has been rejected.\n\n"
                f"💳 If you have already made the payment, please contact the admin (@mot1685) with your payment screenshot and UTR number for verification and assistance.\n\n"
                f"🏛️ **ASR Library**"
            )
            await context.bot.send_message(chat_id=user_id, text=reject_msg, parse_mode="Markdown")
        except: pass
        
        # 3. वेटिंग लिस्ट वाले को नोटिफाई करें
        await trigger_waitlist_notification(context, booking_id)
        return

    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT b.booking_date, b.start_time, b.end_time, u.name, u.phone
            FROM bookings b
            JOIN users u ON b.telegram_id = u.telegram_id
            WHERE b.id = %s
        """, (booking_id,))
        row = cur.fetchone()
        
        if not row:
            await query.message.reply_text("data is not found")
            return
            
        b_date, s_time, e_time, student_name, student_phone = row
        
        cur.execute("UPDATE bookings SET status = 'active' WHERE id = %s", (booking_id,))
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"DB Error: {e}")
        return

    # 🚨 Prepare data for ReportLab PDF
    expiry_date = b_date + timedelta(days=30)
    start_fmt = format_time(str(s_time)[:5])
    end_fmt = format_time(str(e_time)[:5])
    
    row_data = {
        "receipt_no": f"ASR-{booking_id:03d}", # 🚨 यहाँ :03d जोड़ दें ताकि ASR-008 बने
        "student_name": student_name,
        "student_phone": student_phone,
        "seat_number": seat_id,
        "shift_timing": f"{start_fmt} to {end_fmt}",
        "valid_till": expiry_date.strftime('%Y-%m-%d'),
        "amount_paid": amount,
        "payment_date": date.today().strftime('%Y-%m-%d')
    }

    # Generate PDF
    file_path = f"receipt_{user_id}.pdf"
    try:
        build_receipt(row_data, file_path)
    except Exception as e:
        await query.message.reply_text(f"error in pdf making: {e}")
        return

    try:
        with open(file_path, 'rb') as pdf_file:
            await context.bot.send_document(
                chat_id=user_id, 
                document=pdf_file, 
                # ❌ पुराना मैसेज हटाकर नीचे वाला नया मैसेज डालें
                caption="🎉 **Payment Successful!**\n\n📄 Your official receipt is attached. Please download and save it for your records.\n\n🏛️ **ASR Library**", 
                parse_mode="Markdown"
            )
        os.remove(file_path) # फाइल डिलीट करें
        
        # 🚨 सफल होने पर पुराने मैसेज को ही एडिट करें
        try:
            await query.edit_message_caption(
                caption=query.message.caption + "\n\n✅ **Booking approved successfully! Receipt sent to the user.**", 
                reply_markup=None, # बटन हटा दें
                parse_mode="Markdown"
            )
        except: pass

    except Exception as e:
        # 🚨 एरर आने पर भी नया मैसेज न भेजें, पुराने को एडिट करें
        print(f"PDF Send Error: {e}")
        try:
            await query.edit_message_caption(
                caption=query.message.caption + f"\n\n❌ **Error:** Failed to send PDF.\n`{e}`", 
                reply_markup=None,
                parse_mode="Markdown"
            )
        except: pass
async def trigger_waitlist_notification(context: ContextTypes.DEFAULT_TYPE, cancelled_booking_id):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT booking_date, start_time, end_time FROM bookings WHERE id = %s", (cancelled_booking_id,))
    row = cur.fetchone()
    if not row: return
    b_date, s_time, e_time = row
    cur.close()
    conn.close()
    
    shift_key = None
    for k, v in SHIFTS.items():
        if v['start'] == str(s_time)[:5] and v['end'] == str(e_time)[:5]:
            shift_key = k; break
            
    if shift_key:
        next_user = get_next_waitlist_user(shift_key, b_date)
        if next_user:
            w_id, user_id = next_user
            remove_from_waitlist(w_id)
            try:
                await context.bot.send_message(
                    chat_id=user_id, 
                    text=f"🔔 **खुशखबरी!**\n\nआप जिस शिफ्ट ({SHIFTS[shift_key]['hours']}) की वेटिंग लिस्ट में थे, वहाँ एक सीट खाली हो गई है।\n\nकृपया तुरंत **Book a Seat** दबाकर सीट बुक करें!"
                )
            except: pass

async def ban_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    try:
        _, user_id = update.message.text.split()
        ban_user(int(user_id))
        await update.message.reply_text(f"🚫 यूजर {user_id} को बैन कर दिया गया है।")
    except: await update.message.reply_text("सही फॉर्मेट: `/ban 12345678`", parse_mode="Markdown")

async def unban_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    try:
        _, user_id = update.message.text.split()
        unban_user(int(user_id))
        await update.message.reply_text(f"✅ यूजर {user_id} को अनबैन कर दिया गया है।")
    except: await update.message.reply_text("सही फॉर्मेट: `/unban 12345678`", parse_mode="Markdown")

async def revenue_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    rev = get_revenue()
    await update.message.reply_text(f"💰 **कुल कमाई (Active Bookings से): ₹{rev}**", parse_mode="Markdown")

async def userinfo_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    try:
        _, user_id = update.message.text.split()
        user, active_b = get_user_profile(int(user_id))
        if not user:
            await update.message.reply_text("यूजर नहीं मिला!")
            return
        name, phone, banned = user
        status = "🚫 Banned" if banned else "✅ Active"
        await update.message.reply_text(f"👤 **नाम:** {name}\n📱 **फोन:** {phone}\n🆔 **आईडी:** `{user_id}`\n📌 **स्टेटस:** {status}\n🎟️ **एक्टिव बुकिंग्स:** {active_b}", parse_mode="Markdown")
    except: await update.message.reply_text("सही फॉर्मेट: `/userinfo 12345678`", parse_mode="Markdown")

async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    msg = update.message.text.replace("/broadcast ", "")
    if msg == "/broadcast":
        await update.message.reply_text("कृपया मैसेज लिखें। जैसे: `/broadcast कल लाइब्रेरी बंद रहेगी`")
        return
    users = get_all_users()
    success, failed = 0, 0
    await update.message.reply_text(f"⏳ {len(users)} यूजर्स को मैसेज भेजा जा रहा है...")
    for uid in users:
        try:
            await context.bot.send_message(chat_id=uid, text=f"📢 **एडमिन का मैसेज:**\n\n{msg}", parse_mode="Markdown")
            success += 1
        except TelegramError: failed += 1
    await update.message.reply_text(f"✅ **ब्रॉडकास्ट सफल!**\n\nसेंड: {success}\nफेल: {failed}")

async def book_on_behalf_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    try:
        _, user_id, seat_id, shift_key = update.message.text.split()
        b_date = get_today_date_ist()
        b_id = admin_manual_booking(int(user_id), int(seat_id), shift_key, b_date)
        await update.message.reply_text(f"✅ यूजर {user_id} के लिए सीट {seat_id} की बुकिंग (Shift {shift_key}) हो गई।")
        try: await context.bot.send_message(chat_id=int(user_id), text=f"🎉 **एडमिन द्वारा आपकी बुकिंग की गई है!**\nसीट: {seat_id} | शिफ्ट: {SHIFTS[shift_key]['hours']}")
        except: pass
    except: await update.message.reply_text("सही फॉर्मेट: `/bookon <user_id> <seat_id> <shift_no_1_to_9>`", parse_mode="Markdown")

async def daily_reminder_job(context: ContextTypes.DEFAULT_TYPE):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT telegram_id, seat_id FROM bookings WHERE status = 'active' AND CURRENT_DATE = (booking_date + 27 * INTERVAL '1 day')")
    bookings = cur.fetchall()
    cur.close()
    conn.close()
    for b in bookings:
        user_id, seat_id = b
        try:
            await context.bot.send_message(chat_id=user_id, text=f"⏰ **रिमाइंडर!**\n\nआपकी सीट ({seat_id}) की वैलिडिटी 3 दिन में खत्म हो जाएगी।\n\nकृपया **Pay Fees** दबाकर अपनी बुकिंग रिन्यू करें।")
        except: pass

# 🚨 नया फंक्शन: 15 मिनट बाद पेंडिंग यूजर्स को मैसेज भेजना
async def check_pending_timeouts(context: ContextTypes.DEFAULT_TYPE):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        # ऐसी बुकिंग्स ढूंढें जो 'pending' हैं और 15 मिनट से पुरानी हैं
        cur.execute("""
            SELECT id, telegram_id, seat_id 
            FROM bookings 
            WHERE status = 'pending' 
            AND created_at < (CURRENT_TIMESTAMP - INTERVAL '15 minutes')
        """)
        expired_bookings = cur.fetchall()
        
        for b_id, user_id, seat_id in expired_bookings:
            # डेटाबेस में स्टेटस 'expired' कर दें
            cur.execute("UPDATE bookings SET status = 'expired' WHERE id = %s", (b_id,))
            conn.commit()
            
            # यूजर को अलर्ट मैसेज भेजें
            try:
                msg = (
                    f"⚠️ **Seat Hold Expired**\n\n"
                    f"Your 15-minute hold for **Seat {seat_id}** has expired because the payment was not approved in time.\n\n"
                    f"📞 **If you have already made the payment, please contact the Admin immediately to confirm your booking.**\n\n"
                    f"🏛️ **ASR Library**"
                )
                await context.bot.send_message(chat_id=user_id, text=msg, parse_mode="Markdown")
            except Exception as e:
                print(f"Failed to send expiry message to {user_id}: {e}")
                
        cur.close()
        conn.close()
    except Exception as e:
        print(f"Error in check_pending_timeouts job: {e}")

# 🚨 नया फंक्शन: एक्टिव बुकिंग एक्सपायर होने पर यूजर को मैसेज भेजना
async def notify_and_expire_active_bookings(context: ContextTypes.DEFAULT_TYPE):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        # 🚨 यह क्वेरी सिर्फ उन्हीं को पकड़ेगी जिनके 30 दिन + ग्रेस पीरियड पूरे हो चुके हैं
        cur.execute("""
            SELECT id, telegram_id, seat_id 
            FROM bookings 
            WHERE status = 'active' 
            AND CURRENT_DATE > (booking_date + (30 + COALESCE(grace_period, 3)) * INTERVAL '1 day')
        """)
        expired_bookings = cur.fetchall()
        
        for b_id, user_id, seat_id in expired_bookings:
            # 1. डेटाबेस में स्टेटस एक्सपायर करें
            cur.execute("UPDATE bookings SET status = 'expired' WHERE id = %s", (b_id,))
            conn.commit()
            
            # 2. पुराने यूजर को अलर्ट भेजें
            try:
                msg = (
                    f"⚠️ **Booking Expired**\n\n"
                    f"Dear Student, your 30-day booking (plus grace period) for **Seat {seat_id}** has expired.\n\n"
                    f"Your seat is now available for others to book.\n\n"
                    f"🏛️ **ASR Library**"
                )
                await context.bot.send_message(chat_id=user_id, text=msg, parse_mode="Markdown")
            except Exception as e:
                print(f"Failed to send expiry message: {e}")
            
            # 3. 🚨 अब यहाँ से वेटलिस्ट वाले को नोटिफिकेशन जाएगा
            await trigger_waitlist_notification(context, b_id)
                
        cur.close()
        conn.close()
    except Exception as e:
        print(f"Error in notify_and_expire_active_bookings job: {e}")
# 🚨 नया फंक्शन: 30 दिन पूरे होने पर ग्रेस पीरियड की जानकारी देना
async def notify_grace_period_start(context: ContextTypes.DEFAULT_TYPE):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        # ऐसी बुकिंग्स ढूंढें जो 'active' हैं और जिनके ठीक 30 दिन आज पूरे हुए हैं
        cur.execute("""
            SELECT id, telegram_id, seat_id, grace_period 
            FROM bookings 
            WHERE status = 'active' 
            AND CURRENT_DATE = (booking_date + 30 * INTERVAL '1 day')
        """)
        grace_bookings = cur.fetchall()
        
        for b_id, user_id, seat_id, grace_period in grace_bookings:
            # अगर डेटाबेस में grace_period नहीं है तो डिफ़ॉल्ट 3 दिन मान लें
            grace_days = grace_period if grace_period else 3
            
            try:
                msg = (
                    f"📅 **Plan Expiry Notice**\n\n"
                    f"Dear Student, your 30-day booking for **Seat {seat_id}** has officially ended today.\n\n"
                    f"🎁 **Good News:** The library owner has granted you a **{grace_days}-day grace period** to renew your seat.\n\n"
                    f"⚠️ Please renew your plan within the next {grace_days} days to keep your seat. Otherwise, it will be automatically cancelled and given to someone else.\n\n"
                    f"👇 Click on **💳 Pay Fees** to renew now.\n\n"
                    f"🏛️ **ASR Library**"
                )
                await context.bot.send_message(chat_id=user_id, text=msg, parse_mode="Markdown")
            except Exception as e:
                print(f"Failed to send grace period message to {user_id}: {e}")
                
        cur.close()
        conn.close()
    except Exception as e:
        print(f"Error in notify_grace_period_start job: {e}")

async def view_seats_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await is_banned_guard(update): return
    keyboard = [[InlineKeyboardButton(f"{format_time(s['start'])} to {format_time(s['end'])}", callback_data=f"viewshift_{k}")] for k, s in SHIFTS.items()]
    await update.message.reply_text("किस शिफ्ट की सीटें देखना चाहते हैं?", reply_markup=InlineKeyboardMarkup(keyboard))

async def waitlist_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = []
    for key, shift in SHIFTS.items():
        start_fmt = format_time(shift['start'])
        end_fmt = format_time(shift['end'])
        btn_text = f"{start_fmt} to {end_fmt}"
        keyboard.append([InlineKeyboardButton(btn_text, callback_data=f"waitlist_{key}")])
    
    await update.message.reply_text(
        "⏳ **Join Waitlist**\n\nकिस शिफ्ट की वेटिंग लिस्ट में जुड़ना चाहते हैं? सीट खाली होते ही आपको तुरंत मैसेज किया जाएगा।", 
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    ) 
async def help_faq_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # 🚨 यहाँ 4 स्पेस का गैप (Indentation) होना चाहिए
    msg = (
        "❓ **Help & FAQ**\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "**Q1: How do I book a seat?**\n"
        "Go to '📅 Book a Seat', select your shift, and choose an available seat.\n\n"
        "**Q2: How long is my booking valid?**\n"
        "A standard booking is valid for 30 days. You also get a 3-day grace period for renewal.\n\n"
        "**Q3: How do I renew my plan?**\n"
        "Go to '💳 Pay Fees' 2 days before your expiry date.\n\n"
        "**Q4: What is the Waitlist?**\n"
        "If a shift is full, you can join the waitlist. As soon as a seat becomes vacant, the bot will notify you.\n\n"
        "For any other issues, contact Admin: @mot1685\n\n"
        "🏛️ **ASR Library**"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")

async def view_shift_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    shift_key = query.data.replace("viewshift_", "")
    shift_data = SHIFTS[shift_key]
    today = get_today_date_ist()
    available = get_available_seats(today, shift_data['start'], shift_data['end'])
    start_fmt = format_time(shift_data['start'])
    end_fmt = format_time(shift_data['end'])
    if not available:
        keyboard = [[InlineKeyboardButton("⏳ Join Waitlist", callback_data=f"waitlist_{shift_key}")]]
        await query.message.reply_text(f"❌ **{start_fmt} to {end_fmt}** में कोई सीट खाली नहीं है।", reply_markup=InlineKeyboardMarkup(keyboard))
        return
    boys_avail = [s for s in available if s <= 20]
    girls_avail = [s for s in available if s > 20]
    msg = f"🪑 **{start_fmt} to {end_fmt}** की सीटें:\n\n👦 **Boys:** {', '.join(map(str, boys_avail)) if boys_avail else 'कोई नहीं'}\n\n👧 **Girls:** {', '.join(map(str, girls_avail)) if girls_avail else 'कोई नहीं'}\n\nकुल खाली सीटें: **{len(available)}**"
    await query.message.reply_text(msg, parse_mode="Markdown")

async def my_booking_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await is_banned_guard(update): return
    user_id = update.message.from_user.id
    bookings = get_user_bookings(user_id)
    if not bookings:
        await update.message.reply_text("❌ **आपकी कोई बुकिंग नहीं है।**", parse_mode="Markdown")
        return
    active_bookings = [b for b in bookings if b[6] == 'active']
    pending_bookings = [b for b in bookings if b[6] == 'pending']
    response_text = ""
    if active_bookings:
        response_text += "🎟️ **YOUR ACTIVE TICKETS**\n━━━━━━━━━━━━━━━━━━━━\n"
        for b in active_bookings:
            b_id, seat_id, start_time, end_time, amount, b_date, status, grace = b
            start_fmt = format_time(str(start_time)[:5]); end_fmt = format_time(str(end_time)[:5])
            expiry_date = b_date + timedelta(days=30); grace_expiry = expiry_date + timedelta(days=grace)
            days_left = (expiry_date - date.today()).days
            response_text += f"🪑 **Seat No:** `{seat_id}`\n⏰ **Shift:** `{start_fmt} - {end_fmt}`\n📅 **Valid Till:** {expiry_date.strftime('%d-%b-%Y')} _(**{days_left} days** left)_\n🛡️ **Grace Period:** {grace_expiry.strftime('%d-%b-%Y')}\n━━━━━━━━━━━━━━━━━━━━\n"
    if pending_bookings:
        response_text += "\n⏳ **PENDING VERIFICATION**\n_(एडमिन आपके पेमेंट की जाँच कर रहे हैं)_\n\n"
        for b in pending_bookings:
            b_id, seat_id, start_time, end_time, amount, b_date, status, grace = b
            start_fmt = format_time(str(start_time)[:5]); end_fmt = format_time(str(end_time)[:5])
            response_text += f"🔸 Seat `{seat_id}` | `{start_fmt} - {end_fmt}` | ₹{amount}\n"
    await update.message.reply_text(response_text, parse_mode="Markdown")

def main():
    create_tables()
    app = Application.builder().token(BOT_TOKEN).build()
    
    # 🚨 यह लाइन सबसे ज्यादा जरूरी है, जो आपसे छूट गई है
    job_queue = app.job_queue 

    # टेस्टिंग के लिए टाइमर (जैसा आपने अभी सेट किया है)
    job_queue = app.job_queue
    reminder_time = time(hour=10, minute=0, tzinfo=timezone(timedelta(hours=5, minutes=30)))
    job_queue.run_daily(daily_reminder_job, time=reminder_time)
    job_queue.run_repeating(check_pending_timeouts, interval=60, first=10)
    # हर 1 घंटे में चेक करेगा कि कोई बुकिंग एक्सपायर हुई है या नहीं
    job_queue.run_repeating(notify_and_expire_active_bookings, interval=3600, first=10)
    
    # ... (बाकी का सारा कोड वैसा ही रहेगा) ...
    
    reg_conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={WAITING_FOR_CONTACT: [MessageHandler(filters.CONTACT, contact_received)]},
        fallbacks=[CommandHandler("start", start)]
    )
    conv_handler = ConversationHandler(
        entry_points=[
            MessageHandler(filters.Regex("^📅 Book a Seat$"), book_seat_start),
            MessageHandler(filters.Regex("^💳 Pay Fees$"), pay_fees_handler),
            CallbackQueryHandler(renew_selected, pattern="^renew_"),
            CallbackQueryHandler(handle_waitlist, pattern="^waitlist_")
        ],
        states={
            CHOOSING_SHIFT: [CallbackQueryHandler(shift_selected, pattern="^shift_")],
            CHOOSING_SEAT: [CallbackQueryHandler(seat_selected, pattern="^(seat_|ignore)")],
            WAITING_FOR_PROOF: [MessageHandler((filters.PHOTO | filters.TEXT) & ~filters.COMMAND, proof_received)],
            # 🚨 नया स्टेट यहाँ जोड़ें
            WAITLIST_SEAT: [
                CallbackQueryHandler(wl_seat_toggle, pattern="^wlseat_"),
                CallbackQueryHandler(wl_confirm, pattern="^wlconfirm$"),
                CallbackQueryHandler(lambda u, c: ConversationHandler.END, pattern="^cancel_wl$")
            ],
        },
        fallbacks=[CommandHandler("cancel", lambda u, c: ConversationHandler.END)]
    )
    app.add_handler(reg_conv)
    app.add_handler(CommandHandler("ban", ban_command))
    app.add_handler(CommandHandler("unban", unban_command))
    app.add_handler(CommandHandler("revenue", revenue_command))
    app.add_handler(CommandHandler("userinfo", userinfo_command))
    app.add_handler(CommandHandler("broadcast", broadcast_command))
    app.add_handler(CommandHandler("bookon", book_on_behalf_command))
    app.add_handler(conv_handler)
    app.add_handler(MessageHandler(filters.Regex("^🪑 View Available Seats$"), view_seats_handler))
    app.add_handler(MessageHandler(filters.Regex("^📄 My Booking$"), my_booking_handler))
    app.add_handler(CallbackQueryHandler(view_shift_selected, pattern="^viewshift_"))
    app.add_handler(CallbackQueryHandler(admin_approve, pattern="^(approve_|reject_)"))
    # नए बटन्स के हैंडलर्स
    app.add_handler(MessageHandler(filters.Regex("^❓ Help & FAQ$"), help_faq_handler))
    app.add_handler(MessageHandler(filters.Regex("^⏳ Join Waitlist$"), waitlist_menu_handler))
    print("बॉट चालू हो गया है...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()