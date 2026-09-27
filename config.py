import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

class Config:
    SECRET_KEY = os.environ.get("EMP_SECRET_KEY", "change-this-in-production-emp-portal-key")
    DATABASE = os.path.join(BASE_DIR, "emp.db")
    ADMIN_USERNAME = "admin"
    ADMIN_PASSWORD = "admin123"
    ADMIN_EMAIL = "admin@emp.local"
    ADMIN_NAME = "System Administrator"
