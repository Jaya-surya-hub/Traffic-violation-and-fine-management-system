from flask import Flask, render_template, request, redirect, url_for, session
from email_handler import send_otp, send_email
import random
from datetime import datetime, timedelta
import psycopg2

app = Flask(__name__)
app.secret_key = 'police_secret_key'

def get_db_connection():
    return psycopg2.connect(
        host="localhost",
        database="traffic_violation_system",
        user="postgres",
        password="freefire"
    )

VIOLATION_TYPES = [
    'Speeding', 'Parking', 'Red Light', 'Overtake',
    'Signal Jumping', 'Over Speeding', 'Wrong Lane',
    'No Helmet', 'Triple Riding', 'Drunk Driving'
]

CAMERA_IDS = ['speedcam1', 'speedcam2', 'speedcam3', 'speedcam4', 'speedcam5']

CAMERA_TO_ZONE = {
    'speedcam1': 'School Zone',
    'speedcam2': 'Hospital Zone',
    'speedcam3': 'Residential Zone',
    'speedcam4': 'Highway',
    'speedcam5': 'Industrial Zone'
}

def calculate_fine(cur, violation_type, zone, vehicle_type, violation_count=0):
    BASE_FINE_FALLBACK = 500
    try:
        cur.execute("""
            SELECT FineAmount FROM FineRules
            WHERE LOWER(ViolationType) = LOWER(%s)
              AND LOWER(Zone) = LOWER(%s)
              AND LOWER(VehicleType) = LOWER(%s)
        """, (violation_type.strip(), zone.strip(), vehicle_type.strip()))
        result = cur.fetchone()
        if result and result[0] is not None:
            fine_amount = float(result[0])
            multiplier = 1 + (violation_count // 3) * 0.2
            return round(fine_amount * multiplier, 2)
        return BASE_FINE_FALLBACK
    except Exception as e:
        print(f"❌ Fine calculation error: {e}")
        return BASE_FINE_FALLBACK

def notify_driver(vehicle_id, violation_type, camera_id):
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT OwnerName, DriverEmail, VehicleType
            FROM vehicle_details
            WHERE VehicleID = %s
        """, (vehicle_id,))
        vehicle_info = cur.fetchone()
        if not vehicle_info:
            return

        owner_name, driver_email, vehicle_type = vehicle_info
        if not driver_email:
            print(f"No email found for vehicle {vehicle_id}")
            return

        zone = CAMERA_TO_ZONE.get(camera_id, "General")
        cur.execute("SELECT COUNT(*) FROM FinePaymentHistory WHERE VehicleID = %s", (vehicle_id,))
        violation_count = cur.fetchone()[0]
        fine_amount = calculate_fine(cur, violation_type, zone, vehicle_type, violation_count)

        payment_link = f"http://localhost:5004/pay_fine/{vehicle_id}/{camera_id}"
        body = f"""Dear {owner_name},

Your vehicle (ID: {vehicle_id}) has committed a traffic violation.

Violation Type : {violation_type}
Date & Time    : {datetime.now()}
Zone           : {zone}
Camera Source  : {camera_id.upper()}
Vehicle Type   : {vehicle_type}

🧾 Fine Amount  : ₹{fine_amount}

Please pay your fine here: {payment_link}

Drive safe,
Chennai Traffic Management
"""
        send_email(driver_email, "🚨 Traffic Violation Notice", body)
    except psycopg2.Error as e:
        print(f"Error notifying driver: {e}")
    finally:
        cur.close()
        conn.close()

@app.route('/', methods=['GET', 'POST'])
def login():
    # Reset show_otp flag on initial load
    show_otp = session.get('show_otp', False)

    if request.method == 'POST' and 'police_id' in request.form:
        police_id = request.form['police_id']
        conn = get_db_connection()
        cur = conn.cursor()
        try:
            cur.execute("SELECT email FROM police_users WHERE police_id = %s", (police_id,))
            police_email = cur.fetchone()
            if police_email:
                otp = str(random.randint(100000, 999999))
                session['otp'] = otp
                session['police_id'] = police_id
                session['show_otp'] = True  # Set flag to show OTP form
                send_otp(police_email[0], otp)
                return render_template('login.html', show_otp=True)
            else:
                return render_template('login.html', show_otp=False, message="Invalid Police ID or email not found.")
        except psycopg2.Error as e:
            return render_template('login.html', show_otp=False, message=f"Database error: {str(e)}")
        finally:
            cur.close()
            conn.close()
    return render_template('login.html', show_otp=show_otp)

@app.route('/send_otp', methods=['POST'])
def send_otp_route():
    police_id = request.form['police_id']
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT email FROM police_users WHERE police_id = %s", (police_id,))
        police_email = cur.fetchone()
        if police_email:
            otp = str(random.randint(100000, 999999))
            session['otp'] = otp
            session['police_id'] = police_id
            session['show_otp'] = True  # Set flag to show OTP form
            send_otp(police_email[0], otp)
            return render_template('login.html', show_otp=True)
        else:
            return render_template('login.html', show_otp=False, message="Invalid Police ID or email not found.")
    except psycopg2.Error as e:
        return render_template('login.html', show_otp=False, message=f"Database error: {str(e)}")
    finally:
        cur.close()
        conn.close()

@app.route('/otp_verification', methods=['POST'])
def verify_otp():
    otp_input = request.form['otp']
    if otp_input == session.get('otp'):
        session.pop('otp', None)
        session.pop('show_otp', None)  # Reset the flag
        return redirect(url_for('violation_entry'))
    return render_template('login.html', show_otp=True, message="Invalid OTP. Try again.")

@app.route('/dashboard')
def dashboard():
    if 'police_id' not in session:
        return redirect(url_for('login'))
    return redirect(url_for('violation_entry'))

@app.route('/violation_entry', methods=['GET', 'POST'])
def violation_entry():
    if 'police_id' not in session:
        return redirect(url_for('login'))

    calculated_fine = None
    message = ""
    vehicle_id = request.form.get('vehicle_id') if request.method == 'POST' else request.args.get('vehicle_id')

    if request.method == 'POST' and 'action' in request.form:
        vehicle_id = request.form['vehicle_id']
        violation_type = request.form['violation_type']
        camera_id = request.form['camera_id']
        action = request.form['action']

        conn = get_db_connection()
        cur = conn.cursor()

        try:
            cur.execute("SELECT VehicleType FROM vehicle_details WHERE VehicleID = %s", (vehicle_id,))
            vehicle_row = cur.fetchone()

            if not vehicle_row:
                cur.execute("""
                    INSERT INTO LicenseReviewList (VehicleID, NumberOfViolations, AddedDate, ReviewReason)
                    VALUES (%s, 1, NOW(), 'Unknown vehicle - police entry')
                """, (vehicle_id,))
                conn.commit()
                message = f"Vehicle ID {vehicle_id} not found. Added to License Review List."
            else:
                vehicle_type = vehicle_row[0]
                zone = CAMERA_TO_ZONE.get(camera_id, "General")

                cur.execute(f"""
                    SELECT ViolationTime, FinePaid FROM {camera_id}
                    WHERE VehicleID = %s AND ViolationType = %s
                    ORDER BY ViolationTime DESC LIMIT 1
                """, (vehicle_id, violation_type))
                result = cur.fetchone()

                violation_id = f"V{vehicle_id}{int(datetime.now().timestamp())}"
                if not result:
                    cur.execute(f"""
                        INSERT INTO {camera_id} (VehicleID, ViolationID, ViolationType, ViolationTime, FinePaid, CameraID)
                        VALUES (%s, %s, %s, NOW(), FALSE, %s)
                    """, (vehicle_id, violation_id, violation_type, camera_id))
                    conn.commit()
                    notify_driver(vehicle_id, violation_type, camera_id)
                    result = (datetime.now(), False)

                violation_time, fine_paid = result

                if action == 'calculate':
                    if fine_paid:
                        time_diff = datetime.now() - violation_time
                        if time_diff.total_seconds() < 86400:
                            remaining_hours = (86400 - time_diff.total_seconds()) // 3600
                            message = f"Fine already paid. Valid for {int(remaining_hours)} hours."
                        else:
                            cur.execute(f"""
                                UPDATE {camera_id}
                                SET FinePaid = FALSE, ViolationTime = NOW()
                                WHERE VehicleID = %s AND ViolationType = %s
                            """, (vehicle_id, violation_type))
                            conn.commit()
                            fine_paid = False
                            message = "Previous fine expired. Ready to calculate new fine."

                    if not fine_paid:
                        cur.execute("SELECT COUNT(*) FROM FinePaymentHistory WHERE VehicleID = %s", (vehicle_id,))
                        violation_count = cur.fetchone()[0]
                        calculated_fine = calculate_fine(cur, violation_type, zone, vehicle_type, violation_count)

                elif action == 'pay':
                    if fine_paid:
                        time_diff = datetime.now() - violation_time
                        if time_diff.total_seconds() < 86400:
                            remaining_hours = (86400 - time_diff.total_seconds()) // 3600
                            message = f"Fine already paid. Valid for {int(remaining_hours)} hours."
                        else:
                            cur.execute("SELECT COUNT(*) FROM FinePaymentHistory WHERE VehicleID = %s", (vehicle_id,))
                            violation_count = cur.fetchone()[0]
                            fine_amount = calculate_fine(cur, violation_type, zone, vehicle_type, violation_count)
                            cur.execute(f"""
                                UPDATE {camera_id}
                                SET FinePaid = TRUE, ViolationTime = NOW()
                                WHERE VehicleID = %s AND ViolationType = %s
                            """, (vehicle_id, violation_type))
                            cur.execute("""
                                INSERT INTO FinePaymentHistory (VehicleID, ViolationType, ViolationTime, FineAmount, Paid)
                                VALUES (%s, %s, NOW(), %s, TRUE)
                            """, (vehicle_id, violation_type, fine_amount))
                            conn.commit()
                            message = "Fine paid successfully."
                    else:
                        cur.execute("SELECT COUNT(*) FROM FinePaymentHistory WHERE VehicleID = %s", (vehicle_id,))
                        violation_count = cur.fetchone()[0]
                        fine_amount = calculate_fine(cur, violation_type, zone, vehicle_type, violation_count)
                        cur.execute(f"""
                            UPDATE {camera_id}
                            SET FinePaid = TRUE, ViolationTime = NOW()
                            WHERE VehicleID = %s AND ViolationType = %s
                        """, (vehicle_id, violation_type))
                        cur.execute("""
                            INSERT INTO FinePaymentHistory (VehicleID, ViolationType, ViolationTime, FineAmount, Paid)
                            VALUES (%s, %s, NOW(), %s, TRUE)
                        """, (vehicle_id, violation_type, fine_amount))
                        conn.commit()
                        message = "Fine paid successfully."

        except psycopg2.Error as e:
            message = f"Database error: {str(e)}"
        finally:
            cur.close()
            conn.close()

    return render_template(
        'violation_entry.html',
        violation_types=VIOLATION_TYPES,
        camera_ids=CAMERA_IDS,
        camera_to_zone=CAMERA_TO_ZONE,
        calculated_fine=calculated_fine,
        message=message,
        vehicle_id=vehicle_id
    )

@app.route('/vehicle_service_history/<vehicle_id>')
def vehicle_service_history(vehicle_id):
    if 'police_id' not in session:
        return redirect(url_for('login'))

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT ServiceID, VehicleID, ServiceDate, ServiceDescription, ServiceProvider, ServiceCost
            FROM VehicleServiceHistory
            WHERE VehicleID = %s
            ORDER BY ServiceDate DESC
        """, (vehicle_id,))
        service_history = cur.fetchall()
    except psycopg2.Error as e:
        service_history = []
        print(f"Error fetching service history: {e}")
    finally:
        cur.close()
        conn.close()

    return render_template('vehicle_service_history.html', service_history=service_history, vehicle_id=vehicle_id)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001, debug=True)