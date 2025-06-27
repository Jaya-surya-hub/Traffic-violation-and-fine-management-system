from flask import Flask, render_template, request, redirect, url_for, session, jsonify
import psycopg2
from datetime import datetime, timedelta

app = Flask(__name__)
app.secret_key = 'driver_secret_key'

def get_db_connection():
    return psycopg2.connect(
        host="localhost",
        database="traffic_violation_system",
        user="postgres",
        password="freefire"
    )

CAMERA_TO_ZONE = {
    'speedcam1': 'School Zone',
    'speedcam2': 'Hospital Zone',
    'speedcam3': 'Residential Zone',
    'speedcam4': 'Highway',
    'speedcam5': 'Industrial Zone'
}

# Helper function to calculate fine
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
            multiplier = 1 + (violation_count // 3) * 0.2  # Every 3rd violation, 20% increase
            return round(fine_amount * multiplier, 2)
        return BASE_FINE_FALLBACK
    except Exception as e:
        print(f"❌ Fine calculation error: {e}")
        return BASE_FINE_FALLBACK

# Helper function to update safe driving streak
def update_safe_driving_streak(user_id, vehicle_id):
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        latest_violation_time = None
        for camera_id in ['speedcam1', 'speedcam2', 'speedcam3', 'speedcam4', 'speedcam5']:
            cur.execute(f"""
                SELECT ViolationTime FROM {camera_id}
                WHERE VehicleID = %s
                ORDER BY ViolationTime DESC LIMIT 1
            """, (vehicle_id,))
            violation_time = cur.fetchone()
            if violation_time and (not latest_violation_time or violation_time[0] > latest_violation_time):
                latest_violation_time = violation_time[0]

        if not latest_violation_time:
            cur.execute("SELECT created_at FROM user_login WHERE user_id = %s", (user_id,))
            start_date = cur.fetchone()[0]
            if start_date:
                days_since_start = (datetime.now() - start_date).days
                return days_since_start
            return 0

        cur.execute("SELECT last_login FROM user_login WHERE user_id = %s", (user_id,))
        last_login = cur.fetchone()[0]
        if last_login and latest_violation_time > last_login:
            return 0
        else:
            days_since_last_violation = (datetime.now() - latest_violation_time).days
            return days_since_last_violation
    except psycopg2.Error as e:
        print(f"Error updating streak: {e}")
        return 0
    finally:
        cur.close()
        conn.close()

# Route for Registration
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        user_id = request.form['user_id']
        password = request.form['password']
        vehicle_id = request.form['vehicle_id']

        conn = get_db_connection()
        cur = conn.cursor()
        try:
            cur.execute("SELECT VehicleID FROM vehicle_details WHERE VehicleID = %s", (vehicle_id,))
            if not cur.fetchone():
                return render_template('driver_register.html', message="Vehicle ID not found.")

            cur.execute("SELECT user_id FROM user_login WHERE user_id = %s", (user_id,))
            if cur.fetchone():
                return render_template('driver_register.html', message="User ID already registered.")

            cur.execute("""
                INSERT INTO user_login (user_id, password_hash, is_active, last_login, created_at, vehicle_id)
                VALUES (%s, %s, TRUE, NOW(), NOW(), %s)
            """, (user_id, password, vehicle_id))
            conn.commit()
            return redirect(url_for('login'))
        except psycopg2.Error as e:
            return render_template('driver_register.html', message=f"Error: {str(e)}")
        finally:
            cur.close()
            conn.close()
    return render_template('driver_register.html')

# Route for Login
@app.route('/', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user_id = request.form['user_id']
        password = request.form['password']

        conn = get_db_connection()
        cur = conn.cursor()
        try:
            cur.execute(
                "SELECT user_id, vehicle_id, is_active FROM user_login WHERE user_id = %s AND password_hash = %s",
                (user_id, password))
            user = cur.fetchone()
            if user:
                user_id, vehicle_id, is_active = user
                if not is_active:
                    return render_template('driver_login.html', message="Account is not active.")
                cur.execute("UPDATE user_login SET last_login = NOW() WHERE user_id = %s", (user_id,))
                conn.commit()
                session['user_id'] = user_id
                session['vehicle_id'] = vehicle_id
                redirect_url = request.args.get('redirect', url_for('dashboard'))
                return redirect(redirect_url)
            else:
                return render_template('driver_login.html', message="Invalid user ID or password.")
        except psycopg2.Error as e:
            return render_template('driver_login.html', message=f"Error: {str(e)}")
        finally:
            cur.close()
            conn.close()
    return render_template('driver_login.html')

# Route for Dashboard
@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user_id = session['user_id']
    vehicle_id = session['vehicle_id']
    streak = update_safe_driving_streak(user_id, vehicle_id)

    # Fetch unpaid violations
    conn = get_db_connection()
    cur = conn.cursor()
    unpaid_violations = []
    try:
        for camera_id in ['speedcam1', 'speedcam2', 'speedcam3', 'speedcam4', 'speedcam5']:
            cur.execute(f"""
                SELECT ViolationID, ViolationType, ViolationTime, FinePaid
                FROM {camera_id}
                WHERE VehicleID = %s
            """, (vehicle_id,))
            violations = cur.fetchall()
            for violation in violations:
                violation_id, violation_type, violation_time, fine_paid = violation
                if not fine_paid:
                    cur.execute("SELECT VehicleType FROM vehicle_details WHERE VehicleID = %s", (vehicle_id,))
                    vehicle_type = cur.fetchone()[0]
                    zone = CAMERA_TO_ZONE.get(camera_id, "General")
                    cur.execute("SELECT COUNT(*) FROM FinePaymentHistory WHERE VehicleID = %s", (vehicle_id,))
                    violation_count = cur.fetchone()[0]
                    fine_amount = calculate_fine(cur, violation_type, zone, vehicle_type, violation_count)
                    unpaid_violations.append((violation_id, violation_type, violation_time, zone, fine_amount, camera_id))
    except psycopg2.Error as e:
        print(f"Error fetching unpaid violations: {e}")
    finally:
        cur.close()
        conn.close()

    return render_template('driver_dashboard.html', streak=streak, vehicle_id=vehicle_id, unpaid_violations=unpaid_violations)

# Route for Service History
@app.route('/service_history')
def service_history():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    vehicle_id = session['vehicle_id']
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

    return render_template('driver_service_history.html', service_history=service_history, vehicle_id=vehicle_id)

# Route for Fine Payment History
@app.route('/fine_payment_history', methods=['GET', 'POST'])
def fine_payment_history():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    vehicle_id = session['vehicle_id']
    message = ""

    if request.method == 'POST':
        violation_id = request.form['violation_id']
        camera_id = request.form['camera_id']
        violation_type = request.form['violation_type']
        fine_amount = float(request.form['fine_amount'])

        conn = get_db_connection()
        cur = conn.cursor()
        try:
            cur.execute(f"""
                UPDATE {camera_id}
                SET FinePaid = TRUE, ViolationTime = NOW()
                WHERE ViolationID = %s AND VehicleID = %s
            """, (violation_id, vehicle_id))

            cur.execute("""
                INSERT INTO FinePaymentHistory (VehicleID, ViolationType, ViolationTime, FineAmount, Paid)
                VALUES (%s, %s, NOW(), %s, TRUE)
            """, (vehicle_id, violation_type, fine_amount))
            conn.commit()
            message = "Fine paid successfully."
            update_safe_driving_streak(session['user_id'], vehicle_id)
        except psycopg2.Error as e:
            message = f"Error: {str(e)}"
        finally:
            cur.close()
            conn.close()

    conn = get_db_connection()
    cur = conn.cursor()
    unpaid_violations = []
    try:
        for camera_id in ['speedcam1', 'speedcam2', 'speedcam3', 'speedcam4', 'speedcam5']:
            cur.execute(f"""
                SELECT ViolationID, ViolationType, ViolationTime, FinePaid
                FROM {camera_id}
                WHERE VehicleID = %s
            """, (vehicle_id,))
            violations = cur.fetchall()
            for violation in violations:
                violation_id, violation_type, violation_time, fine_paid = violation
                if not fine_paid:
                    cur.execute("SELECT VehicleType FROM vehicle_details WHERE VehicleID = %s", (vehicle_id,))
                    vehicle_type = cur.fetchone()[0]
                    zone = CAMERA_TO_ZONE.get(camera_id, "General")
                    cur.execute("SELECT COUNT(*) FROM FinePaymentHistory WHERE VehicleID = %s", (vehicle_id,))
                    violation_count = cur.fetchone()[0]
                    fine_amount = calculate_fine(cur, violation_type, zone, vehicle_type, violation_count)
                    unpaid_violations.append((violation_id, violation_type, violation_time, fine_amount, camera_id))
    except psycopg2.Error as e:
        print(f"Error fetching violations: {e}")
    finally:
        cur.close()
        conn.close()

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT PaymentID, VehicleID, ViolationType, ViolationTime, FineAmount, Paid
            FROM FinePaymentHistory
            WHERE VehicleID = %s
            ORDER BY ViolationTime DESC
        """, (vehicle_id,))
        fine_history = cur.fetchall()
    except psycopg2.Error as e:
        fine_history = []
        print(f"Error fetching fine history: {e}")
    finally:
        cur.close()
        conn.close()

    return render_template('driver_fine_payment_history.html', unpaid_violations=unpaid_violations,
                           fine_history=fine_history, vehicle_id=vehicle_id, message=message)

# Route for Paying Fine via Link
@app.route('/pay_fine/<vehicle_id>/<violation_id>/<camera_id>', methods=['GET', 'POST'])
def pay_fine(vehicle_id, violation_id, camera_id):
    if 'user_id' not in session:
        return redirect(url_for('login', redirect=request.url))

    if session['vehicle_id'] != vehicle_id:
        return render_template('error.html', message="Unauthorized access. This vehicle does not belong to you.")

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute(f"""
            SELECT ViolationType, ViolationTime, FinePaid
            FROM {camera_id}
            WHERE ViolationID = %s AND VehicleID = %s
        """, (violation_id, vehicle_id))
        violation = cur.fetchone()
        if not violation:
            return render_template('error.html', message="Violation not found.")

        violation_type, violation_time, fine_paid = violation
        cur.execute("SELECT VehicleType FROM vehicle_details WHERE VehicleID = %s", (vehicle_id,))
        vehicle_type = cur.fetchone()
        if not vehicle_type:
            return render_template('error.html', message="Vehicle details not found.")
        vehicle_type = vehicle_type[0]
        zone = CAMERA_TO_ZONE.get(camera_id, "General")
        cur.execute("SELECT COUNT(*) FROM FinePaymentHistory WHERE VehicleID = %s", (vehicle_id,))
        violation_count = cur.fetchone()[0]
        fine_amount = calculate_fine(cur, violation_type, zone, vehicle_type, violation_count)

        violation_details = {
            'violation_type': violation_type,
            'violation_time': violation_time,
            'zone': zone,
            'fine_amount': fine_amount,
            'camera_id': camera_id,
            'fine_paid': fine_paid
        }

        if request.method == 'POST':
            if fine_paid:
                time_diff = datetime.now() - violation_time
                if time_diff.total_seconds() < 86400:
                    remaining_hours = (86400 - time_diff.total_seconds()) // 3600
                    return render_template('driver_pay_fine.html', vehicle_id=vehicle_id, violation_id=violation_id,
                                           camera_id=camera_id, violation_details=violation_details,
                                           message=f"Fine already paid. Valid for {int(remaining_hours)} hours.")
                else:
                    fine_paid = False

            if not fine_paid:
                cur.execute(f"""
                    UPDATE {camera_id}
                    SET FinePaid = TRUE, ViolationTime = NOW()
                    WHERE ViolationID = %s AND VehicleID = %s
                """, (violation_id, vehicle_id))
                cur.execute("""
                    INSERT INTO FinePaymentHistory (VehicleID, ViolationType, ViolationTime, FineAmount, Paid)
                    VALUES (%s, %s, NOW(), %s, TRUE)
                """, (vehicle_id, violation_type, fine_amount))
                conn.commit()
                update_safe_driving_streak(session['user_id'], vehicle_id)
                return render_template('driver_pay_fine.html', vehicle_id=vehicle_id, violation_id=violation_id,
                                       camera_id=camera_id, violation_details=violation_details,
                                       message="Fine paid successfully.")
            return render_template('driver_pay_fine.html', vehicle_id=vehicle_id, violation_id=violation_id,
                                   camera_id=camera_id, violation_details=violation_details,
                                   message="Fine already paid.")

        return render_template('driver_pay_fine.html', vehicle_id=vehicle_id, violation_id=violation_id,
                               camera_id=camera_id, violation_details=violation_details)

    except psycopg2.Error as e:
        print(f"Error in pay_fine: {e}")
        return render_template('error.html', message=f"Database error: {str(e)}")
    finally:
        cur.close()
        conn.close()

# Route for Fetching Violations via AJAX
@app.route('/get_violations/<vehicle_id>')
def get_violations(vehicle_id):
    if 'user_id' not in session or session['vehicle_id'] != vehicle_id:
        return jsonify({'error': 'Unauthorized'}), 403

    conn = get_db_connection()
    cur = conn.cursor()
    violations = []
    try:
        for camera_id in ['speedcam1', 'speedcam2', 'speedcam3', 'speedcam4', 'speedcam5']:
            cur.execute(f"""
                SELECT ViolationID, ViolationType, ViolationTime
                FROM {camera_id}
                WHERE VehicleID = %s
                ORDER BY ViolationTime DESC LIMIT 5
            """, (vehicle_id,))
            camera_violations = cur.fetchall()
            for violation in camera_violations:
                violations.append({
                    'violation_id': violation[0],
                    'violation_type': violation[1],
                    'violation_time': violation[2].isoformat(),
                    'zone': CAMERA_TO_ZONE.get(camera_id, 'General')
                })
    except psycopg2.Error as e:
        print(f"Error fetching violations: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        cur.close()
        conn.close()

    return jsonify({'violations': violations})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)