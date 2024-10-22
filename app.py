import os
import gc
import fitz
import base64
from PIL import Image
import io
from flask import Flask, request, jsonify
from flask_cors import CORS
import time
import logging
import psutil
import sys

app = Flask(__name__)
CORS(app)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def log_memory_usage(message):
    """Log current memory usage with a custom message"""
    process = psutil.Process(os.getpid())
    memory_mb = process.memory_info().rss / 1024 / 1024
    logger.info(f"{message}: {memory_mb:.1f}MB")

def cleanup_resources():
    """Force garbage collection and clear memory"""
    gc.collect()
    if hasattr(sys, 'set_asyncgen_hooks'):
        sys.set_asyncgen_hooks(None)
    log_memory_usage("Memory after cleanup")

def convert_page_to_images(pdf_data, page_number):
    """Convert a single PDF page to image with memory management"""
    try:
        log_memory_usage(f"Memory before processing page {page_number}")
        
        # Create a temporary file for the PDF data
        temp_pdf_path = f"temp_pdf_{page_number}.pdf"
        with open(temp_pdf_path, "wb") as pdf_file:
            pdf_file.write(pdf_data)
        
        # Open PDF and process single page
        pdf_document = fitz.open(temp_pdf_path)
        
        if page_number >= pdf_document.page_count:
            pdf_document.close()
            os.remove(temp_pdf_path)
            return None
            
        page = pdf_document[page_number]
        pix = page.get_pixmap(matrix=fitz.Matrix(300/72, 300/72))
        
        # Convert to PIL Image
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        
        # Convert to base64
        img_byte_arr = io.BytesIO()
        img.save(img_byte_arr, format='PNG', optimize=True)
        img_byte_arr = img_byte_arr.getvalue()
        img_base64 = base64.b64encode(img_byte_arr).decode('utf-8')
        
        # Cleanup
        pdf_document.close()
        os.remove(temp_pdf_path)
        del pix
        del img
        
        log_memory_usage(f"Memory after processing page {page_number}")
        cleanup_resources()
        
        return img_base64
        
    except Exception as e:
        logger.error(f"Error processing page {page_number}: {str(e)}")
        cleanup_resources()
        return None

@app.route('/convert/<int:page_number>', methods=['POST'])
def convert_pdf_page(page_number):
    """Endpoint to convert a specific PDF page to image"""
    try:
        if 'file' not in request.files:
            return jsonify({'error': 'No file provided'}), 400

        pdf_file = request.files['file']
        if not pdf_file.filename.endswith('.pdf'):
            return jsonify({'error': 'File must be a PDF'}), 400

        # Read PDF data
        pdf_data = pdf_file.read()
        
        # Process single page
        result = convert_page_to_images(pdf_data, page_number)
        
        if result is None:
            return jsonify({'error': f'Page {page_number} could not be processed'}), 404
            
        return jsonify({
            'status': 'success',
            'page': page_number,
            'image': result
        })

    except Exception as e:
        logger.error(f"Error in convert_pdf_page: {str(e)}")
        cleanup_resources()
        return jsonify({'error': str(e)}), 500

@app.route('/pagecount', methods=['POST'])
def get_page_count():
    """Endpoint to get the total number of pages in a PDF"""
    try:
        if 'file' not in request.files:
            return jsonify({'error': 'No file provided'}), 400

        pdf_file = request.files['file']
        if not pdf_file.filename.endswith('.pdf'):
            return jsonify({'error': 'File must be a PDF'}), 400

        # Create temporary file
        temp_pdf_path = "temp_pdf_count.pdf"
        pdf_file.save(temp_pdf_path)
        
        # Get page count
        pdf_document = fitz.open(temp_pdf_path)
        page_count = pdf_document.page_count
        
        # Cleanup
        pdf_document.close()
        os.remove(temp_pdf_path)
        cleanup_resources()
        
        return jsonify({
            'status': 'success',
            'pageCount': page_count
        })

    except Exception as e:
        logger.error(f"Error in get_page_count: {str(e)}")
        cleanup_resources()
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True)