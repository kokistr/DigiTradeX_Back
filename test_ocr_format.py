import os
import json
import argparse
import logging
from typing import Dict, Any, List
import pytesseract
from PIL import Image
from pdf2image import convert_from_path

# プロジェクトのモジュールをインポート
from ocr_extractors import identify_po_format, extract_format1_data, extract_format2_data, extract_format3_data, extract_generic_data
from ocr_service import validate_and_clean_result, analyze_extraction_quality, get_extraction_stats

# ロギング設定
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("ocr_test")

def extract_text_from_file(file_path: str) -> str:
    """
    ファイルからOCRテキストを抽出します
    
    :param file_path: ファイルパス
    :return: 抽出されたテキスト
    """
    _, file_ext = os.path.splitext(file_path)
    file_ext = file_ext.lower()
    
    extracted_text = ""
    
    if file_ext == '.pdf':
        images = convert_from_path(file_path)
        for i, image in enumerate(images):
            page_text = pytesseract.image_to_string(image, lang='eng+jpn')
            extracted_text += f"\n--- Page {i+1} ---\n{page_text}"
    
    elif file_ext in ['.png', '.jpg', '.jpeg']:
        image = Image.open(file_path)
        extracted_text = pytesseract.image_to_string(image, lang='eng+jpn')
    
    else:
        raise ValueError(f"サポートされていないファイル形式: {file_ext}")
    
    return extracted_text

def test_format_identification(ocr_text: str) -> Dict[str, float]:
    """
    テキストからPOフォーマットを識別します
    
    :param ocr_text: OCRテキスト
    :return: 各フォーマットの信頼度
    """
    # 主要なフォーマットを識別
    format_name, confidence = identify_po_format(ocr_text)
    logger.info(f"主要フォーマット: {format_name}, 信頼度: {confidence:.2f}")
    
    # 各フォーマットの信頼度を計算
    formats = ["format1", "format2", "format3"]
    format_confidences = {}
    
    for fmt in formats:
        # 仮実装: 実際は各フォーマットごとに確率を計算すべき
        if fmt == format_name:
            format_confidences[fmt] = confidence
        else:
            # 単純化のため0を設定
            format_confidences[fmt] = 0.0
    
    return format_confidences

def test_all_extractors(ocr_text: str) -> Dict[str, Dict[str, Any]]:
    """
    全ての抽出機能をテストします
    
    :param ocr_text: OCRテキスト
    :return: 各抽出機能の結果
    """
    results = {}
    
    # 各フォーマット抽出機能をテスト
    extractors = {
        "format1": extract_format1_data,
        "format2": extract_format2_data,
        "format3": extract_format3_data,
        "generic": extract_generic_data
    }
    
    for name, extractor in extractors.items():
        try:
            result = extractor(ocr_text)
            validate_and_clean_result(result)
            quality = analyze_extraction_quality(result)
            
            results[name] = {
                "data": result,
                "quality": quality
            }
            
            logger.info(f"{name} 抽出結果: 完全性={quality['completeness']:.2f}, 信頼度={quality['confidence']:.2f}")
            
        except Exception as e:
            logger.error(f"{name} 抽出エラー: {str(e)}")
            results[name] = {
                "error": str(e)
            }
    
    return results

def compare_extraction_results(results: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """
    抽出結果を比較して最適な結果を選択します
    
    :param results: 各抽出機能の結果
    :return: 比較分析結果
    """
    comparison = {
        "best_extractor": "",
        "best_quality": 0.0,
        "confidence_scores": {},
        "field_comparison": {}
    }
    
    # 最高品質の抽出機能を特定
    for name, result in results.items():
        if "quality" in result:
            quality = result["quality"]["confidence"]
            comparison["confidence_scores"][name] = quality
            
            if quality > comparison["best_quality"]:
                comparison["best_quality"] = quality
                comparison["best_extractor"] = name
    
    if not comparison["best_extractor"]:
        logger.warning("有効な抽出結果がありません")
        return comparison
    
    # フィールド比較
    core_fields = ["customer", "poNumber", "currency", "totalAmount", "paymentTerms", "terms", "destination"]
    
    for field in core_fields:
        comparison["field_comparison"][field] = {}
        
        for name, result in results.items():
            if "data" in result:
                field_value = result["data"].get(field, "")
                comparison["field_comparison"][field][name] = field_value
    
    # 製品情報の比較
    comparison["field_comparison"]["products"] = {}
    
    for name, result in results.items():
        if "data" in result and result["data"]["products"]:
            # 最初の製品情報のみ比較に使用
            product = result["data"]["products"][0]
            comparison["field_comparison"]["products"][name] = {
                "name": product.get("name", ""),
                "quantity": product.get("quantity", ""),
                "unitPrice": product.get("unitPrice", ""),
                "amount": product.get("amount", "")
            }
    
    return comparison

def run_test(file_path: str, output_dir: str = None):
    """
    OCRフォーマットテストを実行します
    
    :param file_path: テスト対象のファイルパス
    :param output_dir: 結果出力ディレクトリ（オプション）
    """
    logger.info(f"OCRフォーマットテスト開始: {file_path}")
    
    try:
        # OCRテキスト抽出
        ocr_text = extract_text_from_file(file_path)
        logger.info(f"テキスト抽出完了: {len(ocr_text)} 文字")
        
        # フォーマット識別テスト
        format_confidences = test_format_identification(ocr_text)
        
        # 各抽出機能のテスト
        extraction_results = test_all_extractors(ocr_text)
        
        # 結果比較
        comparison = compare_extraction_results(extraction_results)
        
        # 結果サマリー
        summary = {
            "file": file_path,
            "text_length": len(ocr_text),
            "format_identification": format_confidences,
            "best_extractor": comparison["best_extractor"],
            "best_confidence": comparison["best_quality"],
            "recommendation": f"{comparison['best_extractor']}抽出機能を使用してください" if comparison["best_extractor"] else "フォーマットを特定できませんでした"
        }
        
        logger.info(f"テスト結果: {json.dumps(summary, indent=2)}")
        
        # 結果の保存
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)
            filename = os.path.basename(file_path)
            base_name, _ = os.path.splitext(filename)
            
            # テキスト保存
            with open(os.path.join(output_dir, f"{base_name}_ocr.txt"), "w", encoding="utf-8") as f:
                f.write(ocr_text)
            
            # 詳細結果保存
            detailed_results = {
                "summary": summary,
                "ocr_text_sample": ocr_text[:1000] + "..." if len(ocr_text) > 1000 else ocr_text,
                "format_confidences": format_confidences,
                "extraction_results": {
                    name: result.get("data", {}) 
                    for name, result in extraction_results.items() 
                    if "data" in result
                },
                "quality_assessment": {
                    name: result.get("quality", {}) 
                    for name, result in extraction_results.items() 
                    if "quality" in result
                },
                "comparison": comparison
            }
            
            with open(os.path.join(output_dir, f"{base_name}_result.json"), "w", encoding="utf-8") as f:
                json.dump(detailed_results, f, indent=2, ensure_ascii=False)
            
            logger.info(f"結果をディレクトリに保存しました: {output_dir}")
        
    except Exception as e:
        logger.error(f"テスト実行エラー: {str(e)}")
        raise

def main():
    parser = argparse.ArgumentParser(description="OCRフォーマット分析テスト")
    parser.add_argument("file", help="分析対象のPDFまたは画像ファイル")
    parser.add_argument("--output", "-o", help="結果出力ディレクトリ", default="./test_results")
    
    args = parser.parse_args()
    
    run_test(args.file, args.output)

if __name__ == "__main__":
    main()