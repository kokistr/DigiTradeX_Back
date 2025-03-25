# minimal_app.py
from fastapi import FastAPI
import os
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

@app.get("/")
async def root():
    logger.info("ルートエンドポイントにアクセスがありました")
    return {"message": "Hello World"}

@app.get("/debug/info")
async def debug_info():
    logger.info("デバッグ情報エンドポイントにアクセスがありました")
    return {
        "cwd": os.getcwd(),
        "tmp_dir_exists": os.path.exists("/tmp"),
        "tmp_dir_writable": os.access("/tmp", os.W_OK),
        "upload_folder": os.getenv("UPLOAD_FOLDER"),
        "ocr_temp_folder": os.getenv("OCR_TEMP_FOLDER")
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
