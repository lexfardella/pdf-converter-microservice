import requests
import urllib3
import ssl
import os

# Disable warnings about insecure requests - use only for testing
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Replace with your actual Heroku app URL
heroku_url = "https://pdf-converter-microservice-67628533e7ab.herokuapp.com/convert"

# List PDF files in the current directory
pdf_files = [f for f in os.listdir('.') if f.endswith('.pdf')]

if not pdf_files:
    print("No PDF files found in the current directory.")
    exit()

print("Available PDF files:")
for i, file in enumerate(pdf_files, 1):
    print(f"{i}. {file}")

# Ask user to select a file
while True:
    try:
        selection = int(input("Enter the number of the file you want to use: ")) - 1
        if 0 <= selection < len(pdf_files):
            pdf_file_path = pdf_files[selection]
            break
        else:
            print("Invalid selection. Please try again.")
    except ValueError:
        print("Please enter a number.")

def test_with_ssl_verification(verify=True):
    try:
        # Open the PDF file in binary mode
        with open(pdf_file_path, "rb") as pdf_file:
            # Prepare the files for the POST request
            files = {"file": (pdf_file_path, pdf_file, "application/pdf")}
            
            # Send the POST request to your Heroku app
            response = requests.post(heroku_url, files=files, verify=verify)

        # Check the response
        if response.status_code == 200:
            print("Success! Response content:")
            print(response.text)
        else:
            print(f"Error: {response.status_code}")
            print(response.text)
    except requests.exceptions.SSLError as e:
        print(f"SSL Error occurred: {e}")
    except requests.exceptions.RequestException as e:
        print(f"An error occurred: {e}")
    except FileNotFoundError:
        print(f"File not found: {pdf_file_path}")

print("\nTesting with SSL verification:")
test_with_ssl_verification()

print("\nTesting without SSL verification (insecure, use only for testing):")
test_with_ssl_verification(verify=False)