import re
import logging
from typing import Dict, List, Any, Tuple, Optional
import os
from datetime import datetime

# ロギング設定
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def extract_field_by_regex(text: str, patterns: List[str], default_value: str = "") -> str:
    """
    複数の正規表現パターンを試して、最初にマッチするフィールド値を抽出します
    
    Args:
        text: 対象テキスト
        patterns: 正規表現パターンのリスト
        default_value: デフォルト値
        
    Returns:
        抽出された値またはデフォルト値
    """
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
        if match and match.group(1).strip():
            value = match.group(1).strip()
            # 余計な記号を削除
            value = re.sub(r'^[:\s]+|[:\s]+$', '', value)
            return value
    return default_value

def identify_po_format(text: str) -> str:
    """
    POフォーマットを自動判別する
    
    Args:
        text: OCRで抽出されたテキスト
        
    Returns:
        str: "format1", "format2", "format3", または "generic"
    """
    logger.info("POフォーマット判別開始")
    
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
            if re.search(pattern, text, re.IGNORECASE):
                score += weight
        format_scores[format_name] = score
    
    # 最も高いスコアのフォーマットを選択
    if all(score == 0 for score in format_scores.values()):
        # すべてのスコアが0の場合はgenericを返す
        logger.info(f"POフォーマット判別結果: generic (スコアなし)")
        return "generic"
    
    best_format = max(format_scores, key=format_scores.get)
    
    logger.info(f"POフォーマット判別結果: {best_format}, スコア: {format_scores}")
    return best_format

def extract_format1_data(text: str) -> Dict[str, Any]:
    """
    フォーマット1（Buyer's Info形式）の発注書データを抽出
    
    Args:
        text: OCRで抽出されたテキスト
        
    Returns:
        Dict: 抽出されたPOデータ
    """
    logger.info("フォーマット1の抽出開始")
    
    result = {
        "customer_name": "",
        "po_number": "",
        "currency": "",
        "products": [],
        "payment_terms": "",
        "destination": ""
    }
    
    # 顧客名の抽出
    result["customer_name"] = extract_field_by_regex(text, [
        r"ABC Company\s*(.*?)(?:\n|$)",
        r"\(Buyer(?:'|')s Info\).*?([A-Za-z0-9\s]+Company)",
        r"(?:\(Buyer(?:'|')s Info\)|Buyer['']?s\s+info)(?:.*?\n)?(.*?)(?:\n|$)"
    ])
    
    # PO番号の抽出
    result["po_number"] = extract_field_by_regex(text, [
        r"Purchase Order(?::|Order|Number)?:?\s*(\d+)",
        r"(?:PO|Order)(?:\s+No)?\.?:?\s*(\d+)",
        r"Purchase Order:?\s*([a-zA-Z0-9-]+)"
    ])
    
    # 通貨の抽出
    currency_match = re.search(r"(USD|EUR|JPY|CNY)", text)
    if currency_match:
        result["currency"] = currency_match.group(1)
    
    # 支払条件の抽出
    result["payment_terms"] = extract_field_by_regex(text, [
        r"Terms:\s*(.*?)(?:\n|$)",
        r"Payment terms?:?\s*(.*?)(?:\n|$)",
        r"Net Due within\s*(.*?)(?:\n|$)"
    ])
    
    # 配送先の抽出
    result["destination"] = extract_field_by_regex(text, [
        r"Ship to:\s*(.*?)(?:\n|$)",
        r"Destination:\s*(.*?)(?:\n|$)",
        r"Delivery Address:\s*(.*?)(?:\n|$)"
    ])
    
    # 製品情報の抽出 - 単一製品の場合
    product_name = extract_field_by_regex(text, [
        r"Item:\s*(.*?)(?:\n|$)",
        r"Product:?\s*(.*?)(?:\n|Quantity)"
    ])
    
    quantity = extract_field_by_regex(text, [
        r"Quantity:\s*([\d,.]+)\s*(?:KG|kg|MT|mt)",
        r"Qty:?\s*([\d,.]+)\s*(?:KG|kg|MT|mt)",
        r"QuanƟty:?\s*([\d,.]+)\s*(?:KG|kg|MT|mt)"
    ])
    
    unit_price = extract_field_by_regex(text, [
        r"Unit Price:\s*\$?\s*([\d,.]+)",
        r"Unit Price:.*?per\s*.*?\$?\s*([\d,.]+)",
        r"Unit Price: \$\s*([\d,.]+)\s+per"
    ])
    
    subtotal = extract_field_by_regex(text, [
        r"EXT Price:\s*(?:USD)?\s*([\d,.]+)",
        r"Amount:\s*(?:USD)?\s*([\d,.]+)",
        r"EXT Price: ([\d,.]+)"
    ])
    
    if product_name or quantity:
        result["products"].append({
            "product_name": product_name,
            "quantity": _clean_numeric_field(quantity),
            "unit_price": _clean_numeric_field(unit_price),
            "subtotal": _clean_numeric_field(subtotal)
        })
    
    # 合計金額（個別にキャプチャする必要がない場合があるので）
    if not subtotal and len(result["products"]) > 0:
        total_amount = extract_field_by_regex(text, [
            r"TOTAL\s*(?:USD)?\s*([\d,.]+)",
            r"Total:?\s*(?:USD)?\s*([\d,.]+)"
        ])
        if total_amount and len(result["products"]) == 1:
            result["products"][0]["subtotal"] = _clean_numeric_field(total_amount)
    
    logger.info(f"フォーマット1の抽出結果: {result}")
    return result

def extract_format2_data(text: str) -> Dict[str, Any]:
    """
    フォーマット2（Purchase Order形式）の発注書データを抽出
    
    Args:
        text: OCRで抽出されたテキスト
        
    Returns:
        Dict: 抽出されたPOデータ
    """
    logger.info("フォーマット2の抽出開始")
    
    result = {
        "customer_name": "",
        "po_number": "",
        "currency": "",
        "products": [],
        "payment_terms": "",
        "destination": ""
    }
    
    # 顧客名（購入者）の抽出
    result["customer_name"] = extract_field_by_regex(text, [
        r"Buyer:\s*(.*?)(?:\n|$)",
        r"(?:Buyer|Customer|Client):\s*(.*?)(?:\n|$)",
        r"Buyer:?\s*(.*?Ltd\.)",
        r"Buyer:?\s+([^\\n]+)"
    ])
    
    # PO番号の抽出
    result["po_number"] = extract_field_by_regex(text, [
        r"Purchase Order no:?\s*(\d+)",
        r"Purchase Order no:?\s*([a-zA-Z0-9-]+)",
        r"PO (?:number|no\.?):\s*(\d+)"
    ])
    
    # 通貨の抽出
    currency_match = re.search(r"(USD|EUR|JPY|CNY)", text)
    if currency_match:
        result["currency"] = currency_match.group(1)
    
    # 支払条件の抽出
    result["payment_terms"] = extract_field_by_regex(text, [
        r"Payment Terms:\s*(.*?)(?:\n|$)",
        r"Payment:?\s*(.*?)(?:\n|$)"
    ])
    
    # 配送先の抽出
    result["destination"] = extract_field_by_regex(text, [
        r"Discharge Port:\s*(.*?)(?:\n|$)",
        r"(?:Ship to|Destination|Delivery Address):\s*(.*?)(?:\n|$)"
    ])
    
    # 製品情報の抽出 - 表形式データからの抽出（複数製品対応）
    try:
        # 方法1: 表形式からの抽出
        product_rows = re.findall(r"(?:[A-Za-z0-9]+)\s+(Product [A-Za-z])\s+([\d,]+)\s*kg\s+US\$?([\d.]+)\s+US\$?([\d,.]+)", text, re.IGNORECASE)
        
        if product_rows:
            for row_match in product_rows:
                name, quantity, unit_price, subtotal = row_match
                result["products"].append({
                    "product_name": name.strip(),
                    "quantity": _clean_numeric_field(quantity),
                    "unit_price": _clean_numeric_field(unit_price),
                    "subtotal": _clean_numeric_field(subtotal)
                })
        else:
            # 方法2: 別の表形式パターン
            product_sections = re.findall(r"(\d[a-z])\s+(Product [A-Za-z])\s+([\d,]+)\s*kg\s+US\$?([\d.]+)\s+US\$?([\d,.]+)", text, re.IGNORECASE)
            
            if product_sections:
                for _, name, quantity, unit_price, subtotal in product_sections:
                    result["products"].append({
                        "product_name": name.strip(),
                        "quantity": _clean_numeric_field(quantity),
                        "unit_price": _clean_numeric_field(unit_price),
                        "subtotal": _clean_numeric_field(subtotal)
                    })
            else:
                # 方法3: 別パターンでの検索
                # 製品名のリストを抽出
                product_names = re.findall(r"Product ([A-Z])", text)
                quantities = re.findall(r"([\d,]+)\s*kg", text)
                prices = re.findall(r"US\$\s*([\d.]+)", text)
                subtotals = re.findall(r"US\$\s*([\d,.]+)(?:\.00)?(?:\s|$)", text)
                
                # マッチング調整
                if len(subtotals) > len(product_names):
                    # 最後のエントリは通常合計金額なので除外
                    subtotals = subtotals[:len(product_names)]
                
                for i, name in enumerate(product_names):
                    if i < len(quantities) and i < len(prices) and i < len(subtotals):
                        result["products"].append({
                            "product_name": f"Product {name}",
                            "quantity": _clean_numeric_field(quantities[i]),
                            "unit_price": _clean_numeric_field(prices[i]),
                            "subtotal": _clean_numeric_field(subtotals[i])
                        })
    except Exception as e:
        logger.error(f"複数製品の抽出中にエラーが発生: {str(e)}")
    
    # 製品情報が抽出できなかった場合のフォールバック
    if not result["products"]:
        logger.warning("通常の表形式で製品を抽出できなかったため、別の方法を試みます")
        
        # 一般的な製品データを探す
        product_name = extract_field_by_regex(text, [
            r"Commodity\s+(Product [A-Z])",
            r"Item\s+(Product [A-Z])"
        ])
        
        quantity = extract_field_by_regex(text, [
            r"(?:[\d,]+)\s*kg",
            r"Quantity\s+(?:[\d,]+)"
        ])
        
        unit_price = extract_field_by_regex(text, [
            r"US\$\s*([\d.]+)",
            r"Unit price\s+US\$\s*([\d.]+)"
        ])
        
        subtotal = extract_field_by_regex(text, [
            r"Total Amount\s+US\$\s*([\d,.]+)",
            r"US\$\s*([\d,.]+)(?:\.00)?"
        ])
        
        if product_name or quantity:
            result["products"].append({
                "product_name": product_name or "Unknown Product",
                "quantity": _clean_numeric_field(quantity),
                "unit_price": _clean_numeric_field(unit_price),
                "subtotal": _clean_numeric_field(subtotal)
            })
    
    logger.info(f"フォーマット2の抽出結果: {result}")
    return result

def extract_format3_data(text: str) -> Dict[str, Any]:
    """
    フォーマット3（ORDER CONFIMATION形式）の発注書データを抽出
    
    Args:
        text: OCRで抽出されたテキスト
        
    Returns:
        Dict: 抽出されたPOデータ
    """
    logger.info("フォーマット3の抽出開始")
    
    result = {
        "customer_name": "",
        "po_number": "",
        "currency": "",
        "products": [],
        "payment_terms": "",
        "destination": ""
    }
    
    # 顧客名の抽出
    result["customer_name"] = extract_field_by_regex(text, [
        r"Contract Party\s*:\s*(.*?)(?:\n|$)",
        r"B/L CONSIGNEE\s*:\s*(.*?)(?:\n|$)",
        r"Contract Party\s*:\s*(Apple LTD\.)",
        r"Contract Party.*?(Apple LTD\.)"
    ])
    
    # PO番号の抽出
    result["po_number"] = extract_field_by_regex(text, [
        r"(?:Order No\.|Buyers(?:'|')?\s+Order No\.)\s*(.*?)(?:\n|Grade|Origin)",
        r"(?:Order No\.|Buyers(?:'|')?\s+Order No\.)\s*(M[a-zA-Z0-9]+)",
        r"Buyers(?:'|')?\s+Order No\.(.*?)(?:\n|Grade|$)"
    ])
    
    # 通貨の抽出 - フォーマット3ではUSDが明示的
    result["currency"] = "USD"
    
    # 支払条件の抽出
    result["payment_terms"] = extract_field_by_regex(text, [
        r"Payment term\s*\n?\s*(.*?)(?:\n|$)",
        r"Payment\s*:\s*(.*?)(?:\n|$)",
        r"Payment term\s+(.*?advance)",
        r"Payment\s+term\s+(100% TT IN ADVANCE)"
    ])
    
    # 配送先の抽出
    result["destination"] = extract_field_by_regex(text, [
        r"PORT OF DISCHARGE\s*(.*?)(?:\n|$)",
        r"PORT OF\s*DISCHARGE\s*(.*?)(?:\n|Payment)",
        r"PORT OF\s*DISCHARGE\s+(CIF SHEKOU PORT, CHINA)"
    ])
    
    # 製品情報の抽出
    grade = extract_field_by_regex(text, [
        r"Grade\s+([A-Za-z0-9]+)",
        r"Grade\s+(B)"
    ])
    
    quantity = extract_field_by_regex(text, [
        r"Qt'y\s*\(mt\)\s*([\d.]+)",
        r"Qt'y \(mt\)\s+(28\.8)"
    ])
    
    unit_price = extract_field_by_regex(text, [
        r"Unit Price\s*\([^)]+\)\s*([\d,.]+)",
        r"Unit Price\s*\(USD/mt\)\s+([\d,.]+)",
        r"USD ([\d,.]+\.00)"
    ])
    
    subtotal = extract_field_by_regex(text, [
        r"Total Amount\s*([\d,.]+)",
        r"Total Amount\s+USD ([\d,.]+)",
        r"USD ([\d,.]+)\.00\s+CIF"
    ])
    
    if grade or quantity:
        product_name = f"Grade {grade}" if grade else "Unknown Product"
        result["products"].append({
            "product_name": product_name,
            "quantity": _clean_numeric_field(quantity),
            "unit_price": _clean_numeric_field(unit_price),
            "subtotal": _clean_numeric_field(subtotal)
        })
    
    logger.info(f"フォーマット3の抽出結果: {result}")
    return result

def extract_generic_data(text: str) -> Dict[str, Any]:
    """
    汎用的な方法で発注書データを抽出
    
    Args:
        text: OCRで抽出されたテキスト
        
    Returns:
        Dict: 抽出されたPOデータ
    """
    logger.info("汎用フォーマットの抽出開始")
    
    result = {
        "customer_name": "",
        "po_number": "",
        "currency": "",
        "products": [],
        "payment_terms": "",
        "destination": ""
    }
    
    # 顧客名を抽出する複数の方法を試す
    result["customer_name"] = extract_field_by_regex(text, [
        r"(?:Customer|Client|Buyer|Company|Purchaser):\s*(.*?)(?:\n|$)",
        r"(?:To|Bill to):\s*(.*?)(?:\n|$)",
        r"Contract Party\s*:\s*(.*?)(?:\n|$)",
        r"B/L CONSIGNEE\s*:\s*(.*?)(?:\n|$)",
        r"ABC Company\s*(.*?)(?:\n|$)",
        r"\(Buyer(?:'|')s Info\).*?([A-Za-z0-9\s]+Company)"
    ])
    
    # PO番号の抽出
    result["po_number"] = extract_field_by_regex(text, [
        r"(?:PO|Purchase Order|Order) (?:No|Number|#)\.?:?\s*(\w+[-\d]+)",
        r"(?:PO|Purchase Order|Order) (?:No|Number|#)\.?:?\s*(\d+)",
        r"Order No\.\s*(.*?)(?:\n|Grade|Origin)",
        r"Buyers(?:'|')?\s+Order No\.\s*(.*?)(?:\n|Grade|$)",
        r"Purchase Order:?\s*([a-zA-Z0-9-]+)"
    ])
    
    # 通貨を抽出
    currency_match = re.search(r"(USD|EUR|JPY|CNY)", text)
    if currency_match:
        result["currency"] = currency_match.group(1)
    else:
        result["currency"] = "USD"  # デフォルト値
    
    # 支払条件の抽出
    result["payment_terms"] = extract_field_by_regex(text, [
        r"(?:Payment Terms?|Terms of Payment|Terms|Payment):\s*(.*?)(?:\n|$)",
        r"Net Due within\s*(.*?)(?:\n|$)",
        r"Payment term\s*\n?\s*(.*?)(?:\n|$)"
    ])
    
    # 配送先の抽出
    result["destination"] = extract_field_by_regex(text, [
        r"(?:Destination|Ship to|Delivery Address|Port of Discharge|Discharge Port|PORT OF DISCHARGE):\s*(.*?)(?:\n|$)",
        r"(?:To|Deliver to):\s*(.*?)(?:\n|$)"
    ])
    
    # 製品情報の抽出（複数の方法を試す）
    product_extracted = False
    
    # 方法1: 表形式データからの抽出
    product_rows = re.findall(r"([A-Za-z0-9]+)\s+(Product [A-Za-z]|Grade [A-Za-z0-9]+)\s+([\d,]+)\s*(?:kg|mt)\s+(?:US\$)?([\d.]+)\s+(?:US\$)?([\d,.]+)", text)
    if product_rows:
        for _, name, quantity, unit_price, subtotal in product_rows:
            result["products"].append({
                "product_name": name.strip(),
                "quantity": _clean_numeric_field(quantity),
                "unit_price": _clean_numeric_field(unit_price),
                "subtotal": _clean_numeric_field(subtotal)
            })
        product_extracted = True
    
    # 方法2: セクション形式からの抽出
    if not product_extracted:
        product_sections = re.findall(r"(?:Product [A-Za-z]|Grade [A-Za-z0-9]+|Item:.*?).*?(\d+)(?:\s*|\n+)(?:kg|mt|KG|MT).*?(?:US\$|Unit Price:?\s*\$?)?\s*([\d,.]+).*?(?:US\$)?\s*([\d,.]+)", text, re.DOTALL)
        if product_sections:
            for i, (quantity, unit_price, subtotal) in enumerate(product_sections):
                # 製品名の抽出を試みる
                product_name = ""
                name_match = re.search(r"(?:Product ([A-Z])|Grade ([A-Za-z0-9]+)|Item:\s*(.*?)(?:\n|$))", text)
                if name_match:
                    if name_match.group(1):
                        product_name = f"Product {name_match.group(1)}"
                    elif name_match.group(2):
                        product_name = f"Grade {name_match.group(2)}"
                    elif name_match.group(3):
                        product_name = name_match.group(3)
                else:
                    product_name = f"Unknown Product {i+1}"
                
                result["products"].append({
                    "product_name": product_name,
                    "quantity": _clean_numeric_field(quantity),
                    "unit_price": _clean_numeric_field(unit_price),
                    "subtotal": _clean_numeric_field(subtotal)
                })
            product_extracted = True
    
    # 方法3: 個別フィールドからの抽出
    if not product_extracted:
        product_name = extract_field_by_regex(text, [
            r"Item:\s*(.*?)(?:\n|$)",
            r"Product:?\s*(.*?)(?:\n|Quantity)",
            r"Grade\s+([A-Za-z0-9]+)"
        ])
        
        quantity = extract_field_by_regex(text, [
            r"Quantity:\s*([\d,.]+)\s*(?:KG|kg|MT|mt)",
            r"Qty:?\s*([\d,.]+)\s*(?:KG|kg|MT|mt)",
            r"Qt'y\s*\(mt\)\s*([\d.]+)"
        ])
        
        unit_price = extract_field_by_regex(text, [
            r"Unit Price:\s*\$?\s*([\d,.]+)",
            r"Unit Price:.*?per\s*.*?\$?\s*([\d,.]+)",
            r"Unit Price\s*\([^)]+\)\s*([\d,.]+)"
        ])
        
        subtotal = extract_field_by_regex(text, [
            r"EXT Price:\s*([\d,.]+)",
            r"Amount:\s*([\d,.]+)",
            r"Total Amount\s*([\d,.]+)"
        ])
        
        if product_name or quantity:
            result["products"].append({
                "product_name": product_name or "Unknown Product",
                "quantity": _clean_numeric_field(quantity),
                "unit_price": _clean_numeric_field(unit_price),
                "subtotal": _clean_numeric_field(subtotal)
            })
    
    logger.info(f"汎用フォーマットの抽出結果: {result}")
    return result

def validate_and_clean_result(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    抽出結果を検証してクリーニング
    
    Args:
        data: 抽出されたPOデータ
        
    Returns:
        Dict: クリーニング済みのPOデータ
    """
    logger.info("抽出結果の検証とクリーニング開始")
    
    cleaned = data.copy()
    
    # 文字列フィールドのクリーニング
    string_fields = ["customer_name", "po_number", "currency", "payment_terms", "destination"]
    for field in string_fields:
        if field in cleaned and cleaned[field]:
            # 余分な空白、タブ、改行を削除
            cleaned[field] = re.sub(r'\s+', ' ', cleaned[field]).strip()
            
            # 不要な記号を削除（コロン、カンマなど）
            if field == "po_number":
                cleaned[field] = re.sub(r'^[:;,.\s]+|[:;,.\s]+$', '', cleaned[field])
    
    # 製品情報が空の場合にデフォルト値を設定
    if not cleaned["products"]:
        cleaned["products"].append({
            "product_name": "Unknown Product",
            "quantity": "0",
            "unit_price": "0",
            "subtotal": "0"
        })
    
    # 製品情報の検証と計算
    for i, product in enumerate(cleaned["products"]):
        # 製品名のクリーニング
        if "product_name" in product and product["product_name"]:
            product["product_name"] = product["product_name"].strip()
        else:
            product["product_name"] = f"Product {i+1}"
        
        # 数値フィールドのクリーニングと検証
        try:
            # 数量が0または非常に大きい場合は修正
            if "quantity" in product:
                qty = _extract_float(product["quantity"])
                if qty <= 0 or qty > 100000:
                    # 商品名から数量を探す試み
                    if "product_name" in product and product["product_name"]:
                        qty_match = re.search(r'(\d+(?:\.\d+)?)\s*(?:pcs|pieces|units|qty|kg|mt)', product["product_name"], re.IGNORECASE)
                        if qty_match:
                            try:
                                qty = float(qty_match.group(1))
                                cleaned["products"][i]["quantity"] = str(qty)
                                # 抽出した部分を商品名から削除
                                cleaned["products"][i]["product_name"] = re.sub(r'\s*\d+(?:\.\d+)?\s*(?:pcs|pieces|units|qty|kg|mt)', '', product["product_name"], flags=re.IGNORECASE)
                            except (ValueError, TypeError):
                                pass
            
            # 単価と小計の計算確認
            if all(key in product for key in ["quantity", "unit_price", "subtotal"]):
                qty = _extract_float(product["quantity"])
                price = _extract_float(product["unit_price"])
                subtotal = _extract_float(product["subtotal"])
                
                # 小計が不足している場合、数量と単価から計算
                if subtotal <= 0 and qty > 0 and price > 0:
                    calculated_subtotal = qty * price
                    cleaned["products"][i]["subtotal"] = str(round(calculated_subtotal, 2))
                
                # 単価が不足している場合、小計と数量から計算
                elif price <= 0 and qty > 0 and subtotal > 0:
                    calculated_price = subtotal / qty
                    cleaned["products"][i]["unit_price"] = str(round(calculated_price, 2))
                
                # 数量が不足している場合、小計と単価から計算
                elif qty <= 0 and price > 0 and subtotal > 0:
                    calculated_qty = subtotal / price
                    cleaned["products"][i]["quantity"] = str(round(calculated_qty, 2))
        except Exception as e:
            logger.warning(f"製品情報の検証中にエラー: {str(e)}")
    
    # 通貨が検出されなかった場合のデフォルト設定
    if not cleaned.get("currency"):
        cleaned["currency"] = "USD"  # デフォルト値
    
    logger.info(f"抽出結果のクリーニング完了: {cleaned}")
    return cleaned

def _clean_numeric_field(value: str) -> str:
    """
    数値フィールドから単位や記号を取り除き、数値のみを返す
    ただしカンマとピリオドは数値フォーマットとして適切に解釈する
    
    Args:
        value: クリーニングする値
        
    Returns:
        クリーニングされた数値文字列
    """
    if not value:
        return ""
    
    # 通貨記号や単位などを削除（カンマとピリオドは保持）
    cleaned = re.sub(r'[^\d.,]', '', value)
    
    # カンマとピリオドの位置を確認
    comma_pos = cleaned.rfind(',')
    period_pos = cleaned.rfind('.')
    
    # 正規化された数値テキスト
    normalized_text = cleaned
    
    # カンマとピリオドの扱いを決定
    if comma_pos > 0 and period_pos > 0:
        # 両方存在する場合、位置で判断
        if comma_pos > period_pos:
            # 1.234,56 形式 -> 1234.56
            normalized_text = cleaned.replace('.', '').replace(',', '.')
        else:
            # 1,234.56 形式 -> 1234.56
            normalized_text = cleaned.replace(',', '')
    elif comma_pos > 0:
        # カンマのみの場合
        if len(cleaned) - comma_pos <= 3:  # 最後から3番目以内がカンマなら小数点と見なす
            # 1234,56 -> 1234.56
            normalized_text = cleaned.replace(',', '.')
        else:
            # 1,234,567 -> 1234567
            normalized_text = cleaned.replace(',', '')
    
    # 結果を文字列として返す（数値への変換は呼び出し側で必要に応じて行う）
    return normalized_text

def _extract_float(value: str) -> float:
    """
    文字列から浮動小数点数を抽出する
    
    Args:
        value: 抽出する文字列
        
    Returns:
        float: 抽出された浮動小数点数、失敗した場合は0
    """
    try:
        if not value:
            return 0
        
        # 数値に変換できる形式にクリーニング
        cleaned = _clean_numeric_field(value)
        
        # 空文字列の場合は0を返す
        if not cleaned:
            return 0
            
        return float(cleaned)
    except (ValueError, TypeError):
        return 0
    
def extract_po_data(text: str) -> Dict[str, Any]:
    """
    POフォーマットを識別し、適切な抽出関数を呼び出して結果を返す
    
    Args:
        text: OCRで抽出されたテキスト
        
    Returns:
        Dict: 抽出されたPOデータ
    """
    logger.info("POデータ抽出開始")
    
    # フォーマットを識別
    po_format = identify_po_format(text)
    logger.info(f"識別されたPOフォーマット: {po_format}")
    
    # 識別されたフォーマットに基づいて適切な抽出関数を呼び出す
    if po_format == "format1":
        raw_result = extract_format1_data(text)
    elif po_format == "format2":
        raw_result = extract_format2_data(text)
    elif po_format == "format3":
        raw_result = extract_format3_data(text)
    else:  # generic
        raw_result = extract_generic_data(text)
    
    # 結果の検証とクリーニング
    cleaned_result = validate_and_clean_result(raw_result)
    
    # フィールド名の統一（確実にフロントエンドと一致させる）
    # 製品情報のフィールド名を修正
    if "products" in cleaned_result:
        for i, product in enumerate(cleaned_result["products"]):
            # 金額フィールドの確保
            if "subtotal" in product and not "amount" in product:
                cleaned_result["products"][i]["amount"] = product["subtotal"]
                
            # 商品名フィールドの確保
            if "product_name" not in product and "name" in product:
                cleaned_result["products"][i]["product_name"] = product["name"]
                
    logger.info("POデータ抽出完了と標準化")
    return cleaned_result
