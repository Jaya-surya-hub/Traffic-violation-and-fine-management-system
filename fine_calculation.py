# fine_calculation.py

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
            adjusted_fine = round(fine_amount * multiplier, 2)
            return adjusted_fine
        else:
            return BASE_FINE_FALLBACK
    except Exception as e:
        print(f"❌ Fine calculation error: {e}")
        return BASE_FINE_FALLBACK
