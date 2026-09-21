from app.database import SessionLocal, engine, Base
import app.models  # Registers model metadata
from app.models import Property, Unit

# 1. Drop all old tables to wipe outdated schemas cleanly
Base.metadata.drop_all(bind=engine)

# 2. Recreate tables with the new columns (rent_amount, payment_status, tenant_name)
Base.metadata.create_all(bind=engine)

db = SessionLocal()

try:
    # Create sample property
    property1 = Property(name="Rubangura House", location="Nyarugenge, Kigali")
    db.add(property1)
    db.commit()
    db.refresh(property1)

    # Add sample units matching your layout mockup
    units_data = [
        Unit(unit_number="Apt 3B", tenant_name="J.Mugisha", rent_amount=350000, payment_status="Paid", property_id=property1.id),
        Unit(unit_number="Apt 4A", tenant_name="A. Uwase", rent_amount=300000, payment_status="Paid", property_id=property1.id),
        Unit(unit_number="Apt 4B", tenant_name="D. Habimana", rent_amount=300000, payment_status="Late", property_id=property1.id),
        Unit(unit_number="Shop 12", tenant_name="K. Textiles", rent_amount=500000, payment_status="Late", property_id=property1.id),
    ]

    db.add_all(units_data)
    db.commit()
    print("Database successfully seeded!")
except Exception as e:
    db.rollback()
    print(f"Error seeding database: {e}")
finally:
    db.close()