import fitz
import base64
import io
from PIL import Image
import traceback
from flask import Flask, request, jsonify
import os
import gc

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 30 * 1024 * 1024  # 30MB limit

def convert_page_to_image(page, dpi=300, output_format="PNG"):
    try:
        matrix = fitz.Matrix(dpi/72, dpi/72)
        pix = page.get_pixmap(matrix=matrix, alpha=False)
        
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        
        buffered = io.BytesIO()
        img.save(buffered, format=output_format, optimize=True, quality=95)
        img_str = base64.b64encode(buffered.getvalue()).decode()
        
        # Clear memory
        del pix
        del img
        buffered.close()
        gc.collect()
        
        return img_str
    except Exception as e:
        print(f"Error converting page: {str(e)}")
        return None

def convert_pdf_to_images(pdf_bytes, dpi=300, output_format="PNG"):
    encoded_images = []
    try:
        print(f"Processing PDF of size: {len(pdf_bytes)} bytes")
        pdf_document = fitz.open(stream=pdf_bytes, filetype="pdf")
        total_pages = len(pdf_document)
        print(f"PDF has {total_pages} pages")
        
        for page_num in range(total_pages):
            print(f"Processing page {page_num + 1}")
            page = pdf_document.load_page(page_num)
            img_str = convert_page_to_image(page, dpi, output_format)
            
            if img_str:
                encoded_images.append(img_str)
            else:
                encoded_images.append(None)
            
            # Clear memory after each page
            del page
            gc.collect()
        
        pdf_document.close()
        gc.collect()
        
        print("PDF processing completed successfully")
        
        return {
            "total_pages": total_pages,
            "images": encoded_images,
            "failed_pages": [i for i, img in enumerate(encoded_images) if img is None]
        }
    except Exception as e:
        print(f"Error in convert_pdf_to_images: {str(e)}")
        print(traceback.format_exc())
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
        if 'file' not in request.files:
            return jsonify({"error": "No file part"}), 400
        file = request.files['file']
        if file.filename == '':
            return jsonify({"error": "No selected file"}), 400

        pdf_bytes = file.read()
        result = convert_pdf_to_images(pdf_bytes)
        gc.collect()  # Final memory cleanup
        return jsonify(result)
    except Exception as e:
        print(f"Error in handle_convert: {str(e)}")
        print(traceback.format_exc())
        return jsonify({"error": str(e), "traceback": traceback.format_exc()}), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)