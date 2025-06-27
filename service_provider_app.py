from flask import Flask, render_template, request, redirect, url_for
import psycopg2
from datetime import datetime

app = Flask(__name__)
app.secret_key = 'service_provider_secret_key'

def get_db_connection():
    return psycopg2.connect(
        host="localhost",
        database="traffic_violation_system",
        user="postgres",
        password="freefire"
    )

# Route for Service Provider Dashboard
@app.route('/')
def service_provider_dashboard():
    return render_template('service_provider_dashboard.html')

# Route for Service Provider to Update Vehicle Service Details
@app.route('/service_provider_update', methods=['GET', 'POST'])
def service_provider_update():
    if request.method == 'POST':
        vehicle_id = request.form['vehicle_id']
        service_id = request.form['service_id']
        service_date = request.form['service_date']
        service_description = request.form['service_description']
        service_provider = request.form['service_provider']
        service_cost = float(request.form['service_cost'])

        conn = get_db_connection()
        cur = conn.cursor()
        try:
            # Check if vehicle exists in vehicle_details
            cur.execute("SELECT VehicleID FROM vehicle_details WHERE VehicleID = %s", (vehicle_id,))
            if not cur.fetchone():
                return render_template('service_provider_update.html', message="Vehicle ID not found.")

            # Check if service_id already exists to prevent duplicates
            cur.execute("SELECT ServiceID FROM VehicleServiceHistory WHERE ServiceID = %s", (service_id,))
            if cur.fetchone():
                return render_template('service_provider_update.html', message="Service ID already exists. Please use a unique Service ID.")

            # Insert the service record into VehicleServiceHistory
            cur.execute("""
                INSERT INTO VehicleServiceHistory (ServiceID, VehicleID, ServiceDate, ServiceDescription, ServiceProvider, ServiceCost)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (service_id, vehicle_id, service_date, service_description, service_provider, service_cost))
            conn.commit()
            return render_template('service_provider_update.html', message="Service record updated successfully.")
        except psycopg2.Error as e:
            return render_template('service_provider_update.html', message=f"Error: {str(e)}")
        finally:
            cur.close()
            conn.close()
    return render_template('service_provider_update.html')

# Route for Service Provider to View Vehicle Service History
@app.route('/service_history', methods=['GET'])
def service_history():
    vehicleid = request.args.get('vehicleid')
    service_history = None
    if vehicleid:
        conn = get_db_connection()
        cur = conn.cursor()
        try:
            # Check if vehicle exists in vehicle_details
            cur.execute("SELECT VehicleID FROM vehicle_details WHERE VehicleID = %s", (vehicleid,))
            if not cur.fetchone():
                return render_template('service_history.html', vehicleid=vehicleid, message="Vehicle ID not found.")

            # Fetch service history for the vehicle
            cur.execute("""
                SELECT ServiceID, VehicleID, ServiceDate, ServiceDescription, ServiceProvider, ServiceCost
                FROM VehicleServiceHistory
                WHERE VehicleID = %s
                ORDER BY ServiceDate DESC
            """, (vehicleid,))
            service_history = cur.fetchall()
        except psycopg2.Error as e:
            return render_template('service_history.html', vehicleid=vehicleid, message=f"Error: {str(e)}")
        finally:
            cur.close()
            conn.close()
    return render_template('service_history.html', vehicleid=vehicleid, service_history=service_history)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5002, debug=True)