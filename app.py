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
import resource
import logging

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 31457280  # 30MB limit

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@dataclass
class QualitySettings:
    dpi: int = 200  # Reduced default DPI
    format: str = "JPEG"  # Default to JPEG for better compression
    max_dimension: int = 2048  # Reduced maximum dimension
    quality: int = 85  # Slightly reduced quality
    optimize: bool = True

    def adjust_for_page_size(self, page_size_mb: float) -> None:
        """Dynamically adjust quality settings based on page size"""
        if page_size_mb > 15:  # Very large page
            self.dpi = 150
            self.quality = 75
            self.max_dimension = 1800
        elif page_size_mb > 8:  # Large page
            self.dpi = 175
            self.quality = 80
            self.max_dimension = 2048

def get_memory_usage_mb() -> float:
    """Get current memory usage in MB"""
    process = psutil.Process(os.getpid())
    mem = process.memory_info().rss / 1024 / 1024
    logger.info(f"Current memory usage: {mem:.1f}MB")
    return mem

def force_cleanup() -> None:
    """Aggressive memory cleanup"""
    gc.collect()
    gc.collect()
    
    # Set Python's memory threshold lower to trigger more frequent collection
    gc.set_threshold(100, 5, 5)
    
    # Attempt to release memory back to the system
    if hasattr(gc, 'freeze'):
        gc.freeze()
    
    logger.info(f"Memory after cleanup: {get_memory_usage_mb():.1f}MB")

def estimate_page_size(page: fitz.Page, dpi: int) -> float:
    """Estimate page size in MB before processing"""
    width, height = page.rect.width, page.rect.height
    scale = dpi / 72
    estimated_pixels = width * height * scale * scale * 3  # 3 for RGB
    return estimated_pixels / (1024 * 1024)

def process_page_to_image(page: fitz.Page, settings: QualitySettings) -> Tuple[Image.Image, int, int]:
    """Convert PDF page to PIL Image with memory optimization"""
    estimated_size = estimate_page_size(page, settings.dpi)
    settings.adjust_for_page_size(estimated_size)
    
    logger.info(f"Processing page with settings: DPI={settings.dpi}, Format={settings.format}, Quality={settings.quality}")
    
    scale = settings.dpi / 72
    matrix = fitz.Matrix(scale, scale)
    pix = None
    
    try:
        pix = page.get_pixmap(matrix=matrix, alpha=False)
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        
        # Release pixmap memory immediately
        pix = None
        gc.collect()
        
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

def process_single_page(pdf_data: bytes, page_num: int) -> Dict:
    """Process a single page with optimized memory handling"""
    start_memory = get_memory_usage_mb()
    logger.info(f"Starting page {page_num} processing. Initial memory: {start_memory:.1f}MB")
    
    doc = None
    img = None
    buffer = None
    settings = QualitySettings()
    
    try:
        doc = fitz.open(stream=pdf_data, filetype="pdf")
        total_pages = len(doc)
        
        if page_num >= total_pages:
            return {
                "error": f"Page number {page_num} exceeds document length ({total_pages} pages)",
                "total_pages": total_pages
            }
        
        page = doc.load_page(page_num)
        img, width, height = process_page_to_image(page, settings)
        
        buffer = io.BytesIO()
        img.save(
            buffer, 
            format=settings.format, 
            optimize=settings.optimize, 
            quality=settings.quality
        )
        
        img_str = base64.b64encode(buffer.getvalue()).decode()
        
        return {
            "image": img_str,
            "total_pages": total_pages,
            "page_dimensions": {
                "width": width,
                "height": height
            },
            "settings_used": {
                "dpi": settings.dpi,
                "format": settings.format,
                "quality": settings.quality
            }
        }
        
    except Exception as e:
        logger.error(f"Error processing page {page_num}: {str(e)}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        return {
            "error": str(e),
            "details": traceback.format_exc()
        }
        
    finally:
        if buffer:
            buffer.close()
        if img:
            del img
        if doc:
            doc.close()
            del doc
        
        force_cleanup()
        end_memory = get_memory_usage_mb()
        logger.info(f"Completed page {page_num}. Memory change: {end_memory - start_memory:.1f}MB")

@app.route('/convert/<int:page_num>', methods=['POST'])
def handle_convert_page(page_num):
    if 'file' not in request.files:
        return jsonify({"error": "No file uploaded"}), 400
    
    file = request.files['file']
    if not file or file.filename == '':
        return jsonify({"error": "Invalid file"}), 400
    
    try:
        # Read file data and process immediately
        pdf_data = file.read()
        file_size_mb = len(pdf_data) / (1024 * 1024)
        
        logger.info(f"Received PDF file. Size: {file_size_mb:.1f}MB")
        
        if file_size_mb > 30:
            return jsonify({
                "error": "File too large",
                "details": f"File size ({file_size_mb:.1f}MB) exceeds 30MB limit"
            }), 413
        
        result = process_single_page(pdf_data, page_num)
        
        if "error" in result:
            return jsonify(result), 500
        
        return jsonify(result)
        
    except Exception as e:
        logger.error(f"Conversion error: {str(e)}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        return jsonify({
            "error": "PDF processing failed",
            "details": str(e)
        }), 500
        
    finally:
        force_cleanup()

if __name__ == "__main__":
    # Set resource limits
    resource.setrlimit(resource.RLIMIT_AS, (1024 * 1024 * 1024, -1))  # 1GB memory limit
    
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)