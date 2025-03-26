# startup.py - Azure App Service用スタートアップスクリプト
import os
import sys
import subprocess
import logging
import time
import shutil
from pathlib import Path

# ロギング設定
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("startup")

def setup_environment():
    """環境設定を行う関数"""
    logger.info("=============== 環境設定開始 ===============")
    
    # 現在の作業ディレクトリを確認
    current_dir = os.getcwd()
    logger.info(f"現在の作業ディレクトリ: {current_dir}")
    
    # 必要なディレクトリ作成
    tmp_dir = "/tmp"
    ocr_temp_dir = os.path.join(tmp_dir, "ocr_temp")
    upload_dir = os.path.join(tmp_dir, "uploads")
    
    os.makedirs(ocr_temp_dir, exist_ok=True)
    os.makedirs(upload_dir, exist_ok=True)
    
    logger.info(f"OCR一時ディレクトリ作成: {ocr_temp_dir}")
    logger.info(f"アップロードディレクトリ作成: {upload_dir}")
    
    # 環境変数設定
    os.environ["UPLOAD_FOLDER"] = upload_dir
    os.environ["OCR_TEMP_FOLDER"] = ocr_temp_dir
    
    # requirements.txtが存在するか確認
    req_file = os.path.join(current_dir, "requirements.txt")
    if not os.path.exists(req_file):
        logger.warning(f"requirements.txt が見つかりません: {req_file}")
        # 既知のパスをチェック
        alternative_paths = [
            "/home/site/wwwroot/requirements.txt",
            "/tmp/8dd6c400210b5d5/requirements.txt"
        ]
        for alt_path in alternative_paths:
            if os.path.exists(alt_path):
                logger.info(f"代替 requirements.txt を見つけました: {alt_path}")
                req_file = alt_path
                break
    
    logger.info("=============== 環境設定完了 ===============")
    return current_dir, req_file

def install_dependencies(req_file):
    """依存パッケージのインストールを行う関数"""
    logger.info("=============== 依存パッケージインストール開始 ===============")
    
    # requirements.txtが存在するか再確認
    if os.path.exists(req_file):
        logger.info(f"requirements.txt からインストール: {req_file}")
        try:
            subprocess.run([sys.executable, "-m", "pip", "install", "--upgrade", "pip"], check=True)
            subprocess.run([sys.executable, "-m", "pip", "install", "-r", req_file], check=True)
            logger.info("依存パッケージのインストールが完了しました")
        except subprocess.CalledProcessError as e:
            logger.error(f"依存パッケージのインストールに失敗しました: {e}")
            # フォールバック: 直接インストール
            install_core_dependencies()
    else:
        logger.warning(f"requirements.txt が見つかりません。直接インストールを実行します。")
        install_core_dependencies()
    
    logger.info("=============== 依存パッケージインストール完了 ===============")

def install_core_dependencies():
    """コア依存パッケージを直接インストールする関数"""
    logger.info("コア依存パッケージを直接インストールします")
    
    core_packages = [
        "fastapi==0.110.0",
        "uvicorn==0.30.0",
        "gunicorn==22.0.0",
        "python-multipart==0.0.9",
        "pillow==10.2.0",
        "pdf2image==1.17.0",
        "pytesseract==0.3.10",
        "python-jose[cryptography]==3.3.0",
        "passlib[bcrypt]==1.7.4",
        "sqlalchemy==2.0.28",
        "pymysql==1.1.0",
        "python-dotenv==1.0.1",
        "cryptography==41.0.3",
        "numpy==1.26.4",
        "opencv-python-headless==4.9.0.80",
        "pydantic==2.3.0",
        "pydantic[email]==2.3.0",
        "aiofiles==23.2.1",
        "pyopenssl==23.2.0"
    ]
    
    for package in core_packages:
        try:
            logger.info(f"インストール中: {package}")
            subprocess.run([sys.executable, "-m", "pip", "install", package], check=True)
        except subprocess.CalledProcessError as e:
            logger.error(f"パッケージのインストールに失敗しました: {package} - {e}")

def start_application(app_dir):
    """アプリケーションを起動する関数"""
    logger.info("=============== アプリケーション起動 ===============")
    
    # アプリケーションファイルの確認
    app_file = os.path.join(app_dir, "app.py")
    if not os.path.exists(app_file):
        logger.error(f"アプリケーションファイルが見つかりません: {app_file}")
        # 既知のパスをチェック
        alternative_paths = [
            "/home/site/wwwroot/app.py",
            "/tmp/8dd6c400210b5d5/app.py"
        ]
        for alt_path in alternative_paths:
            if os.path.exists(alt_path):
                logger.info(f"代替アプリケーションファイルを見つけました: {alt_path}")
                app_file = alt_path
                app_dir = os.path.dirname(alt_path)
                break
        else:
            logger.error("アプリケーションファイルが見つかりません。終了します。")
            return False
    
    # ポート設定
    port = os.environ.get("WEBSITES_PORT", "8181")
    logger.info(f"ポート設定: {port}")
    
    # アプリケーション起動
    try:
        os.chdir(app_dir)
        logger.info(f"アプリケーションディレクトリに移動: {app_dir}")
        
        cmd = [
            "gunicorn", "app:app", 
            "--workers", "2", 
            "--worker-class", "uvicorn.workers.UvicornWorker", 
            "--bind", f"0.0.0.0:{port}", 
            "--timeout", "120"
        ]
        
        logger.info(f"実行コマンド: {' '.join(cmd)}")
        subprocess.run(cmd, check=True)
        return True
    except subprocess.CalledProcessError as e:
        logger.error(f"アプリケーション起動に失敗しました: {e}")
        return False

if __name__ == "__main__":
    try:
        # 診断用スクリプトの実行
        subprocess.run([sys.executable, "diagnosis.py"], check=False)
        
        # 環境設定
        app_dir, req_file = setup_environment()
        
        # 依存パッケージのインストール
        install_dependencies(req_file)
        
        # アプリケーション起動
        start_application(app_dir)
    except Exception as e:
        logger.error(f"予期しないエラーが発生しました: {e}")
        sys.exit(1)
