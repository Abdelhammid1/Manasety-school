import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-change-me")
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL", "postgresql://manasety:manasety@localhost:5432/manasety_lms"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    LOCKOUT_MAX_ATTEMPTS = int(os.environ.get("LOCKOUT_MAX_ATTEMPTS", "5"))
    LOCKOUT_MINUTES = int(os.environ.get("LOCKOUT_MINUTES", "15"))
    DEFAULT_SCHOOL_NAME = os.environ.get(
        "DEFAULT_SCHOOL_NAME", "مدرستي"
    )
    DEFAULT_SCHOOL_CODE = os.environ.get("DEFAULT_SCHOOL_CODE", "SCH")
    WHATSAPP_PROVIDER = os.environ.get("WHATSAPP_PROVIDER", "stub")
    LANGUAGES = ["ar"]
    DEFAULT_LANGUAGE = "ar"
    # Sprint 10 Phase 2 — cap uploaded material file size at 10 MB
    MAX_CONTENT_LENGTH = 10 * 1024 * 1024
    # Sprint 10 Phase 3 — Firebase Cloud Messaging service-account path (optional)
    FCM_SERVICE_ACCOUNT_PATH = os.environ.get("FCM_SERVICE_ACCOUNT_PATH")
    # Ticket "Additional 3" — token protecting the /cron/tick endpoint
    # that flips overdue invoices + sends payment reminders daily.
    CRON_TOKEN = os.environ.get("CRON_TOKEN", "dev-cron-token-change-me")
