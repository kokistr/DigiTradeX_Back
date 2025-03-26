from fastapi import FastAPI, File, UploadFile, Form, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
import os
import logging
import shutil
import uuid
from typing import Optional
import json
from pathlib import Path
import uvicorn

# ロギングの設定
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# アプリケーション初期化
app = FastAPI()

# 環境変数から設定を取得
UPLOAD_FOLDER = os.getenv("UPLOAD_FOLDER", "/tmp")
OCR_TEMP_FOLDER = os.getenv("OCR_TEMP_FOLDER", "/tmp")
DEV_MODE = os.getenv("DEV_MODE", "True").lower() in ("true", "1", "t")

# フォルダが存在しない場合は作成
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(OCR_TEMP_FOLDER, exist_ok=True)

# CORS設定
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 本番環境では特定のオリジンに制限することをお勧めします
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

@app.get("/")
async def root():
    """
    ルートエンドポイント - アプリケーションの状態確認
    """
    logger.info("ルートエンドポイントにアクセスがありました")
    return {"status": "running", "timestamp": "2025-03-26T02:54:38.203086", "upload_dir_exists": True, "upload_dir_writable": True, "env": {"dev_mode": DEV_MODE, "db_host": "tech0-gen-8-step4-dtx-db.mysql.database.azure.com", "cors_enabled": True}, "python_version": "3.10"}

@app.get("/api/health")
async def health_check():
    """
    ヘルスチェックエンドポイント
    """
    logger.info("ヘルスチェックエンドポイントにアクセスがありました")
    return {"status": "healthy", "timestamp": "2025-03-26T02:54:38.203086"}

@app.get("/api/debug/info")
async def debug_info():
    """
    デバッグ情報を返すエンドポイント
    """
    logger.info("デバッグ情報エンドポイントにアクセスがありました")
    return {
        "cwd": os.getcwd(),
        "upload_folder_exists": os.path.exists(UPLOAD_FOLDER),
        "upload_folder_writable": os.access(UPLOAD_FOLDER, os.W_OK),
        "ocr_temp_folder_exists": os.path.exists(OCR_TEMP_FOLDER),
        "ocr_temp_folder_writable": os.access(OCR_TEMP_FOLDER, os.W_OK),
        "upload_folder": UPLOAD_FOLDER,
        "ocr_temp_folder": OCR_TEMP_FOLDER,
        "dev_mode": DEV_MODE,
        "env_vars": dict(os.environ)
    }

@app.get("/api/debug/status")
async def debug_status():
    """
    詳細な状態情報を提供するエンドポイント
    """
    logger.info("デバッグステータスエンドポイントにアクセスがありました")
    
    # テストファイルの作成を試みる
    test_file_path = os.path.join(UPLOAD_FOLDER, "test.txt")
    test_success = False
    try:
        with open(test_file_path, "w") as f:
            f.write("テスト")
        test_success = True
        os.remove(test_file_path)
    except Exception as e:
        logger.error(f"テストファイル作成エラー: {str(e)}")
    
    # アップロードフォルダの内容確認
    upload_files = []
    try:
        upload_files = os.listdir(UPLOAD_FOLDER)
    except Exception as e:
        logger.error(f"アップロードフォルダ読み取りエラー: {str(e)}")
    
    return {
        "app_status": "running",
        "file_system_check": {
            "test_file_write_success": test_success,
            "upload_folder_contents": upload_files[:10],  # 最初の10ファイルのみを表示
            "upload_folder_count": len(upload_files)
        },
        "environment": {
            "upload_folder": UPLOAD_FOLDER,
            "ocr_temp_folder": OCR_TEMP_FOLDER,
            "dev_mode": DEV_MODE
        }
    }

@app.get("/api/ocr/preview/{filename}")
async def get_preview(filename: str):
    """
    アップロードされたPOファイルのプレビューを提供するエンドポイント
    """
    logger.info(f"プレビューリクエスト: {filename}")
    file_path = os.path.join(UPLOAD_FOLDER, filename)
    
    if not os.path.exists(file_path):
        logger.error(f"ファイルが見つかりません: {file_path}")
        raise HTTPException(status_code=404, detail="File not found")
    
    return FileResponse(file_path)

@app.get("/api/ocr/upload")
async def get_ocr_upload():
    """
    OCRアップロードフォームの情報を返すGETエンドポイント
    """
    logger.info("GET /api/ocr/upload へのアクセス")
    return {
        "message": "Please use POST method to upload files",
        "supported_formats": ["PDF", "PNG", "JPG", "JPEG"],
        "max_file_size": "10MB",
        "endpoint": "/api/ocr/upload"
    }

@app.post("/api/ocr/upload")
async def upload_file(
    file: UploadFile = File(...),
    local_kw: Optional[str] = Form(None)
):
    """
    PO（発注書）ファイルをアップロードしてOCR処理を開始するエンドポイント
    """
    logger.info(f"ファイルアップロードリクエスト: {file.filename}, local_kw: {local_kw}")
    
    try:
        # ファイル名の生成（一意のIDを付加）
        file_id = str(uuid.uuid4())
        filename = f"{file_id}_{file.filename}"
        file_path = os.path.join(UPLOAD_FOLDER, filename)
        
        # ファイルを保存
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        
        logger.info(f"ファイルを保存しました: {file_path}")
        
        # OCR処理をモックで返す（実際のOCR処理は実装時に統合）
        mock_ocr_result = {
            "id": file_id,
            "filename": filename,
            "status": "processing",
            "message": "OCR処理を開始しました",
            "preview_url": f"/api/ocr/preview/{filename}"
        }
        
        return JSONResponse(content=mock_ocr_result)
    
    except Exception as e:
        logger.error(f"ファイルアップロードエラー: {str(e)}")
        return JSONResponse(
            status_code=500,
            content={"message": f"Error processing upload: {str(e)}"}
        )

@app.get("/api/debug/upload")
async def debug_upload_get():
    """
    アップロードデバッグ用のGETエンドポイント
    """
    logger.info("GET /api/debug/upload へのアクセス")
    return {
        "message": "Upload debug endpoint is working",
        "method": "GET",
        "upload_folder": UPLOAD_FOLDER,
        "upload_folder_exists": os.path.exists(UPLOAD_FOLDER),
        "upload_folder_writable": os.access(UPLOAD_FOLDER, os.W_OK)
    }

@app.post("/api/debug/upload")
async def debug_upload_post(
    file: Optional[UploadFile] = None,
    data: Optional[str] = Form(None)
):
    """
    アップロードデバッグ用のPOSTエンドポイント
    """
    logger.info(f"POST /api/debug/upload へのアクセス: file={file}, data={data}")
    
    result = {
        "message": "Debug upload endpoint received request",
        "method": "POST",
        "received_file": file.filename if file else None,
        "received_data": data,
        "upload_folder": UPLOAD_FOLDER
    }
    
    if file:
        try:
            # ファイル名の生成（一意のIDを付加）
            file_id = str(uuid.uuid4())
            filename = f"debug_{file_id}_{file.filename}"
            file_path = os.path.join(UPLOAD_FOLDER, filename)
            
            # ファイルを保存
            with open(file_path, "wb") as buffer:
                shutil.copyfileobj(file.file, buffer)
            
            logger.info(f"デバッグファイルを保存しました: {file_path}")
            result["saved_path"] = file_path
            result["success"] = True
        except Exception as e:
            logger.error(f"デバッグファイル保存エラー: {str(e)}")
            result["error"] = str(e)
            result["success"] = False
    
    return JSONResponse(content=result)

@app.get("/api/ocr/status/{job_id}")
async def get_ocr_status(job_id: str):
    """
    OCR処理のステータスを確認するエンドポイント
    """
    logger.info(f"OCRステータス確認: {job_id}")
    
    # この例ではモックステータスを返します
    status = {
        "id": job_id,
        "status": "completed",  # 常に「完了」を返す（テスト用）
        "progress": 100,
        "message": "OCR処理が完了しました"
    }
    
    return JSONResponse(content=status)

@app.get("/api/ocr/extract/{job_id}")
async def get_ocr_result(job_id: str):
    """
    OCR処理の結果を取得するエンドポイント
    """
    logger.info(f"OCR結果取得: {job_id}")
    
    # モックデータを返す
    mock_result = {
        "id": job_id,
        "data": {
            "customer": "Sample Customer Corp.",
            "po_number": "PO-2025-12345",
            "currency": "USD",
            "items": [
                {
                    "name": "Widget A",
                    "quantity": 10,
                    "unit_price": 15.5,
                    "amount": 155
                },
                {
                    "name": "Widget B",
                    "quantity": 5,
                    "unit_price": 25.0,
                    "amount": 125
                }
            ],
            "payment_terms": "Net 30",
            "destination": "Tokyo, Japan"
        }
    }
    
    return JSONResponse(content=mock_result)

if __name__ == "__main__":
    # 直接実行された場合は開発サーバーを起動
    print("開発サーバーを起動します...")
    uvicorn.run(app, host="0.0.0.0", port=8181)
