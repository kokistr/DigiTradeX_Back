"""
OCR抽出ロジックを実装するモジュール
"""
import re
import logging
from typing import Dict, List, Any, Optional

# ロギングの設定
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def identify_po_format(text: str) -> str:
    """
    テキスト内容からPOフォーマットを識別する
    
    Args:
        text: OCRで抽出されたテキスト
        
    Returns:
        識別されたフォーマット名 ("format1", "format2", "format3", "generic")
    """
    logger.info("POフォーマットの識別を開始")
    
    # スコアリングによるフォーマット判定
    scores = {
        "format1": 0,
        "format2": 0,
        "format3": 0
    }
    
    # フォーマット1の特徴
    if re.search(r"(?i)(Buyer'?s?\s*Info)", text):
        scores["format1"] += 3
    if re.search(r"(?i)(Consignee|Port\s+of\s+Loading)", text):
        scores["format1"] += 1
    
    # フォーマット2の特徴
    if re.search(r"(?i)(Purchase\s+Order)", text):
        scores["format2"] += 3
    if re.search(r"(?i)(Bill\s+To|Ship\s+To)", text):
        scores["format2"] += 1
    
    # フォーマット3の特徴
    if re.search(r"(?i)(\/\/\/\s*ORDER\s*CONFIMATION\s*\/\/\/)", text):
        scores["format3"] += 5  # 決定的な特徴なので高いスコア
    if re.search(r"(?i)(CONFIMATION|CONFIRMATION)", text):
        scores["format3"] += 1
    
    # 最高スコアのフォーマットを選択
    max_score = max(scores.values())
    if max_score > 0:
        for format_name, score in scores.items():
            if score == max_score:
                logger.info(f"識別されたPOフォーマット: {format_name} (スコア: {score})")
                return format_name
    
    # 特徴が見つからない場合はジェネリックフォーマットを返す
    logger.info("特定のフォーマットが識別できません。汎用的な抽出を行います。")
    return "generic"

def extract_field_by_regex(ocr_text: str, patterns: List[str], default_value: str = "") -> str:
    """
    正規表現パターンリストを使用して、最初にマッチするフィールド値を抽出します
    
    Args:
        ocr_text: OCRで抽出したテキスト
        patterns: 正規表現パターンのリスト
        default_value: デフォルト値
        
    Returns:
        抽出された値または空文字列
    """
    for pattern in patterns:
        match = re.search(pattern, ocr_text, re.IGNORECASE | re.MULTILINE)
        if match and match.group(1).strip():
            value = match.group(1).strip()
            # 余計な記号を削除
            value = re.sub(r'^[:\s]+|[:\s]+$', '', value)
            return value
    return default_value

def extract_format1_data(text: str) -> Dict[str, Any]:
    """
    フォーマット1（左上にBuyer's Infoと記載）からPOデータを抽出
    
    Args:
        text: OCRで抽出されたテキスト
        
    Returns:
        抽出されたPO情報を含む辞書
    """
    logger.info("フォーマット1のPOデータ抽出を開始")
    
    result = {
        "customer": "",
        "poNumber": "",
        "destination": "",
        "terms": "",
        "products": [],
        "totalAmount": "",
        "paymentTerms": "",
        "currency": ""
    }
    
    # Buyer情報の抽出
    buyer_match = re.search(r"(?i)Buyer'?s?\s*Info.*?:\s*(.*?)(?:\n|$)", text)
    if buyer_match:
        result["customer"] = buyer_match.group(1).strip()
    
    # PO番号の抽出
    po_match = re.search(r"(?i)P\.?O\.?\s*No\.?[\s:]*([A-Za-z0-9-]+)", text)
    if po_match:
        result["poNumber"] = po_match.group(1).strip()
    
    # 仕向地の抽出
    dest_match = re.search(r"(?i)Port\s+of\s+Destination\s*:\s*(.*?)(?:\n|$)", text)
    if dest_match:
        result["destination"] = dest_match.group(1).strip()
    
    # 支払条件の抽出
    terms_match = re.search(r"(?i)Payment\s+Terms\s*:\s*(.*?)(?:\n|$)", text)
    if terms_match:
        result["paymentTerms"] = terms_match.group(1).strip()
    
    # 出荷条件の抽出
    shipping_match = re.search(r"(?i)Shipping\s+Terms\s*:\s*(.*?)(?:\n|$)", text)
    if shipping_match:
        result["terms"] = shipping_match.group(1).strip()
    
    # 通貨の抽出
    currency_match = re.search(r"(?i)Currency\s*:\s*(USD|EUR|JPY|CNY)", text)
    if currency_match:
        result["currency"] = currency_match.group(1).strip()
    elif re.search(r"\$([\d,.]+)", text):
        result["currency"] = "USD"
    
    # 製品情報の抽出
    # 表形式のデータを解析する複雑なロジックが必要かもしれません
    product_section = re.search(r"(?i)(Item.*?Quantity.*?Amount).*?(Total|Grand\s+Total)", text, re.DOTALL)
    if product_section:
        product_text = product_section.group(0)
        
        # 行ごとに処理
        lines = product_text.split("\n")
        current_product = {}
        
        for line in lines:
            # 製品名と数量のパターン
            prod_match = re.search(r"(\d+)\s+(.*?)\s+(\d+(?:\.\d+)?)\s+(\w+)\s+(\d+(?:\.\d+)?)", line)
            if prod_match:
                if current_product and current_product.get("name"):
                    result["products"].append(current_product)
                
                current_product = {
                    "name": prod_match.group(2).strip(),
                    "quantity": prod_match.group(3),
                    "unitPrice": prod_match.group(5),
                    "amount": str(float(prod_match.group(3)) * float(prod_match.group(5)))
                }
        
        # 最後の製品を追加
        if current_product and current_product.get("name"):
            result["products"].append(current_product)
    
    # 合計金額の抽出
    total_match = re.search(r"(?i)Total\s*:?\s*\$?\s*([\d,.]+)", text)
    if total_match:
        result["totalAmount"] = total_match.group(1).replace(",", "")
    
    return result

def extract_format2_data(text: str) -> Dict[str, Any]:
    """
    フォーマット2（一番上の行にPurchase Orderと記載）からPOデータを抽出
    
    Args:
        text: OCRで抽出されたテキスト
        
    Returns:
        抽出されたPO情報を含む辞書
    """
    logger.info("フォーマット2のPOデータ抽出を開始")
    
    result = {
        "customer": "",
        "poNumber": "",
        "destination": "",
        "terms": "",
        "products": [],
        "totalAmount": "",
        "paymentTerms": "",
        "currency": ""
    }
    
    # Buyer情報の抽出
    buyer_match = re.search(r"(?i)Bill\s+To\s*:?\s*(.*?)(?:Ship\s+To|$)", text, re.DOTALL)
    if buyer_match:
        # 複数行に分かれている可能性があるので整形
        buyer_text = buyer_match.group(1).strip()
        buyer_lines = buyer_text.split("\n")
        # 空行を削除し、先頭行を選択
        buyer_lines = [line.strip() for line in buyer_lines if line.strip()]
        if buyer_lines:
            result["customer"] = buyer_lines[0]
    
    # PO番号の抽出
    po_match = re.search(r"(?i)P\.?O\.?\s*(?:#|No\.?)?\s*[:\s]?\s*([A-Za-z0-9-]+)", text)
    if po_match:
        result["poNumber"] = po_match.group(1).strip()
    
    # 仕向地の抽出（Ship Toセクションから）
    ship_to_match = re.search(r"(?i)Ship\s+To\s*:?\s*(.*?)(?:\n\n|\n[A-Z]|$)", text, re.DOTALL)
    if ship_to_match:
        ship_to_text = ship_to_match.group(1).strip()
        ship_to_lines = ship_to_text.split("\n")
        if ship_to_lines:
            result["destination"] = " ".join([line.strip() for line in ship_to_lines if line.strip()])
    
    # 支払条件の抽出
    terms_match = re.search(r"(?i)Terms\s*:?\s*(.*?)(?:\n|$)", text)
    if terms_match:
        result["paymentTerms"] = terms_match.group(1).strip()
    
    # 出荷条件の抽出
    shipping_match = re.search(r"(?i)Shipping\s+Terms\s*:?\s*(.*?)(?:\n|$)", text)
    if shipping_match:
        result["terms"] = shipping_match.group(1).strip()
    
    # 通貨の抽出
    if re.search(r"(?i)USD|US\$|\$", text):
        result["currency"] = "USD"
    elif re.search(r"(?i)EUR|€", text):
        result["currency"] = "EUR"
    elif re.search(r"(?i)JPY|¥", text):
        result["currency"] = "JPY"
    
    # 製品情報の抽出
    # フォーマット2の表形式を解析
    product_section = re.search(r"(?i)(Item.*?Qty.*?Price.*?Amount).*?(Total|Sub\-?total)", text, re.DOTALL)
    if product_section:
        product_text = product_section.group(0)
        
        # 行ごとに処理
        lines = product_text.split("\n")
        for i in range(1, len(lines)):  # ヘッダー行をスキップ
            line = lines[i].strip()
            if not line or re.search(r"(?i)(Total|Sub\-?total)", line):
                continue
                
            # 製品情報の抽出パターン
            prod_match = re.search(r"(\d+)\s+(.*?)\s+(\d+(?:\.\d+)?)\s+(\d+(?:\.\d+)?)\s+(\d+(?:\.\d+)?)", line)
            if prod_match:
                product = {
                    "name": prod_match.group(2).strip(),
                    "quantity": prod_match.group(3),
                    "unitPrice": prod_match.group(4),
                    "amount": prod_match.group(5)
                }
                result["products"].append(product)
    
    # 合計金額の抽出
    total_match = re.search(r"(?i)Total\s*:?\s*\$?\s*([\d,.]+)", text)
    if total_match:
        result["totalAmount"] = total_match.group(1).replace(",", "")
    
    return result

def extract_format3_data(text: str) -> Dict[str, Any]:
    """
    フォーマット3（///ORDER CONFIMATION ///と記載）からPOデータを抽出
    
    Args:
        text: OCRで抽出されたテキスト
        
    Returns:
        抽出されたPO情報を含む辞書
    """
    logger.info("フォーマット3のPOデータ抽出を開始")
    
    result = {
        "customer": "",
        "poNumber": "",
        "destination": "",
        "terms": "",
        "products": [],
        "totalAmount": "",
        "paymentTerms": "",
        "currency": ""
    }
    
    # Buyer情報の抽出（注文確認書のフォーマットによる）
    buyer_match = re.search(r"(?i)CUSTOMER\s*:?\s*(.*?)(?:\n|$)", text)
    if buyer_match:
        result["customer"] = buyer_match.group(1).strip()
    
    # PO番号の抽出
    po_match = re.search(r"(?i)ORDER\s+(?:NO\.?|NUMBER)\s*:?\s*([A-Za-z0-9-]+)", text)
    if po_match:
        result["poNumber"] = po_match.group(1).strip()
    
    # 仕向地の抽出
    dest_match = re.search(r"(?i)PORT\s+OF\s+DISCHARGE\s*:?\s*(.*?)(?:\n|$)", text)
    if dest_match:
        result["destination"] = dest_match.group(1).strip()
    
    # 出荷条件の抽出
    ship_match = re.search(r"(?i)TERMS?\s*:?\s*(.*?)(?:\n|$)", text)
    if ship_match:
        result["terms"] = ship_match.group(1).strip()
    
    # 支払条件の抽出
    pay_match = re.search(r"(?i)PAYMENT\s+TERMS?\s*:?\s*(.*?)(?:\n|$)", text)
    if pay_match:
        result["paymentTerms"] = pay_match.group(1).strip()
    
    # 通貨の抽出（通常USDが使用される）
    result["currency"] = "USD"
    
    # 製品情報の抽出
    grade_match = re.search(r"(?i)GRADE\s+([A-Za-z0-9]+)", text)
    qty_match = re.search(r"(?i)QUANTITY\s*:?\s*([\d,.]+)\s*(?:MT|KG)", text)
    price_match = re.search(r"(?i)UNIT\s+PRICE\s*:?\s*(?:USD)?\s*([\d,.]+)", text)
    
    if grade_match and qty_match:
        product_name = f"Grade {grade_match.group(1)}"
        quantity = qty_match.group(1).replace(",", "")
        unit_price = price_match.group(1).replace(",", "") if price_match else "0"
        amount = str(float(quantity) * float(unit_price)) if unit_price != "0" else ""
        
        result["products"].append({
            "name": product_name,
            "quantity": quantity,
            "unitPrice": unit_price,
            "amount": amount
        })
    
    # 合計金額の抽出
    total_match = re.search(r"(?i)TOTAL\s+(?:AMOUNT|PRICE)\s*:?\s*(?:USD)?\s*([\d,.]+)", text)
    if total_match:
        result["totalAmount"] = total_match.group(1).replace(",", "")
    
    return result

def extract_generic_data(text: str) -> Dict[str, Any]:
    """
    一般的なPOフォーマットからデータを抽出します（フォーマットが特定できない場合）
    
    Args:
        text: OCRで抽出されたテキスト
        
    Returns:
        抽出されたPO情報を含む辞書
    """
    logger.info("汎用フォーマットのPOデータ抽出を開始")
    
    result = {
        "customer": "",
        "poNumber": "",
        "destination": "",
        "terms": "",
        "products": [],
        "totalAmount": "",
        "paymentTerms": "",
        "currency": ""
    }
    
    # 顧客名を抽出する複数の方法を試す
    customer_patterns = [
        r"(?:Customer|Client|Buyer|Company|Purchaser):\s*(.*?)(?:\n|$)",
        r"(?:To|Bill to):\s*(.*?)(?:\n|$)",
        r"Contract Party\s*:\s*(.*?)(?:\n|$)",
        r"B/L CONSIGNEE\s*:\s*(.*?)(?:\n|$)",
        r"ABC Company\s*(.*?)(?:\n|$)",
        r"\(Buyer(?:'|')s Info\).*?([A-Za-z0-9\s]+Company)"
    ]
    
    for pattern in customer_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            result["customer"] = match.group(1).strip()
            break
    
    # PO番号の抽出
    po_patterns = [
        r"(?:PO|Purchase Order|Order) (?:No|Number|#)\.?:?\s*(\w+[-\d]+)",
        r"(?:PO|Purchase Order|Order) (?:No|Number|#)\.?:?\s*(\d+)",
        r"Order No\.\s*(.*?)(?:\n|Grade|Origin)",
        r"Buyers(?:'|')?\s+Order No\.\s*(.*?)(?:\n|Grade|$)"
    ]
    
    for pattern in po_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            result["poNumber"] = match.group(1).strip()
            break
    
    # 配送先の抽出
    destination_patterns = [
        r"(?:Destination|Ship to|Delivery Address|Port of Discharge|Discharge Port|PORT OF DISCHARGE):\s*(.*?)(?:\n|$)",
        r"(?:To|Deliver to):\s*(.*?)(?:\n|$)"
    ]
    
    for pattern in destination_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            result["destination"] = match.group(1).strip()
            break
    
    # 出荷条件の抽出
    terms_patterns = [
        r"(?:Incoterms|Inco Terms|Shipping Terms|Delivery Terms|Term):\s*(.*?)(?:\n|$)",
        r"(?:CIF|FOB|EXW)\s+([A-Za-z\s]+)"
    ]
    
    for pattern in terms_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            result["terms"] = match.group(1).strip()
            break
    
    # 支払条件の抽出
    payment_patterns = [
        r"(?:Payment Terms?|Terms of Payment|Terms|Payment):\s*(.*?)(?:\n|$)",
        r"Net Due within\s*(.*?)(?:\n|$)",
        r"Payment term\s*\n?\s*(.*?)(?:\n|$)"
    ]
    
    for pattern in payment_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            result["paymentTerms"] = match.group(1).strip()
            break
    
    # 通貨の抽出
    if re.search(r"(?i)USD|US\$|\$", text):
        result["currency"] = "USD"
    elif re.search(r"(?i)EUR|€", text):
        result["currency"] = "EUR"
    elif re.search(r"(?i)JPY|¥", text):
        result["currency"] = "JPY"
    else:
        result["currency"] = "USD"  # デフォルト
    
    # 製品情報の検出（単純なパターン）
    product_patterns = [
        # 商品コード、名称、数量、単価、金額が一行に並んでいるパターン
        r"(\d+)\s+(.*?)\s+(\d+(?:\.\d+)?)\s+(\w+)\s+(\d+(?:\.\d+)?)\s+(\d+(?:\.\d+)?)",
        # 品名が先に来て、その後に数量、単価、金額が並ぶパターン
        r"(.*?)\s+(\d+(?:\.\d+)?)\s*(?:pcs|units|kg|mt)\s+(\d+(?:\.\d+)?)\s+(\d+(?:\.\d+)?)"
    ]
    
    products_found = False
    
    for pattern in product_patterns:
        matches = re.finditer(pattern, text, re.MULTILINE)
        for match in matches:
            # パターンによって抽出位置が異なる
            if len(match.groups()) >= 6:  # 最初のパターン
                product = {
                    "name": match.group(2).strip(),
                    "quantity": match.group(3),
                    "unitPrice": match.group(5),
                    "amount": match.group(6)
                }
            else:  # 2番目のパターン
                product = {
                    "name": match.group(1).strip(),
                    "quantity": match.group(2),
                    "unitPrice": match.group(3),
                    "amount": match.group(4)
                }
            
            result["products"].append(product)
            products_found = True
    
    # 製品情報が見つからない場合のフォールバック
    if not products_found:
        # 品名、数量、単価を個別に探す
        product_name = ""
        quantity = ""
        unit_price = ""
        
        # 品名の検索
        name_match = re.search(r"(?:Item|Product|Description):\s*(.*?)(?:\n|$)", text, re.IGNORECASE)
        if name_match:
            product_name = name_match.group(1).strip()
        
        # 数量の検索
        qty_match = re.search(r"(?:Quantity|Qty):\s*([\d,.]+)\s*(?:pcs|units|kg|mt)?", text, re.IGNORECASE)
        if qty_match:
            quantity = qty_match.group(1).replace(",", "")
        
        # 単価の検索
        price_match = re.search(r"(?:Unit Price|Price):\s*(?:USD|US\$)?\s*([\d,.]+)", text, re.IGNORECASE)
        if price_match:
            unit_price = price_match.group(1).replace(",", "")
        
        # 金額の計算（数量×単価）
        amount = ""
        if quantity and unit_price:
            try:
                amount = str(float(quantity) * float(unit_price))
            except ValueError:
                pass
        
        # 有効なデータがあれば製品情報を追加
        if product_name or quantity or unit_price:
            result["products"].append({
                "name": product_name or "Unknown Product",
                "quantity": quantity,
                "unitPrice": unit_price,
                "amount": amount
            })
    
    # 合計金額の抽出
    total_patterns = [
        r"(?:Total|Grand Total):\s*(?:USD|US\$)?\s*([\d,.]+)",
        r"Total Amount:\s*(?:USD|US\$)?\s*([\d,.]+)",
        r"(?:[$]|USD)\s*([\d,.]+)(?:\s+total|\s+USD)",
        r"TOTAL\s+(?:AMOUNT|PRICE)\s*:?\s*(?:USD)?\s*([\d,.]+)"
    ]
    
    for pattern in total_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            result["totalAmount"] = match.group(1).replace(",", "")
            break
    
    return result

def validate_and_clean_result(result: Dict[str, Any]) -> Dict[str, Any]:
    """
    抽出結果の検証とクリーニングを行い、無効な値を修正します。
    
    Args:
        result: 抽出された結果
        
    Returns:
        検証・クリーニング済みの結果
    """
    # 必須フィールドのデフォルト値設定
    if not result.get("customer"):
        result["customer"] = "Unknown Customer"
    
    if not result.get("poNumber"):
        result["poNumber"] = "N/A"
    
    if not result.get("currency"):
        result["currency"] = "USD"
    
    # 製品情報の検証と補完
    if not result.get("products") or len(result["products"]) == 0:
        # 製品情報がない場合、ダミーの製品情報を追加
        result["products"] = [{
            "name": "Unknown Product",
            "quantity": "0",
            "unitPrice": "0",
            "amount": "0"
        }]
    else:
        # 既存の製品情報をクリーニング
        for i, product in enumerate(result["products"]):
            # 製品名が空の場合
            if not product.get("name"):
                product["name"] = f"Product {i+1}"
            
            # 数量、単価、金額の数値チェックと変換
            for field in ["quantity", "unitPrice", "amount"]:
                if field not in product or not product[field]:
                    product[field] = "0"
                else:
                    # 数値として解析可能か確認し、不可能な場合は0にする
                    try:
                        value = product[field].replace(",", "")
                        float(value)  # 数値変換テスト
                        product[field] = value
                    except (ValueError, TypeError):
                        product[field] = "0"
    
    # 合計金額の計算と検証
    if not result.get("totalAmount"):
        # 製品の金額から合計を計算
        try:
            total = sum(float(product.get("amount", 0)) for product in result["products"])
            result["totalAmount"] = str(total)
        except (ValueError, TypeError):
            result["totalAmount"] = "0"
    else:
        # 既存の合計金額の数値チェック
        try:
            value = result["totalAmount"].replace(",", "")
            float(value)  # 数値変換テスト
            result["totalAmount"] = value
        except (ValueError, TypeError):
            result["totalAmount"] = "0"
    
    return result

def analyze_extraction_quality(result: Dict[str, Any]) -> Dict[str, float]:
    """
    抽出結果の品質を分析します
    
    Args:
        result: 抽出された結果
        
    Returns:
        品質分析結果（信頼度や完全性などの指標）
    """
    # 必須フィールド
    required_fields = ["customer", "poNumber", "totalAmount"]
    # 推奨フィールド
    recommended_fields = ["currency", "destination", "terms", "paymentTerms"]
    
    # 必須フィールドの存在確認
    required_score = sum(1 for field in required_fields if result.get(field) and result[field] != "N/A") / len(required_fields)
    
    # 推奨フィールドの存在確認
    recommended_score = sum(1 for field in recommended_fields if result.get(field)) / len(recommended_fields)
    
    # 製品情報の分析
    product_fields = ["name", "quantity", "unitPrice", "amount"]
    product_score = 0
    
    if result.get("products") and len(result["products"]) > 0:
        valid_products = 0
        for product in result["products"]:
            # 各製品フィールドのスコア
            field_score = sum(1 for field in product_fields if product.get(field) and product[field] != "0" and product[field] != "Unknown Product") / len(product_fields)
            valid_products += field_score
        
        product_score = valid_products / len(result["products"])
    
    # 総合スコア（重み付け）
    completeness = 0.4 * required_score + 0.3 * recommended_score + 0.3 * product_score
    
    # 信頼度（完全性に基づいて計算）
    confidence = completeness * 0.8  # 最大80%の信頼度（残りの20%は人間のレビューに委ねる）
    
    return {
        "completeness": completeness,
        "confidence": confidence,
        "required_fields_score": required_score,
        "recommended_fields_score": recommended_score,
        "product_info_score": product_score
    }

def get_extraction_stats(ocr_text: str, result: Dict[str, Any]) -> Dict[str, Any]:
    """
    OCR抽出に関する統計情報を取得します
    
    Args:
        ocr_text: OCRで抽出したテキスト
        result: 抽出された結果
        
    Returns:
        抽出に関する統計情報
    """
    # フォーマット判定
    po_format = identify_po_format(ocr_text)
    
    # 必須フィールドの検出率
    required_fields = ["customer", "poNumber", "totalAmount"]
    fields_detected = sum(1 for field in required_fields if result.get(field) and result[field] != "N/A")
    
    # 製品情報の分析
    product_count = len(result.get("products", []))
    
    # 抽出品質の分析
    quality = analyze_extraction_quality(result)
    
    # 文字認識の質の推定
    text_length = len(ocr_text)
    text_quality = min(1.0, max(0.1, text_length / 5000))  # テキスト量に基づく簡易的な推定
    
    # 改行やスペースの検出（構造化データの目安）
    structure_quality = min(1.0, ocr_text.count("\n") / 50)
    
    # フォーマット候補を取得
    format_candidates = []
    if po_format == "format1":
        format_candidates = ["Buyer's Info Style"]
    elif po_format == "format2":
        format_candidates = ["Purchase Order Header Style"]
    elif po_format == "format3":
        format_candidates = ["Order Confirmation Style"]
    else:
        format_candidates = ["Generic PO Format"]
    
    return {
        "text_quality": text_quality,
        "structure_quality": structure_quality,
        "format": po_format,
        "format_candidates": format_candidates,
        "fields_detected": fields_detected,
        "total_fields": len(required_fields),
        "product_count": product_count,
        "extraction_quality": quality,
        "completeness": quality["completeness"],
        "confidence": quality["confidence"]
    }
