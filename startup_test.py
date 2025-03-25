# startup_test.py
import os
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

try:
    logger.info("アプリケーション起動テストを実行しています")
    
    # 環境変数のログ出力
    logger.info(f"環境変数: UPLOAD_FOLDER = {os.getenv('UPLOAD_FOLDER')}")
    logger.info(f"環境変数: OCR_TEMP_FOLDER = {os.getenv('OCR_TEMP_FOLDER')}")
    
    # 必要なディレクトリの作成
    tmp_dir = "/tmp"
    os.makedirs(tmp_dir, exist_ok=True)
    logger.info(f"ディレクトリ作成: {tmp_dir}")
    
    # アクセス権のチェック
    logger.info(f"ディレクトリのアクセス権: {tmp_dir} 読み取り可能: {os.access(tmp_dir, os.R_OK)}, 書き込み可能: {os.access(tmp_dir, os.W_OK)}")
    
    # テストファイルの作成
    test_file = os.path.join(tmp_dir, "test.txt")
    with open(test_file, "w") as f:
        f.write("Test")
    logger.info(f"テストファイル作成: {test_file}")
    
    # 後片付け
    os.remove(test_file)
    logger.info("テストファイル削除完了")
    
    logger.info("アプリケーション起動テストが正常に完了しました")
except Exception as e:
    logger.error(f"起動テストエラー: {str(e)}")
