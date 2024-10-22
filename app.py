import fitz
import base64
import io
from PIL import Image
import traceback
from flask import Flask, request, jsonify
import os
import gc
import psutil
from typing import List, Dict, Optional
from dataclasses import dataclass

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 30 * 1024 * 1024  # 30MB limit

@dataclass
class PageConfig:
    max_dimension: int = 1920
    quality: int = 85
    format: str = "JPEG"

def get_memory_usage_mb() -> float:
    """Get current memory usage in MB"""
    process = psutil.Process(os.getpid())
    return process.memory_info().rss / 1024 / 1024

def cleanup_memory():
    """Force garbage collection and memory cleanup"""
    gc.collect()
    
def process_single_page(page: fitz.Page, config: PageConfig) -> Optional[str]:
    """Process a single page with memory management"""
    try:
        # Calculate optimal scale based on page size
        width, height = page.rect.width, page.rect.height
        scale = min(config.max_dimension / max(width, height), 1.0)
        matrix = fitz.Matrix(scale, scale)
        
        # Get pixmap with minimal memory usage
        pix = page.get_pixmap(matrix=matrix, alpha=False)
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        
        # Optimize and encode
        buffer = io.BytesIO()
        img.save(buffer, format=config.format, optimize=True, quality=config.quality)
        img_str = base64.b64encode(buffer.getvalue()).decode()
        
        # Cleanup
        del pix
        del img
        buffer.close()
        cleanup_memory()
        
        return img_str
    except Exception as e:
        print(f"Error processing page: {str(e)}")
        return None
    
def convert_pdf_to_images(pdf_bytes: bytes) -> Dict:
    """Convert PDF to images with careful memory management"""
    images: List[Optional[str]] = []
    failed_pages: List[int] = []
    doc = None
    
    try:
        # Open document
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        total_pages = len(doc)
        config = PageConfig()
        
        # Process pages one at a time
        for page_num in range(total_pages):
            try:
                # Load and process single page
                page = doc.load_page(page_num)
                img_str = process_single_page(page, config)
                
                if img_str:
                    images.append(img_str)
                else:
                    images.append(None)
                    failed_pages.append(page_num)
                
                # Cleanup after each page
                del page
                cleanup_memory()
                
                # Log memory usage
                current_mem = get_memory_usage_mb()
                print(f"Memory after page {page_num + 1}/{total_pages}: {current_mem:.1f}MB")
                
            except Exception as e:
                print(f"Error on page {page_num}: {str(e)}")
                images.append(None)
                failed_pages.append(page_num)
                cleanup_memory()
                
    except Exception as e:
        return {
            "error": str(e),
            "traceback": traceback.format_exc()
        }
    finally:
        if doc:
            doc.close()
        cleanup_memory()
    
    return {
        "total_pages": len(images),
        "images": images,
        "failed_pages": failed_pages,
        "memory_usage_mb": get_memory_usage_mb()
    }

@app.route('/convert', methods=['POST'])
def handle_convert():
    if 'file' not in request.files:
        return jsonify({"error": "No file part"}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "No selected file"}), 400
    
    try:
        # Read file and process
        pdf_bytes = file.read()
        result = convert_pdf_to_images(pdf_bytes)
        
        # Check for errors
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