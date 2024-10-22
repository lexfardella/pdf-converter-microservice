import fitz
import base64
import io
from PIL import Image
import traceback
from flask import Flask, request, jsonify
import os
import gc
from werkzeug.wsgi import FileWrapper

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 30 * 1024 * 1024

def get_pdf_info(pdf_bytes):
    try:
        pdf_document = fitz.open(stream=pdf_bytes, filetype="pdf")
        total_pages = len(pdf_document)
        pdf_document.close()
        return {"total_pages": total_pages}
    except Exception as e:
        return {"error": str(e)}

def convert_single_page(pdf_bytes, page_number, dpi=300, output_format="PNG"):
    try:
        pdf_document = fitz.open(stream=pdf_bytes, filetype="pdf")
        page = pdf_document.load_page(page_number)
        
        matrix = fitz.Matrix(dpi/72, dpi/72)
        pix = page.get_pixmap(matrix=matrix, alpha=False)
        
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        
        buffered = io.BytesIO()
        img.save(buffered, format=output_format, optimize=True, quality=95)
        img_str = base64.b64encode(buffered.getvalue()).decode()
        
        pdf_document.close()
        del pix
        del img
        buffered.close()
        gc.collect()
        
        return {"image": img_str, "page_number": page_number}
    except Exception as e:
        return {"error": str(e), "page_number": page_number}

@app.route('/')
def home():
    return "PDF Converter Microservice is running!"

@app.route('/pdf-info', methods=['POST'])
def get_info():
    if 'file' not in request.files:
        return jsonify({"error": "No file part"}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "No selected file"}), 400

    pdf_bytes = file.read()
    info = get_pdf_info(pdf_bytes)
    return jsonify(info)

@app.route('/convert-page/<int:page_number>', methods=['POST'])
def convert_page(page_number):
    if 'file' not in request.files:
        return jsonify({"error": "No file part"}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "No selected file"}), 400

    pdf_bytes = file.read()
    result = convert_single_page(pdf_bytes, page_number)
    gc.collect()
    return jsonify(result)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)