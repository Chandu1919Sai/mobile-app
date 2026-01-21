from sqlalchemy import Column, Integer, String, DateTime, Date, Time, ForeignKey,Float
from database import Base
from datetime import datetime

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
class Attendance(Base):
    __tablename__ = "attendance"

    id = Column(Integer, primary_key=True)

    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    shift_id = Column(Integer, ForeignKey("shifts.id"), nullable=False)

    attendance_date = Column(Date, nullable=False)

    check_in = Column(DateTime, nullable=True)
    check_out = Column(DateTime, nullable=True)

    worked_hours = Column(Float, nullable=True)

    status = Column(String, nullable=False, default="IN_PROGRESS")

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
