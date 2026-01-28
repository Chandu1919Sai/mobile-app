from sqlalchemy import Column, Integer, String, DateTime, Date, Time, ForeignKey,Enum
from database import Base
from datetime import datetime
from sqlalchemy.orm import relationship
from enum import Enum
class User(Base):
    __tablename__ = "users"

    id = Column(Integer, unique=True,primary_key=True)
    name = Column(String, nullable=False)
    username = Column(String, nullable=False)
    email = Column(String, unique=True, nullable=False)
    phone_number = Column(String, unique=True, nullable=False)
    password = Column(String, nullable=False)
    role = Column(String, default="user")
    profile_image = Column(String, nullable=True)
    shift_id = Column(Integer, ForeignKey("shifts.id"), nullable=False)
    date_of_joining = Column(Date, nullable=False)
class Attendance(Base):
    __tablename__ = "attendance"

    id = Column(Integer, primary_key=True)

    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    shift_id = Column(Integer, ForeignKey("shifts.id"), nullable=False)

    attendance_date = Column(Date, nullable=False)

    sign_in_time = Column(DateTime, nullable=True)
    sign_out_time = Column(DateTime, nullable=True)

    # Must match DB CHECK constraint chk_attendance_type
    # Allowed: PRESENT, ABSENT, HOLIDAY, HALF_DAY, WEEK_OFF
    type = Column(String, nullable=False, default="PRESENT")

class Shift(Base):
    __tablename__ = "shifts"

    id = Column(Integer, primary_key=True)
    name = Column(String)               # Morning / Afternoon / Evening
    start_time = Column(Time)           # 06:00
    end_time = Column(Time)             # 15:00
    min_hours = Column(Integer, default=9)
    weekend_days = Column(String)       # "5,6" → Sat,Sun
class Holiday(Base):
    __tablename__ = "holidays"

    id = Column(Integer, primary_key=True)
    date = Column(Date, unique=True)
    name = Column(String)
class LeaveRequest(Base):
    __tablename__ = "leave_requests"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    leave_type = Column(String, nullable=False)
    from_date = Column(Date, nullable=False)
    to_date = Column(Date, nullable=False)
    reason = Column(String, nullable=True)
    status = Column(String, default="PENDING")
    applied_at = Column(DateTime, default=datetime.utcnow)
class LeaveTypeEnum(str, Enum):
    SICK = "Sick Leave"
    CASUAL = "Casual Leave"
    EARNED = "Earned Leave"
    WFH = "Work From Home"

