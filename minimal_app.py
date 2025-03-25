from fastapi import FastAPI, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
import os
import logging
import uuid
from typing import Optional

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
app = FastAPI()
# CORS設定を追加
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # すべてのオリジンを許可
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
@app.get("/")
async def root():
    logger.info("ルートエンドポイントにアクセスがありました")
    return {"message": "Hello World"}

@app.get("/debug/info")
async def debug_info():
    logger.info("デバッグ情報エンドポイントにアクセスがありました")
    return {
        "cwd": os.getcwd(),
        "tmp_dir_exists": os.path.exists("/tmp"),
        "tmp_dir_writable": os.access("/tmp", os.W_OK),
        "upload_folder": os.getenv("UPLOAD_FOLDER", "/tmp"),
        "ocr_temp_folder": os.getenv("OCR_TEMP_FOLDER", "/tmp")
    }

# フロントエンドから呼び出される実際のOCRアップロードエンドポイント
@app.post("/api/ocr/upload")
async def ocr_upload(
    file: UploadFile = File(...),
    local_kw: Optional[str] = Form(None)
):
    logger.info(f"OCRアップロードリクエスト受信: {file.filename}")
    logger.info(f"パラメータ: local_kw={local_kw}")
    
    try:
        # 一時ファイル保存
        file_content = await file.read()
        unique_id = str(uuid.uuid4())
        file_path = f"/tmp/upload_{unique_id}_{file.filename}"
        
        # ファイル保存
        with open(file_path, "wb") as f:
            f.write(file_content)
        
        logger.info(f"ファイル保存成功: {file_path}")
        
        # 本来のAPIレスポース形式に合わせる
        return {
            "ocrId": unique_id, 
            "status": "processing"
        }
    except Exception as e:
        logger.error(f"ファイルアップロードエラー: {str(e)}")
        return {"success": False, "error": str(e)}

# 簡易的なファイルアップロードエンドポイント
@app.post("/api/debug/upload")
async def debug_upload(file: UploadFile = File(...)):
    logger.info(f"ファイルアップロードリクエスト: {file.filename}")
    
    try:
        # 一時ファイル保存
        file_content = await file.read()
        unique_id = str(uuid.uuid4())
        file_path = f"/tmp/upload_{unique_id}_{file.filename}"
        
        # ファイル保存
        with open(file_path, "wb") as f:
            f.write(file_content)
        
        logger.info(f"ファイル保存成功: {file_path}")
        
        # 成功レスポンス
        return {
            "success": True,
            "filename": file.filename,
            "size": len(file_content),
            "path": file_path,
            "ocrId": unique_id,
            "status": "completed"
        }
    except Exception as e:
        logger.error(f"ファイルアップロードエラー: {str(e)}")
        return {"success": False, "error": str(e)}

# OCRマネジメント用のモックエンドポイント
@app.get("/api/ocr/status/{ocr_id}")
async def ocr_status(ocr_id: str):
    logger.info(f"OCRステータス確認: {ocr_id}")
    return {"ocrId": ocr_id, "status": "completed"}

@app.get("/api/ocr/extract/{ocr_id}")
async def ocr_extract(ocr_id: str):
    logger.info(f"OCRデータ抽出: {ocr_id}")
    return {
        "ocrId": ocr_id,
        "data": {
            "customer": "サンプル株式会社",
            "poNumber": "PO-2025-001",
            "currency": "USD",
            "terms": "CIF",
            "destination": "Tokyo",
            "products": [
                {
                    "name": "Widget A",
                    "quantity": "1000",
                    "unitPrice": "2.50",
                    "amount": "2500.00"
                }
            ],
            "totalAmount": "2500.00"
        }
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
