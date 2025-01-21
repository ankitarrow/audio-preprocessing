import ffmpeg
import os
import requests
from uuid import uuid4
from flask import Flask, request, jsonify
from flask_cors import CORS
from azure.storage.blob import BlobServiceClient
from dotenv import load_dotenv
load_dotenv()
# Initialize Flask app
app = Flask(__name__)

# Enable CORS for all origins
CORS(app)

# Azure Storage account URL and SAS token
account_url = os.getenv('ACCOUNT_URL')
sas_token = os.getenv('SAS_TOKEN')
# Initialize Azure Blob Service client using account URL and SAS token
blob_service_client = BlobServiceClient(account_url=f"{ACCOUNT_URL}?{SAS_TOKEN}")

def parse_duration(duration_str):
    """Convert duration in 'mm:ss' format or plain seconds to seconds."""
    if ":" in duration_str:
        minutes, seconds = map(float, duration_str.split(":"))
        return int(minutes * 60 + seconds)
    else:
        return int(float(duration_str))

@app.route('/trim-audio', methods=['POST'])
def trim_audio():
    try:
        # Parse input data from JSON
        data = request.json
        audio_url = data.get("audio_url")
        start_time_str = data.get("start_time")
        end_time_str = data.get("end_time")

        if not audio_url or not start_time_str or not end_time_str:
            return jsonify({"error": "Invalid input data"}), 400

        # Convert start and end times to seconds
        start_time = parse_duration(start_time_str)
        end_time = parse_duration(end_time_str)

        # Ensure that end time is greater than start time
        if end_time <= start_time:
            return jsonify({"error": "End time must be greater than start time"}), 400

        # Download audio from the provided URL
        local_audio_path = f"temp/{uuid4()}.mp3"
        os.makedirs("temp", exist_ok=True)
        response = requests.get(audio_url)

        if response.status_code != 200:
            return jsonify({"error": "Failed to download audio"}), 400

        with open(local_audio_path, "wb") as audio_file:
            audio_file.write(response.content)

        # Define output path for the trimmed audio
        trimmed_audio_path = f"temp/{uuid4()}_trimmed.mp3"

        # Use ffmpeg to trim the audio
        ffmpeg.input(local_audio_path, ss=start_time, to=end_time).output(trimmed_audio_path).run(cmd=r'C:\ffmpeg\bin\ffmpeg')


        # Upload trimmed audio to Azure Blob Storage
        container_client = blob_service_client.get_container_client("upload-temp")
        blob_name = f"{uuid4()}.mp3"
        blob_client = container_client.get_blob_client(blob_name)

        with open(trimmed_audio_path, "rb") as audio_file:
            blob_client.upload_blob(audio_file, overwrite=True)

        # Generate URL for the trimmed audio
        trimmed_audio_url = f"{ACCOUNT_URL}/upload-temp/{blob_name}?{SAS_TOKEN}"

        # Cleanup local files
        os.remove(local_audio_path)
        os.remove(trimmed_audio_path)

        return jsonify({"trimmed_audio_url": trimmed_audio_url}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True, port=5000)
