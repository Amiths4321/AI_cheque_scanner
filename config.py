import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))


class Config:
    SECRET_KEY = "change-this-secret-key-in-production"
    SQLALCHEMY_DATABASE_URI = "sqlite:///" + os.path.join(BASE_DIR, "database.db")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")
    MAX_CONTENT_LENGTH = 8 * 1024 * 1024  # 8 MB max upload size
    ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg"}

    # ---- Ollama / Qwen2.5-VL settings (same remote GPU server as the other projects) ----
    OLLAMA_HOST = "http://10.22.39.192:11434"   # <-- replace with your server's address
    OLLAMA_MODEL = "qwen2.5vl:latest"
    OLLAMA_TIMEOUT_SECONDS = 60