import re
import logging
from typing import Dict, List, Any, Tuple, Optional
import os
from datetime import datetime

# ロギング設定
logging.basicConfig(level=logging.INFO)  # DEBUGからINFOに変更
logger = logging.getLogger(__name__)

def identify_po_format(text: str) -> str:
    """
    POフォーマットを自動判別する
    
    Args:
        text: OCRで抽出されたテキスト
        
    Returns:
        str: "format1", "format2", "format3", または "generic"
    """
    logger.debug("POフォーマット判別開始")
    
    # スコアリング初期化
    scores = {
        "format1": 0,
        "format2": 0,
        "format3": 0
    }
    
    # フォーマット1の特徴: 左上に(Buyer's Info)と記載
    if re.search(r"buyer['']?s\s+info", text.lower()):
        scores["format1"] += 10
    
    # フォーマット2の特徴: 一番上の行にPurchase Orderと記載
    first_lines = text.split('\n')[:5]  # 最初の5行を取得
    for line in first_lines:
        if re.search(r"purchase\s+order", line.lower()):
            scores["format2"] += 10
    
    # フォーマット3の特徴: ファイル内に///ORDER CONFIMATION ///と記載
    if re.search(r"///\s*order\s+conf[i]?[r]?mation\s*///", text.lower()):
        scores["format3"] += 10
    
    # 最も高いスコアのフォーマットを選択
    format_type = max(scores, key=scores.get)
    
    # 十分な信頼度があるかチェック (閾値: 5)
    if scores[format_type] < 5:
        format_type = "generic"
    
    logger.debug(f"POフォーマット判別結果: {format_type}, スコア: {scores}")
    return format_type

def extract_format1_data(text: str) -> Dict[str, Any]:
    """
    フォーマット1（Buyer's Info形式）の発注書データを抽出
    
    Args:
        text: OCRで抽出されたテキスト
        
    Returns:
        Dict: 抽出されたPOデータ
    """
    logger.debug("フォーマット1の抽出開始")
    
    result = {
        "customer_name": "",  # customerからcustomer_nameに変更
        "po_number": "",
        "currency": "",
        "products": [],  # itemsからproductsに変更
        "payment_terms": "",
        "destination": ""
    }
    
    # 顧客名の抽出（Buyer's Infoセクションの下）
    buyer_match = re.search(r"buyer['']?s\s+info.*?\n(.*?)\n", text, re.IGNORECASE | re.DOTALL)
    if buyer_match:
        result["customer_name"] = buyer_match.group(1).strip()
    
    # PO番号の抽出
    po_match = re.search(r"p\.?o\.?\s*no\.?[\s:#]*([\w\d\-]+)", text, re.IGNORECASE)
    if po_match:
        result["po_number"] = po_match.group(1).strip()
    
    # 通貨の抽出
    currency_match = re.search(r"currency[\s:]*(\w{3})", text, re.IGNORECASE)
    if currency_match:
        result["currency"] = currency_match.group(1).strip()
    
    # 支払い条件の抽出
    payment_match = re.search(r"payment\s+terms?[\s:]*(.+?)(?:\n|$)", text, re.IGNORECASE)
    if payment_match:
        result["payment_terms"] = payment_match.group(1).strip()
    
    # 仕向地の抽出
    dest_match = re.search(r"destination[\s:]*(.+?)(?:\n|$)", text, re.IGNORECASE)
    if dest_match:
        result["destination"] = dest_match.group(1).strip()
    
    # 商品情報の抽出（表形式を想定）
    items_section = re.search(r"item.*?description.*?qty.*?price.*?amount(.*?)total", text, re.IGNORECASE | re.DOTALL)
    if items_section:
        items_text = items_section.group(1).strip()
        item_lines = [line.strip() for line in items_text.split('\n') if line.strip()]
        
        for line in item_lines:
            # 行から項目を抽出（スペースまたはタブで分割）
            parts = re.split(r'\s{2,}|\t', line)
            if len(parts) >= 4:  # 少なくとも品番、説明、数量、単価が必要
                item = {
                    "product_name": parts[1] if len(parts) > 1 else "",  # nameからproduct_nameに変更
                    "quantity": _extract_number(parts[2]) if len(parts) > 2 else 0,
                    "unit_price": _extract_number(parts[3]) if len(parts) > 3 else 0,
                    "subtotal": _extract_number(parts[4]) if len(parts) > 4 else 0  # amountからsubtotalに変更
                }
                result["products"].append(item)
    
    logger.debug(f"フォーマット1の抽出結果: {result}")
    return result

def extract_format2_data(text: str) -> Dict[str, Any]:
    """
    フォーマット2（Purchase Order形式）の発注書データを抽出
    
    Args:
        text: OCRで抽出されたテキスト
        
    Returns:
        Dict: 抽出されたPOデータ
    """
    logger.debug("フォーマット2の抽出開始")
    
    result = {
        "customer_name": "",  # customerからcustomer_nameに変更
        "po_number": "",
        "currency": "",
        "products": [],  # itemsからproductsに変更
        "payment_terms": "",
        "destination": ""
    }
    
    # 顧客名の抽出（通常はヘッダーに記載）
    lines = text.split('\n')
    for i, line in enumerate(lines[:10]):  # 最初の10行を検索
        if "purchase order" in line.lower():
            if i + 1 < len(lines) and lines[i + 1].strip():
                result["customer_name"] = lines[i + 1].strip()
                break
    
    # PO番号の抽出
    po_match = re.search(r"(?:p\.?o\.?\s*(?:number|no\.?)|order\s+number)[\s:#]*(\w+[-\s]?\w+)", text, re.IGNORECASE)
    if po_match:
        result["po_number"] = po_match.group(1).strip()
    
    # 通貨の抽出
    currency_match = re.search(r"(?:currency|cur)[\s:]*(\w{3})", text, re.IGNORECASE)
    if currency_match:
        result["currency"] = currency_match.group(1).strip()
    
    # 支払い条件の抽出
    payment_match = re.search(r"(?:payment\s+terms?|term)[\s:]*(.+?)(?:\n|$)", text, re.IGNORECASE)
    if payment_match:
        result["payment_terms"] = payment_match.group(1).strip()
    
    # 仕向地の抽出
    dest_match = re.search(r"(?:destination|ship\s+to|delivery\s+to)[\s:]*(.+?)(?:\n|$)", text, re.IGNORECASE)
    if dest_match:
        result["destination"] = dest_match.group(1).strip()
    
    # 商品情報の抽出
    items_section = re.search(r"(?:item.*?description|product.*?description).*?(?:qty|quantity).*?(?:unit.*?price|price).*?(?:amount|total)(.*?)(?:total|grand\s+total)", text, re.IGNORECASE | re.DOTALL)
    if items_section:
        items_text = items_section.group(1).strip()
        item_lines = [line.strip() for line in items_text.split('\n') if line.strip()]
        
        for line in item_lines:
            # 行から項目を抽出
            parts = re.split(r'\s{2,}|\t', line)
            if len(parts) >= 3:  # 少なくとも説明、数量、単価が必要
                item = {
                    "product_name": parts[0] if len(parts) > 0 else "",  # nameからproduct_nameに変更
                    "quantity": _extract_number(parts[1]) if len(parts) > 1 else 0,
                    "unit_price": _extract_number(parts[2]) if len(parts) > 2 else 0,
                    "subtotal": _extract_number(parts[3]) if len(parts) > 3 else 0  # amountからsubtotalに変更
                }
                result["products"].append(item)
    
    logger.debug(f"フォーマット2の抽出結果: {result}")
    return result

def extract_format3_data(text: str) -> Dict[str, Any]:
    """
    フォーマット3（ORDER CONFIRMATION形式）の発注書データを抽出
    
    Args:
        text: OCRで抽出されたテキスト
        
    Returns:
        Dict: 抽出されたPOデータ
    """
    logger.debug("フォーマット3の抽出開始")
    
    result = {
        "customer_name": "",  # customerからcustomer_nameに変更
        "po_number": "",
        "currency": "",
        "products": [],  # itemsからproductsに変更
        "payment_terms": "",
        "destination": ""
    }
    
    # 顧客名の抽出
    customer_match = re.search(r"(?:customer|client|buyer)[\s:]*(.+?)(?:\n|$)", text, re.IGNORECASE)
    if customer_match:
        result["customer_name"] = customer_match.group(1).strip()
    
    # PO番号の抽出
    po_match = re.search(r"(?:p\.?o\.?\s*(?:number|no\.?)|reference\s+no\.?|order\s+no\.?)[\s:#]*(\w+[-\s]?\w+)", text, re.IGNORECASE)
    if po_match:
        result["po_number"] = po_match.group(1).strip()
    
    # 通貨の抽出
    currency_match = re.search(r"(?:currency|cur|in)[\s:]*(\w{3})", text, re.IGNORECASE)
    if currency_match:
        result["currency"] = currency_match.group(1).strip()
    
    # 支払い条件の抽出
    payment_match = re.search(r"(?:payment\s+terms?|payment\s+condition|terms)[\s:]*(.+?)(?:\n|$)", text, re.IGNORECASE)
    if payment_match:
        result["payment_terms"] = payment_match.group(1).strip()
    
    # 仕向地の抽出
    dest_match = re.search(r"(?:destination|ship\s+to|delivery\s+to|delivery\s+address)[\s:]*(.+?)(?:\n|$)", text, re.IGNORECASE)
    if dest_match:
        result["destination"] = dest_match.group(1).strip()
    
    # 商品情報の抽出
    items_pattern = r"(?:item.*?description|product.*?name).*?(?:qty|quantity).*?(?:unit.*?price|price).*?(?:amount|subtotal)(.*?)(?:total|grand\s+total)"
    items_section = re.search(items_pattern, text, re.IGNORECASE | re.DOTALL)
    
    if not items_section:
        # 代替パターンを試す
        items_pattern = r"(?:order\s+details|ordered\s+items).*?(.*?)(?:total|grand\s+total)"
        items_section = re.search(items_pattern, text, re.IGNORECASE | re.DOTALL)
    
    if items_section:
        items_text = items_section.group(1).strip()
        item_lines = [line.strip() for line in items_text.split('\n') if line.strip()]
        
        for line in item_lines:
            # 行から項目を抽出
            parts = re.split(r'\s{2,}|\t', line)
            if len(parts) >= 3:  # 少なくとも説明、数量、単価が必要
                item = {
                    "product_name": parts[0] if len(parts) > 0 else "",  # nameからproduct_nameに変更
                    "quantity": _extract_number(parts[1]) if len(parts) > 1 else 0,
                    "unit_price": _extract_number(parts[2]) if len(parts) > 2 else 0,
                    "subtotal": _extract_number(parts[3]) if len(parts) > 3 else 0  # amountからsubtotalに変更
                }
                result["products"].append(item)
    
    logger.debug(f"フォーマット3の抽出結果: {result}")
    return result

def extract_generic_data(text: str) -> Dict[str, Any]:
    """
    汎用的な方法で発注書データを抽出
    
    Args:
        text: OCRで抽出されたテキスト
        
    Returns:
        Dict: 抽出されたPOデータ
    """
    logger.debug("汎用フォーマットの抽出開始")
    
    result = {
        "customer_name": "",  # customerからcustomer_nameに変更
        "po_number": "",
        "currency": "",
        "products": [],  # itemsからproductsに変更
        "payment_terms": "",
        "destination": ""
    }
    
    # PO番号の抽出 (複数のパターンを試す)
    po_patterns = [
        r"p\.?o\.?\s*(?:number|no\.?)[\s:#]*(\w+[-\s]?\w+)",
        r"order\s+(?:number|no\.?)[\s:#]*(\w+[-\s]?\w+)",
        r"reference\s+(?:number|no\.?)[\s:#]*(\w+[-\s]?\w+)",
        r"(?<=\n|\s)po[:#\s]*(\w+[-\s]?\w+)",
        r"(?<=\n|\s)no[:#\s]*(\w+[-\s]?\w+)",
    ]
    
    for pattern in po_patterns:
        po_match = re.search(pattern, text, re.IGNORECASE)
        if po_match:
            result["po_number"] = po_match.group(1).strip()
            break
    
    # 顧客名の抽出 (複数のパターンを試す)
    customer_patterns = [
        r"(?:customer|client|buyer|to)[\s:]*(.+?)(?:\n|$)",
        r"(?:bill\s+to|sold\s+to)[\s:]*(.+?)(?:\n|$)",
        r"(?:company|organization)[\s:]*(.+?)(?:\n|$)"
    ]
    
    for pattern in customer_patterns:
        customer_match = re.search(pattern, text, re.IGNORECASE)
        if customer_match:
            result["customer_name"] = customer_match.group(1).strip()
            break
    
    # 通貨の抽出
    currency_patterns = [
        r"(?:currency|cur)[\s:]*(\w{3})",
        r"(?:amount|total)\s+in\s+(\w{3})",
        r"(?:USD|EUR|JPY|GBP|CNY)"
    ]
    
    for pattern in currency_patterns:
        currency_match = re.search(pattern, text, re.IGNORECASE)
        if currency_match:
            result["currency"] = currency_match.group(1).strip() if pattern != r"(?:USD|EUR|JPY|GBP|CNY)" else currency_match.group(0)
            break
    
    # 支払い条件の抽出
    payment_patterns = [
        r"(?:payment\s+terms?|payment\s+condition)[\s:]*(.+?)(?:\n|$)",
        r"(?:terms\s+of\s+payment)[\s:]*(.+?)(?:\n|$)",
        r"(?:payment)[\s:]*(.+?)(?:\n|$)"
    ]
    
    for pattern in payment_patterns:
        payment_match = re.search(pattern, text, re.IGNORECASE)
        if payment_match:
            result["payment_terms"] = payment_match.group(1).strip()
            break
    
    # 仕向地の抽出
    dest_patterns = [
        r"(?:destination|ship\s+to|delivery\s+to)[\s:]*(.+?)(?:\n|$)",
        r"(?:shipping\s+address|delivery\s+address)[\s:]*(.+?)(?:\n|$)",
        r"(?:ship|deliver)[\s:]*(?:to)[\s:]*(.+?)(?:\n|$)"
    ]
    
    for pattern in dest_patterns:
        dest_match = re.search(pattern, text, re.IGNORECASE)
        if dest_match:
            result["destination"] = dest_match.group(1).strip()
            break
    
    # 商品情報の抽出（多様なパターンに対応）
    try:
        # 数字とテキストが混在する行を抽出
        lines = text.split('\n')
        potential_items = []
        
        for line in lines:
            # 数値が2つ以上ある行を商品行の候補とする
            numbers = re.findall(r'\d+(?:\.\d+)?', line)
            if len(numbers) >= 2 and len(line.split()) >= 3:
                potential_items.append(line)
        
        # 隣接する候補行をグループ化
        item_groups = []
        current_group = []
        
        for i, line in enumerate(lines):
            if line in potential_items:
                current_group.append(line)
            elif current_group and i < len(lines) - 1 and lines[i + 1] in potential_items:
                # 空行を1つ許容
                continue
            elif current_group:
                item_groups.append(current_group)
                current_group = []
        
        if current_group:
            item_groups.append(current_group)
        
        # 最大のグループを商品テーブルと見なす
        if item_groups:
            largest_group = max(item_groups, key=len)
            
            for line in largest_group:
                parts = re.split(r'\s{2,}|\t', line)
                # 数値を含む部分を抽出
                quantity = unit_price = subtotal = 0  # amountからsubtotalに変更
                product_name = ""  # nameからproduct_nameに変更
                
                # 商品名は最初の部分と仮定
                if parts:
                    product_name = parts[0]
                
                # 数値を探して割り当て
                numbers = [_extract_number(part) for part in parts]
                numbers = [n for n in numbers if n > 0]
                
                if len(numbers) >= 3:
                    # 通常は「数量、単価、金額」の順
                    quantity, unit_price, subtotal = numbers[:3]
                elif len(numbers) == 2:
                    # 2つしかない場合は「数量、単価」と仮定
                    quantity, unit_price = numbers
                    subtotal = quantity * unit_price
                
                if quantity > 0:  # 数量が抽出できた場合のみ追加
                    item = {
                        "product_name": product_name,  # nameからproduct_nameに変更
                        "quantity": quantity,
                        "unit_price": unit_price,
                        "subtotal": subtotal  # amountからsubtotalに変更
                    }
                    result["products"].append(item)
    except Exception as e:
        logger.error(f"商品情報の抽出中にエラー発生: {str(e)}")
    
    logger.debug(f"汎用フォーマットの抽出結果: {result}")
    return result

def validate_and_clean_result(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    抽出結果を検証してクリーニング
    
    Args:
        data: 抽出されたPOデータ
        
    Returns:
        Dict: クリーニング済みのPOデータ
    """
    logger.debug("抽出結果の検証とクリーニング開始")
    
    cleaned = data.copy()
    
    # 文字列フィールドのクリーニング
    string_fields = ["customer_name", "po_number", "currency", "payment_terms", "destination"]  # customerからcustomer_nameに変更
    for field in string_fields:
        if field in cleaned and cleaned[field]:
            # 余分な空白、タブ、改行を削除
            cleaned[field] = re.sub(r'\s+', ' ', cleaned[field]).strip()
            
            # 不要な記号を削除（コロン、カンマなど）
            if field == "po_number":
                cleaned[field] = re.sub(r'^[:;,.\s]+|[:;,.\s]+$', '', cleaned[field])
    
    # 数値の検証
    if "products" in cleaned and cleaned["products"]:  # itemsからproductsに変更
        for i, item in enumerate(cleaned["products"]):  # itemsからproductsに変更
            # 数量が0または非常に大きい場合は修正
            if "quantity" in item:
                if item["quantity"] <= 0 or item["quantity"] > 10000:
                    # 商品名から数量を探す試み
                    if "product_name" in item and item["product_name"]:  # nameからproduct_nameに変更
                        qty_match = re.search(r'(\d+(?:\.\d+)?)\s*(?:pcs|pieces|units|qty)', item["product_name"], re.IGNORECASE)
                        if qty_match:
                            try:
                                cleaned["products"][i]["quantity"] = float(qty_match.group(1))
                                # 抽出した部分を商品名から削除
                                cleaned["products"][i]["product_name"] = re.sub(r'\s*\d+(?:\.\d+)?\s*(?:pcs|pieces|units|qty)', '', item["product_name"], flags=re.IGNORECASE)
                            except (ValueError, TypeError):
                                pass
            
            # 単価と金額の計算確認
            if "quantity" in item and "unit_price" in item and "subtotal" in item:  # amountからsubtotalに変更
                if item["subtotal"] <= 0 and item["quantity"] > 0 and item["unit_price"] > 0:  # amountからsubtotalに変更
                    # 金額を計算
                    cleaned["products"][i]["subtotal"] = round(item["quantity"] * item["unit_price"], 2)  # amountからsubtotalに変更
                elif item["unit_price"] <= 0 and item["quantity"] > 0 and item["subtotal"] > 0:  # amountからsubtotalに変更
                    # 単価を計算
                    cleaned["products"][i]["unit_price"] = round(item["subtotal"] / item["quantity"], 2)  # amountからsubtotalに変更
    
    # 通貨が検出されなかった場合のデフォルト設定
    if not cleaned.get("currency"):
        # 金額から通貨を推測
        if cleaned.get("products") and any(item.get("subtotal") > 0 for item in cleaned["products"]):  # itemsからproducts、amountからsubtotalに変更
            # 金額の範囲で予測
            amounts = [item.get("subtotal") for item in cleaned["products"] if item.get("subtotal") > 0]  # itemsからproducts、amountからsubtotalに変更
            if amounts:
                avg_amount = sum(amounts) / len(amounts)
                if avg_amount < 10:  # 非常に小さい金額
                    cleaned["currency"] = "JPY"  # 仮定
                elif avg_amount < 1000:
                    cleaned["currency"] = "USD"  # 仮定
                else:
                    cleaned["currency"] = "JPY"  # 仮定
    
    logger.debug(f"抽出結果のクリーニング完了: {cleaned}")
    return cleaned

def analyze_extraction_quality(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    抽出結果の品質を分析
    
    Args:
        data: 抽出されたPOデータ
        
    Returns:
        Dict: 品質分析結果
    """
    logger.debug("抽出品質の分析開始")
    
    quality = {
        "completeness": 0,
        "missing_fields": [],
        "confidence": {
            "customer_name": 0,  # customerからcustomer_nameに変更
            "po_number": 0,
            "currency": 0,
            "products": 0,  # itemsからproductsに変更
            "payment_terms": 0,
            "destination": 0
        },
        "suggestions": []
    }
    
    # 必須フィールドの存在チェック
    required_fields = ["customer_name", "po_number"]  # customerからcustomer_nameに変更
    recommended_fields = ["currency", "payment_terms", "destination"]
    
    # 必須フィールドの完全性チェック
    missing_required = [field for field in required_fields if not data.get(field)]
    missing_recommended = [field for field in recommended_fields if not data.get(field)]
    
    quality["missing_fields"] = missing_required + missing_recommended
    
    # 商品情報のチェック
    products = data.get("products", [])  # itemsからproductsに変更
    if not products:
        quality["missing_fields"].append("products")  # itemsからproductsに変更
    else:
        # 商品情報の完全性チェック
        incomplete_items = []
        for i, item in enumerate(products):
            if not all(key in item and item[key] for key in ["product_name", "quantity", "unit_price"]):  # nameからproduct_nameに変更
                incomplete_items.append(i)
        
        if incomplete_items:
            quality["suggestions"].append(f"商品 {', '.join(map(str, incomplete_items))} の情報が不完全です")
    
    # 完全性スコアの計算
    total_fields = len(required_fields) + len(recommended_fields) + (1 if products else 0)  # itemsからproductsに変更
    present_fields = (
        len(required_fields) - len([f for f in missing_required]) +
        len(recommended_fields) - len([f for f in missing_recommended]) +
        (1 if products and not "products" in quality["missing_fields"] else 0)  # itemsからproductsに変更
    )
    
    quality["completeness"] = round((present_fields / total_fields) * 100) if total_fields > 0 else 0
    
    # 各フィールドの信頼度評価
    for field in required_fields + recommended_fields:
        if field in data and data[field]:
            # 長さと内容に基づく基本的な信頼度評価
            value = data[field]
            if isinstance(value, str):
                # 長すぎる/短すぎる値は信頼度が低い
                if len(value) > 100 or len(value) < 2:
                    quality["confidence"][field] = 30
                # 標準的な長さは信頼度が高い
                elif 3 <= len(value) <= 50:
                    quality["confidence"][field] = 90
                else:
                    quality["confidence"][field] = 70
            else:
                quality["confidence"][field] = 80
    
    # 商品情報の信頼度評価
    if products:  # itemsからproductsに変更
        valid_items = len([item for item in products if all(key in item and item[key] for key in ["product_name", "quantity", "unit_price"])])  # nameからproduct_name
        quality["confidence"]["products"] = round((valid_items / len(products)) * 100) if products else 0  # itemsからproductsに変更
    
    # 改善提案の追加
    if missing_required:
        quality["suggestions"].append(f"必須フィールド {', '.join(missing_required)} が欠落しています")
    
    if missing_recommended:
        quality["suggestions"].append(f"推奨フィールド {', '.join(missing_recommended)} が欠落しています")
    
    if quality["completeness"] < 60:
        quality["suggestions"].append("抽出品質が低いため、手動での確認が必要です")
    
    logger.debug(f"抽出品質の分析結果: {quality}")
    return quality

def get_extraction_stats(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    抽出結果の統計情報を取得
    
    Args:
        data: 抽出されたPOデータ
        
    Returns:
        Dict: 統計情報
    """
    logger.debug("抽出統計情報の計算開始")
    
    stats = {
        "extracted_fields_count": 0,
        "items_count": 0,
        "total_amount": 0,
        "extraction_timestamp": None
    }
    
    # 抽出されたフィールド数をカウント
    for field in ["customer_name", "po_number", "currency", "payment_terms", "destination"]:  # customerからcustomer_nameに変更
        if field in data and data[field]:
            stats["extracted_fields_count"] += 1
    
    # 商品数と合計金額の計算
    products = data.get("products", [])  # itemsからproductsに変更
    stats["items_count"] = len(products)
    
    if products:
        stats["total_amount"] = sum(item.get("subtotal", 0) for item in products)  # amountからsubtotalに変更
    
    # タイムスタンプの設定
    stats["extraction_timestamp"] = datetime.now().isoformat()
    
    logger.debug(f"抽出統計情報: {stats}")
    return stats

def _extract_number(text: str) -> float:
    """
    テキストから数値を抽出する補助関数
    
    Args:
        text: 数値を含む可能性のあるテキスト
        
    Returns:
        float: 抽出された数値、抽出できない場合は0
    """
    if not text:
        return 0
    
    # 様々な数値フォーマットに対応
    # 1,234.56や1.234,56などの形式に対応
    text = str(text).strip()
    
    # カンマとピリオドの位置を確認
    comma_pos = text.rfind(',')
    period_pos = text.rfind('.')
    
    # 正規化された数値テキスト
    normalized_text = text
    
    # カンマとピリオドの扱いを決定
    if comma_pos > 0 and period_pos > 0:
        # 両方存在する場合、位置で判断
        if comma_pos > period_pos:
            # 1.234,56 形式 -> 1234.56
            normalized_text = text.replace('.', '').replace(',', '.')
        else:
            # 1,234.56 形式 -> そのまま、カンマだけ除去
            normalized_text = text.replace(',', '')
    elif comma_pos > 0:
        # カンマのみの場合
        if comma_pos == len(text) - 3:  # 最後から3番目がカンマなら小数点と見なす
            # 1234,56 -> 1234.56
            normalized_text = text.replace(',', '.')
        else:
            # 1,234 -> 1234
            normalized_text = text.replace(',', '')
    # ピリオドのみの場合はそのまま
    
    # 数値以外の文字を除去
    normalized_text = re.sub(r'[^\d.]', '', normalized_text)
    
    try:
        return float(normalized_text) if normalized_text else 0
    except (ValueError, TypeError):
        return 0
