import smtplib
from email.message import EmailMessage
from config import get_connection

SENDER_EMAIL = 'jayasuryag01092005@gmail.com'
SENDER_PASSWORD = 'kvam vuao bmga vbkz'  # Gmail app password
OFFICER_EMAIL = 'officer.trafficcontrol@gmail.com'

def send_email(to_address, subject, body):
    msg = EmailMessage()
    msg['Subject'] = subject
    msg['From'] = SENDER_EMAIL
    msg['To'] = to_address
    msg.set_content(body)

    try:
        with smtplib.SMTP('smtp.gmail.com', 587) as smtp:
            smtp.starttls()
            smtp.login(SENDER_EMAIL, SENDER_PASSWORD)
            smtp.send_message(msg)
            print(f"[📨] Email sent to {to_address}")
    except Exception as e:
        print(f"[✖] Failed to send email to {to_address}: {e}")

def send_otp(to_address, otp_code):
    subject = "Your OTP for Police Login"
    body = f"Dear Officer,\n\nYour One-Time Password (OTP) for login is: {otp_code}\n\nThis OTP is valid for 5 minutes.\n\n- Traffic Control System"
    send_email(to_address, subject, body)
