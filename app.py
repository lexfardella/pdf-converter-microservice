import fitz
import base64
import io
from PIL import Image
import traceback
from flask import Flask, request, jsonify
import os
import gc
import psutil
from typing import Optional
from dataclasses import dataclass

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 30 * 1024 * 1024  # 30MB limit

@dataclass
class QualitySettings:
    dpi: int = 300               # Maintain 300 DPI for high quality
    format: str = "PNG"          # Use PNG for lossless quality
    max_dimension: int = 4096    # Allow larger dimensions for detail
    optimize: bool = True        # Optimize without quality loss

def cleanup_memory():
    gc.collect()

def get_memory_usage_mb() -> float:
    process = psutil.Process(os.getpid())
    return process.memory_info().rss / 1024 / 1024

def process_single_page(pdf_bytes: bytes, page_num: int, settings: QualitySettings) -> Optional[dict]:
    """Process a single page from PDF with high quality settings"""
    doc = None
    try:
        cleanup_memory()
        print(f"Memory before processing page {page_num}: {get_memory_usage_mb():.1f}MB")
        
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        total_pages = len(doc)
        
        if page_num >= total_pages:
            return {
                "error": "Page number exceeds document length",
                "total_pages": total_pages
            }
        
        # Process with high quality settings
        page = doc.load_page(page_num)
        
        # Use exact DPI scaling
        scale = settings.dpi / 72  # Convert from PDF points to pixels
        matrix = fitz.Matrix(scale, scale)
        
        # Get high-quality pixmap
        pix = page.get_pixmap(matrix=matrix, alpha=False)
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        
        # Only resize if absolutely necessary for memory constraints
        if max(img.width, img.height) > settings.max_dimension:
            ratio = settings.max_dimension / max(img.width, img.height)
            new_size = (int(img.width * ratio), int(img.height * ratio))
            img = img.resize(new_size, Image.Resampling.LANCZOS)
        
        # Save with lossless settings
        buffer = io.BytesIO()
        if settings.format == "PNG":
            img.save(
                buffer,
                format="PNG",
                optimize=settings.optimize,
            )
        else:
            img.save(
                buffer,
                format="JPEG",
                quality=100,  # Maximum quality if JPEG is used
                optimize=settings.optimize
            )
        
        img_str = base64.b64encode(buffer.getvalue()).decode()
        
        # Cleanup
        del pix
        del img
        buffer.close()
        cleanup_memory()
        
        print(f"Memory after processing page {page_num}: {get_memory_usage_mb():.1f}MB")
        
        return {
            "image": img_str,
            "page_number": page_num,
            "total_pages": total_pages,
            "width": img.width,
            "height": img.height,
            "dpi": settings.dpi
        }
        
    except Exception as e:
        print(f"Error processing page {page_num}: {str(e)}")
        return {
            "error": str(e),
            "page_number": page_num
        }
    finally:
        if doc:
            doc.close()
        cleanup_memory()

@app.route('/convert/<int:page_num>', methods=['POST'])
def handle_convert_page(page_num):
    if 'file' not in request.files:
        return jsonify({"error": "No file part"}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "No selected file"}), 400
    
    # Use high quality settings
    settings = QualitySettings(
        dpi=300,          # Maintain 300 DPI
        format="PNG",     # Use PNG for lossless quality
        max_dimension=4096  # Allow large dimensions
    )
    
    try:
        pdf_bytes = file.read()
        result = process_single_page(pdf_bytes, page_num, settings)
        
        if "error" in result:
            return jsonify(result), 500
            
        return jsonify(result)
        
    except Exception as e:
        return jsonify({
            "error": "PDF processing failed",
            "details": str(e)
        }), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)