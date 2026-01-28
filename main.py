import os
from datetime import datetime, date, time
from calendar import monthrange
from typing import Optional

from fastapi import (
    FastAPI, Depends, HTTPException, status,
    UploadFile, File, Form, Query, Body
)
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from pydantic import BaseModel

from database import Base, engine, SessionLocal
from models import User, Attendance, Holiday, Shift, LeaveRequest, LeaveTypeEnum
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
        date_of_joining=date.today()
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
        "profile_image": user.profile_image,
        "date_of_joining": user.date_of_joining
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
        sign_in_time=datetime.now(),
        type="PRESENT"
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
        if attendance and attendance.sign_in_time:
            raise HTTPException(status_code=400, detail="Already checked in")

        if not attendance:
            attendance = Attendance(
                user_id=user.id,
                attendance_date=attendance_date,
                shift_id=user.shift_id,
                sign_in_time=ts,
                type="PRESENT"
            )
            db.add(attendance)
        else:
            attendance.sign_in_time = ts
            attendance.type = "PRESENT"
        
        db.commit()
        return {"message": "Check-in successful", "attendance_date": attendance_date}

    # check_out
    if not attendance or not attendance.sign_in_time:
        raise HTTPException(status_code=400, detail="Check-in missing (cannot check out before check-in)")

    if attendance.sign_out_time:
        raise HTTPException(status_code=400, detail="Already checked out")

    attendance.sign_out_time = ts
    hours = (attendance.sign_out_time - attendance.sign_in_time).total_seconds() / 3600
    shift = db.query(Shift).get(user.shift_id)
    min_hours = (shift.min_hours if shift and shift.min_hours else 9)
    half_day_hours = min_hours / 2
    attendance.type = (
        "PRESENT" if hours >= min_hours else
        "HALF_DAY" if hours >= half_day_hours else
        "ABSENT"
    )
    db.commit()

    return {
        "message": "Check-out successful",
        "attendance_date": attendance_date,
        "type": attendance.type,
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

    if not attendance or not attendance.sign_in_time:
        raise HTTPException(400, "Check-in missing")

    attendance.sign_out_time = datetime.now()
    hours = (attendance.sign_out_time - attendance.sign_in_time).total_seconds() / 3600
    shift = db.query(Shift).get(user.shift_id)
    min_hours = (shift.min_hours if shift and shift.min_hours else 9)
    half_day_hours = min_hours / 2
    attendance.type = (
        "PRESENT" if hours >= min_hours else
        "HALF_DAY" if hours >= half_day_hours else
        "ABSENT"
    )

    db.commit()
    return {"message": "Check-out successful", "type": attendance.type}

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
def attendance_calendar(
    year: int,
    month: int,
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db)
):
    user = get_current_user_from_token(token, db)
    ensure_user_shift(user, db)

    # 🔒 Year restriction (same as before)
    if user.date_of_joining:
        join_year = user.date_of_joining.year
        if year < join_year:
            raise HTTPException(
                status_code=400,
                detail="Attendance not available before joining year"
            )

    calendar = []
    join_date = user.date_of_joining  # may be None for legacy users

    for d in range(1, monthrange(year, month)[1] + 1):
        day = date(year, month, d)

        # ❌ Joining date mundu skip (unchanged)
        if join_date and day < join_date:
            continue

        # 🔥 LEAVE CHECK (ADDED – FIRST PRIORITY)
        leave = db.query(LeaveRequest).filter(
            LeaveRequest.user_id == user.id,
            LeaveRequest.status == "APPROVED",
            LeaveRequest.from_date <= day,
            LeaveRequest.to_date >= day
        ).first()

        if leave:
            calendar.append({
                "date": day,
                "sign_in_time": None,
                "sign_out_time": None,
                "type": "LEAVE"
            })
            continue   # 👈 attendance check skip

        # ✅ EXISTING ATTENDANCE LOGIC (UNCHANGED)
        attendance = db.query(Attendance).filter(
            Attendance.user_id == user.id,
            Attendance.attendance_date == day
        ).first()

        calendar.append({
            "date": day,
            "sign_in_time": attendance.sign_in_time if attendance else None,
            "sign_out_time": attendance.sign_out_time if attendance else None,
            "type": attendance.type if attendance else get_day_type(user, day, db)
        })

    return {
        "join_date": join_date,
        "calendar": calendar
    }



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
        "sign_in_time": attendance.sign_in_time if attendance else None,
        "sign_out_time": attendance.sign_out_time if attendance else None,
        "type": attendance.type if attendance else day_type,
   
    }

@app.get("/leave/types")
def get_leave_types():
    return [{"value": e.value, "name": e.name} for e in LeaveTypeEnum]

@app.post("/leave/apply")
def apply_leave(
    leave_type: str = Form(...),
    from_date: date = Form(...),
    to_date: date = Form(...),
    reason: Optional[str] = Form(None),
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db)
):
    user = get_current_user_from_token(token, db)

    # Validate leave_type is one of the allowed enum values
    valid_types = [e.value for e in LeaveTypeEnum]
    if leave_type not in valid_types:
        raise HTTPException(400, f"Invalid leave type. Must be one of: {valid_types}")

    # 🔒 joining date check
    if user.date_of_joining and from_date < user.date_of_joining:
        raise HTTPException(400, "Leave before joining date not allowed")

    if from_date > to_date:
        raise HTTPException(400, "Invalid date range")

    # ❌ attendance already marked
    existing_attendance = db.query(Attendance).filter(
        Attendance.user_id == user.id,
        Attendance.attendance_date.between(from_date, to_date)
    ).first()
    if existing_attendance:
        raise HTTPException(400, "Attendance already marked for selected dates")

    leave = LeaveRequest(
        user_id=user.id,
        leave_type=leave_type,
        from_date=from_date,
        to_date=to_date,
        reason=reason
    )
    db.add(leave)
    db.commit()

    return {"message": "Leave applied successfully"}
@app.get("/leave/my")
def my_leaves(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db)
):
    user = get_current_user_from_token(token, db)
    return db.query(LeaveRequest).filter(
        LeaveRequest.user_id == user.id
    ).order_by(LeaveRequest.applied_at.desc()).all()
@app.get("/admin/leave/pending")
def get_pending_leaves(
    admin=Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    return db.query(LeaveRequest).filter(
        LeaveRequest.status == "PENDING"
    ).all()


class LeaveActionPayload(BaseModel):
    leave_id: int
    action: str


def process_leave_action(
    leave_id: int,
    action: str,
    db: Session
):
    """Shared function to process leave approval/rejection"""
    leave = db.query(LeaveRequest).filter(
        LeaveRequest.id == leave_id
    ).first()

    if not leave:
        raise HTTPException(
            status_code=404, 
            detail=f"Leave request with ID {leave_id} not found"
        )

    if leave.status != "PENDING":
        raise HTTPException(
            status_code=400, 
            detail=f"Leave request already processed. Current status: {leave.status}"
        )

    # Accept both "APPROVE"/"REJECT" and "APPROVED"/"REJECTED"
    action_upper = action.upper().strip()

    if action_upper in ("APPROVE", "APPROVED"):
        leave.status = "APPROVED"
    elif action_upper in ("REJECT", "REJECTED"):
        leave.status = "REJECTED"
    else:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid action '{action}'. Use 'approve' or 'reject'"
        )

    db.commit()
    db.refresh(leave)

    return {
        "message": f"Leave request {leave.status.lower()} successfully",
        "leave_id": leave.id,
        "status": leave.status
    }

@app.put("/admin/leave/action")
def leave_action_put(
    leave_id: Optional[int] = Query(None, description="ID of the leave request"),
    action: Optional[str] = Query(None, description="Action to take: approve or reject"),
    payload: Optional[LeaveActionPayload] = Body(None),
    admin=Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """
    Approve or reject a leave request.
    Preferred usage: PUT with JSON body (or query params).
    """
    final_leave_id = leave_id if leave_id is not None else (payload.leave_id if payload else None)
    final_action = action if action is not None else (payload.action if payload else None)

    if final_leave_id is None or final_action is None:
        raise HTTPException(
            status_code=422,
            detail="Missing required fields: provide 'leave_id' and 'action' as query params or JSON body",
        )

    return process_leave_action(final_leave_id, final_action, db)


@app.get("/admin/leave/action")
def leave_action_get(
    leave_id: int = Query(..., description="ID of the leave request"),
    action: str = Query(..., description="Action to take: approve or reject"),
    admin=Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """
    Compatibility endpoint (not RESTful): supports older clients that call GET.
    """
    return process_leave_action(leave_id, action, db)