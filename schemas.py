from pydantic import BaseModel, EmailStr
from typing import Literal, Optional

class SignupSchema(BaseModel):
    name: str
    username: str
    email: EmailStr
    password: str
    phone_number:str
    role: str = "user"
    # Optional for backwards compatibility with existing mobile clients.
    # If not provided, backend will assign the default shift.
    shift_id: Optional[int] = None

class LoginSchema(BaseModel):
    password: str
    username: str

class AttendanceMarkSchema(BaseModel):
 
    qr_token: str
    status: Literal["check_in", "check_out"]
    timestamp: str

