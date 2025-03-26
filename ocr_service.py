"""
OCR処理を行うサービスモジュール
"""
import os
import uuid
import logging
import shutil
import json
import time
from typing import Dict, List, Any, Tuple, Optional
import pytesseract
from pdf2image import convert_from_path
from PIL import Image, ImageEnhance
import io
import tempfile
import re
from sqlalchemy.orm import Session

# OCR処理で抽出する内容の設定（必要に応じて拡張）
from config import UPLOAD_FOLDER, OCR_TEMP_FOLDER
import models
from ocr_extractors import (
    identify_po_format, 
    extract_format1_data, 
    extract_format2_data, 
    extract_format3_data, 
    extract_generic_data,
    validate_and_clean_result,
    analyze_extraction_quality,
    get_extraction_stats
)

# ロギングの設定
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class OCRError(Exception):
    """OCR処理中のエラーを表す例外クラス"""
    pass

def ensure_directories_exist():
    """必要なディレクトリが存在することを確認する"""
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    os.makedirs(OCR_TEMP_FOLDER, exist_ok=True)
    logger.info(f"ディレクトリの確認: UPLOAD_FOLDER={UPLOAD_FOLDER}, OCR_TEMP_FOLDER={OCR_TEMP_FOLDER}")
    
    # ディレクトリの権限も確認
    for dir_path in [UPLOAD_FOLDER, OCR_TEMP_FOLDER]:
        readable = os.access(dir_path, os.R_OK)
        writable = os.access(dir_path, os.W_OK)
        logger.info(f"ディレクトリ {dir_path} の権限: 読み取り={readable}, 書き込み={writable}")

def save_uploaded_file(file, destination_folder: str = UPLOAD_FOLDER) -> str:
    """
    アップロードされたファイルを保存し、保存先のパスを返す
    
    Args:
        file: FastAPIのUploadFileオブジェクト
        destination_folder: 保存先ディレクトリ
        
    Returns:
        保存されたファイルのパス
    """
    # ディレクトリの存在確認
    ensure_directories_exist()
    
    # 一意のファイル名を生成
    unique_id = str(uuid.uuid4())
    filename = f"{unique_id}_{file.filename}"
    file_path = os.path.join(destination_folder, filename)
    
    try:
        # ファイルを保存
        content = file.file.read()
        with open(file_path, "wb") as buffer:
            buffer.write(content)
        
        # ファイルの先頭に戻す（他の処理で再度読み込めるように）
        file.file.seek(0)
        
        logger.info(f"ファイルを保存しました: {file_path}")
        return file_path
    except Exception as e:
        logger.error(f"ファイル保存中にエラーが発生: {str(e)}")
        raise OCRError(f"ファイル保存中にエラーが発生: {str(e)}")

def process_document(file_path: str) -> str:
    """
    PDFまたは画像ファイルを処理してテキストを抽出
    
    Args:
        file_path: 処理するファイルのパス
        
    Returns:
        抽出されたテキスト
    """
    logger.info(f"ドキュメント処理開始: {file_path}")
    
    # ファイルの存在確認
    if not os.path.exists(file_path):
        error_msg = f"ファイルが存在しません: {file_path}"
        logger.error(error_msg)
        raise OCRError(error_msg)
    
    # ファイル拡張子の取得（小文字に変換）
    file_ext = os.path.splitext(file_path)[1].lower()
    
    try:
        # PDFファイルの場合
        if file_ext == '.pdf':
            logger.info("PDFファイルを処理します")
            return process_pdf(file_path)
        # 画像ファイルの場合
        elif file_ext in ['.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.tif']:
            logger.info("画像ファイルを処理します")
            return process_image(file_path)
        else:
            error_msg = f"サポートされていないファイル形式です: {file_ext}"
            logger.error(error_msg)
            raise OCRError(error_msg)
    except Exception as e:
        logger.error(f"ドキュメント処理中にエラーが発生: {str(e)}")
        raise OCRError(f"ドキュメント処理中にエラーが発生: {str(e)}")

def preprocess_image(image):
    """画像の前処理を行う（OCR精度向上のため）"""
    try:
        # グレースケール変換
        if image.mode != 'L':
            image = image.convert('L')
        
        # コントラスト強調
        enhancer = ImageEnhance.Contrast(image)
        image = enhancer.enhance(2.0)
        
        # 明るさ調整
        enhancer = ImageEnhance.Brightness(image)
        image = enhancer.enhance(1.2)
        
        # シャープネス強調
        enhancer = ImageEnhance.Sharpness(image)
        image = enhancer.enhance(1.5)
        
        return image
    except Exception as e:
        logger.warning(f"画像前処理中にエラー: {e}")
        return image  # 元の画像を返す

def process_pdf(pdf_path: str) -> str:
    """
    PDFファイルを画像に変換し、テキストを抽出
    
    Args:
        pdf_path: PDFファイルのパス
        
    Returns:
        抽出されたテキスト
    """
    logger.info(f"PDF処理開始: {pdf_path}")
    
    # PDFファイルから画像への変換
    try:
        # 一時ディレクトリを作成
        with tempfile.TemporaryDirectory() as temp_dir:
            logger.info(f"一時ディレクトリを作成: {temp_dir}")
            
            # PDFからイメージへの変換（popplerが必要）
            try:
                # まずpoppler_pathなしで試す
                try:
                    images = convert_from_path(
                        pdf_path,
                        output_folder=temp_dir,
                        fmt="png",
                        dpi=300
                    )
                    logger.info(f"PDFを{len(images)}枚の画像に変換しました")
                except Exception as e:
                    # poppler_pathの指定を試みる
                    logger.warning(f"標準パスでのPDF変換失敗: {e}")
                    
                    # 一般的なpopplerインストールパスを試す
                    poppler_paths = [
                        '/usr/bin',
                        '/usr/local/bin',
                        '/opt/homebrew/bin',
                        '/usr/local/Cellar/poppler/21.08.0/bin',
                        'C:\\Program Files\\poppler\\bin'
                    ]
                    
                    for path in poppler_paths:
                        try:
                            logger.info(f"poppler_path試行: {path}")
                            images = convert_from_path(
                                pdf_path,
                                output_folder=temp_dir,
                                fmt="png",
                                dpi=300,
                                poppler_path=path
                            )
                            logger.info(f"PDFを{len(images)}枚の画像に変換しました (poppler_path={path})")
                            break
                        except Exception:
                            continue
                    else:
                        # すべてのパスが失敗した場合
                        raise OCRError("poppler-toolsが見つからないか、インストールが必要です。")
            except Exception as e:
                logger.error(f"PDF変換エラー: {str(e)}")
                # 別の方法を試す
                try:
                    # ImageMagickを試みる（コマンドライン実行）
                    logger.info("代替方法としてImageMagickを試行")
                    img_path = os.path.join(temp_dir, "output.png")
                    os.system(f"convert -density 300 '{pdf_path}' '{img_path}'")
                    
                    # 生成されたファイルを確認
                    image_files = [f for f in os.listdir(temp_dir) if f.endswith('.png')]
                    if image_files:
                        images = [Image.open(os.path.join(temp_dir, f)) for f in sorted(image_files)]
                        logger.info(f"ImageMagickで{len(images)}枚の画像に変換しました")
                    else:
                        raise OCRError("PDF変換に失敗しました。poppler-toolsまたはImageMagickをインストールしてください。")
                except Exception as img_error:
                    logger.error(f"ImageMagickも失敗: {img_error}")
                    raise OCRError(f"PDFから画像への変換中にエラーが発生: {str(e)} および {str(img_error)}")
            
            # 各画像をOCR処理
            all_text = ""
            for i, image in enumerate(images):
                logger.info(f"画像 {i+1}/{len(images)} からテキストを抽出しています")
                
                # 画像の前処理
                processed_image = preprocess_image(image)
                
                # pytesseractを使用してテキスト抽出
                try:
                    page_text = pytesseract.image_to_string(processed_image, lang='eng')
                except Exception as ocr_error:
                    logger.error(f"OCRエラー: {ocr_error}")
                    # 代替方法: 画像を一時ファイルとして保存して処理
                    temp_image_path = os.path.join(temp_dir, f"page_{i}.png")
                    processed_image.save(temp_image_path, 'PNG')
                    try:
                        page_text = pytesseract.image_to_string(temp_image_path, lang='eng')
                    except Exception as e:
                        logger.error(f"代替OCR方法も失敗: {e}")
                        page_text = ""
                
                all_text += f"\n--- Page {i+1} ---\n{page_text}"
                logger.debug(f"ページ {i+1} の抽出テキスト長: {len(page_text)} 文字")
            
            logger.info("PDFからのテキスト抽出が完了しました")
            return all_text.strip()
    except Exception as e:
        logger.error(f"PDF処理中にエラーが発生: {str(e)}")
        raise OCRError(f"PDF処理中にエラーが発生: {str(e)}")

def process_image(image_path: str) -> str:
    """
    画像ファイルからテキストを抽出
    
    Args:
        image_path: 画像ファイルのパス
        
    Returns:
        抽出されたテキスト
    """
    logger.info(f"画像処理開始: {image_path}")
    
    try:
        # PILを使用して画像を開く
        with Image.open(image_path) as img:
            # 画像の前処理
            processed_image = preprocess_image(img)
            
            # pytesseractを使用してテキスト抽出
            try:
                text = pytesseract.image_to_string(processed_image, lang='eng')
            except Exception as ocr_error:
                logger.error(f"OCRエラー: {ocr_error}")
                # 代替方法: 一時ファイルとして保存して処理
                with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as temp_file:
                    temp_path = temp_file.name
                
                processed_image.save(temp_path, 'PNG')
                try:
                    text = pytesseract.image_to_string(temp_path, lang='eng')
                    os.unlink(temp_path)  # 一時ファイルを削除
                except Exception as e:
                    logger.error(f"代替OCR方法も失敗: {e}")
                    if os.path.exists(temp_path):
                        os.unlink(temp_path)
                    text = ""
            
            logger.info("画像からのテキスト抽出が完了しました")
            return text.strip()
    except Exception as e:
        logger.error(f"画像処理中にエラーが発生: {str(e)}")
        raise OCRError(f"画像処理中にエラーが発生: {str(e)}")

def extract_po_data(text: str) -> Dict[str, Any]:
    """
    OCRで抽出されたテキストからPO情報を抽出
    
    Args:
        text: OCRで抽出されたテキスト
        
    Returns:
        抽出されたPO情報を含む辞書
    """
    logger.info("POデータの抽出を開始します")
    
    try:
        # POフォーマットを識別
        po_format = identify_po_format(text)
        logger.info(f"識別されたPOフォーマット: {po_format}")
        
        # フォーマットに応じた抽出処理を実行
        if po_format == "format1":
            result = extract_format1_data(text)
        elif po_format == "format2":
            result = extract_format2_data(text)
        elif po_format == "format3":
            result = extract_format3_data(text)
        else:
            # 汎用的な抽出処理を実行
            result = extract_generic_data(text)
        
        # 抽出結果のログ出力
        logger.info(f"抽出結果: {result}")
        
        # 抽出結果の検証とクリーニング
        result = validate_and_clean_result(result)
        
        # テーブル定義に合わせたフィールド名に変換
        db_compatible_result = {
            # PurchaseOrdersテーブルのフィールド
            "customer_name": result.get("customer", ""),
            "po_number": result.get("po_number", ""),
            "currency": result.get("currency", "USD"),
            "total_amount": result.get("totalAmount", "0"),
            "payment_terms": result.get("paymentTerms", ""),
            "shipping_terms": result.get("terms", ""),
            "destination": result.get("destination", ""),
            "status": "pending",  # デフォルト値
            
            # 商品情報（OrderItemsテーブルに対応）
            "products": []
        }
        
        # 商品情報の変換
        if "items" in result and result["items"]:
            for item in result["items"]:
                db_compatible_result["products"].append({
                    "product_name": item.get("name", ""),
                    "quantity": item.get("quantity", 0),
                    "unit_price": item.get("unit_price", 0),
                    "subtotal": item.get("amount", 0)
                })
        
        return db_compatible_result
    except Exception as e:
        logger.error(f"POデータの抽出中にエラーが発生: {str(e)}")
        # エラーが発生しても基本的な情報は返す
        return {
            "error": str(e),
            "status": "error",
            "customer_name": "",
            "po_number": "",
            "currency": "USD",
            "total_amount": "0",
            "payment_terms": "",
            "shipping_terms": "",
            "destination": "",
            "products": []
        }

def update_ocr_result(
    db: Session, 
    ocr_id: int, 
    raw_text: str, 
    processed_data: str, 
    status: str, 
    error_message: str = None
):
    """
    OCR結果を更新します
    
    Args:
        db: データベースセッション
        ocr_id: OCR結果のID
        raw_text: 抽出されたテキスト
        processed_data: 処理済みデータ（JSON文字列）
        status: 処理状態
        error_message: エラーメッセージ（オプション）
    """
    try:
        ocr_result = db.query(models.OCRResult).filter(models.OCRResult.id == ocr_id).first()
        
        if ocr_result:
            ocr_result.raw_text = raw_text
            ocr_result.processed_data = processed_data
            ocr_result.status = status
            
            if error_message:
                # エラーメッセージがあれば保存
                error_data = json.loads(processed_data) if processed_data and processed_data != "{}" else {}
                error_data["error"] = error_message
                ocr_result.processed_data = json.dumps(error_data)
            
            db.commit()
            logger.info(f"OCR結果更新: ID={ocr_id}, ステータス={status}")
        else:
            logger.warning(f"OCR結果更新失敗: ID={ocr_id} が見つかりません")
    
    except Exception as e:
        logger.error(f"OCR結果更新中にエラー: {e}")
        db.rollback()

def process_ocr_with_enhanced_extraction(file_path: str, ocr_id: int, db: Session):
    """
    拡張抽出機能を持つOCR処理を実行します
    
    Args:
        file_path: 処理するファイルのパス
        ocr_id: OCR結果のID
        db: データベースセッション
    """
    try:
        logger.info(f"拡張OCR処理開始: {file_path}")
        
        # 基本的なOCR処理を実行
        start_time = time.time()
        raw_text = process_document(file_path)
        processing_time = time.time() - start_time
        
        # PO情報の抽出
        extracted_data = extract_po_data(raw_text)
        
        # 抽出統計情報の取得
        stats = get_extraction_stats(raw_text, extracted_data)
        
        # 抽出結果と統計情報を含む完全な結果を保存
        complete_result = {
            "data": extracted_data,
            "stats": stats,
            "processing_time": processing_time
        }
        
        # 結果をJSONに変換して保存
        processed_data = json.dumps(complete_result, ensure_ascii=False)
        
        # データベースに結果を保存
        update_ocr_result(db, ocr_id, raw_text, processed_data, "completed")
        
        logger.info(f"拡張OCR処理完了: ID={ocr_id}, 処理時間={processing_time:.2f}秒")
        
    except Exception as e:
        logger.error(f"拡張OCR処理エラー: {str(e)}")
        update_ocr_result(db, ocr_id, "", "{}", "failed", str(e))
        
    return None

def get_ocr_status(job_id: str) -> Dict[str, Any]:
    """
    OCRジョブのステータスを取得
    
    Args:
        job_id: OCRジョブID
        
    Returns:
        ジョブステータス情報を含む辞書
    """
    # 実際のプロジェクトでは、データベースやキャッシュからジョブ状態を取得
    # このサンプルでは、常に完了状態を返す
    return {
        "job_id": job_id,
        "status": "completed",
        "progress": 100,
        "message": "処理が完了しました"
    }

def save_ocr_result(job_id: str, result: Dict[str, Any]) -> bool:
    """
    OCR結果をデータベースに保存
    
    Args:
        job_id: OCRジョブID
        result: 保存するOCR結果
        
    Returns:
        保存が成功したかどうか
    """
    # 実際のプロジェクトでは、データベースに結果を保存
    # このサンプルでは、常に成功を返す
    logger.info(f"OCR結果を保存: job_id={job_id}")
    return True

def get_ocr_result(job_id: str) -> Dict[str, Any]:
    """
    OCR結果を取得
    
    Args:
        job_id: OCRジョブID
        
    Returns:
        OCR結果を含む辞書
    """
    # 実際のプロジェクトでは、データベースから結果を取得
    # このサンプルでは、テーブル定義に合わせたモックデータを返す
    return {
        "job_id": job_id,
        "data": {
            "customer_name": "サンプル株式会社",
            "po_number": "PO-2024-001",
            "currency": "USD",
            "products": [
                {
                    "product_name": "サンプル製品A",
                    "quantity": "100",
                    "unit_price": "10.00",
                    "subtotal": "1000.00"
                }
            ],
            "total_amount": "1000.00",
            "payment_terms": "30日",
            "shipping_terms": "CIF",
            "destination": "東京",
            "status": "pending"
        }
    }

def process_po_file(file_path: str) -> Dict[str, Any]:
    """
    POファイルを処理し、OCR結果を返す
    
    Args:
        file_path: 処理するファイルのパス
        
    Returns:
        処理結果を含む辞書
    """
    try:
        # テキスト抽出
        ocr_text = process_document(file_path)
        
        # POデータの抽出
        po_data = extract_po_data(ocr_text)
        
        return {
            "id": str(uuid.uuid4()),
            "status": "completed",
            "data": po_data
        }
    except Exception as e:
        logger.error(f"POファイル処理エラー: {str(e)}")
        return {
            "id": str(uuid.uuid4()),
            "status": "error",
            "error": str(e)
        }
