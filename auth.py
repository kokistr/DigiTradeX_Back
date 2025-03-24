from fastapi import Depends
from sqlalchemy.orm import Session
import models
from database import get_db
import logging

# ロギング設定
logger = logging.getLogger(__name__)

# 現在のユーザーを常に開発ユーザーとして返す関数
async def get_current_user(db: Session = Depends(get_db)):
    # 開発ユーザーを探す、なければ作成する
    dev_user = db.query(models.User).filter(models.User.email == "dev@example.com").first()
    
    # ユーザーが存在しない場合は作成
    if not dev_user:
        logger.info("開発ユーザーを作成します")
        dev_user = models.User(
            name="開発ユーザー",
            email="dev@example.com",
            password_hash="not_used",
            role="admin"
        )
        db.add(dev_user)
        db.commit()
        db.refresh(dev_user)
    
    return dev_user

# ダミー関数（使用されないが、インポートエラーを防ぐため）
def create_access_token(data: dict, expires_delta=None):
    return "dummy_token"

def get_password_hash(password: str):
    return "dummy_hash"

def verify_password(plain_password: str, hashed_password: str):
    return True
