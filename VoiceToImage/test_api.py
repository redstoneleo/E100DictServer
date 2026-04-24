import requests
import time
import os

BASE_URL = "http://127.0.0.1:8000/VoiceToImage/"
AUDIO_FILE = "../dicts/speech.wav"  # Using an existing wav file from the project

def test_flow():
    if not os.path.exists(AUDIO_FILE):
        print(f"Audio file {AUDIO_FILE} not found. Please provide a valid audio file.")
        return

    # 1. Upload
    print(f"Uploading {AUDIO_FILE}...")
    with open(AUDIO_FILE, 'rb') as f:
        files = {'audio': f}
        response = requests.post(BASE_URL + "upload/", files=files)
    
    if response.status_code != 200:
        print(f"Upload failed: {response.text}")
        return
    
    data = response.json()
    task_id = data['task_id']
    print(f"Upload success. Task ID: {task_id}")

    # 2. Poll Status
    print("Waiting for processing...")
    while True:
        status_response = requests.get(BASE_URL + f"status/{task_id}/")
        status_data = status_response.json()
        status = status_data['status']
        print(f"Current Status: {status}")
        
        if status == 'COMPLETED':
            print("Processing complete!")
            print(f"Recognized Text: {status_data['recognized_text']}")
            print(f"Generated Image URL: {status_data['generated_image_url']}")
            break
        elif status == 'FAILED':
            print(f"Processing failed: {status_data['error_message']}")
            break
        
        time.sleep(5)

if __name__ == "__main__":
    # Make sure the server is running before executing this
    # python manage.py runserver
    # celery -A E100DictServer worker --loglevel=info
    test_flow()
