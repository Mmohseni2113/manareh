from fastapi import FastAPI, Depends, HTTPException, status, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi.middleware.cors import CORSMiddleware

from sqlalchemy import create_engine, Column, Integer, String, DateTime, Float, ForeignKey, text, inspect, Boolean, func
from sqlalchemy.orm import sessionmaker, declarative_base, Session
from jose import JWTError, jwt
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
from pydantic import BaseModel
import re
import hashlib
import base64
import os
import random
import time
import logging
from kavenegar import *

# تنظیمات لاگ‌گیری
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("manareh")

# ایجاد اپلیکیشن
app = FastAPI()

# CORS middleware
origins = [
    "https://manareh.onrender.com",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:8000",
    "http://127.0.0.1:8000",
    "http://localhost:5500",
    "http://127.0.0.1:5500",
    "*"  # برای تست - در تولید بهتر است دامنه‌های مشخص شده باشند
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# mount استاتیک
app.mount("/static", StaticFiles(directory="static"), name="static")

# صفحه اصلی
@app.get("/")
def home():
    return FileResponse("static/index.html")

# خواندن متغیرهای محیطی
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./manareh.db")
KAVENEGAR_API_KEY = os.getenv("KAVENEGAR_API_KEY")
SENDER_NUMBER = os.getenv("SENDER_NUMBER", "2000660110")
SECRET_KEY = os.getenv("MANAREH_SECRET_KEY", "manareh-secret-key-2024-very-secure-key-here")

# تست اتصال به دیتابیس
def test_database_connection():
    try:
        database_urls = [
            # اولویت اول: Railway database
            "mysql+pymysql://root:fNCKZuguXMprcpWgfFtrxcQMXnEvVLAE@yamabiko.proxy.rlwy.net:40321/railway",
            # دوم: اتصالات محلی به عنوان fallback
            "mysql+pymysql://M.mohseni:123m456o789h@127.0.0.1/manareh",
            "mysql+pymysql://M.mohseni:123m456o789h@localhost/manareh",
        ]
        
        for db_url in database_urls:
            try:
                logger.info(f"🔧 تست اتصال به: {db_url}")
                engine = create_engine(db_url)
                with engine.connect() as conn:
                    result = conn.execute(text("SELECT 1"))
                    logger.info(f"✅ اتصال موفق به: {db_url}")
                    return db_url
            except Exception as e:
                logger.error(f"❌ خطا در اتصال به {db_url}: {e}")
                continue
        
        logger.error("❌ هیچ یک از اتصالات کار نکرد")
        return None
        
    except Exception as e:
        logger.error(f"❌ خطا در تست اتصال: {e}")
        return None

# پیدا کردن اتصال درست
if not DATABASE_URL or DATABASE_URL == "sqlite:///./manareh.db":
    DATABASE_URL = test_database_connection()

if not DATABASE_URL:
    DATABASE_URL = "sqlite:///./manareh.db"
    logger.info("🔧 استفاده از SQLite به عنوان fallback")

logger.info(f"🎯 اتصال نهایی: {DATABASE_URL}")

# تنظیمات اتصال دیتابیس
connect_args = {}
if "sqlite" in DATABASE_URL:
    connect_args = {"check_same_thread": False}

engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# تنظیمات JWT
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

# تنظیمات کاوه‌نگار
kave_api = None
if KAVENEGAR_API_KEY:
    try:
        kave_api = KavenegarAPI(KAVENEGAR_API_KEY)
        logger.info("✅ سرویس کاوه‌نگار راه‌اندازی شد")
    except Exception as e:
        logger.error(f"❌ خطا در راه‌اندازی کاوه‌نگار: {e}")
else:
    logger.warning("⚠️ کلید API کاوه‌نگار تنظیم نشده است")

# مدل‌های دیتابیس
class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    first_name = Column(String(50), nullable=False)
    last_name = Column(String(50), nullable=False)
    email = Column(String(100), unique=True, nullable=False)
    national_id = Column(String(10), unique=True, nullable=False)
    phone_number = Column(String(11), nullable=False)
    country = Column(String(50), nullable=False)
    province = Column(String(50), nullable=False)
    city = Column(String(50), nullable=False)
    gender = Column(String(10), nullable=False)
    password = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    verification_code = Column(String(10), nullable=True)
    code_expire_time = Column(DateTime, nullable=True)
    is_verified = Column(Boolean, default=False)

class Event(Base):
    __tablename__ = "events"
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    title = Column(String(100), nullable=False)
    time = Column(DateTime, nullable=False)
    location = Column(String(255), nullable=False)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    host = Column(String(100), nullable=False)
    creator = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    type = Column(String(20), default="religious")
    city = Column(String(50), default="تهران")
    province = Column(String(50), default="تهران")
    country = Column(String(50), default="iran")
    capacity = Column(Integer, default=100)
    active = Column(Integer, default=1)
    is_free = Column(Boolean, default=True)
    price = Column(Float, default=0.0)

class Comment(Base):
    __tablename__ = "comments"
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    event_id = Column(Integer, ForeignKey("events.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    comment = Column(String(500), nullable=False)
    rating = Column(Integer, default=5)
    created_at = Column(DateTime, default=datetime.utcnow)

class EventParticipant(Base):
    __tablename__ = "event_participants"
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    event_id = Column(Integer, ForeignKey("events.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    registered_at = Column(DateTime, default=datetime.utcnow)
    attended = Column(Boolean, default=False)

class Notification(Base):
    __tablename__ = "notifications"
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    title = Column(String(200), nullable=False)
    message = Column(String(500), nullable=False)
    type = Column(String(50), default="info")
    read = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

class UserFavorite(Base):
    __tablename__ = "user_favorites"
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    event_id = Column(Integer, ForeignKey("events.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

class OTPCode(Base):
    __tablename__ = "otp_codes"
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    phone_number = Column(String(11), nullable=False)
    email = Column(String(100), nullable=False)
    code = Column(String(10), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=False)
    used = Column(Boolean, default=False)

# تابع برای بررسی و ایجاد فیلدهای جدید
def check_and_create_missing_columns():
    """بررسی و ایجاد فیلدهای جدید در جداول"""
    db = SessionLocal()
    try:
        inspector = inspect(engine)
        
        # بررسی فیلدهای users
        users_columns = [col['name'] for col in inspector.get_columns('users')]
        missing_columns = []
        
        expected_columns = ['verification_code', 'code_expire_time', 'is_verified']
        for col in expected_columns:
            if col not in users_columns:
                missing_columns.append(col)
        
        if missing_columns:
            logger.info(f"🔧 ایجاد فیلدهای جدید در users: {missing_columns}")
            
            for col in missing_columns:
                if col == 'verification_code':
                    db.execute(text("ALTER TABLE users ADD COLUMN verification_code VARCHAR(10)"))
                elif col == 'code_expire_time':
                    db.execute(text("ALTER TABLE users ADD COLUMN code_expire_time DATETIME"))
                elif col == 'is_verified':
                    db.execute(text("ALTER TABLE users ADD COLUMN is_verified BOOLEAN DEFAULT FALSE"))
            
            db.commit()
            logger.info("✅ فیلدهای جدید در users ایجاد شدند")
        
        # بررسی فیلدهای events
        events_columns = [col['name'] for col in inspector.get_columns('events')]
        missing_columns = []
        
        expected_columns = ['type', 'city', 'province', 'country', 'capacity', 'active', 'is_free', 'price']
        for col in expected_columns:
            if col not in events_columns:
                missing_columns.append(col)
        
        if missing_columns:
            logger.info(f"🔧 ایجاد فیلدهای جدید در events: {missing_columns}")
            
            for col in missing_columns:
                if col == 'type':
                    db.execute(text("ALTER TABLE events ADD COLUMN type VARCHAR(20) DEFAULT 'religious'"))
                elif col == 'city':
                    db.execute(text("ALTER TABLE events ADD COLUMN city VARCHAR(50) DEFAULT 'تهران'"))
                elif col == 'province':
                    db.execute(text("ALTER TABLE events ADD COLUMN province VARCHAR(50) DEFAULT 'تهران'"))
                elif col == 'country':
                    db.execute(text("ALTER TABLE events ADD COLUMN country VARCHAR(50) DEFAULT 'iran'"))
                elif col == 'capacity':
                    db.execute(text("ALTER TABLE events ADD COLUMN capacity INT DEFAULT 100"))
                elif col == 'active':
                    db.execute(text("ALTER TABLE events ADD COLUMN active TINYINT DEFAULT 1"))
                elif col == 'is_free':
                    db.execute(text("ALTER TABLE events ADD COLUMN is_free TINYINT DEFAULT 1"))
                elif col == 'price':
                    db.execute(text("ALTER TABLE events ADD COLUMN price FLOAT DEFAULT 0.0"))
            
            db.commit()
            logger.info("✅ فیلدهای جدید در events ایجاد شدند")
        
        # بررسی وجود جدول comments
        if 'comments' not in inspector.get_table_names():
            logger.info("🔧 ایجاد جدول comments")
            Base.metadata.tables['comments'].create(bind=engine)
            logger.info("✅ جدول comments ایجاد شد")
        
        # بررسی وجود جدول event_participants
        if 'event_participants' not in inspector.get_table_names():
            logger.info("🔧 ایجاد جدول event_participants")
            Base.metadata.tables['event_participants'].create(bind=engine)
            logger.info("✅ جدول event_participants ایجاد شد")
        
        # بررسی وجود جدول notifications
        if 'notifications' not in inspector.get_table_names():
            logger.info("🔧 ایجاد جدول notifications")
            Base.metadata.tables['notifications'].create(bind=engine)
            logger.info("✅ جدول notifications ایجاد شد")
        
        # بررسی وجود جدول user_favorites
        if 'user_favorites' not in inspector.get_table_names():
            logger.info("🔧 ایجاد جدول user_favorites")
            Base.metadata.tables['user_favorites'].create(bind=engine)
            logger.info("✅ جدول user_favorites ایجاد شد")
        
        # بررسی وجود جدول otp_codes
        if 'otp_codes' not in inspector.get_table_names():
            logger.info("🔧 ایجاد جدول otp_codes")
            Base.metadata.tables['otp_codes'].create(bind=engine)
            logger.info("✅ جدول otp_codes ایجاد شد")
        
        # بررسی فیلد rating در comments
        comments_columns = [col['name'] for col in inspector.get_columns('comments')]
        if 'rating' not in comments_columns:
            logger.info("🔧 ایجاد فیلد rating در comments")
            db.execute(text("ALTER TABLE comments ADD COLUMN rating INT DEFAULT 5"))
            db.commit()
            logger.info("✅ فیلد rating ایجاد شد")
            
    except Exception as e:
        logger.error(f"❌ خطا در ایجاد فیلدها: {e}")
        db.rollback()
    finally:
        db.close()

# ایجاد جداول در دیتابیس
try:
    Base.metadata.create_all(bind=engine)
    logger.info("✅ جداول دیتابیس ایجاد شدند")
    
    # بررسی و ایجاد فیلدهای جدید
    check_and_create_missing_columns()
    
except Exception as e:
    logger.error(f"❌ خطا در ایجاد جداول: {e}")

# مدل‌های Pydantic
class RepeatPattern(BaseModel):
    type: str
    interval: int = 1
    days: Optional[List[int]] = None
    day_of_month: Optional[int] = None
    end_date: Optional[datetime] = None
    occurrences: Optional[int] = None

class UserCreate(BaseModel):
    first_name: str
    last_name: str
    email: str
    national_id: str
    phone_number: str
    country: str
    province: str
    city: str
    gender: str
    password: str

class UserResponse(BaseModel):
    id: int
    first_name: str
    last_name: str
    email: str
    national_id: str
    phone_number: str
    country: str
    province: str
    city: str
    gender: str
    created_at: datetime
    is_verified: bool

    class Config:
        from_attributes = True

class EventCreate(BaseModel):
    title: str
    time: datetime
    location: str
    latitude: float
    longitude: float
    host: str
    creator: int
    type: Optional[str] = "religious"
    city: Optional[str] = None
    province: Optional[str] = None
    country: Optional[str] = "iran"
    capacity: Optional[int] = 100
    is_free: Optional[bool] = True
    price: Optional[float] = 0.0
    repeat_pattern: Optional[RepeatPattern] = None

class EventResponse(BaseModel):
    id: int
    title: str
    time: datetime
    location: str
    latitude: float
    longitude: float
    host: str
    creator: int
    created_at: datetime
    type: Optional[str] = "religious"
    city: Optional[str] = None
    province: Optional[str] = None
    country: Optional[str] = "iran"
    capacity: Optional[int] = 100
    active: Optional[int] = 1
    is_free: Optional[bool] = True
    price: Optional[float] = 0.0
    average_rating: Optional[float] = 0.0
    comment_count: Optional[int] = 0
    current_participants: Optional[int] = 0
    is_favorite: Optional[bool] = False

    class Config:
        from_attributes = True

class CommentCreate(BaseModel):
    event_id: int
    user_id: int
    comment: str
    rating: Optional[int] = 5

class CommentResponse(BaseModel):
    id: int
    event_id: int
    user_id: int
    comment: str
    rating: int
    created_at: datetime
    user_name: str

    class Config:
        from_attributes = True

class EventParticipantCreate(BaseModel):
    event_id: int
    user_id: int

class EventParticipantResponse(BaseModel):
    id: int
    event_id: int
    user_id: int
    registered_at: datetime
    attended: bool
    user_name: str

    class Config:
        from_attributes = True

class NotificationCreate(BaseModel):
    user_id: int
    title: str
    message: str
    type: Optional[str] = "info"

class NotificationResponse(BaseModel):
    id: int
    user_id: int
    title: str
    message: str
    type: str
    read: bool
    created_at: datetime

    class Config:
        from_attributes = True

class Token(BaseModel):
    access_token: str
    token_type: str
    user_id: int

class LoginRequest(BaseModel):
    username: str
    password: str

class UserStatsResponse(BaseModel):
    events_count: int
    notifications_count: int
    favorites_count: int
    join_year: int

class FavoriteCreate(BaseModel):
    user_id: int
    event_id: int

class FavoriteResponse(BaseModel):
    id: int
    user_id: int
    event_id: int
    created_at: datetime

    class Config:
        from_attributes = True

# مدل‌های جدید برای OTP
class OTPSendRequest(BaseModel):
    phone_number: str
    email: str

class OTPVerifyRequest(BaseModel):
    email: str
    code: str

class UserRegisterRequest(BaseModel):
    first_name: str
    last_name: str
    email: str
    national_id: str
    phone_number: str
    country: str
    province: str
    city: str
    gender: str
    password: str
    verification_code: str

# توابع کمکی برای هش کردن رمز عبور
def get_password_hash(password: str) -> str:
    """هش ساده رمز عبور با SHA-256 + salt"""
    salt = "manareh-salt-2024"
    password_bytes = (password + salt).encode('utf-8')
    hash_bytes = hashlib.sha256(password_bytes).digest()
    return base64.b64encode(hash_bytes).decode('utf-8')

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """بررسی تطابق رمز عبور"""
    return get_password_hash(plain_password) == hashed_password

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

# توابع کمکی
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    try:
        # اگر توکن خالی است، خطا نده و None برگردان
        if not token or token == "null" or token == "undefined":
            return None
            
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email: str = payload.get("sub")
        if email is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Could not validate credentials"
            )
            
        user = db.query(User).filter(User.email == email).first()
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Could not validate credentials"
            )
        return user
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials"
        )

# اضافه کردن dependency اختیاری برای کاربر جاری
def get_optional_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    try:
        return get_current_user(token, db)
    except HTTPException:
        return None

# تابع ارسال پیامک
def send_sms_via_kavenegar(receptor: str, message: str, sender: str = None) -> tuple[bool, str]:
    """ارسال پیامک با استفاده از کاوه‌نگار"""
    if not kave_api:
        logger.error("سرویس کاوه‌نگار راه‌اندازی نشده است")
        return False, "kavenegar_not_initialized"
    
    try:
        params = {
            'receptor': receptor,
            'message': message
        }
        
        if sender:
            params['sender'] = sender
        else:
            params['sender'] = SENDER_NUMBER
            
        response = kave_api.sms_send(params)
        logger.info(f"✅ پیامک ارسال شد به {receptor}: {response}")
        return True, "success"
        
    except APIException as e:
        logger.error(f"❌ خطای API کاوه‌نگار: {e}")
        return False, str(e)
    except Exception as e:
        logger.error(f"❌ خطای ناشناخته در ارسال پیامک: {e}")
        return False, str(e)

# 📤 ارسال OTP
@app.post("/send-otp")
async def send_otp(req: OTPSendRequest, db: Session = Depends(get_db)):
    try:
        logger.info(f"📤 درخواست ارسال OTP برای: {req.email} - {req.phone_number}")
        
        # بررسی وجود کاربر با این ایمیل یا شماره تلفن
        existing_user = db.query(User).filter(
            (User.email == req.email) | (User.phone_number == req.phone_number)
        ).first()
        
        if existing_user and existing_user.is_verified:
            raise HTTPException(status_code=400, detail="این ایمیل یا شماره تلفن قبلاً ثبت شده است")
        
        # تولید کد OTP
        code = str(random.randint(10000, 99999))
        logger.info(f"🔢 کد OTP تولید شده: {code} برای {req.phone_number}")

        # ارسال پیامک
        sms_sent, sms_result = send_sms_via_kavenegar(
            receptor=req.phone_number,
            message=f'کد تایید مناره: {code}'
        )
        
        if not sms_sent:
            logger.warning(f"⚠️ ارسال پیامک ناموفق بود، اما کد در دیتابیس ذخیره می‌شود: {sms_result}")

        # حذف کدهای قدیمی برای این شماره
        db.query(OTPCode).filter(
            OTPCode.phone_number == req.phone_number,
            OTPCode.used == False
        ).delete()

        # ذخیره کد جدید در دیتابیس
        otp_record = OTPCode(
            phone_number=req.phone_number,
            email=req.email,
            code=code,
            expires_at=datetime.utcnow() + timedelta(minutes=5)
        )
        
        db.add(otp_record)
        db.commit()

        logger.info(f"✅ کد OTP برای {req.phone_number} ذخیره شد")
        
        return {
            "message": "کد تأیید ارسال شد", 
            "success": True,
            "sms_sent": sms_sent
        }
        
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"❌ خطا در ارسال OTP: {e}")
        raise HTTPException(status_code=500, detail="خطا در ارسال کد تأیید")

# ✔ تایید OTP
@app.post("/verify-otp")
async def verify_otp(req: OTPVerifyRequest, db: Session = Depends(get_db)):
    try:
        logger.info(f"✅ درخواست تأیید OTP برای: {req.email} با کد: {req.code}")
        
        # پیدا کردن کد OTP معتبر
        otp_record = db.query(OTPCode).filter(
            OTPCode.email == req.email,
            OTPCode.code == req.code,
            OTPCode.used == False,
            OTPCode.expires_at > datetime.utcnow()
        ).first()
        
        if not otp_record:
            raise HTTPException(status_code=400, detail="کد تأیید اشتباه یا منقضی شده است")
        
        # علامت‌گذاری کد به عنوان استفاده شده
        otp_record.used = True
        db.commit()

        logger.info(f"✅ شماره تلفن کاربر {req.email} تأیید شد")
        return {
            "message": "شماره تلفن با موفقیت تأیید شد", 
            "success": True,
            "phone_number": otp_record.phone_number
        }
        
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"❌ خطا در تأیید OTP: {e}")
        raise HTTPException(status_code=500, detail="خطا در تأیید کد")

# 🔄 ارسال مجدد OTP
@app.post("/resend-otp")
async def resend_otp(req: OTPSendRequest, db: Session = Depends(get_db)):
    try:
        logger.info(f"🔄 درخواست ارسال مجدد OTP برای: {req.email}")
        return await send_otp(req, db)
    except Exception as e:
        logger.error(f"❌ خطا در ارسال مجدد OTP: {e}")
        raise HTTPException(status_code=500, detail="خطا در ارسال مجدد کد تأیید")

# 📝 ثبت‌نام کاربر جدید با تأیید OTP
@app.post("/register")
async def register_user(req: UserRegisterRequest, db: Session = Depends(get_db)):
    try:
        logger.info(f"📝 درخواست ثبت‌نام کاربر: {req.email}")
        
        # بررسی کد تأیید
        otp_record = db.query(OTPCode).filter(
            OTPCode.email == req.email,
            OTPCode.code == req.verification_code,
            OTPCode.used == True,
            OTPCode.expires_at > datetime.utcnow() - timedelta(minutes=30)  # تأیید باید در 30 دقیقه گذشته انجام شده باشد
        ).first()
        
        if not otp_record:
            raise HTTPException(status_code=400, detail="کد تأیید معتبر نیست یا منقضی شده است")
        
        # بررسی وجود کاربر با همین مشخصات
        existing_user = db.query(User).filter(
            (User.email == req.email) | 
            (User.national_id == req.national_id) | 
            (User.phone_number == req.phone_number)
        ).first()
        
        if existing_user:
            if existing_user.is_verified:
                raise HTTPException(status_code=400, detail="این ایمیل، کد ملی یا شماره تلفن قبلاً ثبت شده است")
            else:
                # اگر کاربر وجود دارد اما تأیید نشده، اطلاعات را به‌روزرسانی کن
                user = existing_user
        else:
            # ایجاد کاربر جدید
            user = User()
        
        # اعتبارسنجی داده‌ها
        if not all([req.first_name, req.last_name, req.email, req.national_id, 
                   req.phone_number, req.country, req.province, req.city, req.gender, req.password]):
            raise HTTPException(status_code=400, detail="لطفاً همه فیلدها را پر کنید")
        
        if not re.match(r"^[^\s@]+@[^\s@]+\.[^\s@]+$", req.email):
            raise HTTPException(status_code=400, detail="فرمت ایمیل نامعتبر است")
        
        if not req.national_id.isdigit() or len(req.national_id) != 10:
            raise HTTPException(status_code=400, detail="کد ملی باید 10 رقم باشد")
        
        if not req.phone_number.startswith("09") or len(req.phone_number) != 11 or not req.phone_number.isdigit():
            raise HTTPException(status_code=400, detail="شماره تلفن باید 11 رقم و با 09 شروع شود")
        
        if len(req.password) < 6:
            raise HTTPException(status_code=400, detail="رمز عبور باید حداقل 6 کاراکتر باشد")
        
        if req.gender not in ['male', 'female']:
            raise HTTPException(status_code=400, detail="جنسیت باید مرد یا زن باشد")
        
        # به‌روزرسانی اطلاعات کاربر
        hashed_password = get_password_hash(req.password)
        
        user.first_name = req.first_name
        user.last_name = req.last_name
        user.email = req.email
        user.national_id = req.national_id
        user.phone_number = req.phone_number
        user.country = req.country
        user.province = req.province
        user.city = req.city
        user.gender = req.gender
        user.password = hashed_password
        user.is_verified = True
        user.verification_code = None
        user.code_expire_time = None
        
        if not existing_user:
            db.add(user)
        
        db.commit()
        db.refresh(user)
        
        logger.info(f"✅ کاربر با موفقیت ثبت‌نام شد: {user.id} - {user.email}")
        
        # ایجاد توکن دسترسی
        access_token = create_access_token(data={"sub": user.email})
        
        return {
            "message": "ثبت‌نام با موفقیت انجام شد",
            "access_token": access_token,
            "token_type": "bearer",
            "user_id": user.id,
            "user": {
                "id": user.id,
                "first_name": user.first_name,
                "last_name": user.last_name,
                "email": user.email,
                "national_id": user.national_id,
                "phone_number": user.phone_number,
                "country": user.country,
                "province": user.province,
                "city": user.city,
                "gender": user.gender,
                "created_at": user.created_at,
                "is_verified": user.is_verified
            }
        }
        
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"❌ خطا در ثبت‌نام کاربر: {str(e)}")
        raise HTTPException(status_code=500, detail=f"خطای سرور در ثبت‌نام: {str(e)}")

@app.get("/debug-db")
async def debug_db():
    """endpoint برای دیباگ کامل دیتابیس"""
    try:
        with engine.connect() as conn:
            result = conn.execute(text("SELECT 1"))
            db_test = "✅ اتصال به دیتابیس موفق"
            
            if "sqlite" in DATABASE_URL:
                tables_result = conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
            else:
                tables_result = conn.execute(text("SHOW TABLES"))
            
            tables = [row[0] for row in tables_result]
            
            events_columns_result = conn.execute(text("DESCRIBE events"))
            events_columns = [row[0] for row in events_columns_result]
            
            return {
                "status": "success",
                "database_url": DATABASE_URL,
                "connection_test": db_test,
                "tables": tables,
                "events_columns": events_columns,
                "database_type": "SQLite" if "sqlite" in DATABASE_URL else "MySQL"
            }
    except Exception as e:
        return {
            "status": "error",
            "database_url": DATABASE_URL,
            "error": str(e),
            "suggestion": "مشکل در اتصال به دیتابیس. لطفاً مطمئن شوید MySQL در حال اجراست."
        }

@app.get("/check-user")
async def check_user_exists(
    email: str = Query(None),
    national_id: str = Query(None),
    phone: str = Query(None),
    db: Session = Depends(get_db)
):
    try:
        exists = False
        message = ""
        
        if email:
            user_by_email = db.query(User).filter(User.email == email).first()
            if user_by_email:
                exists = True
                message = "ایمیل قبلاً ثبت شده است"
        
        if national_id and not exists:
            user_by_national = db.query(User).filter(User.national_id == national_id).first()
            if user_by_national:
                exists = True
                message = "کد ملی قبلاً ثبت شده است"
        
        if phone and not exists:
            user_by_phone = db.query(User).filter(User.phone_number == phone).first()
            if user_by_phone:
                exists = True
                message = "شماره تلفن قبلاً ثبت شده است"
        
        return {"exists": exists, "message": message}
    except Exception as e:
        logger.error(f"Error in check-user: {e}")
        return {"exists": False, "message": "خطا در بررسی کاربر"}

@app.get("/debug/users")
async def debug_users(db: Session = Depends(get_db)):
    """endpoint برای دیباگ کاربران"""
    try:
        users = db.query(User).all()
        users_list = []
        for user in users:
            users_list.append({
                "id": user.id,
                "first_name": user.first_name,
                "last_name": user.last_name,
                "email": user.email,
                "national_id": user.national_id,
                "phone_number": user.phone_number,
                "country": user.country,
                "province": user.province,
                "city": user.city,
                "gender": user.gender,
                "created_at": user.created_at.isoformat() if user.created_at else None,
                "is_verified": user.is_verified if hasattr(user, 'is_verified') else False,
                "verification_code": user.verification_code if hasattr(user, 'verification_code') else None
            })
        
        return {
            "status": "success",
            "users_count": len(users_list),
            "users": users_list
        }
    except Exception as e:
        return {
            "status": "error",
            "error": str(e)
        }

# endpoint قدیمی users (برای سازگاری)
@app.post("/users", response_model=UserResponse)
async def create_user(user: UserCreate, db: Session = Depends(get_db)):
    try:
        logger.info(f"📝 دریافت اطلاعات کاربر برای ثبت‌نام (روش قدیمی): {user.email}")
        
        # بررسی وجود کاربر
        existing_user = db.query(User).filter(User.email == user.email).first()
        if existing_user:
            if existing_user.is_verified:
                raise HTTPException(status_code=400, detail="این ایمیل قبلاً ثبت شده است")
            else:
                raise HTTPException(status_code=400, detail="این ایمیل ثبت شده اما تأیید نشده است. لطفاً از روش جدید ثبت‌نام استفاده کنید")
        
        # سایر بررسی‌ها...
        if not all([user.first_name, user.last_name, user.email, user.national_id, 
                   user.phone_number, user.country, user.province, user.city, user.gender, user.password]):
            raise HTTPException(status_code=400, detail="لطفاً همه فیلدها را پر کنید")
        
        if not re.match(r"^[^\s@]+@[^\s@]+\.[^\s@]+$", user.email):
            raise HTTPException(status_code=400, detail="فرمت ایمیل نامعتبر است")
        
        existing_national = db.query(User).filter(User.national_id == user.national_id).first()
        if existing_national:
            raise HTTPException(status_code=400, detail="این کد ملی قبلاً ثبت شده است")
        
        existing_phone = db.query(User).filter(User.phone_number == user.phone_number).first()
        if existing_phone:
            raise HTTPException(status_code=400, detail="این شماره تلفن قبلاً ثبت شده است")
        
        if not user.national_id.isdigit() or len(user.national_id) != 10:
            raise HTTPException(status_code=400, detail="کد ملی باید 10 رقم باشد")
        
        if not user.phone_number.startswith("09") or len(user.phone_number) != 11 or not user.phone_number.isdigit():
            raise HTTPException(status_code=400, detail="شماره تلفن باید 11 رقم و با 09 شروع شود")
        
        if len(user.password) < 6:
            raise HTTPException(status_code=400, detail="رمز عبور باید حداقل 6 کاراکتر باشد")
        
        if user.gender not in ['male', 'female']:
            raise HTTPException(status_code=400, detail="جنسیت باید مرد یا زن باشد")
        
        hashed_password = get_password_hash(user.password)
        
        db_user = User(
            first_name=user.first_name,
            last_name=user.last_name,
            email=user.email,
            national_id=user.national_id,
            phone_number=user.phone_number,
            country=user.country,
            province=user.province,
            city=user.city,
            gender=user.gender,
            password=hashed_password,
            is_verified=False  # کاربر تأیید نشده
        )
        
        db.add(db_user)
        db.commit()
        db.refresh(db_user)
        
        logger.info(f"⚠️ کاربر با روش قدیمی ایجاد شد (تأیید نشده): {db_user.id} - {db_user.email}")
        
        return UserResponse(
            id=db_user.id,
            first_name=db_user.first_name,
            last_name=db_user.last_name,
            email=db_user.email,
            national_id=db_user.national_id,
            phone_number=db_user.phone_number,
            country=db_user.country,
            province=db_user.province,
            city=db_user.city,
            gender=db_user.gender,
            created_at=db_user.created_at,
            is_verified=db_user.is_verified
        )
        
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"❌ خطا در ایجاد کاربر: {str(e)}")
        raise HTTPException(status_code=500, detail=f"خطای سرور در ایجاد کاربر: {str(e)}")

@app.post("/token", response_model=Token)
async def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    try:
        logger.info(f"🔐 تلاش برای ورود کاربر: {form_data.username}")
        
        user = db.query(User).filter(User.email == form_data.username).first()
        if not user:
            logger.warning("❌ کاربر یافت نشد")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="ایمیل یا رمز عبور اشتباه است"
            )
        
        logger.info(f"🔍 کاربر پیدا شد: {user.email}")
        
        if not verify_password(form_data.password, user.password):
            logger.warning("❌ رمز عبور نادرست")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="ایمیل یا رمز عبور اشتباه است"
            )
        
        # بررسی تأیید شماره تلفن
        if not user.is_verified:
            logger.warning("⚠️ کاربر تأیید نشده است")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="شماره تلفن شما تأیید نشده است. لطفاً ابتدا شماره تلفن خود را تأیید کنید"
            )
        
        access_token = create_access_token(data={"sub": user.email})
        logger.info(f"✅ ورود موفقیت‌آمیز برای کاربر: {user.id}")
        return {"access_token": access_token, "token_type": "bearer", "user_id": user.id}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ خطا در ورود: {e}")
        raise HTTPException(status_code=500, detail="خطای سرور در ورود")

@app.post("/login")
async def login_debug(login_data: LoginRequest, db: Session = Depends(get_db)):
    try:
        logger.info(f"🔐 درخواست login جدید: {login_data.username}")
        
        user = db.query(User).filter(User.email == login_data.username).first()
        if not user:
            logger.warning("❌ کاربر یافت نشد")
            return JSONResponse(
                status_code=401,
                content={"detail": "ایمیل یا رمز عبور اشتباه است"}
            )
        
        logger.info(f"🔍 کاربر پیدا شد: {user.email}")
        
        if not verify_password(login_data.password, user.password):
            logger.warning("❌ رمز عبور نادرست")
            return JSONResponse(
                status_code=401,
                content={"detail": "ایمیل یا رمز عبور اشتباه است"}
            )
        
        # بررسی تأیید شماره تلفن
        if not user.is_verified:
            logger.warning("⚠️ کاربر تأیید نشده است")
            return JSONResponse(
                status_code=401,
                content={"detail": "شماره تلفن شما تأیید نشده است. لطفاً ابتدا شماره تلفن خود را تأیید کنید"}
            )
        
        access_token = create_access_token(data={"sub": user.email})
        logger.info(f"✅ ورود موفقیت‌آمیز برای کاربر: {user.id}")
        return {"access_token": access_token, "token_type": "bearer", "user_id": user.id}
        
    except Exception as e:
        logger.error(f"❌ خطا در ورود: {e}")
        return JSONResponse(
            status_code=500,
            content={"detail": "خطای سرور در ورود"}
        )

# بقیه endpointها بدون تغییر باقی می‌مانند...
# [اینجا تمام endpointهای دیگر شما قرار می‌گیرد بدون هیچ تغییری]

def generate_recurring_events(base_event: EventCreate, db: Session) -> List[Event]:
    events = []
    
    if not base_event.repeat_pattern:
        db_event = Event(
            title=base_event.title,
            time=base_event.time,
            location=base_event.location,
            latitude=base_event.latitude,
            longitude=base_event.longitude,
            host=base_event.host,
            creator=base_event.creator,
            type=base_event.type,
            city=base_event.city,
            province=base_event.province,
            country=base_event.country,
            capacity=base_event.capacity,
            is_free=base_event.is_free,
            price=base_event.price
        )
        events.append(db_event)
        return events
    
    pattern = base_event.repeat_pattern
    current_date = base_event.time
    event_count = 1
    
    end_date = pattern.end_date
    max_occurrences = pattern.occurrences or 365
    
    first_event = Event(
        title=base_event.title,
        time=current_date,
        location=base_event.location,
        latitude=base_event.latitude,
        longitude=base_event.longitude,
        host=base_event.host,
        creator=base_event.creator,
        type=base_event.type,
        city=base_event.city,
        province=base_event.province,
        country=base_event.country,
        capacity=base_event.capacity,
        is_free=base_event.is_free,
            price=base_event.price
        )
    events.append(first_event)
    
    while event_count < max_occurrences:
        if end_date and current_date > end_date:
            break
        
        if pattern.type == 'daily':
            current_date = current_date + timedelta(days=pattern.interval)
        elif pattern.type == 'weekly':
            current_date = current_date + timedelta(weeks=pattern.interval)
            if pattern.days:
                current_weekday = current_date.weekday()
                for day in sorted(pattern.days):
                    if day > current_weekday:
                        days_to_add = day - current_weekday
                        current_date = current_date + timedelta(days=days_to_add)
                        break
        elif pattern.type == 'monthly':
            next_month = current_date.month + pattern.interval
            next_year = current_date.year + (next_month - 1) // 12
            next_month = (next_month - 1) % 12 + 1
            
            if pattern.day_of_month:
                day_of_month = pattern.day_of_month
            else:
                day_of_month = current_date.day
            
            try:
                current_date = current_date.replace(year=next_year, month=next_month, day=day_of_month)
            except ValueError:
                import calendar
                last_day = calendar.monthrange(next_year, next_month)[1]
                current_date = current_date.replace(year=next_year, month=next_month, day=last_day)
        
        elif pattern.type == 'yearly':
            current_date = current_date.replace(year=current_date.year + pattern.interval)
        
        if end_date and current_date > end_date:
            break
        
        new_event = Event(
            title=base_event.title,
            time=current_date,
            location=base_event.location,
            latitude=base_event.latitude,
            longitude=base_event.longitude,
            host=base_event.host,
            creator=base_event.creator,
            type=base_event.type,
            city=base_event.city,
            province=base_event.province,
            country=base_event.country,
            capacity=base_event.capacity,
            is_free=base_event.is_free,
            price=base_event.price
        )
        events.append(new_event)
        event_count += 1
        
        if event_count >= 365:
            break
    
    return events

@app.post("/events", response_model=EventResponse)
async def create_event(event: EventCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        logger.info(f"📝 دریافت درخواست ایجاد رویداد از کاربر: {current_user.email if current_user else 'Anonymous'}")
        
        if not all([event.title, event.time, event.location]):
            raise HTTPException(status_code=400, detail="لطفاً همه فیلدها را پر کنید")
        
        user_exists = db.query(User).filter(User.id == event.creator).first()
        if not user_exists:
            raise HTTPException(status_code=400, detail="کاربر ایجاد کننده معتبر نیست")
        
        if not event.city:
            event.city = current_user.city if current_user else "تهران"
        if not event.province:
            event.province = current_user.province if current_user else "تهران"
        
        events_to_create = generate_recurring_events(event, db)
        created_events = []
        
        for event_obj in events_to_create:
            db.add(event_obj)
            db.flush()
            created_events.append(event_obj)
        
        db.commit()
        
        for event_obj in created_events:
            db.refresh(event_obj)
        
        logger.info(f"✅ {len(created_events)} رویداد با موفقیت ایجاد شد")
        
        return EventResponse(
            id=created_events[0].id,
            title=created_events[0].title,
            time=created_events[0].time,
            location=created_events[0].location,
            latitude=created_events[0].latitude,
            longitude=created_events[0].longitude,
            host=created_events[0].host,
            creator=created_events[0].creator,
            created_at=created_events[0].created_at,
            type=created_events[0].type,
            city=created_events[0].city,
            province=created_events[0].province,
            country=created_events[0].country,
            capacity=created_events[0].capacity,
            active=created_events[0].active,
            is_free=created_events[0].is_free,
            price=created_events[0].price
        )
        
    except Exception as e:
        db.rollback()
        logger.error(f"❌ خطا در ایجاد رویداد: {e}")
        raise HTTPException(status_code=500, detail="خطای سرور در ایجاد رویداد")

@app.get("/events", response_model=List[EventResponse])
async def get_events(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        logger.info(f"📋 دریافت درخواست لیست رویدادها از کاربر: {current_user.email if current_user else 'Anonymous'}")
        events = db.query(Event).all()
        
        events_list = []
        for event in events:
            avg_rating_result = db.query(func.avg(Comment.rating)).filter(Comment.event_id == event.id).scalar()
            average_rating = round(float(avg_rating_result or 0), 1)
            
            comment_count = db.query(Comment).filter(Comment.event_id == event.id).count()
            
            current_participants = db.query(EventParticipant).filter(EventParticipant.event_id == event.id).count()
            
            # بررسی آیا رویداد مورد علاقه کاربر است
            is_favorite = False
            if current_user:
                favorite = db.query(UserFavorite).filter(
                    UserFavorite.user_id == current_user.id,
                    UserFavorite.event_id == event.id
                ).first()
                is_favorite = favorite is not None
            
            event_dict = {
                "id": event.id,
                "title": event.title,
                "time": event.time,
                "location": event.location,
                "latitude": event.latitude,
                "longitude": event.longitude,
                "host": event.host,
                "creator": event.creator,
                "created_at": event.created_at,
                "type": getattr(event, 'type', 'religious'),
                "city": getattr(event, 'city', 'تهران'),
                "province": getattr(event, 'province', 'تهران'),
                "country": getattr(event, 'country', 'iran'),
                "capacity": getattr(event, 'capacity', 100),
                "active": getattr(event, 'active', 1),
                "is_free": getattr(event, 'is_free', True),
                "price": getattr(event, 'price', 0.0),
                "average_rating": average_rating,
                "comment_count": comment_count,
                "current_participants": current_participants,
                "is_favorite": is_favorite
            }
            events_list.append(event_dict)
        
        return events_list
    except Exception as e:
        logger.error(f"خطا در دریافت رویدادها: {e}")
        raise HTTPException(status_code=500, detail="خطای سرور در دریافت رویدادها")

# اضافه کردن endpoint جدید برای events/optimized
@app.get("/events/optimized", response_model=List[EventResponse])
async def get_events_optimized(
    current_user: Optional[User] = Depends(get_optional_current_user), 
    db: Session = Depends(get_db)
):
    """Endpoint جدید برای دریافت بهینه‌شده رویدادها"""
    try:
        logger.info("📋 دریافت درخواست لیست رویدادهای بهینه‌شده")
        events = db.query(Event).all()
        
        events_list = []
        for event in events:
            avg_rating_result = db.query(func.avg(Comment.rating)).filter(Comment.event_id == event.id).scalar()
            average_rating = round(float(avg_rating_result or 0), 1)
            
            comment_count = db.query(Comment).filter(Comment.event_id == event.id).count()
            
            current_participants = db.query(EventParticipant).filter(EventParticipant.event_id == event.id).count()
            
            # بررسی آیا رویداد مورد علاقه کاربر است
            is_favorite = False
            if current_user:
                favorite = db.query(UserFavorite).filter(
                    UserFavorite.user_id == current_user.id,
                    UserFavorite.event_id == event.id
                ).first()
                is_favorite = favorite is not None
            
            event_dict = {
                "id": event.id,
                "title": event.title,
                "time": event.time,
                "location": event.location,
                "latitude": event.latitude,
                "longitude": event.longitude,
                "host": event.host,
                "creator": event.creator,
                "created_at": event.created_at,
                "type": getattr(event, 'type', 'religious'),
                "city": getattr(event, 'city', 'تهران'),
                "province": getattr(event, 'province', 'تهران'),
                "country": getattr(event, 'country', 'iran'),
                "capacity": getattr(event, 'capacity', 100),
                "active": getattr(event, 'active', 1),
                "is_free": getattr(event, 'is_free', True),
                "price": getattr(event, 'price', 0.0),
                "average_rating": average_rating,
                "comment_count": comment_count,
                "current_participants": current_participants,
                "is_favorite": is_favorite
            }
            events_list.append(event_dict)
        
        logger.info(f"✅ {len(events_list)} رویداد بهینه‌شده بازگردانده شد")
        return events_list
    except Exception as e:
        logger.error(f"خطا در دریافت رویدادهای بهینه‌شده: {e}")
        raise HTTPException(status_code=500, detail="خطای سرور در دریافت رویدادها")

@app.get("/events/public", response_model=List[EventResponse])
async def get_public_events(db: Session = Depends(get_db)):
    try:
        logger.info("📋 دریافت درخواست لیست رویدادهای عمومی")
        events = db.query(Event).all()
        
        events_list = []
        for event in events:
            avg_rating_result = db.query(func.avg(Comment.rating)).filter(Comment.event_id == event.id).scalar()
            average_rating = round(float(avg_rating_result or 0), 1)
            
            comment_count = db.query(Comment).filter(Comment.event_id == event.id).count()
            
            current_participants = db.query(EventParticipant).filter(EventParticipant.event_id == event.id).count()
            
            event_dict = {
                "id": event.id,
                "title": event.title,
                "time": event.time,
                "location": event.location,
                "latitude": event.latitude,
                "longitude": event.longitude,
                "host": event.host,
                "creator": event.creator,
                "created_at": event.created_at,
                "type": getattr(event, 'type', 'religious'),
                "city": getattr(event, 'city', 'تهران'),
                "province": getattr(event, 'province', 'تهران'),
                "country": getattr(event, 'country', 'iran'),
                "capacity": getattr(event, 'capacity', 100),
                "active": getattr(event, 'active', 1),
                "is_free": getattr(event, 'is_free', True),
                "price": getattr(event, 'price', 0.0),
                "average_rating": average_rating,
                "comment_count": comment_count,
                "current_participants": current_participants,
                "is_favorite": False
            }
            events_list.append(event_dict)
        
        return events_list
    except Exception as e:
        logger.error(f"خطا در دریافت رویدادهای عمومی: {e}")
        raise HTTPException(status_code=500, detail="خطای سرور در دریافت رویدادها")

# بقیه endpointها...
# [تمام endpointهای دیگر شما اینجا قرار می‌گیرند بدون تغییر]

@app.get("/test-db")
async def test_db(db: Session = Depends(get_db)):
    try:
        users_count = db.query(User).count()
        events_count = db.query(Event).count()
        comments_count = db.query(Comment).count()
        participants_count = db.query(EventParticipant).count()
        favorites_count = db.query(UserFavorite).count()
        otp_codes_count = db.query(OTPCode).count()
        
        users = db.query(User).all()
        users_list = [{"id": u.id, "email": u.email, "name": f"{u.first_name} {u.last_name}", "province": u.province, "city": u.city, "is_verified": u.is_verified} for u in users]
        
        events = db.query(Event).all()
        events_list = []
        for event in events:
            event_dict = {
                "id": event.id,
                "title": event.title,
                "type": getattr(event, 'type', 'N/A'),
                "city": getattr(event, 'city', 'N/A'),
                "province": getattr(event, 'province', 'N/A'),
                "country": getattr(event, 'country', 'N/A'),
                "capacity": getattr(event, 'capacity', 'N/A'),
                "active": getattr(event, 'active', 'N/A'),
                "is_free": getattr(event, 'is_free', 'N/A'),
                "price": getattr(event, 'price', 'N/A')
            }
            events_list.append(event_dict)
        
        return {
            "status": "اتصال به دیتابیس موفقیت‌آمیز",
            "users_count": users_count,
            "events_count": events_count,
            "comments_count": comments_count,
            "participants_count": participants_count,
            "favorites_count": favorites_count,
            "otp_codes_count": otp_codes_count,
            "users": users_list,
            "events": events_list,
            "database": "SQLite" if "sqlite" in DATABASE_URL else "MySQL",
            "kavenegar_initialized": kave_api is not None
        }
    except Exception as e:
        return {"error": str(e), "status": "خطا در اتصال به دیتابیس"}

@app.get("/health")
async def health_check():
    return {"status": "healthy", "timestamp": datetime.utcnow()}

@app.on_event("startup")
async def startup_event():
    db = SessionLocal()
    try:
        users_count = db.query(User).count()
        logger.info(f"👥 تعداد کاربران در دیتابیس: {users_count}")
        
        if users_count == 0:
            test_user = User(
                first_name="تست",
                last_name="کاربر",
                email="test@example.com",
                national_id="1234567890",
                phone_number="09123456789",
                country="iran",
                province="تهران",
                city="تهران",
                gender="male",
                password=get_password_hash("123456"),
                is_verified=False
            )
            db.add(test_user)
            db.commit()
            logger.info("✅ کاربر تستی ایجاد شد: test@example.com / 123456")
        else:
            users = db.query(User).all()
            for user in users:
                logger.info(f"👤 کاربر موجود: {user.email} - {user.first_name} {user.last_name} - {user.province}, {user.city} - تأیید شده: {user.is_verified}")
        
        events_count = db.query(Event).count()
        if events_count == 0 and users_count > 0:
            test_user = db.query(User).first()
            test_event = Event(
                title="مراسم تستی",
                time=datetime.utcnow() + timedelta(days=1),
                location="مکان تستی",
                latitude=35.6892,
                longitude=51.3890,
                host="امام جماعت",
                creator=test_user.id,
                type="religious",
                city="تهران",
                province="تهران",
                country="iran",
                capacity=100,
                active=1,
                is_free=True,
                price=0.0
            )
            db.add(test_event)
            db.commit()
            logger.info("✅ رویداد تستی ایجاد شد")
        
        events = db.query(Event).all()
        updated_count = 0
        for event in events:
            needs_update = False
            
            if not hasattr(event, 'type') or not event.type:
                event.type = "religious"
                needs_update = True
                
            if not hasattr(event, 'city') or not event.city:
                creator = db.query(User).filter(User.id == event.creator).first()
                if creator:
                    event.city = creator.city
                    event.province = creator.province
                else:
                    event.city = "تهران"
                    event.province = "تهران"
                needs_update = True
                
            if not hasattr(event, 'country') or not event.country:
                event.country = "iran"
                needs_update = True
                
            if not hasattr(event, 'capacity') or not event.capacity:
                event.capacity = 100
                needs_update = True
                
            if not hasattr(event, 'active') or event.active is None:
                event.active = 1
                needs_update = True
                
            if not hasattr(event, 'is_free') or event.is_free is None:
                event.is_free = True
                needs_update = True
                
            if not hasattr(event, 'price') or event.price is None:
                event.price = 0.0
                needs_update = True
            
            if needs_update:
                updated_count += 1
        
        if updated_count > 0:
            db.commit()
            logger.info(f"✅ {updated_count} رویداد موجود با فیلدهای جدید به‌روزرسانی شدند")
        else:
            logger.info("✅ همه رویدادها به‌روز هستند")
            
    except Exception as e:
        logger.error(f"❌ خطا در startup: {e}")
    finally:
        db.close()

# 🔥 Start Keep Alive (برای جلوگیری از خاموش شدن سرور Render)
from threading import Thread
import requests

def keep_alive():
    while True:
        try:
            requests.get("https://manareh.onrender.com/health")
        except:
            pass
        time.sleep(240)  # هر 4 دقیقه یک بار

Thread(target=keep_alive, daemon=True).start()
# 🔥 End Keep Alive

if __name__ == "__main__":
    import uvicorn
    logger.info("🚀 شروع سرویس Manareh API...")
    logger.info(f"🎯 اتصال دیتابیس: {DATABASE_URL}")
    logger.info(f"📱 سرویس پیامکی کاوه‌نگار فعال: {kave_api is not None}")
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8000)), reload=False)
