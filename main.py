import ffmpeg
import os
import requests
import logging
from uuid import uuid4
from flask import Flask, request, jsonify
from flask_cors import CORS
from azure.storage.blob import BlobServiceClient
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.DEBUG)

# Initialize Flask app
app = Flask(__name__)

# Enable CORS for all origins
CORS(app)

# Azure Storage account URL and SAS token
ACCOUNT_URL = os.getenv('ACCOUNT_URL')
SAS_TOKEN = os.getenv('SAS_TOKEN')

# Initialize Azure Blob Service client
blob_service_client = BlobServiceClient(account_url=f"{ACCOUNT_URL}?{SAS_TOKEN}")

def parse_duration(duration_str):
    """Convert duration in 'mm:ss' format or plain seconds to seconds."""
    try:
        if ":" in duration_str:
            minutes, seconds = map(float, duration_str.split(":"))
            return int(minutes * 60 + seconds)  # Fixed incorrect multiplication
        else:
            return int(float(duration_str))
    except Exception as e:
        logging.error(f"Error parsing duration: {e}")
        return None

@app.route("/", methods=["GET"])
def home():
    return jsonify({
        "message": "Welcome to the Flask server!",
        "status": "success"
    }), 200

@app.route('/remove-audio', methods=['POST'])
def remove_audio():
    try:
        data = request.json
        video_url = data.get("video_url")
        
        if not video_url:
            return jsonify({"error": "Invalid input data"}), 400
        
        logging.debug(f"Received request to remove audio from: {video_url}")
        
        local_video_path = f"temp/{uuid4()}.mp4"
        os.makedirs("temp", exist_ok=True)

        response = requests.get(video_url, stream=True)
        
        if response.status_code != 200:
            logging.error(f"Failed to download video. HTTP Status: {response.status_code}")
            return jsonify({"error": f"Failed to download video. HTTP Status: {response.status_code}"}), 400

        with open(local_video_path, "wb") as video_file:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    video_file.write(chunk)
        
        logging.debug(f"Video downloaded successfully: {local_video_path}")

        # Define output path for the processed video
        processed_video_path = f"temp/{uuid4()}_no_audio.mp4"

        # Use ffmpeg to remove audio
        ffmpeg.input(local_video_path).output(processed_video_path, an=None).run(cmd='ffmpeg')

        logging.debug(f"Processed video saved at: {processed_video_path}")

        # Upload processed video to Azure Blob Storage
        container_client = blob_service_client.get_container_client("upload-temp")
        blob_name = f"{uuid4()}.mp4"
        blob_client = container_client.get_blob_client(blob_name)

        with open(processed_video_path, "rb") as video_file:
            blob_client.upload_blob(video_file, overwrite=True)

        processed_video_url = f"{ACCOUNT_URL}/upload-temp/{blob_name}?{SAS_TOKEN}"
        
        logging.debug(f"Processed video uploaded successfully: {processed_video_url}")

        # Cleanup local files
        os.remove(local_video_path)
        os.remove(processed_video_path)

        return jsonify({"processed_video_url": processed_video_url}), 201

    except requests.exceptions.RequestException as req_err:
        logging.error(f"Request error: {req_err}")
        return jsonify({"error": f"Request error: {str(req_err)}"}), 500
    except Exception as e:
        logging.error(f"Unexpected error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/add-audio', methods=['POST'])
def add_audio():
    try:
        data = request.json
        video_url = data.get("video_url")
        audio_url = data.get("audio_url")
        
        if not video_url or not audio_url:
            return jsonify({"error": "Invalid input data"}), 400
        
        logging.debug(f"Received request to add audio {audio_url} to video {video_url}")
        
        # Download video and audio
        local_video_path = f"temp/{uuid4()}.mp4"
        local_audio_path = f"temp/{uuid4()}.mp3"
        os.makedirs("temp", exist_ok=True)

        for url, path in [(video_url, local_video_path), (audio_url, local_audio_path)]:
            response = requests.get(url, stream=True)
            if response.status_code != 200:
                logging.error(f"Failed to download file from {url}. HTTP Status: {response.status_code}")
                return jsonify({"error": f"Failed to download file from {url}. HTTP Status: {response.status_code}"}), 400
            with open(path, "wb") as file:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        file.write(chunk)
        
        logging.debug("Video and audio downloaded successfully")

        # Define output path for the processed video
        output_video_path = f"temp/{uuid4()}_with_audio.mp4"

        # Use ffmpeg to add audio to video
        ffmpeg.input(local_video_path).input(local_audio_path).output(output_video_path, codec='copy').run(cmd='ffmpeg')

        logging.debug(f"Processed video saved at: {output_video_path}")

        # Upload processed video to Azure Blob Storage
        container_client = blob_service_client.get_container_client("upload-temp")
        blob_name = f"{uuid4()}.mp4"
        blob_client = container_client.get_blob_client(blob_name)

        with open(output_video_path, "rb") as video_file:
            blob_client.upload_blob(video_file, overwrite=True)

        output_video_url = f"{ACCOUNT_URL}/upload-temp/{blob_name}?{SAS_TOKEN}"
        
        logging.debug(f"Processed video uploaded successfully: {output_video_url}")

        # Cleanup local files
        os.remove(local_video_path)
        os.remove(local_audio_path)
        os.remove(output_video_path)

        return jsonify({"processed_video_url": output_video_url}), 201

    except requests.exceptions.RequestException as req_err:
        logging.error(f"Request error: {req_err}")
        return jsonify({"error": f"Request error: {str(req_err)}"}), 500
    except Exception as e:
        logging.error(f"Unexpected error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/trim-video', methods=['POST'])
def trim_video():
    try:
        data = request.json
        video_url = data.get("video_url")
        start_time = data.get("start_time")
        end_time = data.get("end_time")
        start_time = parse_duration(start_time)
        end_time = parse_duration(end_time)
        if not video_url or start_time is None or end_time is None:
            return jsonify({"error": "Invalid input data"}), 400
        
        logging.debug(f"Received request to trim video {video_url} from {start_time} to {end_time}")
        
        # Download video
        local_video_path = f"temp/{uuid4()}.mp4"
        os.makedirs("temp", exist_ok=True)

        response = requests.get(video_url, stream=True)
        if response.status_code != 200:
            logging.error(f"Failed to download video. HTTP Status: {response.status_code}")
            return jsonify({"error": f"Failed to download video. HTTP Status: {response.status_code}"}), 400
        
        with open(local_video_path, "wb") as video_file:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    video_file.write(chunk)
        
        logging.debug("Video downloaded successfully")

        # Define output path for the trimmed video
        trimmed_video_path = f"temp/{uuid4()}_trimmed.mp4"

        # Use ffmpeg to trim the video
        ffmpeg.input(local_video_path, ss=start_time, to=end_time).output(trimmed_video_path, codec='copy').run(cmd='ffmpeg')

        logging.debug(f"Trimmed video saved at: {trimmed_video_path}")

        # Upload trimmed video to Azure Blob Storage
        container_client = blob_service_client.get_container_client("upload-temp")
        blob_name = f"{uuid4()}.mp4"
        blob_client = container_client.get_blob_client(blob_name)

        with open(trimmed_video_path, "rb") as video_file:
            blob_client.upload_blob(video_file, overwrite=True)

        trimmed_video_url = f"{ACCOUNT_URL}/upload-temp/{blob_name}?{SAS_TOKEN}"
        
        logging.debug(f"Trimmed video uploaded successfully: {trimmed_video_url}")

        # Cleanup local files
        os.remove(local_video_path)
        os.remove(trimmed_video_path)

        return jsonify({"processed_video_url": trimmed_video_url}), 201

    except requests.exceptions.RequestException as req_err:
        logging.error(f"Request error: {req_err}")
        return jsonify({"error": f"Request error: {str(req_err)}"}), 500
    except Exception as e:
        logging.error(f"Unexpected error: {e}")
        return jsonify({"error": str(e)}), 500
                
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

        logging.debug(f"Received request: {data}")

        # Convert start and end times to seconds
        start_time = parse_duration(start_time_str)
        end_time = parse_duration(end_time_str)

        if start_time is None or end_time is None:
            return jsonify({"error": "Invalid time format"}), 400

        # Ensure end time is greater than start time
        if end_time <= start_time:
            return jsonify({"error": "End time must be greater than start time"}), 400

        # Download audio from the provided URL
        local_audio_path = f"temp/{uuid4()}.mp3"
        os.makedirs("temp", exist_ok=True)

        logging.debug(f"Downloading audio from: {audio_url}")

        response = requests.get(audio_url, stream=True)

        # Check if the request was successful
        if response.status_code != 200:
            logging.error(f"Failed to download audio. HTTP Status: {response.status_code}")
            return jsonify({"error": f"Failed to download audio. HTTP Status: {response.status_code}"}), 400

        with open(local_audio_path, "wb") as audio_file:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    audio_file.write(chunk)

        logging.debug(f"Audio downloaded successfully: {local_audio_path}")

        # Define output path for the trimmed audio
        trimmed_audio_path = f"temp/{uuid4()}_trimmed.mp3"

        # Use ffmpeg to trim the audio
        ffmpeg.input(local_audio_path, ss=start_time, to=end_time).output(trimmed_audio_path).run(cmd='ffmpeg')

        logging.debug(f"Trimmed audio saved at: {trimmed_audio_path}")

        # Upload trimmed audio to Azure Blob Storage
        container_client = blob_service_client.get_container_client("upload-temp")
        blob_name = f"{uuid4()}.mp3"
        blob_client = container_client.get_blob_client(blob_name)

        with open(trimmed_audio_path, "rb") as audio_file:
            blob_client.upload_blob(audio_file, overwrite=True)

        # Generate URL for the trimmed audio
        trimmed_audio_url = f"{ACCOUNT_URL}/upload-temp/{blob_name}?{SAS_TOKEN}"

        logging.debug(f"Trimmed audio uploaded successfully: {trimmed_audio_url}")

        # Cleanup local files
        os.remove(local_audio_path)
        os.remove(trimmed_audio_path)

        return jsonify({"trimmed_audio_url": trimmed_audio_url}), 201

    except requests.exceptions.RequestException as req_err:
        logging.error(f"Request error: {req_err}")
        return jsonify({"error": f"Request error: {str(req_err)}"}), 500
    except Exception as e:
        logging.error(f"Unexpected error: {e}")
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
        app.run(
        host='0.0.0.0',
        port=5000,
        ssl_context=(
            '/etc/ssl/certs/selfsigned.crt',  # Path to the certificate file
            '/etc/ssl/private/selfsigned.key'  # Path to the private key file
        )
    )
