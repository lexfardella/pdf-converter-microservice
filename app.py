import fitz
import base64
import io
from PIL import Image
import traceback
from flask import Flask, request, jsonify
import os
import gc
import psutil
from typing import Optional, Tuple, Dict
from dataclasses import dataclass
import threading

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 31457280  # 30MB limit plus buffer

# Thread-local storage for file data
thread_local = threading.local()

@dataclass
class QualitySettings:
    dpi: int = 300
    format: str = "PNG"
    max_dimension: int = 4096
    optimize: bool = True
    quality: int = 95  # For JPEG fallback

    def adjust_for_page_size(self, page_size_mb: float) -> None:
        """Dynamically adjust quality settings based on page size"""
        if page_size_mb > 10:  # Very large page
            self.dpi = 250
            self.format = "JPEG"
            self.quality = 90
        elif page_size_mb > 5:  # Large page
            self.format = "JPEG"
            self.quality = 95

def get_memory_usage_mb() -> float:
    process = psutil.Process(os.getpid())
    return process.memory_info().rss / 1024 / 1024

def force_cleanup():
    """Aggressive memory cleanup"""
    gc.collect()
    gc.collect()  # Second collection for generations
    if hasattr(thread_local, 'pdf_bytes'):
        del thread_local.pdf_bytes
    
def estimate_page_size(page: fitz.Page, dpi: int) -> float:
    """Estimate page size in MB before processing"""
    width, height = page.rect.width, page.rect.height
    scale = dpi / 72
    estimated_pixels = width * height * scale * scale * 3  # 3 for RGB
    return estimated_pixels / (1024 * 1024)  # Convert to MB

def process_page_to_image(page: fitz.Page, settings: QualitySettings) -> Tuple[Image.Image, int, int]:
    """Convert PDF page to PIL Image with dynamic quality adjustment"""
    # Estimate page size and adjust settings
    estimated_size = estimate_page_size(page, settings.dpi)
    settings.adjust_for_page_size(estimated_size)
    
    scale = settings.dpi / 72
    matrix = fitz.Matrix(scale, scale)
    pix = None
    
    try:
        # Use RGB only, no alpha
        pix = page.get_pixmap(matrix=matrix, alpha=False)
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        width, height = img.size
        
        if max(width, height) > settings.max_dimension:
            ratio = settings.max_dimension / max(width, height)
            new_size = (int(width * ratio), int(height * ratio))
            img = img.resize(new_size, Image.Resampling.LANCZOS)
            width, height = img.size
        
        return img, width, height
    finally:
        if pix:
            del pix
        force_cleanup()

def process_single_page(page_num: int, settings: QualitySettings) -> Dict:
    """Process a single page with optimized memory handling"""
    doc = None
    img = None
    buffer = None
    
    try:
        print(f"Memory before processing page {page_num}: {get_memory_usage_mb():.1f}MB")
        
        # Use thread-local storage for PDF bytes
        pdf_bytes = getattr(thread_local, 'pdf_bytes', None)
        if pdf_bytes is None:
            return {"error": "PDF data not found in thread local storage"}
        
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        total_pages = len(doc)
        
        if page_num >= total_pages:
            return {
                "error": "Page number exceeds document length",
                "total_pages": total_pages
            }
        
        page = doc.load_page(page_num)
        img, width, height = process_page_to_image(page, settings)
        
        buffer = io.BytesIO()
        if settings.format == "JPEG":
            img.save(buffer, format=settings.format, optimize=settings.optimize, 
                    quality=settings.quality)
        else:
            img.save(buffer, format=settings.format, optimize=settings.optimize)
        
        img_str = base64.b64encode(buffer.getvalue()).decode()
        
        print(f"Memory after processing page {page_num}: {get_memory_usage_mb():.1f}MB")
        
        return {
            "image": img_str,
            "page_number": page_num,
            "total_pages": total_pages,
            "width": width,
            "height": height,
            "dpi": settings.dpi,
            "format": settings.format
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
        if buffer:
            buffer.close()
        if img:
            del img
        if doc:
            doc.close()
        force_cleanup()
        print(f"Final memory after cleanup: {get_memory_usage_mb():.1f}MB")

@app.route('/convert/<int:page_num>', methods=['POST'])
def handle_convert_page(page_num):
    if 'file' not in request.files:
        return jsonify({"error": "No file part"}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "No selected file"}), 400
    
    try:
        # Store PDF bytes in thread-local storage
        thread_local.pdf_bytes = file.read()
        settings = QualitySettings()
        
        result = process_single_page(page_num, settings)
        
        if "error" in result:
            return jsonify(result), 500
            
        return jsonify(result)
        
    except Exception as e:
        return jsonify({
            "error": "PDF processing failed",
            "details": str(e),
            "traceback": traceback.format_exc()
        }), 500
    finally:
        # Clean up thread-local storage
        if hasattr(thread_local, 'pdf_bytes'):
            del thread_local.pdf_bytes
        force_cleanup()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)