# diagnosis.py - デプロイ環境の診断ツール
import os
import sys
import logging
import platform

# ロギング設定
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("diagnosis")

def diagnose_environment():
    """デプロイ環境の診断を実行する関数"""
    logger.info("=============== 環境診断開始 ===============")
    
    # 基本情報
    logger.info(f"Python バージョン: {platform.python_version()}")
    logger.info(f"実行ディレクトリ: {os.getcwd()}")
    logger.info(f"PYTHONPATH: {os.environ.get('PYTHONPATH', 'Not set')}")
    
    # 環境変数確認
    important_vars = [
        'WEBSITES_PORT', 'UPLOAD_FOLDER', 'OCR_TEMP_FOLDER', 
        'DB_HOST', 'DB_NAME', 'DB_USER'
    ]
    
    logger.info("重要な環境変数:")
    for var in important_vars:
        # パスワードなど機密情報は表示しない
        if 'PASSWORD' in var:
            value = '[REDACTED]' if os.environ.get(var) else 'Not set'
        else:
            value = os.environ.get(var, 'Not set')
        logger.info(f"  {var}: {value}")
    
    # ディレクトリ確認
    important_dirs = [
        '/tmp', '/home/site/wwwroot', '/tmp/8dd6c400210b5d5'
    ]
    
    logger.info("重要なディレクトリ:")
    for dir_path in important_dirs:
        exists = os.path.exists(dir_path)
        is_dir = os.path.isdir(dir_path) if exists else False
        readable = os.access(dir_path, os.R_OK) if exists else False
        writable = os.access(dir_path, os.W_OK) if exists else False
        
        logger.info(f"  {dir_path}: 存在={exists}, ディレクトリ={is_dir}, 読取={readable}, 書込={writable}")
    
    # requirements.txt 確認
    req_paths = [
        './requirements.txt',
        '/home/site/wwwroot/requirements.txt',
        '/tmp/8dd6c400210b5d5/requirements.txt'
    ]
    
    logger.info("requirements.txt 確認:")
    for req_path in req_paths:
        exists = os.path.exists(req_path)
        readable = os.access(req_path, os.R_OK) if exists else False
        logger.info(f"  {req_path}: 存在={exists}, 読取={readable}")
    
    # インストール済みパッケージ確認
    try:
        import pkg_resources
        installed_packages = sorted([f"{pkg.key}=={pkg.version}" 
                                    for pkg in pkg_resources.working_set])
        logger.info(f"インストール済みパッケージ数: {len(installed_packages)}")
        logger.info("主要パッケージ:")
        key_packages = ['fastapi', 'uvicorn', 'gunicorn', 'sqlalchemy', 'pillow', 'pytesseract']
        for pkg in installed_packages:
            if any(key in pkg.lower() for key in key_packages):
                logger.info(f"  {pkg}")
    except ImportError:
        logger.error("pkg_resources モジュールが見つかりません")
    
    # 特定のポートリスニング確認
    import socket
    ports_to_check = [8000, 8080, 8181]
    logger.info("ポート確認:")
    for port in ports_to_check:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1)
        result = sock.connect_ex(('127.0.0.1', port))
        if result == 0:
            logger.info(f"  ポート {port}: 使用中")
        else:
            logger.info(f"  ポート {port}: 未使用")
        sock.close()
    
    logger.info("=============== 環境診断終了 ===============")

if __name__ == "__main__":
    diagnose_environment()
