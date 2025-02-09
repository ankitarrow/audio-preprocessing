import ffmpeg
import os
import requests
from uuid import uuid4
from flask import Flask, request, jsonify
from flask_cors import CORS
from azure.storage.blob import BlobServiceClient, generate_blob_sas, BlobSasPermissions
from datetime import datetime, timedelta
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Initialize Flask app
app = Flask(__name__)
CORS(app)  # Enable CORS for all origins

# Azure Storage Configuration
ACCOUNT_URL = os.getenv('ACCOUNT_URL')
STORAGE_ACCOUNT_KEY = os.getenv('STORAGE_ACCOUNT_KEY')  # Use storage account key instead of SAS token

# Initialize Azure Blob Service client
blob_service_client = BlobServiceClient(account_url=ACCOUNT_URL, credential=STORAGE_ACCOUNT_KEY)

def parse_duration(duration_str):
    """Convert duration in 'mm:ss' format or plain seconds to seconds."""
    if ":" in duration_str:
        minutes, seconds = map(float, duration_str.split(":"))
        return int(minutes * 60 + seconds)  # Fix incorrect 61 multiplier
    else:
        return int(float(duration_str))

@app.route("/", methods=["GET"])
def home():
    return jsonify({
        "message": "Welcome to the Flask server!",
        "status": "success"
    }), 200

@app.route('/trim-audio', methods=['POST'])
def trim_audio():
    try:
        # Parse input JSON
        data = request.json
        audio_url = data.get("audio_url")
        start_time_str = data.get("start_time")
        end_time_str = data.get("end_time")

        if not audio_url or not start_time_str or not end_time_str:
            return jsonify({"error": "Invalid input data"}), 400  # Bad request

        # Convert start and end times to seconds
        start_time = parse_duration(start_time_str)
        end_time = parse_duration(end_time_str)

        if end_time <= start_time:
            return jsonify({"error": "End time must be greater than start time"}), 400  # Bad request

        # Download audio from the provided URL
        local_audio_path = f"temp/{uuid4()}.mp3"
        os.makedirs("temp", exist_ok=True)
        response = requests.get(audio_url)

        if response.status_code != 200:
            return jsonify({"error": "Failed to download audio"}), 500  # Internal Server Error

        with open(local_audio_path, "wb") as audio_file:
            audio_file.write(response.content)

        # Define output path for the trimmed audio
        trimmed_audio_path = f"temp/{uuid4()}_trimmed.mp3"

        # Use ffmpeg to trim the audio
        ffmpeg.input(local_audio_path, ss=start_time, to=end_time).output(trimmed_audio_path).run(cmd=['ffmpeg', '-y'])

        # Upload trimmed audio to Azure Blob Storage
        container_name = "upload-temp"
        blob_name = f"{uuid4()}.mp3"
        container_client = blob_service_client.get_container_client(container_name)
        blob_client = container_client.get_blob_client(blob_name)

        with open(trimmed_audio_path, "rb") as audio_file:
            blob_client.upload_blob(audio_file, overwrite=True)

        # Generate a temporary signed URL (SAS) for secure access
        sas_token = generate_blob_sas(
            account_name=ACCOUNT_URL.replace("https://", "").split(".")[0],
            container_name=container_name,
            blob_name=blob_name,
            account_key=STORAGE_ACCOUNT_KEY,
            permission=BlobSasPermissions(read=True),
            expiry=datetime.utcnow() + timedelta(hours=1)  # 1-hour expiry
        )

        trimmed_audio_url = f"{ACCOUNT_URL}/{container_name}/{blob_name}?{sas_token}"

        # Cleanup local files
        os.remove(local_audio_path)
        os.remove(trimmed_audio_path)

        return jsonify({"trimmed_audio_url": trimmed_audio_url}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500  # Internal Server Error

if __name__ == '__main__':
    app.run(
        host='0.0.0.0',
        port=5001,
        ssl_context=(
            '/etc/ssl/certs/selfsigned.crt',
            '/etc/ssl/private/selfsigned.key'
        )
    )
