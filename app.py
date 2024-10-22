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
import logging
import mmap
import resource
import sys

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 31457280  # 30MB

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@dataclass
class QualitySettings:
    dpi: int = 150  # Reduced default DPI
    format: str = "JPEG"
    max_dimension: int = 1800  # Reduced max dimension
    quality: int = 75  # Lower default quality
    optimize: bool = True

    def adjust_for_page_size(self, page_size_mb: float) -> None:
        if page_size_mb > 15:  # Very large page
            self.dpi = 125
            self.quality = 70
            self.max_dimension = 1600
        elif page_size_mb > 8:  # Large page
            self.dpi = 150
            self.quality = 75
            self.max_dimension = 1800

def limit_memory(max_mem_mb: int = 512) -> None:
    """Set memory limits for the process"""
    soft, hard = resource.getrlimit(resource.RLIMIT_AS)
    resource.setrlimit(resource.RLIMIT_AS, (max_mem_mb * 1024 * 1024, hard))

def get_memory_usage_mb() -> float:
    process = psutil.Process(os.getpid())
    mem = process.memory_info().rss / 1024 / 1024
    logger.info(f"Current memory usage: {mem:.1f}MB")
    return mem

def force_cleanup() -> None:
    """Aggressive memory cleanup"""
    gc.collect()
    
    # Clear PIL's internal cache
    Image.preinit()
    
    if hasattr(sys, 'exc_clear'):
        sys.exc_clear()
    
    # Try to release memory back to OS
    try:
        import ctypes
        libc = ctypes.CDLL('libc.so.6')
        libc.malloc_trim(0)
    except:
        pass

def process_image_chunk(img: Image.Image, max_chunk_size: int = 1024) -> Image.Image:
    """Process image in chunks to reduce memory usage"""
    width, height = img.size
    if width <= max_chunk_size and height <= max_chunk_size:
        return img

    # Process image in chunks
    new_img = Image.new(img.mode, img.size)
    for y in range(0, height, max_chunk_size):
        for x in range(0, width, max_chunk_size):
            box = (x, y, min(x + max_chunk_size, width), min(y + max_chunk_size, height))
            chunk = img.crop(box)
            new_img.paste(chunk, box)
            del chunk
            force_cleanup()
    return new_img

def process_page_to_image(page: fitz.Page, settings: QualitySettings) -> Tuple[Image.Image, int, int]:
    """Convert PDF page to PIL Image with memory optimization"""
    try:
        # Calculate scale
        scale = settings.dpi / 72
        matrix = fitz.Matrix(scale, scale)
        
        # Get pixmap in chunks if possible
        pix = page.get_pixmap(matrix=matrix, alpha=False)
        
        # Convert to PIL Image
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        del pix
        force_cleanup()
        
        # Process in chunks if large
        if max(img.size) > settings.max_dimension:
            # Calculate new size
            width, height = img.size
            ratio = settings.max_dimension / max(width, height)
            new_size = (int(width * ratio), int(height * ratio))
            
            # Resize in chunks
            img = process_image_chunk(img)
            img = img.resize(new_size, Image.Resampling.LANCZOS)
        
        return img, *img.size
        
    except Exception as e:
        logger.error(f"Error in image processing: {str(e)}")
        raise

def process_single_page(pdf_data: bytes, page_num: int) -> Dict:
    """Process a single page with optimized memory handling"""
    start_memory = get_memory_usage_mb()
    logger.info(f"Starting page {page_num} processing. Initial memory: {start_memory:.1f}MB")
    
    doc = None
    img = None
    buffer = None
    settings = QualitySettings()
    
    try:
        # Set memory limit for this process
        limit_memory(512)  # 512MB limit
        
        # Open document
        doc = fitz.open(stream=pdf_data, filetype="pdf")
        total_pages = len(doc)
        
        if page_num >= total_pages:
            return {
                "error": f"Page number exceeds document length ({total_pages} pages)",
                "total_pages": total_pages
            }
        
        # Process page
        page = doc.load_page(page_num)
        estimated_size = (page.rect.width * page.rect.height * settings.dpi * settings.dpi) / (72 * 72 * 1024 * 1024)
        settings.adjust_for_page_size(estimated_size)
        
        img, width, height = process_page_to_image(page, settings)
        
        # Convert to bytes
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
            img.close()
        if doc:
            doc.close()
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
        # Read file data
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
    # Set process-wide memory limit
    limit_memory(512)  # 512MB limit
    
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)