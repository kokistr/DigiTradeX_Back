# ocr_service.py
import os
import re
import json
import time
from typing import Dict, Any, Tuple, List
import logging
import pytesseract
from PIL import Image
from pdf2image import convert_from_path
from sqlalchemy.orm import Session

import models
from ocr_extractors import (
    identify_po_format, 
    extract_format1_data, 
    extract_format2_data, 
    extract_format3_data, 
    extract_generic_data
)

# ロギング設定
logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('ocr_service.log', encoding='utf-8')
    ]
)

def preprocess_image(image_path: str) -> Image.Image:
    """
    画像の前処理を行います
    
    :param image_path: 画像ファイルのパス
    :return: 前処理後の画像
    """
    try:
        image = Image.open(image_path)
        
        # グレースケール変換
        image = image.convert('L')
        
        # コントラスト調整
        from PIL import ImageEnhance
        enhancer = ImageEnhance.Contrast(image)
        image = enhancer.enhance(2.0)
        
        return image
    except Exception as e:
        logger.error(f"画像前処理エラー: {e}")
        return Image.open(image_path)

def process_document(file_path: str, ocr_id: int, db: Session) -> Dict[str, Any]:
    """
    ドキュメントを処理してOCRを実行し、結果を保存します。
    
    :param file_path: 処理するファイルのパス
    :param ocr_id: OCR結果のID
    :param db: データベースセッション
    :return: OCR処理の結果情報
    """
    start_time = time.time()
    try:
        logger.info(f"OCR処理開始: {file_path}")
        
        # ファイルの拡張子を取得
        _, file_ext = os.path.splitext(file_path)
        file_ext = file_ext.lower()
        
        raw_text = ""
        
        # PDFの場合
        if file_ext == '.pdf':
            try:
                # PDFを画像に変換
                images = convert_from_path(file_path)
                
                # 各ページをOCR処理
                for i, image in enumerate(images):
                    # 画像を一時ファイルとして保存
                    temp_image_path = f"/tmp/page_{i}.png"
                    image.save(temp_image_path, 'PNG')
                    
                    # 前処理と OCR
                    preprocessed_image = preprocess_image(temp_image_path)
                    page_text = pytesseract.image_to_string(preprocessed_image, lang='eng+jpn')
                    
                    raw_text += f"\n--- Page {i+1} ---\n{page_text}"
                    logger.debug(f"ページ {i+1} の処理完了")
                    
                    # 一時ファイル削除
                    os.remove(temp_image_path)
            
            except Exception as e:
                logger.error(f"PDF処理エラー: {str(e)}")
                update_ocr_result(db, ocr_id, "", "{}", "failed", f"PDF処理エラー: {str(e)}")
                return {"status": "failed", "error": str(e)}
        
        # 画像の場合
        elif file_ext in ['.png', '.jpg', '.jpeg']:
            try:
                # 前処理と OCR
                preprocessed_image = preprocess_image(file_path)
                raw_text = pytesseract.image_to_string(preprocessed_image, lang='eng+jpn')
                logger.debug("画像のOCR処理完了")
            
            except Exception as e:
                logger.error(f"画像処理エラー: {str(e)}")
                update_ocr_result(db, ocr_id, "", "{}", "failed", f"画像処理エラー: {str(e)}")
                return {"status": "failed", "error": str(e)}
        
        else:
            # サポートされていないファイル形式
            error_msg = f"サポートされていないファイル形式: {file_ext}"
            logger.warning(error_msg)
            update_ocr_result(db, ocr_id, "", "{}", "failed", error_msg)
            return {"status": "failed", "error": error_msg}
        
        # 処理時間計算
        processing_time = time.time() - start_time
        
        # OCR結果を保存
        update_ocr_result(db, ocr_id, raw_text, "{}", "completed")
        logger.info(f"OCR処理完了: {file_path}, 処理時間: {processing_time:.2f}秒")
        
        return {
            "status": "completed", 
            "raw_text": raw_text,
            "processing_time": processing_time
        }
    
    except Exception as e:
        logger.error(f"OCR処理エラー: {str(e)}")
        update_ocr_result(db, ocr_id, "", "{}", "failed", str(e))
        return {"status": "failed", "error": str(e)}

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
    
    :param db: データベースセッション
    :param ocr_id: OCR結果のID
    :param raw_text: 抽出されたテキスト
    :param processed_data: 処理済みデータ（JSON文字列）
    :param status: 処理状態
    :param error_message: エラーメッセージ（オプション）
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

def extract_po_data(ocr_text: str) -> Dict[str, Any]:
    """
    OCRで抽出したテキストから発注書データを抽出します。
    
    :param ocr_text: OCRで抽出したテキスト
    :return: 構造化された発注書データ
    """
    # フォーマットの判別
    po_format, confidence = identify_po_format(ocr_text)
    logger.info(f"POフォーマット判定: {po_format}, 信頼度: {confidence:.2f}")
    
    # フォーマットに応じたデータ抽出
    extraction_mapping = {
        "format1": (extract_format1_data, 0.4),
        "format2": (extract_format2_data, 0.4),
        "format3": (extract_format3_data, 0.4)
    }
    
    # デフォルト値の初期化
    result = {
        "customer": "",
        "poNumber": "",
        "currency": "",
        "products": [],
        "totalAmount": "",
        "paymentTerms": "",
        "terms": "",
        "destination": ""
    }
    
    try:
        # 適切な抽出関数を選択
        if po_format in extraction_mapping and confidence >= extraction_mapping[po_format][1]:
            logger.info(f"{po_format} のデータ抽出を実行します")
            extractor = extraction_mapping[po_format][0]
            result = extractor(ocr_text)
        else:
            logger.info("一般的なフォーマットでのデータ抽出を実行します")
            result = extract_generic_data(ocr_text)
        
        # 結果の検証とクリーニング
        validate_and_clean_result(result)
        
        logger.info(f"PO抽出結果: {result}")
        return result
    
    except Exception as e:
        logger.error(f"PO抽出中にエラー: {e}")
        return result

# 他の関数（validate_and_clean_result, analyze_extraction_quality, 
# get_extraction_stats, process_ocr_with_enhanced_extraction）は
# 前回のコードと基本的に同じです。

def process_ocr_with_enhanced_extraction(file_path: str, ocr_id: int, db: Session):
    """
    拡張抽出機能を持つOCR処理を実行します
    
    :param file_path: 処理するファイルのパス
    :param ocr_id: OCR結果のID
    :param db: データベースセッション
    """
    try:
        logger.info(f"拡張OCR処理開始: {file_path}")
        
        # 基本的なOCR処理を実行
        ocr_result = process_document(file_path, ocr_id, db)
        
        # OCR処理が失敗した場合
        if ocr_result["status"] != "completed":
            logger.warning(f"OCR処理が失敗しました: ID={ocr_id}")
            return
        
        # OCR結果を取得
        raw_text = ocr_result.get("raw_text", "")
        
        # PO情報の抽出
        extracted_data = extract_po_data(raw_text)
        
        # 抽出統計情報の取得
        stats = get_extraction_stats(raw_text, extracted_data)
        
        # 抽出結果と統計情報を含む完全な結果を保存
        complete_result = {
            "data": extracted_data,
            "stats": stats,
            "processing_time": ocr_result.get("processing_time", 0)
        }
        
        # 結果をJSONに変換して保存
        processed_data = json.dumps(complete_result, ensure_ascii=False)
        
        # 結果の保存
        ocr_result_db = db.query(models.OCRResult).filter(models.OCRResult.id == ocr_id).first()
        if ocr_result_db:
            ocr_result_db.processed_data = processed_data
            db.commit()
        
        logger.info(f"拡張OCR処理完了: ID={ocr_id}, フォーマット={stats['format_candidates']}")
        
    except Exception as e:
        logger.error(f"拡張OCR処理エラー: {str(e)}")
        update_ocr_result(db, ocr_id, "", "{}", "failed", str(e))

# モジュールのエントリーポイントを明示
__all__ = [
    'process_document', 
    'extract_po_data', 
    'process_ocr_with_enhanced_extraction',
    'analyze_extraction_quality',
    'get_extraction_stats'
]
