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
import mmap
from contextlib import contextmanager

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 30 * 1024 * 1024  # 30MB limit

@dataclass
class ProcessingSettings:
    dpi: int = 300
    max_dimension: int = 2400
    format: str = "PNG"
    chunk_size: int = 50 * 1024 * 1024  # 50MB chunks for processing

@contextmanager
def memory_tracker(label: str):
    """Track memory usage within a context"""
    gc.collect()
    process = psutil.Process(os.getpid())
    start_mem = process.memory_info().rss / 1024 / 1024
    print(f"{label} - Starting memory: {start_mem:.1f}MB")
    try:
        yield
    finally:
        gc.collect()
        end_mem = process.memory_info().rss / 1024 / 1024
        print(f"{label} - Ending memory: {end_mem:.1f}MB (Change: {end_mem - start_mem:.1f}MB)")

def create_memory_mapped_buffer(size: int) -> mmap.mmap:
    """Create a memory-mapped buffer for large data handling"""
    fd = os.open('/tmp', os.O_TMPFILE | os.O_RDWR, 0o600)
    os.write(fd, b'\0' * size)
    buffer = mmap.mmap(fd, size, mmap.MAP_SHARED, mmap.PROT_READ | mmap.PROT_WRITE)
    os.close(fd)
    return buffer

def process_page(page: fitz.Page, settings: ProcessingSettings) -> Optional[str]:
    """Process single page with optimized memory usage"""
    with memory_tracker(f"Page {page.number + 1}"):
        try:
            # Calculate optimal scale
            width, height = page.rect.width, page.rect.height
            scale = min(settings.max_dimension / max(width, height), 1.0) * (settings.dpi/72)
            matrix = fitz.Matrix(scale, scale)
            
            # Get pixmap in chunks
            with memory_tracker("Pixmap creation"):
                pix = page.get_pixmap(matrix=matrix, alpha=False)
            
            # Create memory-mapped buffer for large images
            buffer_size = pix.width * pix.height * 3 + 1024 * 1024  # Add 1MB padding
            with memory_tracker("Image processing"):
                # Use memory-mapped file for large data
                with create_memory_mapped_buffer(buffer_size) as mm:
                    # Convert to PIL Image using memory-mapped buffer
                    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                    
                    # Free pixmap memory immediately
                    del pix
                    gc.collect()
                    
                    # Use BytesIO with memory-mapped backend
                    bio = io.BytesIO(mm)
                    img.save(bio, format=settings.format, optimize=True)
                    
                    # Get base64 in chunks
                    bio.seek(0)
                    b64_str = base64.b64encode(bio.read()).decode()
                    
                    # Cleanup
                    del img
                    bio.close()
                    
            gc.collect()
            return b64_str
            
        except Exception as e:
            print(f"Error processing page {page.number + 1}: {str(e)}")
            traceback.print_exc()
            return None

def convert_pdf_to_images(pdf_bytes: bytes) -> Dict:
    """Convert PDF to images with optimized memory handling"""
    images: List[str] = []
    settings = ProcessingSettings()
    
    with memory_tracker("PDF Processing"):
        try:
            # Open document with memory tracking
            with memory_tracker("Document loading"):
                doc = fitz.open(stream=pdf_bytes, filetype="pdf")
                total_pages = len(doc)
            
            # Process each page
            for page_num in range(total_pages):
                with memory_tracker(f"Full page {page_num + 1} processing"):
                    try:
                        # Load and process single page
                        page = doc.load_page(page_num)
                        img_str = process_page(page, settings)
                        
                        if img_str:
                            images.append(img_str)
                        else:
                            images.append("")
                        
                        # Explicit cleanup
                        del page
                        gc.collect()
                        
                    except Exception as e:
                        print(f"Error on page {page_num + 1}: {str(e)}")
                        images.append("")
                        gc.collect()
                        
            doc.close()
            return {
                "images": images,
                "total_pages": total_pages
            }
            
        except Exception as e:
            return {
                "error": str(e),
                "traceback": traceback.format_exc()
            }

@app.route('/convert', methods=['POST'])
def handle_convert():
    if 'file' not in request.files:
        return jsonify({"error": "No file part"}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "No selected file"}), 400
    
    try:
        # Process in memory-tracked context
        with memory_tracker("Full request"):
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