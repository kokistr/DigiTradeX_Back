from fastapi import FastAPI, File, UploadFile, Form, Depends, HTTPException, Request, BackgroundTasks
from fastapi.responses import JSONResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
import os
import logging
import shutil
import uuid
import json
from typing import Optional, Dict, Any, List
from pathlib import Path
from datetime import datetime

# ロギングの設定
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

logger.debug("アプリケーション初期化中")

# 環境変数から設定を取得
UPLOAD_FOLDER = os.getenv("UPLOAD_FOLDER", "/tmp")
OCR_TEMP_FOLDER = os.getenv("OCR_TEMP_FOLDER", "/tmp")
DEV_MODE = os.getenv("DEV_MODE", "True").lower() in ("true", "1", "t")

# フォルダが存在しない場合は作成
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(OCR_TEMP_FOLDER, exist_ok=True)

# OCR処理インポート
try:
    from ocr_service import process_document, extract_po_data, process_po_file
    logger.debug("OCRサービスモジュールをインポートしました")
except ImportError as e:
    logger.error(f"OCRモジュールのインポートエラー: {str(e)}")
    # モック関数を用意
    def process_document(file_path):
        logger.warning("モックのprocess_document関数が呼び出されました")
        return "モックテキスト", ["モックページ1", "モックページ2"]
    
    def extract_po_data(ocr_text):
        logger.warning("モックのextract_po_data関数が呼び出されました")
        return {
            "customer": "サンプル顧客",
            "po_number": "PO-MOCK-12345",
            "items": [
                {"name": "サンプル商品", "quantity": 1, "unit_price": 100, "amount": 100}
            ]
        }
    
    def process_po_file(file_path):
        logger.warning("モックのprocess_po_file関数が呼び出されました")
        return {
            "id": str(uuid.uuid4()),
            "status": "completed",
            "data": extract_po_data("")
        }

# アプリケーション初期化
app = FastAPI()

# CORS設定
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 本番環境では特定のオリジンに制限することをお勧めします
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

# 処理状態を保存する辞書
jobs_status = {}

@app.get("/")
async def root():
    """
    ルートエンドポイント - アプリケーションの状態確認
    """
    logger.info("ルートエンドポイントにアクセスがありました")
    return {
        "status": "running",
        "timestamp": datetime.now().isoformat(),
        "upload_dir_exists": os.path.exists(UPLOAD_FOLDER),
        "upload_dir_writable": os.access(UPLOAD_FOLDER, os.W_OK),
        "ocr_temp_dir_exists": os.path.exists(OCR_TEMP_FOLDER),
        "ocr_temp_dir_writable": os.access(OCR_TEMP_FOLDER, os.W_OK),
        "env": {
            "dev_mode": DEV_MODE,
            "db_host": os.getenv("DB_HOST", "未設定"),
            "cors_enabled": True
        },
        "python_version": os.getenv("PYTHON_VERSION", "不明")
    }

@app.get("/api/health")
async def health_check():
    """
    ヘルスチェックエンドポイント
    """
    logger.info("ヘルスチェックエンドポイントにアクセスがありました")
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}

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
        "env_vars": {k: v for k, v in os.environ.items() if not k.startswith("PATH") and not k.startswith("XDG")}
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
            "upload_folder_contents": upload_files[:10] if len(upload_files) > 10 else upload_files,
            "upload_folder_count": len(upload_files)
        },
        "environment": {
            "upload_folder": UPLOAD_FOLDER,
            "ocr_temp_folder": OCR_TEMP_FOLDER,
            "dev_mode": DEV_MODE
        },
        "jobs_count": len(jobs_status)
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

def process_file_background(file_path: str, job_id: str):
    """
    バックグラウンドでファイルを処理する関数
    
    Args:
        file_path: 処理するファイルのパス
        job_id: 処理ジョブのID
    """
    try:
        logger.debug(f"バックグラウンド処理開始: {job_id}")
        
        # OCR処理を実行
        result = process_po_file(file_path)
        
        # 結果を保存
        jobs_status[job_id] = result
        logger.debug(f"バックグラウンド処理完了: {job_id}")
    
    except Exception as e:
        logger.error(f"バックグラウンド処理エラー: {str(e)}")
        # エラー情報を保存
        jobs_status[job_id] = {
            "id": job_id,
            "status": "error",
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }

@app.post("/api/ocr/upload")
async def upload_file(
    background_tasks: BackgroundTasks,
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
        
        # 処理ステータスを初期化
        jobs_status[file_id] = {
            "id": file_id,
            "filename": filename,
            "status": "processing",
            "timestamp": datetime.now().isoformat()
        }
        
        # バックグラウンドでOCR処理を開始
        background_tasks.add_task(process_file_background, file_path, file_id)
        
        return JSONResponse(content={
            "id": file_id,
            "filename": filename,
            "status": "processing",
            "message": "OCR処理を開始しました",
            "preview_url": f"/api/ocr/preview/{filename}"
        })
    
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
    
    if job_id in jobs_status:
        status = jobs_status[job_id]
        # 必要な情報のみを返す
        response = {
            "id": status.get("id", job_id),
            "status": status.get("status", "unknown"),
            "progress": 100 if status.get("status") == "completed" else 50,
            "message": "OCR処理が完了しました" if status.get("status") == "completed" else "OCR処理中です"
        }
        
        # エラーがある場合はメッセージを追加
        if status.get("status") == "error":
            response["message"] = f"エラーが発生しました: {status.get('error', '不明なエラー')}"
        
        return JSONResponse(content=response)
    else:
        # ジョブIDが見つからない場合
        # 開発モードでは常に完了したレスポンスを返す
        if DEV_MODE:
            logger.warning(f"ジョブID ({job_id}) が見つかりません。開発モードのためモックレスポンスを返します。")
            return JSONResponse(content={
                "id": job_id,
                "status": "completed",
                "progress": 100,
                "message": "OCR処理が完了しました (モックデータ)"
            })
        else:
            logger.error(f"ジョブIDが見つかりません: {job_id}")
            return JSONResponse(
                status_code=404,
                content={"message": f"Job ID {job_id} not found"}
            )

@app.get("/api/ocr/extract/{job_id}")
async def get_ocr_result(job_id: str):
    """
    OCR処理の結果を取得するエンドポイント
    """
    logger.info(f"OCR結果取得: {job_id}")
    
    if job_id in jobs_status:
        status = jobs_status[job_id]
        
        # 処理が完了している場合
        if status.get("status") == "completed":
            # データがある場合はそれを返す
            if "data" in status:
                return JSONResponse(content={
                    "id": job_id,
                    "data": status["data"]
                })
            else:
                # データがない場合はエラーを返す
                return JSONResponse(
                    status_code=500,
                    content={"message": "OCR data not available"}
                )
        
        # 処理中の場合
        elif status.get("status") == "processing":
            return JSONResponse(
                status_code=202,
                content={
                    "id": job_id,
                    "status": "processing",
                    "message": "OCR処理中です。後ほど再試行してください。"
                }
            )
        
        # エラーの場合
        elif status.get("status") == "error":
            return JSONResponse(
                status_code=500,
                content={
                    "id": job_id,
                    "status": "error",
                    "message": f"エラーが発生しました: {status.get('error', '不明なエラー')}"
                }
            )
    
    # ジョブIDが見つからない場合
    # 開発モードでは常にモックデータを返す
    if DEV_MODE:
        logger.warning(f"ジョブID ({job_id}) が見つかりません。開発モードのためモックレスポンスを返します。")
        return JSONResponse(content={
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
        })
    else:
        logger.error(f"ジョブIDが見つかりません: {job_id}")
        return JSONResponse(
            status_code=404,
            content={"message": f"Job ID {job_id} not found"}
        )

@app.post("/api/po/register")
async def register_po(request: Request):
    """
    PO情報を登録するエンドポイント
    """
    logger.info("PO登録リクエスト")
    
    try:
        # リクエストボディを取得
        data = await request.json()
        
        # 必須フィールドの確認
        required_fields = ["customer", "po_number", "items"]
        missing_fields = [field for field in required_fields if field not in data or not data[field]]
        
        if missing_fields:
            return JSONResponse(
                status_code=400,
                content={"message": f"Missing required fields: {', '.join(missing_fields)}"}
            )
        
        # ここでデータベースに保存する処理を行う (現在はモック)
        po_id = str(uuid.uuid4())
        
        logger.info(f"PO登録成功: {po_id}")
        
        return JSONResponse(content={
            "id": po_id,
            "message": "PO登録が完了しました",
            "success": True
        })
    
    except Exception as e:
        logger.error(f"PO登録エラー: {str(e)}")
        return JSONResponse(
            status_code=500,
            content={"message": f"Error registering PO: {str(e)}"}
        )

@app.get("/api/po/list")
async def get_po_list():
    """
    PO一覧を取得するエンドポイント
    """
    logger.info("PO一覧取得リクエスト")
    
    # モックデータを返す (本来はデータベースから取得)
    mock_list = [
        {
            "id": "po1",
            "customer": "Sample Customer A",
            "po_number": "PO-2025-001",
            "status": "pending",
            "created_at": "2025-03-20T10:00:00Z",
            "items_count": 3,
            "total_amount": 450,
            "currency": "USD",
            "destination": "Tokyo"
        },
        {
            "id": "po2",
            "customer": "Sample Customer B",
            "po_number": "PO-2025-002",
            "status": "completed",
            "created_at": "2025-03-22T14:30:00Z",
            "items_count": 2,
            "total_amount": 280,
            "currency": "USD",
            "destination": "Osaka"
        }
    ]
    
    return JSONResponse(content=mock_list)

@app.delete("/api/po/delete")
async def delete_po(request: Request):
    """
    POを削除するエンドポイント
    """
    logger.info("PO削除リクエスト")
    
    try:
        # リクエストボディを取得
        data = await request.json()
        
        # IDの確認
        if "ids" not in data or not data["ids"]:
            return JSONResponse(
                status_code=400,
                content={"message": "Missing PO IDs"}
            )
        
        po_ids = data["ids"]
        logger.info(f"PO削除: {po_ids}")
        
        # ここでデータベースから削除する処理を行う (現在はモック)
        # モック成功レスポンス
        return JSONResponse(content={
            "message": f"{len(po_ids)}件のPOを削除しました",
            "deleted_count": len(po_ids),
            "success": True
        })
    
    except Exception as e:
        logger.error(f"PO削除エラー: {str(e)}")
        return JSONResponse(
            status_code=500,
            content={"message": f"Error deleting PO: {str(e)}"}
        )

if __name__ == "__main__":
    # 直接実行された場合は開発サーバーを起動
    import uvicorn
    print("開発サーバーを起動します...")
    uvicorn.run(app, host="0.0.0.0", port=8181)
