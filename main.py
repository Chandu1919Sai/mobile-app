import os
from datetime import datetime, date, time
from calendar import monthrange
from typing import Optional

from fastapi import (
    FastAPI, Depends, HTTPException, status,
    UploadFile, File, Form
)
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from database import Base, engine, SessionLocal
from models import User, Attendance, Holiday, Shift
from schemas import SignupSchema, AttendanceMarkSchema
from auth import hash_password, verify_password, create_token, decode_token

# ---------------- APP SETUP ----------------

Base.metadata.create_all(bind=engine)

app = FastAPI(title="QR Attendance System")
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login")

BASE_URL = "http://192.168.1.3:8000"
UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

# ---------------- SHIFT HELPERS ----------------

def get_or_create_default_shift(db: Session) -> Shift:
    """
    Ensures there's at least one shift in the DB and returns it.
    This also protects check-in paths from NULL shift_id inserts.
    """
    shift = db.query(Shift).order_by(Shift.id.asc()).first()
    if shift:
        return shift

    # Create a reasonable default so the system can function out-of-the-box.
    shift = Shift(
        name="Default",
        start_time=time(9, 0),
        end_time=time(18, 0),
        min_hours=9,
        weekend_days="5,6",
    )
    db.add(shift)
    db.commit()
    db.refresh(shift)
    return shift


def ensure_user_shift(user: User, db: Session) -> int:
    """
    Guarantees user.shift_id is populated, creating/assigning a default shift
    when legacy users have NULL shift_id.
    """
    if getattr(user, "shift_id", None):
        return user.shift_id

    default_shift = get_or_create_default_shift(db)
    user.shift_id = default_shift.id
    db.commit()
    db.refresh(user)
    return user.shift_id

# ---------------- DB ----------------

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ---------------- AUTH HELPERS ----------------

def get_current_user_from_token(
    token: str,
    db: Session
) -> User:
    payload = decode_token(token)
    user = db.query(User).filter(User.id == payload["user_id"]).first()

    if not user:
        raise HTTPException(status_code=401, detail="Invalid user")

    return user


def get_current_admin(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db)
):
    payload = decode_token(token)
    if payload.get("role") != "admin":
        raise HTTPException(403, "Admin access only")
    return payload

# ---------------- SIGNUP ----------------

@app.post("/signup")
def signup(data: SignupSchema, db: Session = Depends(get_db)):
    if db.query(User).filter(
        (User.username == data.username) |
        (User.email == data.email) |
        (User.phone_number == data.phone_number)
    ).first():
        raise HTTPException(400, "User already exists")

    default_shift = get_or_create_default_shift(db)
    shift_id = data.shift_id or default_shift.id

    user = User(
        name=data.name,
        username=data.username,
        email=data.email,
        phone_number=data.phone_number,
        password=hash_password(data.password),
        role=data.role,
        shift_id=shift_id,
    )
    db.add(user)
    db.commit()
    return {"message": "Signup successful"}

# ---------------- LOGIN ----------------

@app.post("/login")
def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db)
):
    user = db.query(User).filter(User.username == form_data.username).first()
    if not user or not verify_password(form_data.password, user.password):
        raise HTTPException(401, "Invalid credentials")

    token = create_token({"user_id": user.id, "role": user.role}, minutes=60)
    return {"access_token": token, "token_type": "Bearer"}

# ---------------- PROFILE ----------------

@app.get("/profile")
def profile(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db)
):
    user = get_current_user_from_token(token, db)
    return {
        "id": user.id,
        "name": user.name,
        "username": user.username,
        "email": user.email,
        "phone_number": user.phone_number,
        "role": user.role,
        "profile_image": user.profile_image
    }

# ---------------- PROFILE PATCH ----------------

from datetime import datetime
@app.patch("/profile")
def patch_profile(
    name: Optional[str] = Form(None),
    username: Optional[str] = Form(None),
    email: Optional[str] = Form(None),
    phone_number: Optional[str] = Form(None),
    image: UploadFile = File(None),
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db)
):
    user = get_current_user_from_token(token, db)

    if username:
        user.username = username
    if email:
        user.email = email
    if phone_number:
        user.phone_number = phone_number
    if name:
        user.name = name

    if image:
        ext = image.filename.split(".")[-1]
        filename = f"user_{user.id}.{ext}"
        path = os.path.join(UPLOAD_DIR, filename)

        with open(path, "wb") as f:
            f.write(image.file.read())

        # 🔥 CACHE-BUSTING URL
        user.profile_image = (
            f"{BASE_URL}/uploads/{filename}"
            f"?v={int(datetime.utcnow().timestamp())}"
        )

    db.commit()

    return {
        "message": "Profile updated",
        "profile_image": user.profile_image
    }

# ---------------- QR GENERATE ----------------

@app.get("/admin/generate-qr")
def generate_qr(admin=Depends(get_current_admin)):
    qr_token = create_token(
        {"purpose": "attendance", "session_id": str(datetime.utcnow().timestamp())},
        minutes=10
    )
    return {"qr_token": qr_token}

# ---------------- CHECK-IN ----------------

@app.post("/attendance/check-in")
def check_in(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db)
):
    user = get_current_user_from_token(token, db)
    today = date.today()

    ensure_user_shift(user, db)

    if db.query(Attendance).filter(
        Attendance.user_id == user.id,
        Attendance.attendance_date == today
    ).first():
        raise HTTPException(400, "Already checked in")

    attendance = Attendance(
        user_id=user.id,
        attendance_date=today,
        shift_id=user.shift_id,
        check_in=datetime.now()
    )
    db.add(attendance)
    db.commit()
    return {"message": "Check-in successful"}


# ---------------- QR MARK (check-in/out via QR token) ----------------

@app.post("/attendance/mark")
def attendance_mark(
    data: AttendanceMarkSchema,
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db)
):
    """
    Mobile client hits this after scanning QR.
    qr_token encodes {"purpose": "attendance", "session_id": ...}
    data.status is "check_in" or "check_out".
    """
    user = get_current_user_from_token(token, db)
    ensure_user_shift(user, db)

    payload = decode_token(data.qr_token)
    purpose = payload.get("purpose")
    if purpose != "attendance":
        raise HTTPException(
            status_code=400,
            detail=f"Invalid QR token purpose: {purpose!r} (expected 'attendance')"
        )

    try:
        ts = datetime.fromisoformat(data.timestamp)
    except Exception:
        ts = datetime.now()

    attendance_date = ts.date()

    attendance = db.query(Attendance).filter(
        Attendance.user_id == user.id,
        Attendance.attendance_date == attendance_date
    ).first()

    if data.status == "check_in":
        if attendance and attendance.check_in:
            raise HTTPException(status_code=400, detail="Already checked in")

        if not attendance:
            attendance = Attendance(
                user_id=user.id,
                attendance_date=attendance_date,
                shift_id=user.shift_id
            )
            db.add(attendance)

        attendance.check_in = ts
        db.commit()
        return {"message": "Check-in successful", "attendance_date": attendance_date}

    # check_out
    if not attendance or not attendance.check_in:
        raise HTTPException(status_code=400, detail="Check-in missing (cannot check out before check-in)")

    if attendance.check_out:
        raise HTTPException(status_code=400, detail="Already checked out")

    attendance.check_out = ts
    hours = (attendance.check_out - attendance.check_in).total_seconds() / 3600
    attendance.worked_hours = round(hours, 2)
    attendance.status = (
        "Present" if hours >= 9 else
        "Half-Day" if hours >= 4.5 else
        "Absent"
    )
    db.commit()

    return {
        "message": "Check-out successful",
        "worked_hours": attendance.worked_hours,
        "status": attendance.status,
        "attendance_date": attendance_date
    }

# ---------------- CHECK-OUT ----------------

@app.post("/attendance/check-out")
def check_out(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db)
):
    user = get_current_user_from_token(token, db)
    today = date.today()

    attendance = db.query(Attendance).filter(
        Attendance.user_id == user.id,
        Attendance.attendance_date == today
    ).first()

    if not attendance or not attendance.check_in:
        raise HTTPException(400, "Check-in missing")

    attendance.check_out = datetime.now()
    hours = (attendance.check_out - attendance.check_in).total_seconds() / 3600
    attendance.worked_hours = round(hours, 2)

    attendance.status = (
        "Present" if hours >= 9 else
        "Half-Day" if hours >= 4.5 else
        "Absent"
    )

    db.commit()
    return {"worked_hours": attendance.worked_hours, "status": attendance.status}

# ---------------- DAY TYPE ----------------

def get_day_type(user: User, day: date, db: Session):
    if db.query(Holiday).filter(Holiday.date == day).first():
        return "Holiday"

    shift = db.query(Shift).get(ensure_user_shift(user, db))
    if day.weekday() in [int(d) for d in shift.weekend_days.split(",")]:
        return "Week-off"

    return "Working"

# ---------------- MONTHLY CALENDAR ----------------

@app.get("/attendance/calendar")
def monthly_calendar(
    year: int,
    month: int,
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db)
):
    user = get_current_user_from_token(token, db)
    calendar = []

    ensure_user_shift(user, db)

    for d in range(1, monthrange(year, month)[1] + 1):
        day = date(year, month, d)
        attendance = db.query(Attendance).filter(
            Attendance.user_id == user.id,
            Attendance.attendance_date == day
        ).first()

        day_type = get_day_type(user, day, db)

        calendar.append({
            "date": day,
            "day": day.strftime("%A"),
            "shift": db.query(Shift).get(user.shift_id).name,
            "check_in": attendance.check_in if attendance else None,
            "check_out": attendance.check_out if attendance else None,
            "worked_hours": attendance.worked_hours if attendance else 0,
            "status": attendance.status if attendance else day_type
        })

    return {"calendar": calendar}


# ---------------- ATTENDANCE GET ----------------

@app.get("/attendance/get")
def get_attendance(
    attendance_date: Optional[date] = None,
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db)
):
    user = get_current_user_from_token(token, db)
    ensure_user_shift(user, db)

    day = attendance_date or date.today()
    attendance = db.query(Attendance).filter(
        Attendance.user_id == user.id,
        Attendance.attendance_date == day
    ).first()

    day_type = get_day_type(user, day, db)
    shift = db.query(Shift).get(user.shift_id)

    return {
        "date": day,
        "shift": {"id": shift.id, "name": shift.name},
        "check_in": attendance.check_in if attendance else None,
        "check_out": attendance.check_out if attendance else None,
        "worked_hours": attendance.worked_hours if attendance else 0,
        "status": attendance.status if attendance else day_type
    }
