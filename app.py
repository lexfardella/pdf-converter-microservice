import fitz
import base64
import io
from PIL import Image
import traceback
from flask import Flask, request, jsonify
import os

app = Flask(__name__)

def convert_pdf_to_images(pdf_bytes, dpi=300, output_format="PNG"):
    encoded_images = []
    try:
        pdf_document = fitz.open(stream=pdf_bytes, filetype="pdf")
        total_pages = len(pdf_document)
        
        for page_num in range(total_pages):
            page = pdf_document.load_page(page_num)
            matrix = fitz.Matrix(dpi/72, dpi/72)
            pix = page.get_pixmap(matrix=matrix, alpha=False)
            
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            
            buffered = io.BytesIO()
            img.save(buffered, format=output_format, optimize=True, quality=95)
            img_str = base64.b64encode(buffered.getvalue()).decode()
            encoded_images.append(img_str)
        
        pdf_document.close()
        
        return {
            "total_pages": total_pages,
            "images": encoded_images
        }
    except Exception as e:
        return {
            "error": str(e),
            "traceback": traceback.format_exc()
        }

@app.route('/')
def home():
    return "PDF Converter Microservice is running!"

@app.route('/convert', methods=['POST'])
def handle_convert():
    if 'file' not in request.files:
        return jsonify({"error": "No file part"}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "No selected file"}), 400

    pdf_bytes = file.read()
    result = convert_pdf_to_images(pdf_bytes)
    return jsonify(result)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)