import os
import logging
from datetime import datetime
import requests

logger = logging.getLogger(__name__)

def get_synology_sid() -> str:
    """
    Authenticate with Synology DSM WebAPI and return the session ID (sid).
    """
    nas_ip = os.getenv("SYNOLOGY_NAS_IP")
    nas_port = os.getenv("SYNOLOGY_NAS_PORT", "5000")
    nas_user = os.getenv("SYNOLOGY_NAS_USER")
    nas_pass = os.getenv("SYNOLOGY_NAS_PASSWORD")
    
    if not all([nas_ip, nas_user, nas_pass]):
        raise ValueError("Synology NAS credentials are not complete in environment variables.")
        
    url = f"http://{nas_ip}:{nas_port}/webapi/auth.cgi"
    params = {
        "api": "SYNO.API.Auth",
        "version": "3",
        "method": "login",
        "account": nas_user,
        "passwd": nas_pass,
        "session": "FileStation",
        "format": "cookie"
    }
    
    response = requests.get(url, params=params, timeout=10)
    response.raise_for_status()
    data = response.json()
    
    if not data.get("success"):
        error_code = data.get("error", {}).get("code", "unknown")
        raise RuntimeError(f"Synology DSM login failed with error code: {error_code}")
        
    return data["data"]["sid"]


def upload_to_synology(file_bytes: bytes, filename: str) -> str:
    """
    Upload a file to Synology NAS DS418j under '/volume1/photo/packed_orders/YYYY-MM-DD/'.
    If credentials are missing or the NAS is offline, falls back to local static storage.
    """
    today_str = datetime.now().strftime("%Y-%m-%d")
    target_dir = f"/volume1/photo/packed_orders/{today_str}"
    
    nas_ip = os.getenv("SYNOLOGY_NAS_IP")
    nas_port = os.getenv("SYNOLOGY_NAS_PORT", "5000")
    
    if not nas_ip:
        # Fallback to local static folder
        logger.warning("SYNOLOGY_NAS_IP is not set. Saving photo to local static files.")
        local_dir = os.path.join("static", "photos", today_str)
        os.makedirs(local_dir, exist_ok=True)
        local_path = os.path.join(local_dir, filename)
        with open(local_path, "wb") as f:
            f.write(file_bytes)
        # Return a relative URL path that our server can serve
        return f"/static/photos/{today_str}/{filename}"
        
    try:
        sid = get_synology_sid()
        
        # Upload endpoint
        url = f"http://{nas_ip}:{nas_port}/webapi/entry.cgi"
        
        form_data = {
            "api": "SYNO.FileStation.Upload",
            "version": "2",
            "method": "upload",
            "path": target_dir,
            "create_parents": "true",
            "_sid": sid
        }
        
        files = {
            "file": (filename, file_bytes, "image/jpeg")
        }
        
        response = requests.post(url, data=form_data, files=files, timeout=20)
        response.raise_for_status()
        data = response.json()
        
        if not data.get("success"):
            error_code = data.get("error", {}).get("code", "unknown")
            raise RuntimeError(f"Synology File Station upload failed with error code: {error_code}")
            
        logger.info(f"Successfully uploaded {filename} to Synology NAS: {target_dir}")
        return f"{target_dir}/{filename}"
        
    except Exception as e:
        logger.exception("Error uploading to Synology NAS. Falling back to local static storage.")
        local_dir = os.path.join("static", "photos", today_str)
        os.makedirs(local_dir, exist_ok=True)
        local_path = os.path.join(local_dir, filename)
        with open(local_path, "wb") as f:
            f.write(file_bytes)
        return f"/static/photos/{today_str}/{filename}"
