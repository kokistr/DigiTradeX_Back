# app.py
from fastapi import FastAPI, HTTPException, Depends, File, UploadFile, Form, BackgroundTasks, Request, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from sqlalchemy.orm import Session
from typing import List, Optional
import os
import shutil
import uuid
import json
from datetime import datetime, timedelta
import re
import logging
import sys

from database import SessionLocal, engine, test_db_connection
import models
import schemas
from auth import get_current_user, create_access_token, get_password_hash, verify_password
from ocr_service import process_document, extract_po_data
import config

# ロギングの設定
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

logger.info("アプリケーション初期化開始")

# 確実にテンポラリディレクトリを設定
UPLOAD_FOLDER = "/tmp"
OCR_TEMP_FOLDER = "/tmp"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(OCR_TEMP_FOLDER, exist_ok=True)

# データベース接続テスト
try:
    test_db_connection()
    logger.info("データベース接続成功")
except Exception as e:
    logger.error(f"データベース接続エラー: {e}")
    # ここではエラーで終了せず、続行する

# モデルの作成
try:
    models.Base.metadata.create_all(bind=engine)
    logger.info("データベーステーブル作成成功")
except Exception as e:
    logger.error(f"データベーステーブル作成エラー: {e}")

app = FastAPI(title="DigiTradeX API", description="PO管理システムのAPI")

# CORSミドルウェアの設定 - 全てのオリジンを許可
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # すべてのオリジンを許可
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],  # 明示的に全メソッドを許可
    allow_headers=["*"],
    expose_headers=["*"]
)

logger.info("CORSミドルウェア設定完了")

# アップロードディレクトリの作成と権限確認
try:
    # ディレクトリへの書き込み権限を確認
    test_file_path = os.path.join(UPLOAD_FOLDER, "test_write.txt")
    with open(test_file_path, "w") as f:
        f.write("Test write permission")
    os.remove(test_file_path)
    logger.info(f"アップロードディレクトリの書き込み権限確認成功: {UPLOAD_FOLDER}")
except Exception as e:
    logger.error(f"アップロードディレクトリの権限チェックに失敗しました: {str(e)}")

# 依存関係
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# デバッグ用: 認証をバイパスする関数 (開発環境でのみ使用)
def get_current_user_debug():
    """開発環境用のダミーユーザーを返す"""
    dummy_user = models.User(
        user_id=1,
        name="開発ユーザー",
        email="dev@example.com",
        password_hash="dummy_hash",
        role="admin"
    )
    return dummy_user

# 環境に応じて適切な認証を選択
if os.environ.get("DEV_MODE", "true").lower() == "true":
    logger.info("開発モードで実行中: 認証をバイパスします")
    current_user_dependency = get_current_user_debug
else:
    logger.info("本番モードで実行中: 通常の認証を使用します")
    current_user_dependency = get_current_user

# 認証関連のエンドポイント（ダミーレスポンスを返す）
@app.post("/api/auth/login", response_model=schemas.Token)
def login(user_data: schemas.UserLogin, db: Session = Depends(get_db)):
    # ダミートークンを返す
    logger.info(f"ダミーログイン成功: {user_data.email}")
    return {"token": "dummy_token", "token_type": "bearer"}

@app.post("/api/auth/register", response_model=schemas.User)
def register_user(user_data: schemas.UserCreate, db: Session = Depends(get_db)):
    # ダミーユーザーを返す
    logger.info(f"ダミーユーザー登録成功: {user_data.email}")
    return {
        "user_id": 1,
        "name": user_data.name,
        "email": user_data.email,
        "role": user_data.role
    }

# GETメソッド対応のOCRアップロードエンドポイント（新規追加）
@app.get("/api/ocr/upload")
async def upload_document_get():
    """
    GETメソッドでアクセスされた場合のヘルパーエンドポイント
    """
    logger.info("GETメソッドでOCRアップロードエンドポイントにアクセスがありました")
    return JSONResponse(
        status_code=200, 
        content={
            "message": "このエンドポイントはPOSTメソッドでファイルアップロードに使用します。GETメソッドは対応していません。",
            "api_status": "running"
        }
    )

# OCR関連のエンドポイント
@app.post("/api/ocr/upload")
async def upload_document(
    file: UploadFile = File(...),
    local_kw: Optional[str] = Form(None),
    background_tasks: BackgroundTasks = BackgroundTasks(),
    current_user: models.User = Depends(current_user_dependency),  # 修正: 認証依存関係を変更
    db: Session = Depends(get_db),
    request: Request = None,
):
    logger.info("ファイルアップロードリクエスト受信")
    if request:
        logger.info(f"ヘッダー情報: {dict(request.headers)}")
    
    try:
        # ファイル拡張子の確認
        file_ext = os.path.splitext(file.filename)[1].lower()
        if file_ext not in ['.pdf', '.png', '.jpg', '.jpeg']:
            logger.warning(f"サポートされていないファイル形式: {file_ext}")
            return JSONResponse(
                status_code=400, 
                content={"message": "サポートされていないファイル形式です。PDF, PNG, JPG, JPEGのみがサポートされています。"}
            )
        
        # ユニークなファイル名生成
        unique_filename = f"{uuid.uuid4()}{file_ext}"
        file_location = os.path.join(UPLOAD_FOLDER, unique_filename)
        
        logger.info(f"ファイルを保存: {file_location}")
        
        # ファイルの内容を読み取り
        file_content = await file.read()
        file_size = len(file_content)
        logger.info(f"ファイルコンテンツ読み取り完了: サイズ={file_size}バイト")

        # ファイルを保存
        try:
            with open(file_location, "wb") as buffer:
                buffer.write(file_content)
            logger.info(f"ファイル保存成功: {file_location}")
        except Exception as save_error:
            logger.error(f"ファイル保存エラー: {str(save_error)}")
            return JSONResponse(
                status_code=500,
                content={"message": f"ファイルの保存に失敗しました: {str(save_error)}"}
            )
        
        # OCR結果レコード作成 (データベースエラーを無視)
        ocr_id = str(uuid.uuid4())  # 仮のIDを生成
        try:
            ocr_result = models.OCRResult(
                user_id=current_user.user_id,
                file_path=file_location,
                status="processing",
                raw_text="",
                processed_data="{}"
            )
            db.add(ocr_result)
            db.commit()
            db.refresh(ocr_result)
            ocr_id = str(ocr_result.id)
            logger.info(f"OCR結果レコード作成: ID={ocr_id}")
        except Exception as db_error:
            logger.error(f"データベース登録エラー（無視して続行）: {str(db_error)}")
            # 開発モードではデータベースエラーを無視
            
        # モック処理の即時返却 (バックグラウンド処理は一時的に無効化)
        logger.info(f"OCRモック処理を返却: ID={ocr_id}")
        return {
            "ocrId": ocr_id, 
            "status": "processing"
        }

    except Exception as e:
        logger.error(f"ファイルアップロード中の予期しないエラー: {str(e)}", exc_info=True)
        return JSONResponse(
            status_code=500, 
            content={"message": f"ファイルのアップロードに失敗しました: {str(e)}"}
        )

# GETメソッド対応のデバッグアップロードエンドポイント（新規追加）
@app.get("/api/debug/upload")
async def debug_upload_get():
    """
    GETメソッドでアクセスされた場合のデバッグエンドポイント
    """
    logger.info("GETメソッドでデバッグアップロードエンドポイントにアクセスがありました")
    return {
        "message": "このエンドポイントはPOSTメソッドでファイルアップロードに使用します。",
        "status": "ok",
        "allowed_methods": ["POST"],
        "example_usage": "POSTリクエストでmultipart/form-dataとしてファイルをアップロードしてください"
    }

# デバッグ用: シンプルなアップロードエンドポイント（認証不要）
@app.post("/api/debug/upload")
async def debug_upload(
    file: UploadFile = File(...),
    request: Request = None,
):
    logger.info(f"デバッグアップロードリクエスト受信: ファイル名={file.filename}")
    if request:
        logger.info(f"デバッグヘッダー情報: {dict(request.headers)}")
    
    try:
        # ファイル拡張子の確認
        file_ext = os.path.splitext(file.filename)[1].lower()
        
        # ファイル保存
        unique_filename = f"debug_{uuid.uuid4()}{file_ext}"
        file_location = os.path.join(UPLOAD_FOLDER, unique_filename)
        
        logger.info(f"デバッグファイル保存: {file_location}")
        
        content = await file.read()
        with open(file_location, "wb") as buffer:
            buffer.write(content)
        
        logger.info(f"デバッグファイル保存成功: サイズ={len(content)}バイト")
        
        # モックデータを返す
        mock_data = {
            "success": True,
            "filename": unique_filename,
            "size": len(content),
            "ocrId": str(uuid.uuid4()),
            "status": "completed"
        }
        
        logger.info(f"デバッグモックデータを返却: {mock_data}")
        return mock_data
        
    except Exception as e:
        logger.error(f"デバッグアップロードエラー: {str(e)}", exc_info=True)
        return JSONResponse(
            status_code=500, 
            content={"error": str(e)}
        )

# ヘルスチェック用エンドポイント
@app.get("/api/health")
async def health_check():
    """アプリケーションの健全性を確認するエンドポイント"""
    return {
        "status": "ok",
        "timestamp": datetime.now().isoformat()
    }

# サーバーデバッグ用のエンドポイント
@app.get("/api/debug/status")
async def debug_status():
    """サーバー状態を確認するためのデバッグエンドポイント"""
    return {
        "status": "running",
        "timestamp": datetime.now().isoformat(),
        "upload_dir_exists": os.path.exists(UPLOAD_FOLDER),
        "upload_dir_writable": os.access(UPLOAD_FOLDER, os.W_OK),
        "env": {
            "dev_mode": os.environ.get("DEV_MODE", "true"),
            "db_host": os.environ.get("DB_HOST", "unknown"),
            "cors_enabled": True
        },
        "python_version": os.environ.get("PYTHONVERSION", "unknown")
    }

# デバッグ情報拡張エンドポイント（新規追加）
@app.get("/api/debug/info")
async def debug_info():
    """デバッグ情報を提供する拡張エンドポイント"""
    return {
        "server_time": datetime.now().isoformat(),
        "python_version": sys.version,
        "upload_folder_exists": os.path.exists(UPLOAD_FOLDER),
        "upload_folder_writable": os.access(UPLOAD_FOLDER, os.W_OK),
        "environment": os.environ.get("ENVIRONMENT", "production"),
        "ports": {
            "configured_port": os.environ.get("PORT", "8181"),
            "websites_port": os.environ.get("WEBSITES_PORT", "Not set")
        },
        "endpoints": {
            "health": "/api/health",
            "debug_status": "/api/debug/status",
            "ocr_upload": "/api/ocr/upload (POST)",
            "debug_upload": "/api/debug/upload (POST)"
        }
    }

# OCRステータス確認エンドポイントのGETメソッド対応（修正版）
@app.get("/api/ocr/status/{ocr_id}")
async def check_ocr_status(ocr_id: str, db: Session = Depends(get_db)):
    """OCR処理のステータスを確認します。"""
    logger.info(f"OCRステータス確認リクエスト受信: ID={ocr_id}")
    
    try:
        # OCR結果をデータベースから取得
        ocr_result = db.query(models.OCRResult).filter(models.OCRResult.id == ocr_id).first()
        
        if ocr_result:
            return {
                "ocrId": ocr_id,
                "status": ocr_result.status,
                "last_updated": ocr_result.updated_at.isoformat() if ocr_result.updated_at else None
            }
        else:
            # データがない場合は明示的にエラーを返す
            logger.warning(f"OCR ID={ocr_id} が見つかりません。")
            return JSONResponse(
                status_code=404,
                content={
                    "status": "not_found",
                    "message": "指定されたIDのOCR処理が見つかりません。IDが無効である可能性があります。"
                }
            )
    except Exception as e:
        logger.error(f"OCRステータス確認中にエラー: {str(e)}")
        return JSONResponse(
            status_code=500,
            content={
                "status": "error",
                "message": f"OCRステータスの取得に失敗しました: {str(e)}"
            }
        )

# OCR抽出データ取得エンドポイントのGETメソッド対応（修正版）
@app.get("/api/ocr/extract/{ocr_id}")
async def get_ocr_data(ocr_id: str, db: Session = Depends(get_db)):
    """OCR処理の結果を取得します。"""
    logger.info(f"OCRデータ取得リクエスト受信: ID={ocr_id}")
    
    try:
        # OCR結果をデータベースから取得
        ocr_result = db.query(models.OCRResult).filter(models.OCRResult.id == ocr_id).first()
        
        if ocr_result and ocr_result.processed_data and ocr_result.processed_data != "{}":
            # 処理済みデータがある場合
            try:
                processed_data = json.loads(ocr_result.processed_data)
                return {
                    "ocrId": ocr_id,
                    "status": "success",
                    "data": processed_data
                }
            except json.JSONDecodeError:
                # JSON解析エラー
                logger.error(f"OCRデータのJSON解析エラー: ID={ocr_id}")
                return JSONResponse(
                    status_code=500,
                    content={
                        "status": "error",
                        "message": "OCR結果データの形式が不正です。"
                    }
                )
        else:
            # データがない場合は明示的にエラーを返す
            logger.warning(f"OCR ID={ocr_id} のデータがありません。")
            return JSONResponse(
                status_code=404,
                content={
                    "status": "not_found",
                    "message": "指定されたIDのOCRデータが見つかりません。処理がまだ完了していないか、IDが無効である可能性があります。"
                }
            )
    except Exception as e:
        logger.error(f"OCRデータ取得中にエラー: {str(e)}")
        return JSONResponse(
            status_code=500,
            content={
                "status": "error",
                "message": f"OCRデータの取得に失敗しました: {str(e)}"
            }
        )

# PO情報を登録するエンドポイント
@app.post("/api/po/register")
async def register_po(
    po_data: dict,
    current_user: models.User = Depends(current_user_dependency),
    db: Session = Depends(get_db)
):
    """
    PO情報を登録します。
    """
    logger.info(f"PO登録リクエスト受信")
    
    try:
        # POデータの検証（簡易版）
        if not po_data.get("customer") or not po_data.get("poNumber"):
            return JSONResponse(
                status_code=400,
                content={"success": False, "message": "必須項目が不足しています"}
            )
        
        logger.info(f"PO登録: 顧客={po_data.get('customer')}, PO番号={po_data.get('poNumber')}")
        
        # 実際のデータベース処理を行う（ダミー）
        # 実際にはここでデータベースに保存する処理を実装
        
        return {
            "success": True,
            "message": "PO情報が正常に登録されました",
            "poId": str(uuid.uuid4())  # ダミーID
        }
    
    except Exception as e:
        logger.error(f"PO登録中にエラー: {str(e)}")
        return JSONResponse(
            status_code=500,
            content={"success": False, "message": f"PO登録に失敗しました: {str(e)}"}
        )

# PO一覧を取得するエンドポイント
@app.get("/api/po/list")
async def get_po_list(
    current_user: models.User = Depends(current_user_dependency),
    db: Session = Depends(get_db)
):
    """
    PO一覧を取得します。
    """
    logger.info("PO一覧取得リクエスト受信")
    
    try:
        # デモ用のダミーデータを返す
        dummy_data = [
            {
                "id": 1,
                "status": "手配中",
                "acquisitionDate": "2025-03-15",
                "organization": "営業部",
                "invoice": "未作成",
                "payment": "未払い",
                "booking": "未手配",
                "manager": "山田太郎",
                "invoiceNumber": "INV-2025-001",
                "poNumber": "PO-2025-001",
                "customer": "株式会社ABC",
                "productName": "製品A",
                "quantity": 1000,
                "currency": "USD",
                "unitPrice": 10.5,
                "amount": 10500,
                "paymentTerms": "60日以内",
                "terms": "CIF",
                "destination": "東京",
                "transitPoint": "横浜",
                "cutOffDate": "2025-04-15",
                "etd": "2025-04-20",
                "eta": "2025-05-10",
                "bookingNumber": "",
                "vesselName": "",
                "voyageNumber": "",
                "containerInfo": "",
                "memo": "初回取引"
            },
            {
                "id": 2,
                "status": "手配済",
                "acquisitionDate": "2025-03-10",
                "organization": "営業部",
                "invoice": "作成済",
                "payment": "未払い",
                "booking": "手配済",
                "manager": "鈴木花子",
                "invoiceNumber": "INV-2025-002",
                "poNumber": "PO-2025-002",
                "customer": "株式会社XYZ",
                "productName": "製品B",
                "quantity": 500,
                "currency": "USD",
                "unitPrice": 15.75,
                "amount": 7875,
                "paymentTerms": "30日以内",
                "terms": "FOB",
                "destination": "大阪",
                "transitPoint": "神戸",
                "cutOffDate": "2025-03-25",
                "etd": "2025-03-30",
                "eta": "2025-04-20",
                "bookingNumber": "BK-12345",
                "vesselName": "OCEAN STAR",
                "voyageNumber": "V123",
                "containerInfo": "40FT x 1",
                "memo": "緊急出荷"
            }
        ]
        
        return {
            "success": True,
            "data": dummy_data
        }
    
    except Exception as e:
        logger.error(f"PO一覧取得中にエラー: {str(e)}")
        return JSONResponse(
            status_code=500,
            content={"success": False, "message": f"PO一覧の取得に失敗しました: {str(e)}"}
        )

# バックエンドが起動したことのログ
logger.info("アプリケーション初期化完了")

if __name__ == "__main__":
    import uvicorn
    logger.info("直接実行モードで起動")
    uvicorn.run(app, host="0.0.0.0", port=8181)
