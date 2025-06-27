from flask import Flask, render_template, request, redirect, url_for
import psycopg2
from datetime import datetime
from email_handler import send_email

app = Flask(__name__)
app.secret_key = 'registration_office_secret_key'

def get_db_connection():
    return psycopg2.connect(
        host="localhost",
        database="traffic_violation_system",
        user="postgres",
        password="freefire"
    )

@app.route('/')
def registration_office_dashboard():
    return render_template('registration_office_dashboard.html')

@app.route('/registration_office_add_vehicle', methods=['GET', 'POST'])
def registration_office_add_vehicle():
    if request.method == 'POST':
        vehicle_id = request.form['vehicle_id']
        owner_name = request.form['owner_name']
        driver_email = request.form['driver_email']
        driver_phone = request.form['driver_phone']
        vehicle_type = request.form['vehicle_type']
        is_emergency = request.form['is_emergency']
        home_address = request.form['home_address']
        vehicle_model = request.form['vehicle_model']
        registration_date = request.form['registration_date']

        conn = get_db_connection()
        cur = conn.cursor()
        try:
            cur.execute("SELECT VehicleID FROM vehicle_details WHERE VehicleID = %s", (vehicle_id,))
            if cur.fetchone():
                return render_template('registration_office_add_vehicle.html', message="Vehicle ID already exists.")

            cur.execute("""
                INSERT INTO vehicle_details (VehicleID, OwnerName, DriverEmail, DriverPhone, VehicleType, IsEmergency, HomeAddress, VehicleModel, RegistrationDate)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (vehicle_id, owner_name, driver_email, driver_phone, vehicle_type, is_emergency, home_address, vehicle_model, registration_date))
            conn.commit()

            subject = "Vehicle Registration Successful - Access Your Driver Portal"
            body = f"""Dear {owner_name},\n\nYour vehicle (ID: {vehicle_id}) has been successfully registered with the Traffic Violation System.\n\nDetails:\n- Email: {driver_email}\n- Phone: {driver_phone}\n\nYou can now access your Driver Portal to view your dashboard, check service history, manage fine payments, and more.\n\nVisit the Driver Portal here: http://192.168.74.190:5000\n\n- Traffic Control System"""
            send_email(driver_email, subject, body)

            return render_template('registration_office_add_vehicle.html', message="Vehicle added successfully. Confirmation email sent to the driver.")
        except psycopg2.Error as e:
            return render_template('registration_office_add_vehicle.html', message=f"Error: {str(e)}")
        finally:
            cur.close()
            conn.close()
    return render_template('registration_office_add_vehicle.html')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5003, debug=True)