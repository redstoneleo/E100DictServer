import sys
import os
import requests
import time
import hmac
import hashlib
import pyaudio
import wave
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QComboBox, QTextEdit, QFileDialog,
    QMessageBox
)
from PyQt6.QtCore import QThread, pyqtSignal, Qt
from PyQt6.QtGui import QPixmap

DOMAIN = "https://e600.feing.com.cn"
# DOMAIN = "http://127.0.0.1:8000"
BASE_URL = f"{DOMAIN}/VoiceToImage/"

class ApiWorker(QThread):
    log_signal = pyqtSignal(str)
    result_signal = pyqtSignal(str, str) # text, image_url
    error_signal = pyqtSignal(str)
    finished_signal = pyqtSignal()

    def __init__(self, audio_path, style, device_id, device_secret):
        super().__init__()
        self.audio_path = audio_path
        self.style = style
        self.device_id = device_id
        self.device_secret = device_secret
        self.token = None

    def get_token(self):
        self.log_signal.emit("Fetching nonce...")
        resp = requests.post(f"{DOMAIN}/device/challenge/", json={"device_id": self.device_id}, timeout=10)
        if resp.status_code != 200:
            raise Exception(f"Failed to get nonce: {resp.text}")
        
        nonce = resp.json().get("nonce")
        if not nonce:
            raise Exception("Nonce not found in response")
        
        self.log_signal.emit(f"Got nonce: {nonce}, computing signature...")
        signature = hmac.new(
            self.device_secret.encode('utf-8'),
            nonce.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()

        self.log_signal.emit("Fetching token with signature...")
        resp2 = requests.post(f"{DOMAIN}/device/token/", json={
            "device_id": self.device_id,
            "signature": signature
        }, timeout=10)
        
        if resp2.status_code != 200:
            raise Exception(f"Failed to get token: {resp2.text}")
        
        self.token = resp2.json().get("access")
        if not self.token:
            raise Exception("Access token not found in response")
        
        self.log_signal.emit("Access token successfully acquired.")

    def run(self):
        try:
            self.get_token()

            self.log_signal.emit(f"Uploading {self.audio_path}...")
            headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
            with open(self.audio_path, 'rb') as f:
                files = {'audio': f}
                data = {'style': self.style}
                response = requests.post(BASE_URL + "upload/", files=files, data=data, headers=headers)
            
            if response.status_code != 200:
                self.error_signal.emit(f"Upload failed: {response.text}")
                self.finished_signal.emit()
                return

            resp_data = response.json()
            if 'task_id' not in resp_data:
                self.error_signal.emit(f"Task API returned error: {resp_data}")
                self.finished_signal.emit()
                return

            task_id = resp_data['task_id']
            self.log_signal.emit(f"Task started. ID: {task_id}")

            # 2. 轮询状态
            while True:
                status_resp = requests.get(BASE_URL + f"status/{task_id}/", headers=headers)
                if status_resp.status_code != 200:
                    self.error_signal.emit(f"Get status failed: {status_resp.text}")
                    break

                status_data = status_resp.json()
                status = status_data.get('status', 'UNKNOWN')
                self.log_signal.emit(f"Current Status: {status}")
                
                if status == 'COMPLETED':
                    self.log_signal.emit("Success!")
                    text = status_data.get('recognized_text', '')
                    image_url = status_data.get('generated_image_url', '')
                    
                    if image_url and not image_url.startswith('http'):
                        if image_url.startswith('/'):
                            from urllib.parse import urlparse
                            parsed = urlparse(BASE_URL)
                            domain = f"{parsed.scheme}://{parsed.netloc}"
                            image_url = domain + image_url
                    
                    self.result_signal.emit(text, image_url)
                    break
                elif status == 'FAILED':
                    self.error_signal.emit(f"Task Failed: {status_data.get('error_message', 'Unknown error')}")
                    break
                
                time.sleep(2)

        except Exception as e:
            self.error_signal.emit(f"Exception: {str(e)}")
        finally:
            self.finished_signal.emit()


class AudioRecorderWorker(QThread):
    finished_signal = pyqtSignal(str)
    error_signal = pyqtSignal(str)

    def __init__(self, output_filename="temp_record.wav"):
        super().__init__()
        self.output_filename = output_filename
        self._is_recording = False
        self.frames = []
        
    def start_recording(self):
        self._is_recording = True
        self.start()

    def stop_recording(self):
        self._is_recording = False

    def run(self):
        CHUNK = 1024
        FORMAT = pyaudio.paInt16
        CHANNELS = 1
        RATE = 16000 # Typical 16kHz for speech

        p = pyaudio.PyAudio()

        try:
            stream = p.open(format=FORMAT,
                            channels=CHANNELS,
                            rate=RATE,
                            input=True,
                            frames_per_buffer=CHUNK)
            
            self.frames = []
            while self._is_recording:
                data = stream.read(CHUNK)
                self.frames.append(data)
                
            stream.stop_stream()
            stream.close()
            
            wf = wave.open(self.output_filename, 'wb')
            wf.setnchannels(CHANNELS)
            wf.setsampwidth(p.get_sample_size(FORMAT))
            wf.setframerate(RATE)
            wf.writeframes(b''.join(self.frames))
            wf.close()
            
            self.finished_signal.emit(os.path.abspath(self.output_filename))
        except Exception as e:
            self.error_signal.emit(f"Recording error: {str(e)}")
        finally:
            p.terminate()


class ImageDownloadWorker(QThread):
    image_downloaded_signal = pyqtSignal(bytes)
    error_signal = pyqtSignal(str)

    def __init__(self, url):
        super().__init__()
        self.url = url

    def run(self):
        try:
            resp = requests.get(self.url, timeout=10)
            if resp.status_code == 200:
                self.image_downloaded_signal.emit(resp.content)
            else:
                self.error_signal.emit(f"Failed to download image. Status: {resp.status_code}")
        except Exception as e:
            self.error_signal.emit(f"Download exception: {str(e)}")


class VoiceToImageApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("语音生图 API 测试 (PyQt6)")
        self.resize(800, 600)
        self.setup_ui()

    def setup_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)

        # 顶部：Device Auth, 选择文件和风格
        input_layout = QVBoxLayout()
        
        device_layout = QHBoxLayout()
        self.device_id_label = QLabel("Device ID:")
        self.device_id_input = QLineEdit("FA1-202603-000123")
        self.device_secret_label = QLabel("Device Secret:")
        self.device_secret_input = QLineEdit("381570a6a34e98ea6183687f0932ed938436323be216bab360f9ac2376c2edbe")
        device_layout.addWidget(self.device_id_label)
        device_layout.addWidget(self.device_id_input)
        device_layout.addWidget(self.device_secret_label)
        device_layout.addWidget(self.device_secret_input)
        
        top_layout = QHBoxLayout()
        
        self.style_label = QLabel("Style:")
        self.style_combo = QComboBox()
        self.style_combo.addItems(["简笔画", "水墨", "动漫", "写实", "油画", "素描"])
        self.style_combo.setEditable(False)
        
        self.record_btn = QPushButton("Hold to Record")
        self.record_btn.pressed.connect(self.start_recording)
        self.record_btn.released.connect(self.stop_recording)

        top_layout.addWidget(self.style_label)
        top_layout.addWidget(self.style_combo)
        top_layout.addWidget(self.record_btn)
        
        input_layout.addLayout(device_layout)
        input_layout.addLayout(top_layout)

        main_layout.addLayout(input_layout)

        # 中部：结果和日志
        content_layout = QHBoxLayout()
        
        # 左侧：文本结果和图片显示
        result_layout = QVBoxLayout()
        
        self.text_result_label = QLabel("Recognized Text:")
        self.text_result = QLineEdit()
        self.text_result.setReadOnly(True)
        
        self.image_label = QLabel("Image will be displayed here")
        self.image_label.setMinimumSize(400, 400)
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setStyleSheet("border: 1px solid #ccc; background-color: #f0f0f0;")
        
        result_layout.addWidget(self.text_result_label)
        result_layout.addWidget(self.text_result)
        result_layout.addWidget(self.image_label)
        result_layout.setStretch(2, 1)

        # 右侧：日志输出
        log_layout = QVBoxLayout()
        self.log_label = QLabel("Process Log:")
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        
        log_layout.addWidget(self.log_label)
        log_layout.addWidget(self.log_text)

        content_layout.addLayout(result_layout, 2)
        content_layout.addLayout(log_layout, 1)

        main_layout.addLayout(content_layout)
        
        self.worker = None
        self.img_worker = None

    def log(self, message):
        self.log_text.append(message)

    def start_recording(self):
        self.record_btn.setText("Recording...")
        self.log("Started recording...")
        self.recorder = AudioRecorderWorker()
        self.recorder.finished_signal.connect(self.on_record_finished)
        self.recorder.error_signal.connect(self.on_error)
        self.recorder.start_recording()

    def stop_recording(self):
        self.record_btn.setText("Hold to Record")
        self.log("Stopped recording, processing...")
        if self.recorder:
            self.recorder.stop_recording()

    def on_record_finished(self, file_path):
        self.start_generation(file_path)

    def start_generation(self, audio_path):
        if not os.path.exists(audio_path):
            QMessageBox.warning(self, "Error", "Selected audio file does not exist!")
            return

        style = self.style_combo.currentText()
        device_id = self.device_id_input.text().strip()
        device_secret = self.device_secret_input.text().strip()
        
        if not device_id or not device_secret:
            QMessageBox.warning(self, "Warning", "Please enter Device ID and Secret.")
            return

        self.record_btn.setEnabled(False)
        self.log_text.clear()
        self.text_result.clear()
        self.image_label.setText("Processing...")
        
        self.worker = ApiWorker(audio_path, style, device_id, device_secret)
        self.worker.log_signal.connect(self.log)
        self.worker.error_signal.connect(self.on_error)
        self.worker.result_signal.connect(self.on_result)
        self.worker.finished_signal.connect(self.on_finished)
        self.worker.start()

    def on_error(self, err_msg):
        self.log(f"ERROR: {err_msg}")
        QMessageBox.critical(self, "Error", err_msg)
        self.image_label.setText("Failed")

    def on_result(self, text, image_url):
        self.log(f"Result URL: {image_url}")
        self.text_result.setText(text)
        self.image_label.setText(f"Loading image...\n{image_url}")
        
        # Download image
        if image_url:
            self.img_worker = ImageDownloadWorker(image_url)
            self.img_worker.image_downloaded_signal.connect(self.on_image_downloaded)
            self.img_worker.error_signal.connect(self.on_error)
            self.img_worker.start()
        else:
            self.image_label.setText("No image URL provided")

    def on_image_downloaded(self, img_bytes):
        pixmap = QPixmap()
        pixmap.loadFromData(img_bytes)
        if not pixmap.isNull():
            scaled_pixmap = pixmap.scaled(
                self.image_label.width(), self.image_label.height(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
            self.image_label.setPixmap(scaled_pixmap)
        else:
            self.image_label.setText("Failed to load image data")

    def on_finished(self):
        self.record_btn.setEnabled(True)
        self.log("Task thread finished.")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = VoiceToImageApp()
    window.show()
    sys.exit(app.exec())