# ocr_extractors.py
import re
import logging
from typing import Dict, Any, Tuple, List

# ロギング設定
logger = logging.getLogger(__name__)

def identify_po_format(ocr_text: str) -> Tuple[str, float]:
    """
    OCRで抽出したテキストからPOフォーマットを識別します
    
    :param ocr_text: OCRで抽出したテキスト
    :return: (フォーマット名, 信頼度)
    """
    # 空のテキストや非常に短いテキストは拒否
    if not ocr_text or len(ocr_text.strip()) < 50:
        logger.warning("テキストが短すぎるか空です")
        return "unknown", 0.0

    # フォーマット判定のための特徴と重み
    format_features = {
        "format1": [
            (r"\(Buyer(?:'|')s Info\)", 10),  # 最も重要な特徴
            (r"ABC Company", 5),
            (r"Purchase Order:?\s*\d+", 5),
            (r"Ship to:", 3),
            (r"Unit Price:?\s*\$", 3),
            (r"EXT Price:", 3),
            (r"Inco Terms:", 2),
            (r"Del Date:", 2)
        ],
        "format2": [
            (r"Purchase Order\s*$", 10),  # 最も重要な特徴
            (r"Supplier:", 5),
            (r"Purchase Order no:?\s*\d+", 5),
            (r"Payment Terms:", 3),
            (r"Incoterms:", 3),
            (r"Discharge Port:", 3),
            (r"Buyer:", 3),
            (r"Commodity", 2),
            (r"Grand Total", 2)
        ],
        "format3": [
            (r"(?:\/\/\/|///)ORDER CONFIMATION(?:\/\/\/|///)", 10),  # 最も重要な特徴
            (r"Contract Party\s*:", 5),
            (r"Order No\.", 5),
            (r"Grade [A-Z]", 3),
            (r"Qt'y \(mt\)", 3), 
            (r"PORT OF DISCHARGE", 3),
            (r"Payment term", 2),
            (r"TIME OF SHIPMENT", 2),
            (r"PORT OF LOADING", 2)
        ]
    }
    
    # 各フォーマットの一致スコアを計算
    format_scores = {}
    for format_name, features in format_features.items():
        score = 0
        for pattern, weight in features:
            if re.search(pattern, ocr_text, re.IGNORECASE):
                score += weight
        format_scores[format_name] = score
    
    # 最も高いスコアのフォーマットを選択
    if all(score == 0 for score in format_scores.values()):
        # すべてのスコアが0の場合、フォーマット不明
        return "unknown", 0.0
    
    # 合計スコアを計算して信頼度を算出
    best_format = max(format_scores, key=format_scores.get)
    total_possible_score = sum(weight for _, weight in format_features[best_format])
    confidence = format_scores[best_format] / total_possible_score if total_possible_score > 0 else 0
    
    logger.info(f"識別したPOフォーマット: {best_format}, 信頼度: {confidence:.2f}, スコア: {format_scores}")
    return best_format, confidence

def extract_field_by_regex(ocr_text: str, patterns: List[str], default_value: str = "") -> str:
    """
    正規表現パターンリストを使用して、最初にマッチするフィールド値を抽出します
    
    :param ocr_text: OCRで抽出したテキスト
    :param patterns: 正規表現パターンのリスト
    :param default_value: デフォルト値
    :return: 抽出された値または空文字列
    """
    if not ocr_text:
        return default_value

    for pattern in patterns:
        try:
            match = re.search(pattern, ocr_text, re.IGNORECASE | re.MULTILINE)
            if match and match.group(1).strip():
                value = match.group(1).strip()
                # 余計な記号を削除
                value = re.sub(r'^[:\s]+|[:\s]+$', '', value)
                return value
        except Exception as e:
            logger.warning(f"正規表現マッチング中にエラー発生: {pattern}, エラー: {e}")
    
    return default_value

# extract_format1_data, extract_format2_data, extract_format3_data, 
# extract_generic_dataの関数は前回のコードと同様

def sanitize_numeric_value(value: str) -> str:
    """
    数値文字列をサニタイズし、カンマや不要な文字を除去
    
    :param value: 元の文字列値
    :return: サニタイズされた数値文字列
    """
    if not value:
        return ""
    
    try:
        # カンマと不要な文字を削除し、小数点以下の桁数を制限
        sanitized = re.sub(r'[^\d.]', '', value)
        # 小数点以下2桁に制限
        parts = sanitized.split('.')
        if len(parts) > 1:
            return f"{parts[0]}.{parts[1][:2]}"
        return sanitized
    except Exception as e:
        logger.warning(f"数値サニタイズ中にエラー: {value}, エラー: {e}")
        return ""

def extract_po_data(ocr_text: str) -> Dict[str, Any]:
    """
    OCRテキストから最適なPOデータ抽出方法を選択
    
    :param ocr_text: OCRで抽出したテキスト
    :return: 構造化されたPOデータ
    """
    if not ocr_text:
        logger.warning("空のOCRテキスト")
        return {}

    try:
        # フォーマット識別
        format_type, confidence = identify_po_format(ocr_text)
        
        # フォーマットに応じた抽出処理
        if format_type == "format1":
            result = extract_format1_data(ocr_text)
        elif format_type == "format2":
            result = extract_format2_data(ocr_text)
        elif format_type == "format3":
            result = extract_format3_data(ocr_text)
        else:
            # フォーマット不明の場合は汎用抽出
            result = extract_generic_data(ocr_text)
        
        # 数値のサニタイズ
        if result.get('products'):
            for product in result['products']:
                product['quantity'] = sanitize_numeric_value(product.get('quantity', ''))
                product['unitPrice'] = sanitize_numeric_value(product.get('unitPrice', ''))
                product['amount'] = sanitize_numeric_value(product.get('amount', ''))
        
        result['totalAmount'] = sanitize_numeric_value(result.get('totalAmount', ''))
        
        # 信頼度情報の追加
        result['formatType'] = format_type
        result['extractionConfidence'] = confidence
        
        return result
    
    except Exception as e:
        logger.error(f"PO情報抽出中に予期せぬエラー: {e}")
        return {}

# 外部から呼び出される主要な関数
__all__ = [
    'identify_po_format', 
    'extract_field_by_regex', 
    'extract_po_data',
    'extract_format1_data',
    'extract_format2_data', 
    'extract_format3_data', 
    'extract_generic_data'
]
