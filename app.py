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
class ImageSettings:
    dpi: int = 300               # Higher DPI for better text clarity
    max_dimension: int = 2400    # Larger dimension to preserve detail
    jpeg_quality: int = 95       # Higher quality to prevent artifacts
    format: str = "PNG"          # PNG for better text clarity
    optimize: bool = True        # Still optimize without losing quality

def cleanup_memory():
    """Force garbage collection and memory cleanup"""
    gc.collect()

def get_memory_usage_mb() -> float:
    process = psutil.Process(os.getpid())
    return process.memory_info().rss / 1024 / 1024

def process_page(page: fitz.Page, settings: ImageSettings) -> Optional[str]:
    """Process single page optimized for LLM analysis"""
    try:
        # Calculate scale based on DPI
        scale = settings.dpi / 72  # Convert PDF points to pixels
        matrix = fitz.Matrix(scale, scale)
        
        # Get pixmap with text-optimized settings
        pix = page.get_pixmap(matrix=matrix, alpha=False)
        
        # Convert to PIL Image
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        
        # Check if dimensions need scaling down for memory constraints
        if max(img.width, img.height) > settings.max_dimension:
            ratio = settings.max_dimension / max(img.width, img.height)
            new_size = (int(img.width * ratio), int(img.height * ratio))
            img = img.resize(new_size, Image.Resampling.LANCZOS)
        
        # Optimize and encode
        buffer = io.BytesIO()
        
        if settings.format == "PNG":
            # PNG optimization for text
            img.save(
                buffer,
                format="PNG",
                optimize=settings.optimize,
            )
        else:
            # JPEG with high quality
            img.save(
                buffer,
                format="JPEG",
                quality=settings.jpeg_quality,
                optimize=settings.optimize
            )
        
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
    """Convert PDF to images with focus on text clarity"""
    images: List[str] = []
    doc = None
    settings = ImageSettings()  # Use text-optimized default settings
    
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        total_pages = len(doc)
        
        for page_num in range(total_pages):
            try:
                print(f"Processing page {page_num + 1}/{total_pages}")
                mem_before = get_memory_usage_mb()
                print(f"Memory before processing: {mem_before:.1f}MB")
                
                page = doc.load_page(page_num)
                img_str = process_page(page, settings)
                
                if img_str:
                    images.append(img_str)
                else:
                    images.append("")
                
                # Cleanup after each page
                del page
                cleanup_memory()
                
                mem_after = get_memory_usage_mb()
                print(f"Memory after processing: {mem_after:.1f}MB")
                print(f"Memory change: {mem_after - mem_before:.1f}MB")
                
            except Exception as e:
                print(f"Error on page {page_num}: {str(e)}")
                images.append("")
                cleanup_memory()
                
        return {
            "images": images,
            "total_pages": total_pages
        }
        
    except Exception as e:
        return {
            "error": str(e),
            "traceback": traceback.format_exc()
        }
    finally:
        if doc:
            doc.close()
        cleanup_memory()

@app.route('/convert', methods=['POST'])
def handle_convert():
    if 'file' not in request.files:
        return jsonify({"error": "No file part"}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "No selected file"}), 400
    
    try:
        pdf_bytes = file.read()
        result = convert_pdf_to_images(pdf_bytes)
        
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