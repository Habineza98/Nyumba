from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.main import app
import app.models as models

client = TestClient(app)


def reset_db():
    db = SessionLocal()
    try:
        db.query(models.Unit).delete()
        db.query(models.Property).delete()
        db.commit()
    finally:
        db.close()


def test_property_detail_unit_form_includes_all_fields():
    reset_db()

    db = SessionLocal()
    try:
        prop = models.Property(name="Alpha Homes", location="Kigali")
        db.add(prop)
        db.commit()
        db.refresh(prop)
        property_id = prop.id
    finally:
        db.close()

    response = client.get(f"/property/{property_id}")

    assert response.status_code == 200
    html = response.text
    assert 'name="unit_number"' in html
    assert 'name="tenant_name"' in html
    assert 'name="rent_amount"' in html
    assert 'name="payment_status"' in html
