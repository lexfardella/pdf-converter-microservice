import fitz
import base64
import io
from PIL import Image
import traceback
from flask import Flask, request, jsonify
import os
import gc
import psutil
from typing import Optional, Tuple
from dataclasses import dataclass

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 30 * 1024 * 1024  # 30MB limit

@dataclass
class QualitySettings:
    dpi: int = 300
    format: str = "PNG"
    max_dimension: int = 4096
    optimize: bool = True

def get_memory_usage_mb() -> float:
    process = psutil.Process(os.getpid())
    return process.memory_info().rss / 1024 / 1024

def cleanup_memory():
    gc.collect()

def process_page_to_image(page: fitz.Page, settings: QualitySettings) -> Tuple[Image.Image, int, int]:
    """Convert PDF page to PIL Image with error handling"""
    scale = settings.dpi / 72
    matrix = fitz.Matrix(scale, scale)
    pix = page.get_pixmap(matrix=matrix, alpha=False)
    
    try:
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        width, height = img.size
        
        if max(width, height) > settings.max_dimension:
            ratio = settings.max_dimension / max(width, height)
            new_size = (int(width * ratio), int(height * ratio))
            img = img.resize(new_size, Image.Resampling.LANCZOS)
            width, height = img.size
            
        return img, width, height
    finally:
        # Ensure pixmap is cleaned up
        del pix
        cleanup_memory()

def process_single_page(pdf_bytes: bytes, page_num: int, settings: QualitySettings) -> dict:
    """Process a single page with proper cleanup"""
    doc = None
    img = None
    buffer = None
    
    try:
        print(f"Memory before processing page {page_num}: {get_memory_usage_mb():.1f}MB")
        
        # Open document
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        total_pages = len(doc)
        
        if page_num >= total_pages:
            return {
                "error": "Page number exceeds document length",
                "total_pages": total_pages
            }
        
        # Load and process page
        page = doc.load_page(page_num)
        img, width, height = process_page_to_image(page, settings)
        
        # Convert to base64
        buffer = io.BytesIO()
        img.save(buffer, format=settings.format, optimize=settings.optimize)
        img_str = base64.b64encode(buffer.getvalue()).decode()
        
        print(f"Memory after processing page {page_num}: {get_memory_usage_mb():.1f}MB")
        
        return {
            "image": img_str,
            "page_number": page_num,
            "total_pages": total_pages,
            "width": width,
            "height": height,
            "dpi": settings.dpi
        }
        
    except Exception as e:
        print(f"Error processing page {page_num}: {str(e)}")
        print(f"Traceback: {traceback.format_exc()}")
        return {
            "error": str(e),
            "page_number": page_num,
            "traceback": traceback.format_exc()
        }
        
    finally:
        # Cleanup in reverse order of creation
        if buffer:
            buffer.close()
        if img:
            del img
        if doc:
            doc.close()
        cleanup_memory()
        print(f"Final memory after cleanup: {get_memory_usage_mb():.1f}MB")

@app.route('/convert/<int:page_num>', methods=['POST'])
def handle_convert_page(page_num):
    if 'file' not in request.files:
        return jsonify({"error": "No file part"}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "No selected file"}), 400
    
    settings = QualitySettings()
    
    try:
        pdf_bytes = file.read()
        result = process_single_page(pdf_bytes, page_num, settings)
        
        if "error" in result:
            return jsonify(result), 500
            
        return jsonify(result)
        
    except Exception as e:
        return jsonify({
            "error": "PDF processing failed",
            "details": str(e),
            "traceback": traceback.format_exc()
        }), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)