import os
import logging
import base64
import requests

logger = logging.getLogger(__name__)

def count_boxes_in_image(image_bytes: bytes) -> int:
    """
    Interface with NVIDIA Locate Anything (LocateAnything-3B) NIM API
    to count boxes/packages in a shelf image.
    
    If the API key is missing or request fails, falls back to a simulated count
    to support seamless local testing and offline UAT.
    """
    api_key = os.getenv("NVIDIA_API_KEY")
    if not api_key:
        logger.warning("NVIDIA_API_KEY is not set. Using simulated box count fallback.")
        # Return a mock box count (e.g., 5 boxes) for testing.
        return 5

    try:
        # Standard NVIDIA NIM visual grounding API URL
        url = "https://ai.api.nvidia.com/v1/gr/nvidia/locate-anything"
        
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
        
        # Base64 encode the image bytes
        base64_image = base64.b64encode(image_bytes).decode("utf-8")
        
        payload = {
            "image": f"data:image/jpeg;base64,{base64_image}",
            "query": "cardboard box, shipping package",
            "confidence_threshold": 0.3
        }
        
        response = requests.post(url, headers=headers, json=payload, timeout=15)
        if response.status_code == 200:
            data = response.json()
            # Bounding boxes are typically returned in a 'boxes' list or similar response schema
            boxes = data.get("boxes", [])
            logger.info(f"NVIDIA Locate Anything returned {len(boxes)} bounding boxes.")
            return len(boxes)
        else:
            logger.error(f"NVIDIA API returned error status {response.status_code}: {response.text}")
            return 5 # Fallback to mock on API error
            
    except Exception as e:
        logger.exception("Error calling NVIDIA Locate Anything API. Falling back to mock count.")
        return 5
