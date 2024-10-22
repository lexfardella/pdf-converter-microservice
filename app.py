import fitz
import base64
import io
from PIL import Image
import traceback
from flask import Flask, request, jsonify
import os
import sys

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 30 * 1024 * 1024  # 30MB limit

def convert_pdf_to_images(pdf_bytes, dpi=300, output_format="PNG"):
    encoded_images = []
    try:
        print(f"Processing PDF of size: {len(pdf_bytes)} bytes", file=sys.stderr)  # Debug log
        pdf_document = fitz.open(stream=pdf_bytes, filetype="pdf")
        total_pages = len(pdf_document)
        print(f"PDF has {total_pages} pages", file=sys.stderr)  # Debug log
        
        for page_num in range(total_pages):
            print(f"Processing page {page_num + 1}", file=sys.stderr)  # Debug log
            page = pdf_document.load_page(page_num)
            matrix = fitz.Matrix(dpi/72, dpi/72)
            pix = page.get_pixmap(matrix=matrix, alpha=False)
            
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            
            buffered = io.BytesIO()
            img.save(buffered, format=output_format, optimize=True, quality=95)
            img_str = base64.b64encode(buffered.getvalue()).decode()
            encoded_images.append(img_str)
        
        pdf_document.close()
        print("PDF processing completed successfully", file=sys.stderr)  # Debug log
        
        return {
            "total_pages": total_pages,
            "images": encoded_images
        }
    except Exception as e:
        print(f"Error in convert_pdf_to_images: {str(e)}", file=sys.stderr)  # Debug log
        print(traceback.format_exc(), file=sys.stderr)  # Debug log
        return {
            "error": str(e),
            "traceback": traceback.format_exc()
        }

@app.route('/')
def home():
    return "PDF Converter Microservice is running!"

@app.route('/convert', methods=['POST'])
def handle_convert():
    try:
        print("Received convert request", file=sys.stderr)  # Debug log
        if 'file' not in request.files:
            return jsonify({"error": "No file part"}), 400
        file = request.files['file']
        if file.filename == '':
            return jsonify({"error": "No selected file"}), 400

        print(f"Processing file: {file.filename}", file=sys.stderr)  # Debug log
        pdf_bytes = file.read()
        print(f"File size: {len(pdf_bytes)} bytes", file=sys.stderr)  # Debug log
        
        result = convert_pdf_to_images(pdf_bytes)
        return jsonify(result)
    except Exception as e:
        print(f"Error in handle_convert: {str(e)}", file=sys.stderr)  # Debug log
        print(traceback.format_exc(), file=sys.stderr)  # Debug log
        return jsonify({"error": str(e), "traceback": traceback.format_exc()}), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)