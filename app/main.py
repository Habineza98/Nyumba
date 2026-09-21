import os
import random
import smtplib
from email.message import EmailMessage
from dotenv import load_dotenv

from fastapi import FastAPI, Request, Form, Depends, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
import bcrypt

from app import models, database
from app.database import get_db

# 1. Load Environment Variables
load_dotenv()

SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 465
SENDER_EMAIL = os.getenv("SMTP_EMAIL")
SENDER_PASSWORD = os.getenv("SMTP_PASSWORD")

# 2. Database Tables Initialization
models.Base.metadata.create_all(bind=database.engine)

# 3. Password Hashing Helpers
def get_password_hash(password: str) -> str:
    pwd_bytes = password.encode("utf-8")[:72]
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(pwd_bytes, salt)
    return hashed.decode("utf-8")

def verify_password(plain_password: str, hashed_password: str) -> bool:
    pwd_bytes = plain_password.encode("utf-8")[:72]
    hash_bytes = hashed_password.encode("utf-8")
    return bcrypt.checkpw(pwd_bytes, hash_bytes)

# 4. Application Setup
app = FastAPI()

templates = Jinja2Templates(directory="app/templates")
app.mount("/static", StaticFiles(directory="app/static"), name="static")

PENDING_REGISTRATIONS = {}


# 5. Email Helper
def send_otp_email(recipient_email: str, code: str) -> bool:
    msg = EmailMessage()
    msg["Subject"] = "Nyumba SaaS - Your Verification Code"
    msg["From"] = SENDER_EMAIL
    msg["To"] = recipient_email
    msg.set_content(f"Hello,\n\nYour verification code is: {code}\n\nThis code will expire shortly.")

    try:
        with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT) as smtp:
            smtp.login(SENDER_EMAIL, SENDER_PASSWORD)
            smtp.send_message(msg)
        print(f"[OTP SUCCESS] Code {code} successfully sent to {recipient_email}")
        return True
    except Exception as e:
        print(f"[OTP ERROR] Failed to send email to {recipient_email}: {e}")
        return False


# 6. Routes

@app.get("/", response_class=HTMLResponse)
def get_homepage(request: Request, db: Session = Depends(get_db)):
    user_id = request.cookies.get("user_id")
    user = None
    if user_id:
        try:
            user = db.query(models.User).filter(models.User.id == int(user_id)).first()
        except (ValueError, TypeError):
            user = None

    return templates.TemplateResponse(
        request=request,
        name="landing.html",
        context={"request": request, "user": user}
    )


# --- SIGN UP & OTP ---

@app.get("/signup", response_class=HTMLResponse)
def get_signup_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="signup.html",
        context={"otp_sent": False}
    )


@app.post("/signup")
def process_signup(
    request: Request,
    full_name: str = Form(...),
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db)
):
    raw_pwd_bytes = password.encode("utf-8")
    if len(raw_pwd_bytes) > 72:
        password = raw_pwd_bytes[:72].decode("utf-8", errors="ignore")

    is_email = "@" in username
    existing_user = db.query(models.User).filter(
        (models.User.email == username) if is_email else (models.User.phone_number == username)
    ).first()

    if existing_user:
        return templates.TemplateResponse(
            request=request,
            name="signup.html",
            context={
                "error": "An account with this email/phone already exists.",
                "otp_sent": False
            },
            status_code=status.HTTP_400_BAD_REQUEST
        )

    otp_code = str(random.randint(100000, 999999))
    
    PENDING_REGISTRATIONS[username] = {
        "otp": otp_code,
        "full_name": full_name,
        "password": password
    }

    if is_email:
        email_sent = send_otp_email(username, otp_code)
        if not email_sent:
            return templates.TemplateResponse(
                request=request,
                name="signup.html",
                context={
                    "error": "Failed to send verification email. Please check your address or try again.",
                    "otp_sent": False
                },
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    return templates.TemplateResponse(
        request=request,
        name="signup.html",
        context={
            "otp_sent": True,
            "username": username
        }
    )


@app.post("/verify-otp")
def verify_otp_and_register(
    request: Request,
    username: str = Form(...),
    otp_code: str = Form(...),
    db: Session = Depends(get_db)
):
    registration_data = PENDING_REGISTRATIONS.get(username)

    if not registration_data or otp_code.strip() != registration_data["otp"]:
        return templates.TemplateResponse(
            request=request,
            name="signup.html",
            context={
                "error": "Invalid verification code. Please try again.",
                "otp_sent": True,
                "username": username
            },
            status_code=status.HTTP_400_BAD_REQUEST
        )

    full_name = registration_data["full_name"]
    raw_password = registration_data["password"]
    is_email = "@" in username

    try:
        hashed_pwd = get_password_hash(raw_password)

        new_user = models.User(
            full_name=full_name,
            email=username if is_email else None,
            phone_number=username if not is_email else None,
            hashed_password=hashed_pwd,
            is_active=True
        )

        db.add(new_user)
        db.commit()
        db.refresh(new_user)
        
        PENDING_REGISTRATIONS.pop(username, None)

    except Exception as e:
        db.rollback()
        return templates.TemplateResponse(
            request=request,
            name="signup.html",
            context={
                "error": f"Registration failed: {e}",
                "otp_sent": False
            },
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

    response = RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    response.set_cookie(key="user_id", value=str(new_user.id), httponly=True)
    return response


# --- SIGN IN ---

@app.get("/signin", response_class=HTMLResponse)
def get_signin_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="signin.html",
        context={}
    )


@app.post("/signin")
def process_signin(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db)
):
    is_email = "@" in username
    user = db.query(models.User).filter(
        (models.User.email == username) if is_email else (models.User.phone_number == username)
    ).first()

    if not user or not verify_password(password, user.hashed_password):
        return templates.TemplateResponse(
            request=request,
            name="signin.html",
            context={"error": "Invalid email/phone or password. Please try again."},
            status_code=status.HTTP_400_BAD_REQUEST
        )

    response = RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    response.set_cookie(key="user_id", value=str(user.id), httponly=True)
    return response


# --- DASHBOARD & PROPERTIES ---

@app.get("/dashboard", response_class=HTMLResponse)
def get_dashboard(request: Request, db: Session = Depends(get_db)):
    user_id = request.cookies.get("user_id")
    if not user_id:
        return RedirectResponse(url="/signin", status_code=status.HTTP_303_SEE_OTHER)

    try:
        user = db.query(models.User).filter(models.User.id == int(user_id)).first()
    except (ValueError, TypeError):
        user = None

    if not user:
        response = RedirectResponse(url="/signin", status_code=status.HTTP_303_SEE_OTHER)
        response.delete_cookie("user_id")
        return response

    properties = db.query(models.Property).filter(models.Property.owner_id == user.id).all()
    
    total_properties = len(properties)
    all_units = []
    for prop in properties:
        all_units.extend(prop.units)

    total_tenants = sum(1 for u in all_units if u.tenant_name)
    monthly_revenue = sum(u.rent_price for u in all_units if u.status == "Paid")

    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            "user": user,
            "total_properties": total_properties,
            "total_tenants": total_tenants,
            "monthly_revenue": monthly_revenue,
            "properties": properties
        }
    )


@app.post("/properties/add")
def create_property(
    request: Request,
    name: str = Form(...),
    address: str = Form(...),
    db: Session = Depends(get_db)
):
    user_id = request.cookies.get("user_id")
    if not user_id:
        return RedirectResponse(url="/signin", status_code=status.HTTP_303_SEE_OTHER)

    new_property = models.Property(
        name=name,
        address=address,
        owner_id=int(user_id)
    )
    db.add(new_property)
    db.commit()

    return RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/property/{property_id}/edit")
def edit_property(
    property_id: int,
    request: Request,
    name: str = Form(...),
    address: str = Form(...),
    db: Session = Depends(get_db)
):
    user_id = request.cookies.get("user_id")
    if not user_id:
        return RedirectResponse(url="/signin", status_code=status.HTTP_303_SEE_OTHER)

    prop = db.query(models.Property).filter(
        models.Property.id == property_id,
        models.Property.owner_id == int(user_id)
    ).first()

    if prop:
        prop.name = name
        prop.address = address
        db.commit()

    return RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/property/{property_id}/delete")
def delete_property(property_id: int, request: Request, db: Session = Depends(get_db)):
    user_id = request.cookies.get("user_id")
    if not user_id:
        return RedirectResponse(url="/signin", status_code=status.HTTP_303_SEE_OTHER)

    prop = db.query(models.Property).filter(
        models.Property.id == property_id,
        models.Property.owner_id == int(user_id)
    ).first()

    if prop:
        db.delete(prop)
        db.commit()

    return RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)


# --- PROPERTY DETAIL & UNITS ---

@app.get("/property/{property_id}", response_class=HTMLResponse)
def get_property_detail(property_id: int, request: Request, db: Session = Depends(get_db)):
    user_id = request.cookies.get("user_id")
    if not user_id:
        return RedirectResponse(url="/signin", status_code=status.HTTP_303_SEE_OTHER)

    try:
        user = db.query(models.User).filter(models.User.id == int(user_id)).first()
    except (ValueError, TypeError):
        user = None

    if not user:
        response = RedirectResponse(url="/signin", status_code=status.HTTP_303_SEE_OTHER)
        response.delete_cookie("user_id")
        return response

    prop = db.query(models.Property).filter(
        models.Property.id == property_id,
        models.Property.owner_id == user.id
    ).first()

    if not prop:
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)

    units = prop.units
    total_units = len(units)
    paid_units = sum(1 for u in units if u.status == "Paid")
    overdue_units = sum(1 for u in units if u.status == "Overdue")
    collected_rent = sum(u.rent_price for u in units if u.status == "Paid")
    
    collection_rate = (paid_units / total_units * 100) if total_units > 0 else 0.0

    return templates.TemplateResponse(
        request=request,
        name="property_detail.html",
        context={
            "user": user,
            "property": prop,
            "units": units,
            "collected_rent": collected_rent,
            "collection_rate": collection_rate,
            "overdue_units": overdue_units
        }
    )


@app.post("/property/{property_id}/unit/add")
def add_unit(
    property_id: int,
    request: Request,
    unit_name: str = Form(...),
    tenant_name: str = Form(""),
    rent_price: float = Form(...),
    due_day: int = Form(5),
    db: Session = Depends(get_db)
):
    user_id = request.cookies.get("user_id")
    if not user_id:
        return RedirectResponse(url="/signin", status_code=status.HTTP_303_SEE_OTHER)

    new_unit = models.Unit(
        unit_name=unit_name,
        tenant_name=tenant_name,
        rent_price=rent_price,
        due_day=due_day,
        status="Pending",
        property_id=property_id
    )
    db.add(new_unit)
    db.commit()

    return RedirectResponse(url=f"/property/{property_id}", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/unit/{unit_id}/edit")
def edit_unit(
    unit_id: int,
    request: Request,
    unit_name: str = Form(...),
    tenant_name: str = Form(""),
    rent_price: float = Form(...),
    due_day: int = Form(5),
    db: Session = Depends(get_db)
):
    user_id = request.cookies.get("user_id")
    if not user_id:
        return RedirectResponse(url="/signin", status_code=status.HTTP_303_SEE_OTHER)

    unit = db.query(models.Unit).filter(models.Unit.id == unit_id).first()
    if unit:
        unit.unit_name = unit_name
        unit.tenant_name = tenant_name
        unit.rent_price = rent_price
        unit.due_day = due_day
        db.commit()
        return RedirectResponse(url=f"/property/{unit.property_id}", status_code=status.HTTP_303_SEE_OTHER)

    return RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/unit/{unit_id}/status")
def update_unit_status(
    unit_id: int,
    request: Request,
    status: str = Form(...),
    db: Session = Depends(get_db)
):
    user_id = request.cookies.get("user_id")
    if not user_id:
        return RedirectResponse(url="/signin", status_code=status.HTTP_303_SEE_OTHER)

    unit = db.query(models.Unit).filter(models.Unit.id == unit_id).first()
    if unit:
        unit.status = status
        db.commit()
        return RedirectResponse(url=f"/property/{unit.property_id}", status_code=status.HTTP_303_SEE_OTHER)

    return RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/unit/{unit_id}/delete")
def delete_unit(unit_id: int, request: Request, db: Session = Depends(get_db)):
    user_id = request.cookies.get("user_id")
    if not user_id:
        return RedirectResponse(url="/signin", status_code=status.HTTP_303_SEE_OTHER)

    unit = db.query(models.Unit).filter(models.Unit.id == unit_id).first()
    if unit:
        prop_id = unit.property_id
        db.delete(unit)
        db.commit()
        return RedirectResponse(url=f"/property/{prop_id}", status_code=status.HTTP_303_SEE_OTHER)
    return RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)


@app.get("/logout")
def logout():
    response = RedirectResponse(url="/signin", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie("user_id")
    return response