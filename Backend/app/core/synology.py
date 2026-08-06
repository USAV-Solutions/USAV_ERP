import os
import logging
from datetime import datetime
import requests

logger = logging.getLogger(__name__)

def get_synology_base_url() -> str:
    """
    Build base URL for Synology NAS supporting IP addresses, QuickConnect domains, or synology.me DDNS.
    """
    nas_host = os.getenv("SYNOLOGY_NAS_IP", "").strip()
    nas_port = os.getenv("SYNOLOGY_NAS_PORT", "").strip()

    if not nas_host:
        raise ValueError("SYNOLOGY_NAS_IP is missing in environment.")

    nas_host = nas_host.rstrip("/")
    if nas_host.startswith("http://") or nas_host.startswith("https://"):
        return nas_host

    port = nas_port if nas_port else ("5001" if "quickconnect" in nas_host.lower() else "5000")
    scheme = "https" if port == "5001" or port == "443" else "http"
    return f"{scheme}://{nas_host}:{port}"


def get_synology_sid() -> str:
    """
    Authenticate with Synology DSM WebAPI and return the session ID (sid).
    """
    nas_host = os.getenv("SYNOLOGY_NAS_IP")
    nas_user = os.getenv("SYNOLOGY_NAS_USER")
    nas_pass = os.getenv("SYNOLOGY_NAS_PASSWORD")
    
    if not all([nas_host, nas_user, nas_pass]):
        raise ValueError("Synology NAS credentials are not complete in environment variables.")
        
    base_url = get_synology_base_url()
    url = f"{base_url}/webapi/auth.cgi"
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
    
    nas_host = os.getenv("SYNOLOGY_NAS_IP")
    
    if not nas_host:
        # Fallback to local static folder
        logger.warning("SYNOLOGY_NAS_IP is not set. Saving photo to local static files.")
        local_dir = os.path.join("static", "photos", today_str)
        os.makedirs(local_dir, exist_ok=True)
        local_path = os.path.join(local_dir, filename)
        with open(local_path, "wb") as f:
            f.write(file_bytes)
        return f"/static/photos/{today_str}/{filename}"
        
    try:
        sid = get_synology_sid()
        base_url = get_synology_base_url()
        url = f"{base_url}/webapi/entry.cgi"
        
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


def list_synology_shares() -> list[str]:
    """
    List root shared folders on Synology NAS via FileStation WebAPI (method=list_share).
    """
    sid = get_synology_sid()
    base_url = get_synology_base_url()
    url = f"{base_url}/webapi/entry.cgi"
    params = {
        "api": "SYNO.FileStation.List",
        "version": "2",
        "method": "list_share",
        "_sid": sid
    }
    response = requests.get(url, params=params, timeout=15)
    response.raise_for_status()
    data = response.json()
    if not data.get("success"):
        error_code = data.get("error", {}).get("code", "unknown")
        raise RuntimeError(f"Synology list_share failed with error code: {error_code}")

    shares = data.get("data", {}).get("shares", [])
    return [s["path"] for s in shares]


def list_synology_files(folder_path: str) -> list[str]:
    """
    List files in a Synology NAS directory via FileStation WebAPI.
    """
    sid = get_synology_sid()
    base_url = get_synology_base_url()
    url = f"{base_url}/webapi/entry.cgi"
    params = {
        "api": "SYNO.FileStation.List",
        "version": "2",
        "method": "list",
        "folder_path": folder_path,
        "_sid": sid
    }
    response = requests.get(url, params=params, timeout=15)
    response.raise_for_status()
    data = response.json()
    if not data.get("success"):
        error_code = data.get("error", {}).get("code", "unknown")
        # Print helpful available shares if error 408 occurs
        if error_code == 408:
            try:
                available = list_synology_shares()
                raise RuntimeError(f"Path '{folder_path}' not found on Synology NAS (error 408). Root shared folders available: {available}")
            except Exception:
                pass
        raise RuntimeError(f"Synology List failed with error code: {error_code}")

    files = data.get("data", {}).get("files", [])
    return [f["path"] for f in files if not f.get("isdir")]


def download_synology_file(file_path: str) -> bytes:
    """
    Download file bytes from Synology NAS via FileStation WebAPI.
    """
    sid = get_synology_sid()
    base_url = get_synology_base_url()
    url = f"{base_url}/webapi/entry.cgi"
    params = {
        "api": "SYNO.FileStation.Download",
        "version": "2",
        "method": "download",
        "path": file_path,
        "mode": "download",
        "_sid": sid
    }
    response = requests.get(url, params=params, timeout=30)
    response.raise_for_status()
    return response.content
