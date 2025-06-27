from email_handler import send_email
from psycopg2 import sql
from datetime import datetime, timedelta

FINE_THRESHOLD = 3
SUSPEND_LIMIT = 7
OFFICER_EMAIL = "23i217@psgtech.ac.in"

CAMERA_TO_ZONE = {
    'speedcam1': 'School Zone',
    'speedcam2': 'Hospital Zone',
    'speedcam3': 'Residential Zone',
    'speedcam4': 'Highway',
    'speedcam5': 'Industrial Zone'
}

def process_violations(cam_table, conn):
    cur = conn.cursor()

    try:
        # Check if table exists
        cur.execute("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables
                WHERE table_name = %s
            );
        """, (cam_table,))
        if not cur.fetchone()[0]:
            print(f"[❌] Table '{cam_table}' does not exist.")
            return

        # Fetch all violations (even paid ones to check 24hr rule)
        query = sql.SQL("""
            SELECT ViolationID, VehicleID, ViolationType, ViolationTime, FinePaid
            FROM {}
        """).format(sql.Identifier(cam_table))
        cur.execute(query)
        violations = cur.fetchall()

        if not violations:
            print(f"[✓] No violations in {cam_table}.")
            return

        # Track vehicles that have already been processed for monthly threshold
        processed_vehicles = set()

        for violation_id, vehicle_id, violation_type, violation_time, fine_paid in violations:
            # Check if fine paid within 24 hours
            if fine_paid:
                now = datetime.now()
                if (now - violation_time).total_seconds() < 86400:  # 24 hours = 86400 seconds
                    print(f"[✓] Vehicle {vehicle_id} already paid fine within 24hrs. Skipping...")
                    continue

            # Check vehicle existence
            cur.execute("""
                SELECT OwnerName, IsEmergency, DriverEmail, VehicleType
                FROM vehicle_details
                WHERE VehicleID = %s
            """, (vehicle_id,))
            vehicle_info = cur.fetchone()

            if not vehicle_info:
                print(f"[!] Unknown vehicle ID {vehicle_id}. Adding default record and review entry...")

                # Insert default vehicle details
                cur.execute("""
                    INSERT INTO vehicle_details (VehicleID, OwnerName, IsEmergency, DriverEmail, VehicleType)
                    VALUES (%s, %s, %s, %s, %s)
                """, (vehicle_id, "Unknown Owner", "N", "unknown@example.com", "Car"))

                # Count total violations
                cur.execute("""
                    SELECT COUNT(*) FROM (
                        SELECT VehicleID FROM speedcam1 WHERE VehicleID = %s
                        UNION ALL SELECT VehicleID FROM speedcam2 WHERE VehicleID = %s
                        UNION ALL SELECT VehicleID FROM speedcam3 WHERE VehicleID = %s
                        UNION ALL SELECT VehicleID FROM speedcam4 WHERE VehicleID = %s
                        UNION ALL SELECT VehicleID FROM speedcam5 WHERE VehicleID = %s
                    ) AS all_violations
                """, (vehicle_id,) * 5)
                total_violations = cur.fetchone()[0]

                # Add to LicenseReviewList
                cur.execute("""
                    INSERT INTO LicenseReviewList (vehicleid, numberofviolations, addeddate, reviewreason)
                    VALUES (%s, %s, NOW(), %s)
                """, (vehicle_id, total_violations, "Unregistered vehicle auto-added for review"))

                # Notify officer about unknown vehicle
                officer_subject = f"Unknown Vehicle Detected: {vehicle_id}"
                officer_body = f"""🚨 UNKNOWN VEHICLE ALERT 🚨

Vehicle ID       : {vehicle_id}
Total Violations : {total_violations}
Detected In      : {cam_table.upper()} ({CAMERA_TO_ZONE.get(cam_table)})
Violation Type   : {violation_type}

This vehicle is not registered in the system and has been added for license review.
Recommended: Investigate the vehicle and its owner.
"""
                send_email(OFFICER_EMAIL, officer_subject, officer_body)

                continue

            owner_name, is_emergency, email, vehicle_type = vehicle_info

            # Skip emergency vehicles
            if is_emergency and is_emergency.upper() == 'Y':
                print(f"[!] Emergency vehicle {vehicle_id}. Skipping...")
                continue

            # Confirm violation
            cur.execute(sql.SQL("""
                SELECT COUNT(*) FROM {}
                WHERE VehicleID = %s AND ViolationID = %s
            """).format(sql.Identifier(cam_table)), (vehicle_id, violation_id))
            if cur.fetchone()[0] == 0:
                print(f"[!] No such violation {violation_id} for {vehicle_id}. Skipping...")
                continue

            # Count total violations (lifetime)
            cur.execute("""
                SELECT COUNT(*) FROM (
                    SELECT VehicleID FROM speedcam1 WHERE VehicleID = %s
                    UNION ALL SELECT VehicleID FROM speedcam2 WHERE VehicleID = %s
                    UNION ALL SELECT VehicleID FROM speedcam3 WHERE VehicleID = %s
                    UNION ALL SELECT VehicleID FROM speedcam4 WHERE VehicleID = %s
                    UNION ALL SELECT VehicleID FROM speedcam5 WHERE VehicleID = %s
                ) AS all_violations
            """, (vehicle_id,) * 5)
            total_violations = cur.fetchone()[0]

            # Count violations in the current month
            current_date = datetime.now()
            start_of_month = current_date.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            cur.execute("""
                SELECT COUNT(*) FROM (
                    SELECT VehicleID FROM speedcam1 WHERE VehicleID = %s AND ViolationTime >= %s
                    UNION ALL SELECT VehicleID FROM speedcam2 WHERE VehicleID = %s AND ViolationTime >= %s
                    UNION ALL SELECT VehicleID FROM speedcam3 WHERE VehicleID = %s AND ViolationTime >= %s
                    UNION ALL SELECT VehicleID FROM speedcam4 WHERE VehicleID = %s AND ViolationTime >= %s
                    UNION ALL SELECT VehicleID FROM speedcam5 WHERE VehicleID = %s AND ViolationTime >= %s
                ) AS monthly_violations
            """, (vehicle_id, start_of_month) * 5)
            monthly_violations = cur.fetchone()[0]

            # Check if monthly threshold exceeded and vehicle not yet processed
            if monthly_violations > FINE_THRESHOLD and vehicle_id not in processed_vehicles:
                processed_vehicles.add(vehicle_id)  # Mark vehicle as processed

                # Send email to driver
                driver_subject = "🚨 Reminder: Monthly Violation Threshold Exceeded"
                driver_body = f"""Dear {owner_name},

You have exceeded the monthly violation threshold of {FINE_THRESHOLD} violations.
Total Violations This Month: {monthly_violations}
Vehicle ID: {vehicle_id}

Please take corrective action to avoid further penalties. Repeated violations may lead to license review.

Drive safe,
Chennai Traffic Management
"""
                send_email(email, driver_subject, driver_body)

                # Send email to officer
                officer_subject = f"Reminder: Vehicle {vehicle_id} Exceeded Monthly Violation Threshold"
                officer_body = f"""🚨 MONTHLY VIOLATION ALERT 🚨

Vehicle ID       : {vehicle_id}
Owner            : {owner_name}
Total Violations This Month: {monthly_violations}
Threshold        : {FINE_THRESHOLD}

Recommended: Monitor this driver for potential license review.
"""
                send_email(OFFICER_EMAIL, officer_subject, officer_body)

                # Add to LicenseReviewList
                cur.execute("""
                    INSERT INTO LicenseReviewList (vehicleid, numberofviolations, addeddate, reviewreason)
                    VALUES (%s, %s, NOW(), %s)
                """, (vehicle_id, monthly_violations, "Exceeded monthly violation threshold"))

            # Validate violation type
            valid_violation_types = [
                'Speeding', 'Parking', 'Red Light', 'Overtake',
                'Signal Jumping', 'Over Speeding', 'Wrong Lane',
                'No Helmet', 'Triple Riding', 'Drunk Driving'
            ]
            if violation_type not in valid_violation_types:
                print(f"[!] Invalid violation type '{violation_type}'. Skipping...")
                continue

            # Officer alert if total violations exceed FINE_THRESHOLD
            if total_violations >= FINE_THRESHOLD:
                officer_msg = f"""🚨 FREQUENT VIOLATOR 🚨

Vehicle ID       : {vehicle_id}
Owner            : {owner_name}
Total Violations : {total_violations}
Zone             : {CAMERA_TO_ZONE.get(cam_table)}
Violation        : {violation_type}

Recommended: License review or re-education counselling.
"""
                send_email(OFFICER_EMAIL, f"Frequent Violator: {vehicle_id}", officer_msg)

            # Add to license review if suspension limit crossed
            if total_violations >= SUSPEND_LIMIT:
                cur.execute("""
                    INSERT INTO LicenseReviewList (vehicleid, numberofviolations, addeddate, reviewreason)
                    VALUES (%s, %s, NOW(), %s)
                """, (vehicle_id, total_violations, "License suspension review"))

            # Send driver email for the specific violation
            extra_note = ""
            if total_violations >= SUSPEND_LIMIT:
                extra_note += "\n⚠️ Your license is under suspension review due to 7+ violations."
                extra_note += "\n📩 A review has been initiated with the traffic authorities."

            subject = "🚨 Traffic Violation Notice"
            body = f"""Dear {owner_name},

Your vehicle (ID: {vehicle_id}) has committed a traffic violation.

Violation Type : {violation_type}
Date & Time    : {violation_time}
Zone           : {CAMERA_TO_ZONE.get(cam_table)}
Camera Source  : {cam_table.upper()}
Vehicle Type   : {vehicle_type}

Please pay your fine here:
 http://192.168.74.190:5000

Drive safe,
Chennai Traffic Management
{extra_note}
"""
            send_email(email, subject, body)

        conn.commit()
        print(f"[✓] Processed violations for {cam_table}")

    except Exception as e:
        conn.rollback()
        print(f"❌ Error processing violations: {e}")

    finally:
        cur.close()