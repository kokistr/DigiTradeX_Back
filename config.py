import os
from pathlib import Path
from dotenv import load_dotenv

# .env ファイルをロード
BASE_DIR = Path(__file__).resolve().parent
env_path = BASE_DIR / '.env'
load_dotenv(dotenv_path=env_path)

# データベース接続情報 - すべて環境変数から取得
DB_HOST = os.getenv("DB_HOST")
DB_PORT = os.getenv("DB_PORT", "3306")
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_NAME = os.getenv("DB_NAME")

# SSL 設定が必要
DB_SSL_REQUIRED = True

# JWT 認証設定 - 環境変数から取得
SECRET_KEY = os.getenv("SECRET_KEY")
ALGORITHM = os.getenv("ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "1440"))

# アプリケーション設定 - /tmp パスに変更
UPLOAD_FOLDER = os.getenv("UPLOAD_FOLDER", "/tmp")
OCR_TEMP_FOLDER = os.getenv("OCR_TEMP_FOLDER", "/tmp")

# 開発モード設定
DEV_MODE = os.getenv("DEV_MODE", "False").lower() in ("true", "1", "t")

# アップロードフォルダが存在しない場合は作成
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(OCR_TEMP_FOLDER, exist_ok=True)

# データベース接続URL（SQLAlchemy形式）
# MySQL+mysqlconnectorの形式を使用してAzure MySQL接続
if DB_SSL_REQUIRED:
    DATABASE_URL = f"mysql+pymysql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}?ssl=true"
else:
    DATABASE_URL = f"mysql+pymysql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
