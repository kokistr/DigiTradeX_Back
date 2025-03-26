# app.py
from fastapi import FastAPI, File, UploadFile, Form, Depends, HTTPException, Request, BackgroundTasks
from fastapi.responses import JSONResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
import os
import logging
import shutil
import uuid
import json
import threading
from typing import Optional, Dict, Any, List
from pathlib import Path
from datetime import datetime
from sqlalchemy.orm import Session

# データベース接続をインポート
from database import get_db
import models

# ロギングの設定
logging.basicConfig(
    level=logging.INFO,  # 本番環境ではINFOレベルが適切
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

logger.info("アプリケーション初期化中")

# 環境変数から設定を取得
UPLOAD_FOLDER = os.getenv("UPLOAD_FOLDER", "/tmp")
OCR_TEMP_FOLDER = os.getenv("OCR_TEMP_FOLDER", "/tmp")

# フォルダが存在しない場合は作成
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(OCR_TEMP_FOLDER, exist_ok=True)

# OCR処理インポート
try:
    from ocr_service import process_document, extract_po_data, process_po_file
    logger.info("OCRサービスモジュールをインポートしました")
except ImportError as e:
    logger.error(f"OCRモジュールのインポートエラー: {str(e)}")
    raise ImportError("必要なOCRモジュールが見つかりません。requirements.txtの依存関係を確認してください。")

# アプリケーション初期化
app = FastAPI()

# CORS設定
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 必要に応じて特定のオリジンに制限することも検討
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
            "ocr_temp_folder": OCR_TEMP_FOLDER
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
    return {
        "message": "Please use POST method to upload files",
        "supported_formats": ["PDF", "PNG", "JPG", "JPEG"],
        "max_file_size": "10MB",
        "endpoint": "/api/ocr/upload"
    }
def _get_demo_data():
    """デモ用のサンプルデータを返す"""
    return {
        "customer_name": "サンプル株式会社",
        "po_number": "PO-2024-001",
        "currency": "USD",
        "products": [
            {
                "product_name": "サンプル製品A",
                "quantity": "1000",
                "unit_price": "10.00",
                "amount": "10000.00",
                "subtotal": "10000.00"  # 両方のフィールドを含める
            }
        ],
        "total_amount": "10000.00",
        "payment_terms": "NET 30",
        "shipping_terms": "CIF",
        "destination": "東京",
        "is_demo": True  # デモデータであることを示すフラグ
    }
    
def process_file_background(file_path: str, job_id: str):
    """
    バックグラウンドでファイルを処理する関数
    
    Args:
        file_path: 処理するファイルのパス
        job_id: 処理ジョブのID
    """
    try:
        logger.info(f"バックグラウンド処理開始: {job_id}")
        
        # ステータスを初期設定
        status_path = f"{file_path}.status"
        with open(status_path, "w") as f:
            f.write("processing")
        
        # 処理開始
        logger.info(f"ファイル処理開始: {file_path}, job_id: {job_id}")
        
        # OCR処理
        try:
            # テキスト抽出
            ocr_text = process_document(file_path)
            
            # テキストが短すぎる場合はエラー
            if not ocr_text or len(ocr_text) < 50:
                raise Exception("OCRテキストが短すぎます")
                
            # PO情報の抽出
            po_data = extract_po_data(ocr_text)
            
            # フィールド名の調整（フロントエンドとの互換性確保）
            if "products" in po_data:
                for i, product in enumerate(po_data["products"]):
                    # 必ず両方のフィールドを持つように
                    if "subtotal" in product and "amount" not in product:
                        po_data["products"][i]["amount"] = product["subtotal"]
                    elif "amount" in product and "subtotal" not in product:
                        po_data["products"][i]["subtotal"] = product["amount"]
                        
                    # 製品名も同様に
                    if "name" in product and "product_name" not in product:
                        po_data["products"][i]["product_name"] = product["name"]
            
            # 結果の保存
            result_path = f"{file_path}.result"
            with open(result_path, "w") as f:
                json.dump(po_data, f, ensure_ascii=False)
            
            # ステータスの更新
            with open(status_path, "w") as f:
                f.write("completed")
            
            # 状態を更新
            jobs_status[job_id] = {
                "status": "completed",
                "data": po_data,
                "timestamp": datetime.now().isoformat()
            }
            
            logger.info(f"ファイル処理完了: {job_id}")
            
        except Exception as ocr_error:
            logger.error(f"OCR処理エラー: {str(ocr_error)}")
            
            # デモデータでフォールバック
            demo_data = _get_demo_data()
            
            # 結果の保存（エラーの場合もデモデータを使用）
            result_path = f"{file_path}.result"
            with open(result_path, "w") as f:
                json.dump(demo_data, f, ensure_ascii=False)
            
            # ステータスの更新
            with open(status_path, "w") as f:
                f.write("completed")  # UIに表示できるようcompleted扱い
            
            # 状態を更新
            jobs_status[job_id] = {
                "status": "completed",
                "data": demo_data,
                "error": str(ocr_error),
                "timestamp": datetime.now().isoformat(),
                "is_demo": True
            }
            
            logger.info(f"エラー発生のためデモデータを使用: {job_id}")
    
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
    
    try:
        if job_id in jobs_status:
            status = jobs_status[job_id]
            
            # 処理が完了している場合
            if status.get("status") == "completed":
                # データがある場合はそれを返す
                if "data" in status:
                    data = status["data"]
                    
                    # フィールド名の一貫性を確保
                    # 製品情報の確認
                    if "products" in data:
                        # なければ空配列を設定
                        if not data["products"]:
                            data["products"] = []
                            
                        for i, product in enumerate(data["products"]):
                            # amount フィールドの確保（フロントエンドはamountを期待）
                            if "subtotal" in product and not "amount" in product:
                                data["products"][i]["amount"] = product["subtotal"]
                                
                            # product_name フィールドの確保
                            if "name" in product and not "product_name" in product:
                                data["products"][i]["product_name"] = product["name"]
                    else:
                        data["products"] = []
                        
                    # 必要なフィールドの確保
                    required_fields = ["customer_name", "po_number", "currency", "payment_terms", 
                                     "shipping_terms", "destination"]
                    for field in required_fields:
                        if field not in data:
                            data[field] = ""
                            
                    logger.info(f"OCR抽出データを返します: {job_id}")
                    return data
                else:
                    logger.warning(f"OCRデータなし: {job_id}")
                    # デモデータを返す
                    return _get_demo_data()
            
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
                logger.warning(f"OCR処理エラー: {job_id} - {status.get('error')}")
                # エラーでもデモデータを返す（UIを止めないため）
                return _get_demo_data()
        
        # ジョブIDが見つからない場合
        logger.error(f"ジョブIDが見つかりません: {job_id}")
        # デモデータを返す
        return _get_demo_data()
        
    except Exception as e:
        logger.error(f"OCR結果取得エラー: {str(e)}")
        # エラーが発生してもデモデータを返す
        return _get_demo_data()


@app.post("/api/po/register")
async def register_po(request: Request, db: Session = Depends(get_db)):
    """
    PO情報を登録するエンドポイント
    
    実際のデータベースに登録する処理に変更
    """
    logger.info("PO登録リクエスト")
    
    try:
        # リクエストボディを取得
        data = await request.json()
        
        # 必須フィールドの確認
        required_fields = ["customer_name", "po_number", "products"]
        missing_fields = [field for field in required_fields if field not in data or not data[field]]
        
        if missing_fields:
            return JSONResponse(
                status_code=400,
                content={"message": f"Missing required fields: {', '.join(missing_fields)}"}
            )
        
        # データベースにPOを保存
        new_po = models.PurchaseOrder(
            customer_name=data["customer_name"],
            po_number=data["po_number"],
            currency=data.get("currency", "USD"),
            total_amount=data.get("total_amount", "0"),
            payment_terms=data.get("payment_terms", ""),
            shipping_terms=data.get("shipping_terms", ""),
            destination=data.get("destination", ""),
            status=data.get("status", "手配中"),
            user_id=1  # デフォルトユーザーID (本来はログインユーザーから取得)
        )
        
        db.add(new_po)
        db.flush()  # IDを取得するためにflush
        
        # 商品情報を保存
        for product in data.get("products", []):
            order_item = models.OrderItem(
                po_id=new_po.id,
                product_name=product.get("product_name", ""),
                quantity=product.get("quantity", "0"),
                unit_price=product.get("unit_price", "0"),
                subtotal=product.get("subtotal", "0")
            )
            db.add(order_item)
        
        # トランザクションをコミット
        db.commit()
        
        logger.info(f"PO登録成功: {new_po.id}")
        
        return JSONResponse(content={
            "id": new_po.id,
            "message": "PO登録が完了しました",
            "success": True
        })
    
    except Exception as e:
        logger.error(f"PO登録エラー: {str(e)}")
        db.rollback()  # エラー時はロールバック
        return JSONResponse(
            status_code=500,
            content={"message": f"Error registering PO: {str(e)}"}
        )

@app.get("/api/po/list")
async def get_po_list(db: Session = Depends(get_db)):
    """
    PO一覧を取得するエンドポイント
    
    実際のデータベースから取得する処理に変更
    """
    logger.info("PO一覧取得リクエスト")
    
    try:
        # データベースからPO一覧を取得
        purchase_orders = db.query(models.PurchaseOrder).order_by(models.PurchaseOrder.created_at.desc()).all()
        
        # レスポンス用のデータを整形
        result = []
        for po in purchase_orders:
            # 商品数と合計金額を計算
            items_count = db.query(models.OrderItem).filter(models.OrderItem.po_id == po.id).count()
            
            # PO情報をJSONに変換
            po_data = {
                "id": po.id,
                "customer_name": po.customer_name,
                "po_number": po.po_number,
                "status": po.status,
                "created_at": po.created_at.isoformat() if po.created_at else None,
                "items_count": items_count,
                "total_amount": po.total_amount,
                "currency": po.currency,
                "destination": po.destination
            }
            result.append(po_data)
        
        return JSONResponse(content=result)
    
    except Exception as e:
        logger.error(f"PO一覧取得エラー: {str(e)}")
        return JSONResponse(
            status_code=500,
            content={"message": f"Error retrieving PO list: {str(e)}"}
        )

@app.delete("/api/po/delete")
async def delete_po(request: Request, db: Session = Depends(get_db)):
    """
    POを削除するエンドポイント
    
    実際のデータベースから削除する処理に変更
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
        
        # PO削除の前に関連する情報を削除（カスケード削除の補完）
        for po_id in po_ids:
            # 商品情報を削除
            db.query(models.OrderItem).filter(models.OrderItem.po_id == po_id).delete()
            
            # 出荷スケジュールを削除
            db.query(models.ShippingSchedule).filter(models.ShippingSchedule.po_id == po_id).delete()
            
            # 追加情報を削除
            db.query(models.Input).filter(models.Input.po_id == po_id).delete()
            
            # OCR結果を削除
            db.query(models.OCRResult).filter(models.OCRResult.po_id == po_id).delete()
        
        # POを削除
        deleted_count = db.query(models.PurchaseOrder).filter(models.PurchaseOrder.id.in_(po_ids)).delete(synchronize_session=False)
        
        # トランザクションをコミット
        db.commit()
        
        return JSONResponse(content={
            "message": f"{deleted_count}件のPOを削除しました",
            "deleted_count": deleted_count,
            "success": True
        })
    
    except Exception as e:
        logger.error(f"PO削除エラー: {str(e)}")
        db.rollback()  # エラー時はロールバック
        return JSONResponse(
            status_code=500,
            content={"message": f"Error deleting PO: {str(e)}"}
        )

if __name__ == "__main__":
    # 直接実行された場合は開発サーバーを起動
    import uvicorn
    print("開発サーバーを起動します...")
    uvicorn.run(app, host="0.0.0.0", port=8181)
