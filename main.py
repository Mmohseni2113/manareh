from fastapi import HTTPException, FastAPI, Depends, status, Query, BackgroundTasks, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from sqlalchemy import create_engine, Column, Integer, String, DateTime, Float, ForeignKey, text, inspect, Boolean, func, Table, Index
from sqlalchemy.orm import sessionmaker, declarative_base, Session, relationship
from sqlalchemy.exc import IntegrityError
from sqlalchemy.dialects.mysql import TEXT

from jose import JWTError, jwt
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
from pydantic import BaseModel
import re
import hashlib
import base64
import os
import random
import logging
import json
import requests
from contextlib import contextmanager

# فقط این دوتا از کاوه‌نگار
import requests
from contextlib import contextmanager

# تنظیمات لاگینگ حرفه‌ای
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('manareh.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ایجاد اپلیکیشن
app = FastAPI()

# GZip Middleware برای فشرده‌سازی پاسخ‌ها
app.add_middleware(GZipMiddleware, minimum_size=1000)

# mount استاتیک
app.mount("/static", StaticFiles(directory="static"), name="static")

# صفحه اصلی
@app.get("/")
def home():
    return FileResponse("static/index.html")

# تست اتصال به دیتابیس
def test_database_connection():
    try:
        database_urls = [
            "mysql+pymysql://M.mohseni:123m456o789h@localhost/manareh",
            "mysql+pymysql://root:@localhost/manareh",
            "mysql+pymysql://M.mohseni:123m456o789h@127.0.0.1/manareh",
        ]
        
        for db_url in database_urls:
            try:
                logger.info(f"تست اتصال به: {db_url}")
                engine = create_engine(db_url)
                with engine.connect() as conn:
                    result = conn.execute(text("SELECT 1"))
                    logger.info(f"اتصال موفق به: {db_url}")
                    return db_url
            except Exception as e:
                logger.error(f"خطا در اتصال به {db_url}: {e}")
                continue
        
        logger.error("هیچ یک از اتصالات کار نکرد")
        return None
        
    except Exception as e:
        logger.error(f"خطا در تست اتصال: {e}")
        return None

# پیدا کردن اتصال درست
DATABASE_URL = test_database_connection()

if not DATABASE_URL:
    DATABASE_URL = "mysql+pymysql://M.mohseni:123m456o789h@localhost/manareh"
    logger.info("استفاده از اتصال پیش‌فرض MySQL")

logger.info(f"اتصال نهایی: {DATABASE_URL}")

engine = create_engine(DATABASE_URL, 
                      pool_pre_ping=True,
                      pool_recycle=300)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# Dependency Injection برای دیتابیس
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# تنظیمات JWT - استفاده از متغیرهای محیطی
SECRET_KEY = os.getenv("MANAREH_SECRET_KEY", "manareh-secret-key-2024-very-secure-key-here-change-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

# تنظیمات کاوه‌نگار - استفاده از متغیرهای محیطی
KAVENEGAR_API_KEY = os.getenv("KAVENEGAR_API_KEY", "6A6F54654839584E356A6633743272783851717A6C7663667477615357533163595267372B68446636426B3D")

# مدل‌های دیتابیس - حذف national_id از User
class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    first_name = Column(String(100), nullable=False)
    last_name = Column(String(100), nullable=False)
    email = Column(String(255), unique=True, nullable=False, index=True)
    phone_number = Column(String(15), unique=True, nullable=False, index=True)
    phone_prefix = Column(String(5), default="+98")
    password = Column(String(255), nullable=False)
    country = Column(String(50), nullable=False)
    province = Column(String(50), nullable=False)
    city = Column(String(50), nullable=False)
    gender = Column(String(10), nullable=False)
    is_verified = Column(Boolean, default=False)
    has_accepted_terms = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    verification_code = Column(String(10), nullable=True)
    code_expire_time = Column(DateTime, nullable=True)

# جدول جدید برای ذخیره موقت OTP
class OTPTemp(Base):
    __tablename__ = "otp_temp"
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    email = Column(String(255), nullable=False, index=True)
    phone_number = Column(String(15), nullable=False)
    verification_code = Column(String(10), nullable=False)
    code_expire_time = Column(DateTime, nullable=False)
    user_data = Column(String(2000), nullable=True)  # ذخیره داده‌های کاربر به صورت JSON
    created_at = Column(DateTime, default=datetime.utcnow)

# جدول جدید برای مناسبت‌های تقویم
class Occasion(Base):
    __tablename__ = "occasions"
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    jmonth = Column(Integer, nullable=False)  # ماه شمسی
    jday = Column(Integer, nullable=False)    # روز شمسی
    title = Column(String(200), nullable=False)
    description = Column(TEXT, nullable=True)
    is_holiday = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    __table_args__ = (
        Index('idx_occasion_date', 'jmonth', 'jday'),
    )

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
    category = Column(String(50), default="مذهبی")  # دسته اصلی
    subcategory = Column(String(50), default="")  # زیردسته
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

# تابع برای بررسی و ایجاد فیلدهای جدید - اصلاح شده
def check_and_create_missing_columns():
    """بررسی و ایجاد فیلدهای جدید در جداول"""
    db = SessionLocal()
    try:
        inspector = inspect(engine)
        
        # بررسی فیلدهای users
        users_columns = [col['name'] for col in inspector.get_columns('users')]
        
        # حذف فیلد national_id اگر وجود دارد
        if 'national_id' in users_columns:
            try:
                # ابتدا ایندکس را حذف کن
                try:
                    db.execute(text("DROP INDEX IF EXISTS uq_users_national_id ON users"))
                except:
                    pass
                # سپس ستون را حذف کن
                db.execute(text("ALTER TABLE users DROP COLUMN national_id"))
                logger.info("فیلد national_id حذف شد")
            except Exception as e:
                logger.info(f"خطا در حذف فیلد national_id: {e}")
        
        # بررسی فیلدهای events
        events_columns = [col['name'] for col in inspector.get_columns('events')]
        
        # اضافه کردن فیلدهای category و subcategory اگر وجود ندارند
        if 'category' not in events_columns:
            try:
                db.execute(text("ALTER TABLE events ADD COLUMN category VARCHAR(50) DEFAULT 'مذهبی'"))
                logger.info("فیلد category در events ایجاد شد")
            except Exception as e:
                logger.info(f"فیلد category قبلاً وجود دارد: {e}")
        
        if 'subcategory' not in events_columns:
            try:
                db.execute(text("ALTER TABLE events ADD COLUMN subcategory VARCHAR(50) DEFAULT ''"))
                logger.info("فیلد subcategory در events ایجاد شد")
            except Exception as e:
                logger.info(f"فیلد subcategory قبلاً وجود دارد: {e}")
        
        # بررسی فیلدهای دیگر
        missing_columns = []
        expected_columns = ['verification_code', 'code_expire_time', 'is_verified', 'has_accepted_terms', 'phone_prefix']
        
        for col in expected_columns:
            if col not in users_columns:
                missing_columns.append(col)
        
        if missing_columns:
            logger.info(f"ایجاد فیلدهای جدید در users: {missing_columns}")
            
            for col in missing_columns:
                if col == 'verification_code':
                    db.execute(text("ALTER TABLE users ADD COLUMN verification_code VARCHAR(10)"))
                elif col == 'code_expire_time':
                    db.execute(text("ALTER TABLE users ADD COLUMN code_expire_time DATETIME"))
                elif col == 'is_verified':
                    db.execute(text("ALTER TABLE users ADD COLUMN is_verified BOOLEAN DEFAULT FALSE"))
                elif col == 'has_accepted_terms':
                    db.execute(text("ALTER TABLE users ADD COLUMN has_accepted_terms BOOLEAN DEFAULT FALSE"))
                elif col == 'phone_prefix':
                    db.execute(text("ALTER TABLE users ADD COLUMN phone_prefix VARCHAR(5) DEFAULT '+98'"))
            
            db.commit()
            logger.info("فیلدهای جدید در users ایجاد شدند")
        
        # بررسی سایر جداول
        tables_to_check = ['event_participants', 'events', 'comments', 'notifications', 'user_favorites', 'otp_temp', 'occasions']
        
        for table_name in tables_to_check:
            if table_name not in inspector.get_table_names():
                logger.info(f"ایجاد جدول {table_name}")
                if table_name == 'occasions':
                    # ایجاد جدول occasions
                    db.execute(text("""
                    CREATE TABLE IF NOT EXISTS occasions (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        jmonth INT NOT NULL,
                        jday INT NOT NULL,
                        title VARCHAR(200) NOT NULL,
                        description TEXT,
                        is_holiday BOOLEAN DEFAULT TRUE,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                        INDEX idx_occasion_date (jmonth, jday)
                    )
                    """))
                else:
                    Base.metadata.tables[table_name].create(bind=engine)
                logger.info(f"جدول {table_name} ایجاد شد")
        
        # بررسی فیلدهای خاص در جداول
        try:
            # بررسی فیلدهای events
            events_columns = [col['name'] for col in inspector.get_columns('events')]
            events_missing = []
            
            event_expected = ['type', 'city', 'province', 'country', 'capacity', 'active', 'is_free', 'price']
            for col in event_expected:
                if col not in events_columns:
                    events_missing.append(col)
            
            if events_missing:
                logger.info(f"ایجاد فیلدهای جدید در events: {events_missing}")
                for col in events_missing:
                    if col == 'type':
                        db.execute(text("ALTER TABLE events ADD COLUMN type VARCHAR(20) DEFAULT 'religious'"))
                    elif col == 'city':
                        db.execute(text("ALTER TABLE events ADD COLUMN city VARCHAR(50) DEFAULT 'تهران'"))
                    elif col == 'province':
                        db.execute(text("ALTER TABLE users ADD COLUMN province VARCHAR(50) DEFAULT 'تهران'"))
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
                logger.info("فیلدهای جدید در events ایجاد شدند")
                
            # بررسی فیلد rating در comments
            comments_columns = [col['name'] for col in inspector.get_columns('comments')]
            if 'rating' not in comments_columns:
                logger.info("ایجاد فیلد rating در comments")
                db.execute(text("ALTER TABLE comments ADD COLUMN rating INT DEFAULT 5"))
                db.commit()
                logger.info("فیلد rating ایجاد شد")
                
        except Exception as e:
            logger.error(f"خطا در ایجاد فیلدها: {e}")
            db.rollback()
            
    except Exception as e:
        logger.error(f"خطا در ایجاد فیلدها: {e}")
        db.rollback()
    finally:
        db.close()

# ایجاد جداول در دیتابیس
def create_tables():
    try:
        Base.metadata.create_all(bind=engine)
        logger.info("جداول دیتابیس ایجاد شدند")
        
        # بررسی و ایجاد فیلدهای جدید
        check_and_create_missing_columns()
        
        # ایجاد مناسبت‌های پیش‌فرض در صورت خالی بودن جدول occasions
        db = SessionLocal()
        try:
            count = db.query(Occasion).count()
            if count == 0:
                default_occasions = [
                    (1, 1, "آغاز سال نو", "آغاز سال نو خورشیدی", True),
                    (1, 12, "روز جمهوری اسلامی ایران", "روز جمهوری اسلامی ایران", True),
                    (1, 13, "روز طبیعت", "سیزدهم فروردین، روز طبیعت", True),
                    (11, 22, "پیروزی انقلاب اسلامی", "سالگرد پیروزی انقلاب اسلامی ایران", True),
                    (3, 14, "رحلت امام خمینی (ره)", "چهاردهم خرداد، سالگرد رحلت امام خمینی", True),
                    (12, 29, "روز ملی شدن صنعت نفت", "سالروز ملی شدن صنعت نفت ایران", True),
                    (9, 17, "قبولی اعمال", "شب هایله القدر", True),
                    (12, 13, "تولد حضرت علی (ع)", "سیزدهم رجب، ولادت امام اول شیعیان", True),
                    (7, 27, "مبعث رسول اکرم", "بیست و هفتم رجب، مبعث پیامبر اسلام", True),
                    (6, 15, "ولادت امام مهدی (عج)", "نیمه شعبان، میلاد امام زمان", True)
                ]
                
                for jmonth, jday, title, description, is_holiday in default_occasions:
                    occasion = Occasion(
                        jmonth=jmonth,
                        jday=jday,
                        title=title,
                        description=description,
                        is_holiday=is_holiday
                    )
                    db.add(occasion)
                
                db.commit()
                logger.info(f"{len(default_occasions)} مناسبت پیش‌فرض ایجاد شد")
            else:
                logger.info(f"جدول occasions دارای {count} مناسبت است")
        except Exception as e:
            logger.error(f"خطا در ایجاد مناسبت‌های پیش‌فرض: {e}")
            db.rollback()
        finally:
            db.close()
        
    except Exception as e:
        logger.error(f"خطا در ایجاد جداول: {e}")

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
    phone_number: str
    country: str
    province: str
    city: str
    gender: str
    password: str
    has_accepted_terms: bool = False
    phone_prefix: str = "+98"

class UserResponse(BaseModel):
    id: int
    first_name: str
    last_name: str
    email: str
    phone_number: str
    country: str
    province: str
    city: str
    gender: str
    created_at: datetime
    is_verified: bool
    has_accepted_terms: bool

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
    category: Optional[str] = "مذهبی"
    subcategory: Optional[str] = ""
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
    category: Optional[str] = "مذهبی"
    subcategory: Optional[str] = ""
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
    is_registered: Optional[bool] = False

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
    email: str
    phone_number: str
    user_data: Optional[Dict[str, Any]] = None

class OTPVerifyRequest(BaseModel):
    email: str
    code: str

class OTPVerifyResponse(BaseModel):
    message: str
    access_token: Optional[str] = None
    token_type: Optional[str] = None
    user_id: Optional[int] = None

# مدل جدید برای ثبت‌نام مرحله اول
class SignupStep1Request(BaseModel):
    first_name: str
    last_name: str
    email: str
    phone_number: str
    country: str
    province: str
    city: str
    gender: str
    password: str
    has_accepted_terms: bool
    phone_prefix: str

class SignupStep1Response(BaseModel):
    message: str
    email: str
    phone_number: str
    requires_verification: bool = True

# مدل جدید برای نذورات
class DonationCreate(BaseModel):
    donation_type: str
    amount: float = 0.0
    payment_method: str = "card"

# مدل جدید برای دسته‌بندی
class CategoryResponse(BaseModel):
    main_category: str
    subcategories: List[str]

# مدل جدید برای مناسبت‌های تقویم
class OccasionCreate(BaseModel):
    jmonth: int
    jday: int
    title: str
    description: Optional[str] = None
    is_holiday: Optional[bool] = True

class OccasionResponse(BaseModel):
    id: int
    jmonth: int
    jday: int
    title: str
    description: Optional[str]
    is_holiday: bool
    created_at: datetime

    class Config:
        from_attributes = True

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

# توابع کمکی - اصلاح شده
def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

async def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials"
    )
    try:
        # اگر توکن خالی است، خطا نده و None برگردان
        if not token or token == "null" or token == "undefined":
            return None
            
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email: str = payload.get("sub")
        if email is None:
            raise credentials_exception
            
        user = db.query(User).filter(User.email == email).first()
        if user is None:
            raise credentials_exception
        
        # بررسی اینکه کاربر تایید شده است
        if not user.is_verified:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="حساب کاربری شما تایید نشده است. لطفاً شماره تلفن خود را تایید کنید."
            )
            
        return user
    except JWTError:
        raise credentials_exception

# اضافه کردن dependency اختیاری برای کاربر جاری
async def get_optional_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    try:
        return await get_current_user(token, db)
    except HTTPException:
        return None

# تنظیمات CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://manareh.com",
        "http://manareh.com",
        "https://www.manareh.com",
        "http://www.manareh.com",
        "https://manareh.onrender.com",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "*"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# سرویس ارسال پیامک
class KavenegarSMSService:
    def __init__(self):
        self.api_key = KAVENEGAR_API_KEY
        self.base_url = f"https://api.kavenegar.com/v1/{self.api_key}"

    async def send_verification_code(self, phone_number: str, code: str) -> bool:
        """
        ارسال کد تأیید با الگوی تأیید شده manareh-otp
        """
        receptor = phone_number

        params = {
            'receptor': receptor,
            'token': code,
            'template': 'manareh-otp'
        }

        url = f"{self.base_url}/verify/lookup.json"

        try:
            response = requests.get(url, params=params, timeout=10)
            
            if response.status_code == 200:
                result = response.json()
                if result.get('return', {}).get('status') == 200:
                    logger.info(f"کد تأیید با الگوی manareh-otp ارسال شد به {phone_number}")
                    return True
                else:
                    error_msg = result.get('return', {}).get('message', 'خطای ناشناخته')
                    logger.error(f"خطای کاوه‌نگار: {error_msg}")
                    return False
            else:
                logger.error(f"HTTP Error {response.status_code}: {response.text}")
                return False

        except Exception as e:
            logger.error(f"خطا در ارتباط با کاوه‌نگار: {e}")
            return False

sms_service = KavenegarSMSService()

# بررسی تکراری بودن ایمیل و شماره تلفن
async def check_duplicate_user(email: str, phone_number: str, db: Session) -> None:
    """
    بررسی تکراری بودن ایمیل و شماره تلفن
    """
    existing_user = db.query(User).filter(User.email == email).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="این ایمیل قبلاً ثبت شده است"
        )
    
    existing_phone = db.query(User).filter(User.phone_number == phone_number).first()
    if existing_phone:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="این شماره تلفن قبلاً ثبت شده است"
        )

# 📤 ارسال OTP
@app.post("/send-otp")
async def send_otp(request: OTPSendRequest, db: Session = Depends(get_db)):
    """
    ارسال کد تأیید به شماره تلفن کاربر
    """
    try:
        logger.info(f"درخواست ارسال OTP برای ایمیل: {request.email} و شماره: {request.phone_number}")
        
        # بررسی وجود کاربر در دیتابیس اصلی
        user = db.query(User).filter(User.email == request.email).first()
        
        if user:
            logger.info(f"کاربر موجود یافت شد: {user.email}")
            
            # بررسی تطابق شماره تلفن برای کاربران موجود
            if user.phone_number != request.phone_number:
                logger.warning(f"شماره تلفن {request.phone_number} با ایمیل {request.email} مطابقت ندارد")
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="شماره تلفن با ایمیل مطابقت ندارد"
                )
            
            # بررسی اینکه آیا کاربر قبلاً تایید شده
            if user.is_verified:
                logger.info(f"کاربر {request.email} قبلاً تایید شده است")
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="حساب کاربری شما قبلاً تایید شده است"
                )
        else:
            logger.info(f"کاربر جدید برای ثبت‌نام: {request.email}")
            # برای کاربران جدید، بررسی تکراری بودن اطلاعات
            if request.user_data:
                try:
                    await check_duplicate_user(
                        request.email, 
                        request.phone_number, 
                        db
                    )
                except HTTPException as e:
                    raise e
                except Exception as e:
                    logger.error(f"خطا در بررسی تکراری بودن کاربر: {e}")
        
        # تولید کد تصادفی
        code = str(random.randint(10000, 99999))  # کد ۵ رقمی
        code_expire_time = datetime.utcnow() + timedelta(minutes=2)  # ۲ دقیقه اعتبار
        
        # حذف کدهای قبلی برای این ایمیل
        db.query(OTPTemp).filter(OTPTemp.email == request.email).delete()
        
        # ذخیره کد در جدول موقت
        otp_temp = OTPTemp(
            email=request.email,
            phone_number=request.phone_number,
            verification_code=code,
            code_expire_time=code_expire_time,
            user_data=json.dumps(request.user_data) if request.user_data else '{}'
        )

        db.add(otp_temp)
        db.commit()
        
        logger.info(f"کد تأیید {code} برای {request.email} تولید و در otp_temp ذخیره شد")
        
        # ارسال پیامک واقعی
        success = await sms_service.send_verification_code(request.phone_number, code)
        
        if not success:
            # اگه ارسال نشد، OTP رو حذف کن تا اسپم نشه
            db.delete(otp_temp)
            db.commit()
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="سرویس پیامک موقتاً در دسترس نیست. لطفاً چند دقیقه دیگر تلاش کنید."
            )
        
        logger.info(f"پیامک با کد {code} به شماره {request.phone_number} ارسال شد")
        
        return {
            "message": "کد تأیید با موفقیت ارسال شد",
            "debug_code": code  # فقط برای محیط توسعه
        }
        
    except HTTPException as he:
        logger.error(f"HTTPException در ارسال OTP: {he.detail}")
        raise he
    except Exception as e:
        logger.error(f"خطا در ارسال OTP: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="خطای سرور در ارسال کد تأیید"
        )

# 📩 تایید کد OTP و فعال‌سازی حساب کاربری
@app.post("/verify-otp", response_model=OTPVerifyResponse)
async def verify_otp(request: OTPVerifyRequest, db: Session = Depends(get_db)):
    try:
        otp_temp = db.query(OTPTemp).filter(OTPTemp.email == request.email).first()

        if not otp_temp:
            raise HTTPException(404, "کد تأیید یافت نشد. لطفاً دوباره درخواست دهید")

        if otp_temp.verification_code != request.code:
            raise HTTPException(400, "کد تأیید اشتباه است")

        if datetime.utcnow() > otp_temp.code_expire_time:
            db.delete(otp_temp)
            db.commit()
            raise HTTPException(400, "کد منقضی شده است. لطفاً دوباره درخواست دهید")

        user = db.query(User).filter(User.email == request.email).first()

        if user:
            if user.is_verified:
                raise HTTPException(400, "حساب شما قبلاً تأیید شده است")

            user.is_verified = True
            user.verification_code = None
            user.code_expire_time = None
            db.commit()
            db.refresh(user)

        else:
            # ایجاد کاربر جدید
            user_data = json.loads(otp_temp.user_data) if otp_temp.user_data else {}

            hashed_password = get_password_hash(user_data.get("password", "DefaultPass123"))

            # ایجاد کاربر
            user = User(
                first_name=user_data.get("first_name", ""),
                last_name=user_data.get("last_name", ""),
                email=request.email,
                phone_number=otp_temp.phone_number,
                country=user_data.get("country", ""),
                province=user_data.get("province", ""),
                city=user_data.get("city", ""),
                gender=user_data.get("gender", ""),
                password=hashed_password,
                is_verified=True,
                has_accepted_terms=user_data.get("has_accepted_terms", False),
                phone_prefix=user_data.get("phone_prefix", "+98")
            )
            
            try:
                db.add(user)
                db.commit()
                db.refresh(user)
            except IntegrityError as e:
                db.rollback()
                logger.error(f"خطای یکتایی در ایجاد کاربر: {e}")
                raise HTTPException(500, "خطا در ایجاد حساب کاربری. ممکن است ایمیل یا شماره تلفن تکراری باشد.")

        # حذف OTP موقت
        db.delete(otp_temp)
        db.commit()

        # ایجاد توکن با استفاده از تابع درست
        access_token = create_access_token(data={"sub": user.email})

        return OTPVerifyResponse(
            message="حساب کاربری شما با موفقیت تایید شد",
            access_token=access_token,
            token_type="bearer",
            user_id=user.id
        )

    except HTTPException as e:
        raise e
    except IntegrityError as e:
        logger.error(f"خطای یکتایی در verify_otp: {str(e)}")
        raise HTTPException(500, "خطا در ایجاد حساب کاربری. اطلاعات تکراری است.")
    except Exception as e:
        logger.error(f"⚠️ خطا در verify_otp: {str(e)}")
        raise HTTPException(500, f"خطای سرور در تایید کد: {str(e)}")

# 📝 ثبت‌نام مرحله اول - فقط ذخیره اطلاعات در otp_temp و ارسال OTP
@app.post("/signup-step1", response_model=SignupStep1Response)
async def signup_step1(user: SignupStep1Request, db: Session = Depends(get_db)):
    """
    مرحله اول ثبت‌نام - ذخیره اطلاعات کاربر در otp_temp و ارسال کد تأیید
    """
    try:
        logger.info(f"دریافت اطلاعات کاربر برای ثبت‌نام مرحله اول: {user.email}")
        
        # اعتبارسنجی فیلدهای الزامی
        required_fields = {
            "first_name": user.first_name,
            "last_name": user.last_name,
            "email": user.email,
            "phone_number": user.phone_number,
            "country": user.country,
            "province": user.province,
            "city": user.city,
            "gender": user.gender,
            "password": user.password
        }
        
        missing_fields = [field for field, value in required_fields.items() if not value]
        if missing_fields:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"فیلدهای زیر الزامی هستند: {', '.join(missing_fields)}"
            )
        
        if not re.match(r"^[^\s@]+@[^\s@]+\.[^\s@]+$", user.email):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="فرمت ایمیل نامعتبر است"
            )
        
        # بررسی تکراری بودن اطلاعات
        await check_duplicate_user(user.email, user.phone_number, db)
        
        # بررسی اینکه آیا کاربر با قوانین موافقت کرده
        if not user.has_accepted_terms:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="لطفاً با قوانین و مقررات موافقت کنید"
            )
        
        if not user.phone_prefix:
            user.phone_prefix = "+98"
        
        # اعتبارسنجی شماره تلفن با در نظر گرفتن پیش‌شماره
        if user.country == "iran":
            # برای ایران: پیش‌شماره +98 و شماره 11 رقمی
            if not user.phone_number.startswith("09") or len(user.phone_number) != 11 or not user.phone_number.isdigit():
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="شماره تلفن باید 11 رقم و با 09 شروع شود"
                )
        else:
            # برای کشورهای دیگر: شماره باید حداقل 8 رقم باشد
            if len(user.phone_number) < 8 or not user.phone_number.isdigit():
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="شماره تلفن باید حداقل 8 رقم باشد"
                )
        
        if len(user.password) < 6:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="رمز عبور باید حداقل 6 کاراکتر باشد"
            )
        
        if user.gender not in ['male', 'female']:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="جنسیت باید مرد یا زن باشد"
            )
        
        # آماده کردن داده‌های کاربر برای ذخیره در otp_temp
        user_data = {
            'first_name': user.first_name,
            'last_name': user.last_name,
            'email': user.email,
            'phone_number': user.phone_number,
            'country': user.country,
            'province': user.province,
            'city': user.city,
            'gender': user.gender,
            'password': user.password,
            'has_accepted_terms': user.has_accepted_terms,
            'phone_prefix': user.phone_prefix
        }
        
        # تولید و ذخیره OTP
        code = str(random.randint(10000, 99999))
        code_expire_time = datetime.utcnow() + timedelta(minutes=2)
        
        # حذف کدهای قبلی
        db.query(OTPTemp).filter(OTPTemp.email == user.email).delete()
        
        # ذخیره کد جدید
        otp_temp = OTPTemp(
            email=user.email,
            phone_number=user.phone_number,
            verification_code=code,
            code_expire_time=code_expire_time,
            user_data=json.dumps(user_data)
        )
        db.add(otp_temp)
        db.commit()
        
        # ارسال پیامک واقعی
        success = await sms_service.send_verification_code(user.phone_number, code)
        if not success:
            # اگه ارسال نشد، OTP رو حذف کن تا اسپم نشه
            db.delete(otp_temp)
            db.commit()
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="سرویس پیامک موقتاً در دسترس نیست. لطفاً چند دقیقه دیگر تلاش کنید."
            )
        
        logger.info(f"اطلاعات کاربر در otp_temp ذخیره شد و OTP ارسال شد: {user.email}")
        
        return SignupStep1Response(
            message="کد تأیید به شماره تلفن شما ارسال شد. لطفاً کد را وارد کنید.",
            email=user.email,
            phone_number=user.phone_number,
            requires_verification=True
        )
        
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"خطا در ثبت‌نام مرحله اول: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"خطای سرور در ثبت‌نام: {str(e)}"
        )

# 🎯 API برای ثبت‌نام در رویداد
@app.post("/events/{event_id}/register")
async def register_for_event(
    event_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    ثبت‌نام در رویداد
    """
    try:
        if not current_user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="برای ثبت‌نام در رویداد باید وارد شوید"
            )
        
        event = db.query(Event).filter(Event.id == event_id).first()
        if not event:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="رویداد یافت نشد"
            )
        
        existing_registration = db.query(EventParticipant).filter(
            EventParticipant.event_id == event_id,
            EventParticipant.user_id == current_user.id
        ).first()
        
        if existing_registration:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="شما قبلاً در این رویداد ثبت‌نام کرده‌اید"
            )
        
        current_participants = db.query(EventParticipant).filter(EventParticipant.event_id == event_id).count()
        if current_participants >= event.capacity:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="ظرفیت رویداد تکمیل شده است"
            )
        
        registration = EventParticipant(
            event_id=event_id,
            user_id=current_user.id
        )
        db.add(registration)
        db.commit()
        db.refresh(registration)
        
        # ایجاد نوتیفیکیشن
        notification = Notification(
            user_id=current_user.id,
            title="ثبت‌نام موفق",
            message=f"شما با موفقیت در رویداد '{event.title}' ثبت‌نام کردید.",
            type="success"
        )
        db.add(notification)
        db.commit()
        
        return {
            "message": "ثبت‌نام با موفقیت انجام شد",
            "registration_id": registration.id
        }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"خطا در ثبت‌نام: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="خطای سرور در ثبت‌نام"
        )

# 🎯 API برای ایجاد رویداد
@app.post("/events", response_model=EventResponse)
async def create_event(event: EventCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """
    ایجاد رویداد جدید
    """
    try:
        logger.info(f"دریافت درخواست ایجاد رویداد از کاربر: {current_user.email if current_user else 'Anonymous'}")
        
        if not current_user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="برای ایجاد رویداد باید وارد شوید"
            )
        
        if not all([event.title, event.time, event.location]):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="لطفاً همه فیلدها را پر کنید"
            )
        
        user_exists = db.query(User).filter(User.id == event.creator).first()
        if not user_exists:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="کاربر ایجاد کننده معتبر نیست"
            )
        
        if not event.city:
            event.city = current_user.city if current_user else "تهران"
        if not event.province:
            event.province = current_user.province if current_user else "تهران"
        
        # استفاده از تابع موجود برای ایجاد رویدادهای تکراری
        events_to_create = generate_recurring_events(event, db)
        created_events = []
        
        for event_obj in events_to_create:
            db.add(event_obj)
            db.flush()
            created_events.append(event_obj)
        
        db.commit()
        
        for event_obj in created_events:
            db.refresh(event_obj)
        
        logger.info(f"{len(created_events)} رویداد با موفقیت ایجاد شد")
        
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
            category=created_events[0].category,
            subcategory=created_events[0].subcategory,
            city=created_events[0].city,
            province=created_events[0].province,
            country=created_events[0].country,
            capacity=created_events[0].capacity,
            active=created_events[0].active,
            is_free=created_events[0].is_free,
            price=created_events[0].price
        )
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"خطا در ایجاد رویداد: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="خطای سرور در ایجاد رویداد"
        )

# 🎯 API برای دریافت اطلاعات کاربر با ایمیل
@app.get("/user-by-email/{email}")
async def get_user_by_email(email: str, db: Session = Depends(get_db)):
    try:
        user = db.query(User).filter(User.email == email).first()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="کاربر یافت نشد"
            )
        
        return {
            "id": user.id,
            "email": user.email,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "phone_number": user.phone_number,
            "has_national_id": False  # همیشه false چون کد ملی حذف شده
        }
    except Exception as e:
        logger.error(f"خطا در دریافت اطلاعات کاربر: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="خطای سرور در دریافت اطلاعات کاربر"
        )

# 🎯 API برای پرداخت نذورات
@app.post("/donations/make-donation")
async def make_donation(
    donation_data: DonationCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    endpoint برای پرداخت نذورات - فقط نمایش شماره کارت
    """
    try:
        if not current_user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="برای پرداخت نذری باید وارد شوید"
            )
        
        # شماره کارت برای پرداخت
        card_number = "6219861918435032"
        
        # ایجاد نوتیفیکیشن
        notification = Notification(
            user_id=current_user.id,
            title="درخواست پرداخت نذری",
            message=f"برای پرداخت نذری {donation_data.donation_type}، مبلغ را به شماره کارت {card_number} واریز کنید.",
            type="donation"
        )
        db.add(notification)
        db.commit()
        
        return {
            "message": "برای پرداخت نذری، مبلغ را به شماره کارت زیر واریز کنید",
            "card_number": card_number,
            "donation_type": donation_data.donation_type,
            "note": "پس از واریز، رسید پرداخت را برای ما ارسال کنید."
        }
        
    except Exception as e:
        logger.error(f"خطا در پرداخت نذری: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="خطای سرور در پرداخت نذری"
        )

# 📝 اضافه کردن endpoint برای ورود
@app.post("/token", response_model=Token)
async def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    try:
        # جستجوی کاربر با ایمیل
        user = db.query(User).filter(User.email == form_data.username).first()
        
        if not user:
            # اگر با ایمیل پیدا نشد، با شماره تلفن جستجو کن
            user = db.query(User).filter(User.phone_number == form_data.username).first()
            
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="ایمیل یا شماره تلفن اشتباه است"
            )
        
        # بررسی رمز عبور
        if not verify_password(form_data.password, user.password):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="رمز عبور اشتباه است"
            )
        
        # بررسی اینکه آیا کاربر تایید شده است
        if not user.is_verified:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="حساب کاربری شما تایید نشده است. لطفاً شماره تلفن خود را تایید کنید."
            )
        
        # ایجاد توکن دسترسی
        access_token = create_access_token(data={"sub": user.email})
        
        return {
            "access_token": access_token,
            "token_type": "bearer",
            "user_id": user.id
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"خطا در ورود: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="خطای سرور در ورود"
        )

# 🎯 API برای دریافت قوانین و حریم خصوصی
@app.get("/terms-and-privacy")
async def get_terms_and_privacy():
    """
    دریافت متن قوانین و حریم خصوصی
    """
    return {
        "terms": {
            "title": "قوانین و مقررات استفاده از پلتفرم مناره",
            "content": """
            1. کاربران باید اطلاعات صحیح و معتبر در هنگام ثبت‌نام ارائه دهند.
            2. مسئولیت هرگونه فعالیت از حساب کاربری بر عهده صاحب حساب است.
            3. هرگونه سوءاستفاده از پلتفرم منجر به مسدود شدن حساب می‌شود.
            4. کاربران باید قوانین جمهوری اسلامی ایران را رعایت کنند.
            5. پلتفرم مناره حق تغییر قوانین را با اطلاع‌رسانی قبلی محفوظ می‌دارد.
            6. کاربران موظفند از پلتفرم تنها برای اهداف قانونی استفاده کنند.
            7. هرگونه تبلیغات غیرقانونی یا مخالف با شئونات اسلامی ممنوع است.
            8. احترام به حقوق دیگر کاربران و حریم خصوصی آنان الزامی است.
            9. کاربران نباید اطلاعات نادرست در پلتفرم منتشر کنند.
            10. پلتفرم مناره مسئولیتی در قبال رویدادهای برگزار شده توسط کاربران ندارد.
            """
        },
        "privacy": {
            "title": "حریم خصوصی",
            "content": """
            1. اطلاعات شخصی کاربران نزد ما محفوظ است و در اختیار اشخاص ثالث قرار نمی‌گیرد.
            2. از اطلاعات کاربران تنها برای بهبود خدمات و ارتباط با کاربران استفاده می‌شود.
            3. در صورت درخواست مقامات قضائی، اطلاعات کاربران ارائه خواهد شد.
            4. کاربران می‌توانند درخواست حذف حساب کاربری خود را ارسال کنند.
            5. اطلاعات پرداختی کاربران به صورت امن ذخیره می‌شود.
            6. پلتفرم مناره از تکنولوژی‌های امنیتی برای محافظت از اطلاعات استفاده می‌کند.
            7. کاربران می‌توانند تنظیمات حریم خصوصی خود را در پنل کاربری مدیریت کنند.
            8. کوکی‌ها برای بهبود تجربه کاربری استفاده می‌شوند.
            9. اطلاعات آمارگیری به صورت ناشناس جمع‌آوری می‌شود.
            10. در صورت تغییر سیاست‌های حریم خصوصی، به کاربران اطلاع‌رسانی خواهد شد.
            """
        }
    }

# API جدید برای دریافت دسته‌بندی‌ها
@app.get("/categories", response_model=Dict[str, List[str]])
async def get_categories():
    """
    دریافت لیست دسته‌بندی‌های اصلی و زیردسته‌ها
    """
    categories = {
        "🇮🇷 ملی": [
            "مراسم دولتی",
            "بزرگداشت شهدا",
            "یادبود شخصیت‌های ملی",
            "افتتاح پروژه",
            "اختتامیه رسمی",
            "مراسم تقدیر",
            "مراسم استقبال",
            "مراسم بدرقه",
            "مراسم مناسبتی کشوری"
        ],
        "🕌 مذهبی": [
            "محرم",
            "صفر",
            "شب قدر",
            "افطاری",
            "عید فطر",
            "عید قربان",
            "عید غدیر",
            "نذری",
            "دعای کمیل",
            "دعای توسل",
            "دعای ندبه",
            "جلسه قرآن",
            "ختم قرآن",
            "مولودی",
            "روضه",
            "هیئت",
            "اعتکاف",
            "اربعین",
            "پیاده‌روی مذهبی"
        ],
        "👨‍👩‍👧‍👦 شخصی": [
            "عروسی",
            "نامزدی",
            "عقد",
            "تولد",
            "جشن دندونی",
            "ولیمه",
            "سالگرد ازدواج",
            "مهمانی خانوادگی",
            "دورهمی دوستانه",
            "جشن فارغ‌التحصیلی",
            "مراسم خداحافظی",
            "سورپرایز",
            "جشن موفقیت",
            "پارتی خصوصی"
        ],
        "🎭 فرهنگی و اجتماعی": [
            "سمینار",
            "همایش",
            "کنفرانس",
            "کارگاه آموزشی",
            "نشست فرهنگی",
            "جلسه کتاب‌خوانی",
            "اکران فیلم",
            "نمایش تئاتر",
            "جشنواره",
            "نمایشگاه",
            "مراسم هنری",
            "رویداد دانشجویی",
            "رویداد استارتاپی",
            "گردهمایی اجتماعی",
            "نشست تخصصی",
            "پنل گفتگو",
            "جلسه نقد و بررسی"
        ]
    }
    
    return categories

# تابع ایجاد رویدادهای تکراری
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
            category=base_event.category,
            subcategory=base_event.subcategory,
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
        category=base_event.category,
        subcategory=base_event.subcategory,
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
            category=base_event.category,
            subcategory=base_event.subcategory,
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

# سایر endpointهای موجود...
@app.get("/events", response_model=List[EventResponse])
async def get_events(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        logger.info(f"دریافت درخواست لیست رویدادها از کاربر: {current_user.email if current_user else 'Anonymous'}")
        events = db.query(Event).filter(Event.active == 1).all()
        
        events_list = []
        for event in events:
            avg_rating_result = db.query(func.avg(Comment.rating)).filter(Comment.event_id == event.id).scalar()
            average_rating = round(float(avg_rating_result or 0), 1)
            
            comment_count = db.query(Comment).filter(Comment.event_id == event.id).count()
            
            current_participants = db.query(EventParticipant).filter(EventParticipant.event_id == event.id).count()
            
            # بررسی آیا رویداد مورد علاقه کاربر است
            is_favorite = False
            # بررسی آیا کاربر در رویداد ثبت‌نام کرده است
            is_registered = False
            
            if current_user:
                favorite = db.query(UserFavorite).filter(
                    UserFavorite.user_id == current_user.id,
                    UserFavorite.event_id == event.id
                ).first()
                is_favorite = favorite is not None
                
                registration = db.query(EventParticipant).filter(
                    EventParticipant.event_id == event.id,
                    EventParticipant.user_id == current_user.id
                ).first()
                is_registered = registration is not None
            
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
                "category": getattr(event, 'category', 'مذهبی'),
                "subcategory": getattr(event, 'subcategory', ''),
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
                "is_favorite": is_favorite,
                "is_registered": is_registered
            }
            events_list.append(event_dict)
        
        return events_list
    except Exception as e:
        logger.error(f"خطا در دریافت رویدادها: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="خطای سرور در دریافت رویدادها"
        )

# اضافه کردن endpoint جدید برای events/optimized
@app.get("/events/optimized", response_model=List[EventResponse])
async def get_events_optimized(
    current_user: Optional[User] = Depends(get_optional_current_user), 
    db: Session = Depends(get_db)
):
    """Endpoint جدید برای دریافت بهینه‌شده رویدادها"""
    try:
        logger.info("دریافت درخواست لیست رویدادهای بهینه‌شده")
        events = db.query(Event).filter(Event.active == 1).all()
        
        events_list = []
        for event in events:
            avg_rating_result = db.query(func.avg(Comment.rating)).filter(Comment.event_id == event.id).scalar()
            average_rating = round(float(avg_rating_result or 0), 1)
            
            comment_count = db.query(Comment).filter(Comment.event_id == event.id).count()
            
            current_participants = db.query(EventParticipant).filter(EventParticipant.event_id == event.id).count()
            
            # بررسی آیا رویداد مورد علاقه کاربر است
            is_favorite = False
            # بررسی آیا کاربر در رویداد ثبت‌نام کرده است
            is_registered = False
            
            if current_user:
                favorite = db.query(UserFavorite).filter(
                    UserFavorite.user_id == current_user.id,
                    UserFavorite.event_id == event.id
                ).first()
                is_favorite = favorite is not None
                
                registration = db.query(EventParticipant).filter(
                    EventParticipant.event_id == event.id,
                    EventParticipant.user_id == current_user.id
                ).first()
                is_registered = registration is not None
            
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
                "category": getattr(event, 'category', 'مذهبی'),
                "subcategory": getattr(event, 'subcategory', ''),
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
                "is_favorite": is_favorite,
                "is_registered": is_registered
            }
            events_list.append(event_dict)
        
        logger.info(f"{len(events_list)} رویداد بهینه‌شده بازگردانده شد")
        return events_list
    except Exception as e:
        logger.error(f"خطا در دریافت رویدادهای بهینه‌شده: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="خطای سرور در دریافت رویدادها"
        )

@app.get("/events/public", response_model=List[EventResponse])
async def get_public_events(db: Session = Depends(get_db)):
    try:
        logger.info("دریافت درخواست لیست رویدادهای عمومی")
        events = db.query(Event).filter(Event.active == 1).all()
        
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
                "category": getattr(event, 'category', 'مذهبی'),
                "subcategory": getattr(event, 'subcategory', ''),
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
                "is_favorite": False,
                "is_registered": False
            }
            events_list.append(event_dict)
        
        return events_list
    except Exception as e:
        logger.error(f"خطا در دریافت رویدادهای عمومی: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="خطای سرور در دریافت رویدادها"
        )

@app.put("/events/{event_id}/update-fields")
async def update_event_fields(event_id: int, db: Session = Depends(get_db)):
    try:
        db_event = db.query(Event).filter(Event.id == event_id).first()
        if not db_event:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="رویداد یافت نشد"
            )
        
        creator_user = db.query(User).filter(User.id == db_event.creator).first()
        
        if not hasattr(db_event, 'type') or not db_event.type:
            db_event.type = "religious"
        if not hasattr(db_event, 'category') or not db_event.category:
            db_event.category = "مذهبی"
        if not hasattr(db_event, 'subcategory') or not db_event.subcategory:
            db_event.subcategory = ""
        if not hasattr(db_event, 'city') or not db_event.city:
            db_event.city = creator_user.city if creator_user else "تهران"
        if not hasattr(db_event, 'province') or not db_event.province:
            db_event.province = creator_user.province if creator_user else "تهران"
        if not hasattr(db_event, 'country') or not db_event.country:
            db_event.country = "iran"
        if not hasattr(db_event, 'capacity') or not db_event.capacity:
            db_event.capacity = 100
        if not hasattr(db_event, 'active') or db_event.active is None:
            db_event.active = 1
        if not hasattr(db_event, 'is_free') or db_event.is_free is None:
            db_event.is_free = True
        if not hasattr(db_event, 'price') or db_event.price is None:
            db_event.price = 0.0
        
        db.commit()
        db.refresh(db_event)
        
        return {"message": "فیلدهای رویداد با موفقیت به‌روزرسانی شد", "event": db_event}
        
    except Exception as e:
        db.rollback()
        logger.error(f"خطا در به‌روزرسانی رویداد: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="خطای سرور در به‌روزرسانی رویداد"
        )

@app.get("/users/{user_id}", response_model=UserResponse)
async def get_user(user_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="کاربر یافت نشد"
            )
        return user
    except Exception as e:
        logger.error(f"خطا در دریافت اطلاعات کاربر: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="خطای سرور در دریافت اطلاعات کاربر"
        )

@app.get("/users/me", response_model=UserResponse)
async def get_current_user_info(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        return current_user
    except Exception as e:
        logger.error(f"خطا در دریافت اطلاعات کاربر جاری: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="خطای سرور در دریافت اطلاعات کاربر"
        )

# اضافه کردن endpoint جدید برای آمار کاربر
@app.get("/users/{user_id}/stats", response_model=UserStatsResponse)
async def get_user_stats(
    user_id: int, 
    current_user: Optional[User] = Depends(get_optional_current_user), 
    db: Session = Depends(get_db)
):
    """دریافت آمار کاربر با پشتیبانی از کاربران مهمان"""
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="کاربر یافت نشد"
            )
        
        # اگر کاربر جاری وجود ندارد یا کاربر جاری با کاربر درخواستی متفاوت است،
        # فقط اطلاعات عمومی را برگردان
        if not current_user or current_user.id != user_id:
            return {
                "events_count": 0,
                "notifications_count": 0,
                "favorites_count": 0,
                "join_year": user.created_at.year if user.created_at else 2024
            }
        
        # کاربر معتبر است، اطلاعات کامل را برگردان
        events_count = db.query(Event).filter(Event.creator == user_id).count()
        
        # تعداد نوتیفیکیشن‌های خوانده نشده
        notifications_count = db.query(Notification).filter(
            Notification.user_id == user_id,
            Notification.read == False
        ).count()
        
        # تعداد علاقه‌مندی‌ها
        favorites_count = db.query(UserFavorite).filter(UserFavorite.user_id == user_id).count()
        
        join_year = user.created_at.year if user.created_at else 2024
        
        return {
            "events_count": events_count,
            "notifications_count": notifications_count,
            "favorites_count": favorites_count,
            "join_year": join_year
        }
        
    except Exception as e:
        logger.error(f"خطا در دریافت آمار کاربر: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="خطای سرور در دریافت آمار کاربر"
        )

# اضافه کردن endpoint عمومی برای آمار کاربر
@app.get("/users/{user_id}/stats/public")
async def get_user_stats_public(user_id: int, db: Session = Depends(get_db)):
    """Endpoint عمومی برای دریافت آمار کاربر (بدون نیاز به احراز هویت)"""
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="کاربر یافت نشد"
            )
        
        # تعداد رویدادهای ایجاد شده توسط کاربر
        events_count = db.query(Event).filter(Event.creator == user_id).count()
        
        # تعداد نوتیفیکیشن‌ها
        notifications_count = db.query(Notification).filter(Notification.user_id == user_id).count()
        
        # تعداد علاقه‌مندی‌ها
        favorites_count = db.query(UserFavorite).filter(UserFavorite.user_id == user_id).count()
        
        # سال عضویت
        join_year = user.created_at.year if user.created_at else 2024
        
        return {
            "events_count": events_count,
            "notifications_count": notifications_count,
            "favorites_count": favorites_count,
            "join_year": join_year
        }
    except Exception as e:
        logger.error(f"خطا در دریافت آمار کاربر: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="خطای سرور در دریافت آمار کاربر"
        )

# اضافه کردن endpoint برای بررسی وضعیت توکن
@app.get("/auth/check")
async def check_auth(current_user: User = Depends(get_current_user)):
    """بررسی معتبر بودن توکن"""
    if current_user:
        return {
            "authenticated": True,
            "user_id": current_user.id,
            "email": current_user.email,
            "name": f"{current_user.first_name} {current_user.last_name}"
        }
    else:
        return {
            "authenticated": False,
            "user_id": None,
            "email": None,
            "name": None
        }

@app.post("/comments", response_model=CommentResponse)
async def create_comment(comment: CommentCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        logger.info(f"دریافت نظر جدید برای رویداد {comment.event_id}")
        
        event = db.query(Event).filter(Event.id == comment.event_id).first()
        if not event:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="رویداد یافت نشد"
            )
        
        user = db.query(User).filter(User.id == comment.user_id).first()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="کاربر یافت نشد"
            )
        
        if comment.rating < 1 or comment.rating > 5:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="امتیاز باید بین 1 تا 5 باشد"
            )
        
        existing_comment = db.query(Comment).filter(
            Comment.event_id == comment.event_id,
            Comment.user_id == comment.user_id
        ).first()
        
        if existing_comment:
            existing_comment.comment = comment.comment
            existing_comment.rating = comment.rating
            db_comment = existing_comment
        else:
            db_comment = Comment(
                event_id=comment.event_id,
                user_id=comment.user_id,
                comment=comment.comment,
                rating=comment.rating
            )
            db.add(db_comment)
        
        db.commit()
        db.refresh(db_comment)
        
        comment_response = CommentResponse(
            id=db_comment.id,
            event_id=db_comment.event_id,
            user_id=db_comment.user_id,
            comment=db_comment.comment,
            rating=db_comment.rating,
            created_at=db_comment.created_at,
            user_name=f"{user.first_name} {user.last_name}"
        )
        
        logger.info("نظر با موفقیت ثبت شد")
        return comment_response
        
    except Exception as e:
        db.rollback()
        logger.error(f"خطا در ثبت نظر: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="خطای سرور در ثبت نظر"
        )

@app.get("/comments/{event_id}", response_model=List[CommentResponse])
async def get_comments(event_id: int, db: Session = Depends(get_db)):
    try:
        logger.info(f"دریافت نظرات برای رویداد {event_id}")
        
        event = db.query(Event).filter(Event.id == event_id).first()
        if not event:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="رویداد یافت نشد"
            )
        
        comments = db.query(Comment).filter(Comment.event_id == event_id).order_by(Comment.created_at.desc()).all()
        
        comments_with_names = []
        for comment in comments:
            user = db.query(User).filter(User.id == comment.user_id).first()
            comment_response = CommentResponse(
                id=comment.id,
                event_id=comment.event_id,
                user_id=comment.user_id,
                comment=comment.comment,
                rating=comment.rating,
                created_at=comment.created_at,
                user_name=f"{user.first_name} {user.last_name}" if user else "کاربر ناشناس"
            )
            comments_with_names.append(comment_response)
        
        return comments_with_names
    except Exception as e:
        logger.error(f"خطا در دریافت نظرات: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="خطای سرور در دریافت نظرات"
        )

# اضافه کردن endpoint جدید برای حذف ثبت‌نام از رویداد
@app.delete("/events/{event_id}/unregister")
async def unregister_from_event(event_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        logger.info(f"حذف ثبت‌نام کاربر {current_user.id} از رویداد {event_id}")
        
        event = db.query(Event).filter(Event.id == event_id).first()
        if not event:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="رویداد یافت نشد"
            )
        
        registration = db.query(EventParticipant).filter(
            EventParticipant.event_id == event_id,
            EventParticipant.user_id == current_user.id
        ).first()
        
        if not registration:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="شما در این رویداد ثبت‌نام نکرده‌اید"
            )
        
        db.delete(registration)
        db.commit()
        
        # ایجاد نوتیفیکیشن
        notification = Notification(
            user_id=current_user.id,
            title="لغو ثبت‌نام",
            message=f"ثبت‌نام شما در رویداد '{event.title}' لغو شد.",
            type="info"
        )
        db.add(notification)
        db.commit()
        
        logger.info("ثبت‌نام با موفقیت حذف شد")
        return {"message": "ثبت‌نام شما با موفقیت حذف شد"}
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"خطا در حذف ثبت‌نام: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="خطای سرور در حذف ثبت‌نام"
        )

# اضافه کردن endpoint جدید برای دریافت رویدادهای ثبت‌نام شده کاربر
@app.get("/users/{user_id}/registered-events")
async def get_user_registered_events(user_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        logger.info(f"دریافت رویدادهای ثبت‌نام شده کاربر {user_id}")
        
        if current_user.id != user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="دسترسی غیرمجاز"
            )
        
        registrations = db.query(EventParticipant).filter(EventParticipant.user_id == user_id).all()
        event_ids = [reg.event_id for reg in registrations]
        
        events = db.query(Event).filter(Event.id.in_(event_ids)).all()
        
        events_list = []
        for event in events:
            avg_rating_result = db.query(func.avg(Comment.rating)).filter(Comment.event_id == event.id).scalar()
            average_rating = round(float(avg_rating_result or 0), 1)
            
            comment_count = db.query(Comment).filter(Comment.event_id == event.id).count()
            
            current_participants = db.query(EventParticipant).filter(EventParticipant.event_id == event.id).count()
            
            # بررسی آیا کاربر در این رویداد ثبت‌نام کرده است
            user_registered = True
            
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
                "category": getattr(event, 'category', 'مذهبی'),
                "subcategory": getattr(event, 'subcategory', ''),
                "city": getattr(event, 'city', 'تهران'),
                "province": getattr(event, 'province', 'تهران'),
                "country": getattr(event, 'country', 'iran'),
                "capacity": getattr(event, 'capacity', 100),
                "active": getattr(event, 'active', 1),
                "is_free": getattr(event, 'is_free', True),
                "price": getattr(event, 'price', 0.0),
                "average_rating": average_rating,
                "comment_count": comment_count,
                "user_registered": user_registered,
                "registration_id": next((reg.id for reg in registrations if reg.event_id == event.id), None)
            }
            events_list.append(event_dict)
        
        return events_list
    except Exception as e:
        logger.error(f"خطا در دریافت رویدادهای ثبت‌نام شده: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="خطای سرور در دریافت رویدادهای ثبت‌نام شده"
        )

@app.get("/events/{event_id}/participants", response_model=List[EventParticipantResponse])
async def get_event_participants(event_id: int, db: Session = Depends(get_db)):
    try:
        logger.info(f"دریافت لیست شرکت‌کنندگان رویداد {event_id}")
        
        event = db.query(Event).filter(Event.id == event_id).first()
        if not event:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="رویداد یافت نشد"
            )
        
        participants = db.query(EventParticipant).filter(EventParticipant.event_id == event_id).all()
        
        participants_with_names = []
        for participant in participants:
            user = db.query(User).filter(User.id == participant.user_id).first()
            participant_response = EventParticipantResponse(
                id=participant.id,
                event_id=participant.event_id,
                user_id=participant.user_id,
                registered_at=participant.registered_at,
                attended=participant.attended,
                user_name=f"{user.first_name} {user.last_name}" if user else "کاربر ناشناس"
            )
            participants_with_names.append(participant_response)
        
        return participants_with_names
    except Exception as e:
        logger.error(f"خطا در دریافت شرکت‌کنندگان: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="خطای سرور در دریافت شرکت‌کنندگان"
        )

@app.get("/users/{user_id}/events")
async def get_user_events(user_id: int, db: Session = Depends(get_db)):
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="کاربر یافت نشد"
            )
        
        # دریافت رویدادهایی که کاربر در آنها ثبت‌نام کرده
        registrations = db.query(EventParticipant).filter(EventParticipant.user_id == user_id).all()
        event_ids = [reg.event_id for reg in registrations]
        
        events = db.query(Event).filter(Event.id.in_(event_ids)).all()
        
        events_list = []
        for event in events:
            avg_rating_result = db.query(func.avg(Comment.rating)).filter(Comment.event_id == event.id).scalar()
            average_rating = round(float(avg_rating_result or 0), 1)
            
            comment_count = db.query(Comment).filter(Comment.event_id == event.id).count()
            
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
                "category": getattr(event, 'category', 'مذهبی'),
                "subcategory": getattr(event, 'subcategory', ''),
                "city": getattr(event, 'city', 'تهران'),
                "province": getattr(event, 'province', 'تهران'),
                "country": getattr(event, 'country', 'iran'),
                "capacity": getattr(event, 'capacity', 100),
                "active": getattr(event, 'active', 1),
                "is_free": getattr(event, 'is_free', True),
                "price": getattr(event, 'price', 0.0),
                "average_rating": average_rating,
                "comment_count": comment_count
            }
            events_list.append(event_dict)
        
        return events_list
    except Exception as e:
        logger.error(f"خطا در دریافت رویدادهای کاربر: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="خطای سرور در دریافت رویدادهای کاربر"
        )

# اضافه کردن endpoint برای نوتیفیکیشن‌ها
@app.get("/users/{user_id}/notifications", response_model=List[NotificationResponse])
async def get_user_notifications(user_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        if current_user.id != user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="دسترسی غیرمجاز"
            )
        
        notifications = db.query(Notification).filter(Notification.user_id == user_id).order_by(Notification.created_at.desc()).all()
        return notifications
    except Exception as e:
        logger.error(f"خطا در دریافت نوتیفیکیشن‌ها: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="خطای سرور در دریافت نوتیفیکیشن‌ها"
        )

@app.get("/users/{user_id}/notifications/unread-count")
async def get_unread_notifications_count(user_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        if current_user.id != user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="دسترسی غیرمجاز"
            )
        
        unread_count = db.query(Notification).filter(
            Notification.user_id == user_id,
            Notification.read == False
        ).count()
        
        return {"unread_count": unread_count}
    except Exception as e:
        logger.error(f"خطا در دریافت تعداد نوتیفیکیشن‌های خوانده نشده: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="خطای سرور در دریافت تعداد نوتیفیکیشن‌ها"
        )

@app.put("/notifications/{notification_id}/mark-read")
async def mark_notification_read(notification_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        notification = db.query(Notification).filter(Notification.id == notification_id).first()
        if not notification:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="نوتیفیکیشن یافت نشد"
            )
        
        if notification.user_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="دسترسی غیرمجاز"
            )
        
        notification.read = True
        db.commit()
        
        return {"message": "نوتیفیکیشن به عنوان خوانده شده علامت گذاری شد"}
    except Exception as e:
        db.rollback()
        logger.error(f"خطا در علامت گذاری نوتیفیکیشن: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="خطای سرور در به‌روزرسانی نوتیفیکیشن"
        )

@app.put("/users/{user_id}/notifications/mark-all-read")
async def mark_all_notifications_read(user_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        if current_user.id != user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="دسترسی غیرمجاز"
            )
        
        db.query(Notification).filter(
            Notification.user_id == user_id,
            Notification.read == False
        ).update({"read": True})
        
        db.commit()
        
        return {"message": "همه نوتیفیکیشن‌ها به عنوان خوانده شده علامت گذاری شدند"}
    except Exception as e:
        db.rollback()
        logger.error(f"خطا در علامت گذاری همه نوتیفیکیشن‌ها: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="خطای سرور در به‌روزرسانی نوتیفیکیشن‌ها"
        )

# اضافه کردن endpoint برای علاقه‌مندی‌ها
@app.post("/favorites", response_model=FavoriteResponse)
async def add_to_favorites(favorite: FavoriteCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        logger.info(f"افزودن رویداد {favorite.event_id} به علاقه‌مندی‌های کاربر {favorite.user_id}")
        
        # بررسی وجود رویداد
        event = db.query(Event).filter(Event.id == favorite.event_id).first()
        if not event:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="رویداد یافت نشد"
            )
        
        # بررسی وجود کاربر
        user = db.query(User).filter(User.id == favorite.user_id).first()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="کاربر یافت نشد"
            )
        
        # بررسی آیا قبلاً به علاقه‌مندی اضافه شده
        existing_favorite = db.query(UserFavorite).filter(
            UserFavorite.user_id == favorite.user_id,
            UserFavorite.event_id == favorite.event_id
        ).first()
        
        if existing_favorite:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="این رویداد قبلاً به علاقه‌مندی‌ها اضافه شده است"
            )
        
        # ایجاد علاقه‌مندی جدید
        db_favorite = UserFavorite(
            user_id=favorite.user_id,
            event_id=favorite.event_id
        )
        db.add(db_favorite)
        db.commit()
        db.refresh(db_favorite)
        
        logger.info("رویداد به علاقه‌مندی‌ها اضافه شد")
        return db_favorite
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"خطا در افزودن به علاقه‌مندی‌ها: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="خطای سرور در افزودن به علاقه‌مندی‌ها"
        )

@app.delete("/favorites/{user_id}/{event_id}")
async def remove_from_favorites(user_id: int, event_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        logger.info(f"حذف رویداد {event_id} از علاقه‌مندی‌های کاربر {user_id}")
        
        if current_user.id != user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="دسترسی غیرمجاز"
            )
        
        favorite = db.query(UserFavorite).filter(
            UserFavorite.user_id == user_id,
            UserFavorite.event_id == event_id
        ).first()
        
        if not favorite:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="این رویداد در علاقه‌مندی‌ها یافت نشد"
            )
        
        db.delete(favorite)
        db.commit()
        
        logger.info("رویداد از علاقه‌مندی‌ها حذف شد")
        return {"message": "رویداد از علاقه‌مندی‌ها حذف شد"}
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"خطا در حذف از علاقه‌مندی‌ها: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="خطای سرور در حذف از علاقه‌مندی‌ها"
        )

@app.get("/users/{user_id}/favorites", response_model=List[EventResponse])
async def get_user_favorites(user_id: int, db: Session = Depends(get_db)):
    try:
        logger.info(f"دریافت علاقه‌مندی‌های کاربر {user_id}")
        
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="کاربر یافت نشد"
            )
        
        favorites = db.query(UserFavorite).filter(UserFavorite.user_id == user_id).all()
        event_ids = [fav.event_id for fav in favorites]
        
        events = db.query(Event).filter(Event.id.in_(event_ids)).all()
        
        events_list = []
        for event in events:
            avg_rating_result = db.query(func.avg(Comment.rating)).filter(Comment.event_id == event.id).scalar()
            average_rating = round(float(avg_rating_result or 0), 1)
            
            comment_count = db.query(Comment).filter(Comment.event_id == event.id).count()
            
            current_participants = db.query(EventParticipant).filter(EventParticipant.event_id == event.id).count()
            
            # بررسی آیا رویداد مورد علاقه کاربر است
            is_favorite = True
            
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
                "category": getattr(event, 'category', 'مذهبی'),
                "subcategory": getattr(event, 'subcategory', ''),
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
                "is_favorite": is_favorite,
                "is_registered": False
            }
            events_list.append(event_dict)
        
        return events_list
    except Exception as e:
        logger.error(f"خطا در دریافت علاقه‌مندی‌ها: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="خطای سرور در دریافت علاقه‌مندی‌ها"
        )

@app.get("/geocode")
async def geocode_address(lat: float, lng: float):
    try:
        import requests
        
        url = f"https://nominatim.openstreetmap.org/reverse"
        params = {
            'format': 'json',
            'lat': lat,
            'lon': lng,
            'zoom': 18,
            'addressdetails': 1,
            'accept-language': 'fa'
        }
        
        response = requests.get(url, params=params, timeout=10)
        data = response.json()
        
        if data and 'address' in data:
            address = data['address']
            address_parts = []
            
            if 'road' in address:
                address_parts.append(address['road'])
            if 'neighbourhood' in address:
                address_parts.append(address['neighbourhood'])
            if 'suburb' in address:
                address_parts.append(address['suburb'])
            if 'city' in address:
                address_parts.append(address['city'])
            if 'state' in address:
                address_parts.append(address['state'])
            if 'country' in address:
                address_parts.append(address['country'])
            
            formatted_address = '، '.join(address_parts)
            return {"address": formatted_address, "raw": address}
        else:
            return {"address": "آدرس نامشخص", "raw": {}}
            
    except Exception as e:
        logger.error(f"خطا در جستجوی آدرس: {e}")
        return {"address": "خطا در دریافت آدرس", "raw": {}}

@app.options("/{path:path}")
async def options_route(path: str):
    return JSONResponse(content={"status": "ok"})

@app.get("/test-db")
async def test_db(db: Session = Depends(get_db)):
    try:
        users_count = db.query(User).count()
        events_count = db.query(Event).count()
        comments_count = db.query(Comment).count()
        participants_count = db.query(EventParticipant).count()
        favorites_count = db.query(UserFavorite).count()
        
        users = db.query(User).all()
        users_list = [{"id": u.id, "email": u.email, "name": f"{u.first_name} {u.last_name}", "province": u.province, "city": u.city} for u in users]
        
        events = db.query(Event).all()
        events_list = []
        for event in events:
            event_dict = {
                "id": event.id,
                "title": event.title,
                "type": getattr(event, 'type', 'N/A'),
                "category": getattr(event, 'category', 'مذهبی'),
                "subcategory": getattr(event, 'subcategory', ''),
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
            "users": users_list,
            "events": events_list,
            "database_type": "MySQL"
        }
    except Exception as e:
        return {"error": str(e), "status": "خطا در اتصال به دیتابیس"}

@app.get("/health")
async def health_check():
    return {"status": "healthy", "timestamp": datetime.utcnow()}

# 🎯 اضافه کردن endpoint برای پرداخت نذورات (ورژن ساده)
@app.post("/donations/pay")
async def pay_donation(
    donation_data: DonationCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    try:
        if not current_user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="برای پرداخت باید وارد شوید"
            )
        
        # شماره کارت برای پرداخت
        card_number = "6219861918435032"
        
        # ثبت درخواست پرداخت
        notification = Notification(
            user_id=current_user.id,
            title="درخواست پرداخت نذری",
            message=f"برای پرداخت نذری {donation_data.donation_type}، لطفاً مبلغ را به شماره کارت {card_number} واریز کنید.",
            type="donation"
        )
        db.add(notification)
        db.commit()
        
        return {
            "success": True,
            "message": "برای پرداخت نذری، مبلغ را به شماره کارت زیر واریز کنید",
            "card_number": card_number,
            "donation_type": donation_data.donation_type,
            "note": "پس از واریز، رسید پرداخت را برای ما ارسال کنید."
        }
        
    except Exception as e:
        logger.error(f"خطا در پرداخت نذری: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="خطای سرور در پرداخت نذری"
        )

# ===================== API های جدید برای تقویم =====================

@app.get("/occasions", response_model=Dict[str, List[str]])
async def get_occasions(db: Session = Depends(get_db)):
    """
    دریافت لیست مناسبت‌ها به فرمت مورد نیاز تقویم
    """
    try:
        occasions = db.query(Occasion).all()
        result = {}
        
        for occasion in occasions:
            key = f"{occasion.jmonth}-{occasion.jday}"
            if key not in result:
                result[key] = []
            result[key].append(occasion.title)
        
        return result
    except Exception as e:
        logger.error(f"خطا در دریافت مناسبت‌ها: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="خطای سرور در دریافت مناسبت‌ها"
        )

@app.get("/occasions/{jmonth}/{jday}", response_model=List[OccasionResponse])
async def get_occasions_by_date(jmonth: int, jday: int, db: Session = Depends(get_db)):
    """
    دریافت مناسبت‌های یک تاریخ خاص
    """
    try:
        occasions = db.query(Occasion).filter(
            Occasion.jmonth == jmonth,
            Occasion.jday == jday
        ).all()
        
        return occasions
    except Exception as e:
        logger.error(f"خطا در دریافت مناسبت‌ها برای تاریخ {jmonth}-{jday}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="خطای سرور در دریافت مناسبت‌ها"
        )

@app.post("/occasions", response_model=OccasionResponse)
async def create_occasion(
    occasion: OccasionCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    ایجاد مناسبت جدید (نیاز به احراز هویت)
    """
    try:
        if not current_user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="برای ایجاد مناسبت باید وارد شوید"
            )
        
        # اعتبارسنجی تاریخ
        if occasion.jmonth < 1 or occasion.jmonth > 12:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="ماه باید بین ۱ تا ۱۲ باشد"
            )
        
        if occasion.jday < 1 or occasion.jday > 31:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="روز باید بین ۱ تا ۳۱ باشد"
            )
        
        # بررسی تکراری بودن
        existing = db.query(Occasion).filter(
            Occasion.jmonth == occasion.jmonth,
            Occasion.jday == occasion.jday,
            Occasion.title == occasion.title
        ).first()
        
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="این مناسبت قبلاً ثبت شده است"
            )
        
        new_occasion = Occasion(
            jmonth=occasion.jmonth,
            jday=occasion.jday,
            title=occasion.title,
            description=occasion.description,
            is_holiday=occasion.is_holiday
        )
        
        db.add(new_occasion)
        db.commit()
        db.refresh(new_occasion)
        
        logger.info(f"مناسبت جدید ایجاد شد: {occasion.title} در {occasion.jmonth}/{occasion.jday}")
        
        return new_occasion
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"خطا در ایجاد مناسبت: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="خطای سرور در ایجاد مناسبت"
        )

@app.get("/calendar")
async def get_calendar_page():
    """
    صفحه HTML تقویم
    """
    html_content = """
    <!DOCTYPE html>
    <html lang="fa" dir="rtl">
    <head>
        <meta charset="UTF-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>تقویم مناره</title>
        <style>
            body {
                margin: 0;
                font-family: 'Vazirmatn', sans-serif;
                background: linear-gradient(to bottom, #e8fffb, #b8f1e6);
                min-height: 100vh;
                padding: 16px;
                box-sizing: border-box;
            }
            
            .calendar-container {
                max-width: 500px;
                margin: 0 auto;
                background: white;
                border-radius: 15px;
                padding: 20px;
                box-shadow: 0 10px 30px rgba(0,0,0,0.1);
            }
            
            .header {
                display: flex;
                justify-content: space-between;
                align-items: center;
                font-weight: 600;
                margin-bottom: 20px;
                padding: 10px;
                background: linear-gradient(to right, #00c6a7, #1fb6ff);
                color: white;
                border-radius: 10px;
            }
            
            .header button {
                background: rgba(255,255,255,0.2);
                border: none;
                color: white;
                padding: 8px 12px;
                border-radius: 5px;
                cursor: pointer;
                font-size: 16px;
                transition: background 0.3s;
            }
            
            .header button:hover {
                background: rgba(255,255,255,0.3);
            }
            
            .weekdays {
                display: grid;
                grid-template-columns: repeat(7, 1fr);
                text-align: center;
                color: #666;
                font-size: 14px;
                margin-bottom: 10px;
                padding: 10px;
                background: #f8fafc;
                border-radius: 8px;
            }
            
            .days {
                display: grid;
                grid-template-columns: repeat(7, 1fr);
                gap: 8px;
                text-align: center;
            }
            
            .day {
                height: 45px;
                border-radius: 10px;
                background: #f3f4f6;
                display: flex;
                align-items: center;
                justify-content: center;
                cursor: pointer;
                font-weight: 500;
                transition: all 0.2s;
                user-select: none;
            }
            
            .day:hover {
                transform: translateY(-2px);
                box-shadow: 0 4px 8px rgba(0,0,0,0.1);
            }
            
            .day.today {
                background: linear-gradient(135deg, #1fb6ff, #00c6a7);
                color: white;
                font-weight: 600;
            }
            
            .day.holiday {
                color: #d32f2f;
                background: #ffecec;
                font-weight: 600;
                border: 2px solid #ffcdd2;
            }
            
            .day.selected {
                outline: 3px solid #1fb6ff;
                transform: scale(1.05);
            }
            
            .occasion-box {
                margin-top: 20px;
                padding: 15px;
                background: #f9fafb;
                border-radius: 12px;
                font-size: 14px;
                border-right: 4px solid #00c6a7;
            }
            
            .occasion-title {
                font-weight: 600;
                color: #1e293b;
                margin-bottom: 8px;
                font-size: 16px;
            }
            
            .occasion-item {
                padding: 8px 0;
                border-bottom: 1px dashed #e5e7eb;
            }
            
            .occasion-item:last-child {
                border-bottom: none;
            }
            
            .no-occasion {
                text-align: center;
                color: #94a3b8;
                padding: 20px;
                font-style: italic;
            }
            
            .month-title {
                font-size: 18px;
                font-weight: 700;
            }
            
            @media (max-width: 480px) {
                .calendar-container {
                    padding: 15px;
                }
                
                .day {
                    height: 40px;
                    font-size: 14px;
                }
                
                .header {
                    padding: 8px;
                }
                
                .month-title {
                    font-size: 16px;
                }
            }
            
            .back-button {
                display: inline-block;
                margin-top: 20px;
                padding: 10px 20px;
                background: #00c6a7;
                color: white;
                text-decoration: none;
                border-radius: 25px;
                font-weight: 600;
                text-align: center;
                transition: all 0.3s;
            }
            
            .back-button:hover {
                background: #00a38c;
                transform: translateY(-2px);
            }
        </style>
    </head>
    
    <body>
        <div class="calendar-container">
            <div class="header">
                <button onclick="prevMonth()">‹</button>
                <div class="month-title" id="monthTitle"></div>
                <button onclick="nextMonth()">›</button>
            </div>
            
            <div class="weekdays">
                <span>ش</span>
                <span>ی</span>
                <span>د</span>
                <span>س</span>
                <span>چ</span>
                <span>پ</span>
                <span>ج</span>
            </div>
            
            <div class="days" id="days"></div>
            
            <div class="occasion-box">
                <div class="occasion-title">مناسبت‌های روز انتخاب شده:</div>
                <div id="occasionList">
                    <div class="no-occasion">یک روز را انتخاب کنید</div>
                </div>
            </div>
            
            <a href="/" class="back-button">بازگشت به سایت</a>
        </div>
        
        <script src="https://cdn.jsdelivr.net/npm/jalaali-js/dist/jalaali.min.js"></script>
        <script>
            // دریافت تاریخ امروز
            let today = new Date();
            // تبدیل به تاریخ شمسی
            let jToday = jalaali.toJalaali(today.getFullYear(), today.getMonth() + 1, today.getDate());
            
            let year = jToday.jy;
            let month = jToday.jm;
            
            let occasions = {};
            
            // بارگذاری مناسبت‌ها از دیتابیس
            fetch("/occasions")
                .then(res => res.json())
                .then(data => {
                    occasions = data;
                    render();
                })
                .catch(error => {
                    console.error("خطا در دریافت مناسبت‌ها:", error);
                    // استفاده از مناسبت‌های پیش‌فرض در صورت خطا
                    occasions = {
                        "1-1": ["آغاز سال نو"],
                        "1-12": ["روز جمهوری اسلامی ایران"],
                        "1-13": ["روز طبیعت"],
                        "11-22": ["پیروزی انقلاب اسلامی"],
                        "3-14": ["رحلت امام خمینی (ره)"],
                        "12-29": ["روز ملی شدن صنعت نفت"],
                        "9-17": ["قبولی اعمال (شب هایله القدر)"],
                        "12-13": ["تولد حضرت علی (ع)"],
                        "7-27": ["مبعث رسول اکرم"],
                        "6-15": ["ولادت امام مهدی (عج)"]
                    };
                    render();
                });
            
            const monthNames = [
                "فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور",
                "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند"
            ];
            
            function render() {
                document.getElementById("monthTitle").innerText =
                    monthNames[month - 1] + " " + year;
                
                const daysEl = document.getElementById("days");
                daysEl.innerHTML = "";
                
                const daysCount = jalaali.jalaaliMonthLength(year, month);
                const firstDay = jalaali.jalaaliToGregorian(year, month, 1);
                const startDay = new Date(firstDay.gy, firstDay.gm - 1, firstDay.gd).getDay();
                
                // روزهای خالی قبل از اول ماه
                for (let i = 0; i < (startDay + 1) % 7; i++) {
                    const emptyDiv = document.createElement("div");
                    emptyDiv.className = "day";
                    emptyDiv.style.visibility = "hidden";
                    daysEl.appendChild(emptyDiv);
                }
                
                for (let d = 1; d <= daysCount; d++) {
                    const div = document.createElement("div");
                    div.className = "day";
                    div.innerText = d;
                    
                    if (d === jToday.jd && month === jToday.jm && year === jToday.jy) {
                        div.classList.add("today");
                    }
                    
                    const key = `${month}-${d}`;
                    if (occasions[key]) {
                        div.classList.add("holiday");
                        div.title = occasions[key].join("، ");
                    }
                    
                    div.onclick = () => {
                        document.querySelectorAll(".day").forEach(x => x.classList.remove("selected"));
                        div.classList.add("selected");
                        
                        const occasionListEl = document.getElementById("occasionList");
                        if (occasions[key]) {
                            occasionListEl.innerHTML = occasions[key].map(occasion => 
                                `<div class="occasion-item">${occasion}</div>`
                            ).join("");
                        } else {
                            occasionListEl.innerHTML = '<div class="no-occasion">مناسبتی برای این روز ثبت نشده است</div>';
                        }
                    };
                    
                    daysEl.appendChild(div);
                }
                
                // انتخاب امروز به صورت خودکار
                setTimeout(() => {
                    const todayElement = document.querySelector('.day.today');
                    if (todayElement) {
                        todayElement.click();
                    }
                }, 100);
            }
            
            function nextMonth() {
                month++;
                if (month > 12) { 
                    month = 1; 
                    year++; 
                }
                render();
            }
            
            function prevMonth() {
                month--;
                if (month < 1) { 
                    month = 12; 
                    year--; 
                }
                render();
            }
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)

@app.on_event("startup")
async def startup_event():
    """
    رویداد startup برای راه‌اندازی اولیه برنامه
    """
    try:
        logger.info("🚀 شروع سرویس Manareh API...")
        
        # ایجاد جداول دیتابیس
        create_tables()
        
        # بررسی اتصال دیتابیس
        db = SessionLocal()
        users_count = db.query(User).count()
        logger.info(f"👥 تعداد کاربران در دیتابیس: {users_count}")
        
        if users_count == 0:
            logger.info("هیچ کاربری در دیتابیس وجود ندارد")
        else:
            users = db.query(User).all()
            for user in users:
                logger.info(f"👤 کاربر موجود: {user.email} - {user.first_name} {user.last_name} - {user.province}, {user.city}")
        
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
                category="مذهبی",
                subcategory="روضه",
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
            logger.info("رویداد تستی ایجاد شد")
        
        # به‌روزرسانی رویدادهای موجود
        events = db.query(Event).all()
        updated_count = 0
        for event in events:
            needs_update = False
            
            if not hasattr(event, 'type') or not event.type:
                event.type = "religious"
                needs_update = True
            
            if not hasattr(event, 'category') or not event.category:
                event.category = "مذهبی"
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
            logger.info(f"{updated_count} رویداد موجود با فیلدهای جدید به‌روزرسانی شدند")
        else:
            logger.info("همه رویدادها به‌روز هستند")
        
        # بررسی مناسبت‌ها
        occasions_count = db.query(Occasion).count()
        logger.info(f"📅 تعداد مناسبت‌ها در دیتابیس: {occasions_count}")
            
        logger.info(f"🎯 اتصال دیتابیس: {DATABASE_URL}")
        logger.info(f"📱 سرویس پیامکی کاوه‌نگار فعال است")
        logger.info("✅ سرویس Manareh API با موفقیت راه‌اندازی شد")
            
    except Exception as e:
        logger.error(f"❌ خطا در startup: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=True)
