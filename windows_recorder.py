import sys
import os
import json
import tempfile
import logging
import time
import fnmatch
import psutil  # برای بررسی درایوها
import shutil
import keyboard
import sounddevice as sd
import numpy as np
import requests
import wave
import pyperclip
from PyQt5.QtWidgets import (
    QApplication, QSystemTrayIcon, QMenu, QMessageBox, QInputDialog,
    QDialog, QLabel, QLineEdit, QPushButton, QVBoxLayout, QHBoxLayout
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QIcon

# مسیر فایل لاگ در پوشه‌ی موقت
temp_dir = tempfile.gettempdir()
log_file = os.path.join(temp_dir, 'audio_recorder.log')

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    filename=log_file
)

# مسیر فایل اعتبارسنجی USB (در همان مسیر اسکریپت)
CREDENTIALS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "usb_credentials.json")


class AudioRecorder(QThread):
    finished = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, sample_rate=16000):
        super().__init__()
        self.sample_rate = sample_rate
        self.recording = False
        self.audio_data = []
        self.token = None
        # اعتبارسنجی پیش‌فرض برای ضبط صوت (همیشه استفاده شود)
        self.username = "word"
        self.password = "1234"
        # اعتبارسنجی اختصاصی برای ارسال فایل‌های USB (ابتدا None است)
        self.usb_username = None
        self.usb_password = None

    def run(self):
        try:
            with sd.InputStream(samplerate=self.sample_rate, channels=1, callback=self.audio_callback):
                while self.recording:
                    sd.sleep(100)
            if self.audio_data:
                audio_array = np.concatenate(self.audio_data, axis=0)
                temp_file = tempfile.mktemp(suffix='.wav')
                with wave.open(temp_file, 'wb') as wf:
                    wf.setnchannels(1)
                    wf.setsampwidth(2)
                    wf.setframerate(self.sample_rate)
                    wf.writeframes((audio_array * 32767).astype(np.int16).tobytes())
                self.send_to_backend(temp_file)
                os.remove(temp_file)
        except Exception as e:
            logging.error(f"Erreur d’enregistrement : {str(e)}")
            self.error.emit(f"Erreur d’enregistrement : {str(e)}")

    def audio_callback(self, indata, frames, time, status):
        if status:
            logging.warning(f"Statut du callback audio : {status}")
        if self.recording:
            self.audio_data.append(indata.copy())

    def start_recording(self):
        self.recording = True
        self.audio_data = []
        self.start()

    def stop_recording(self):
        self.recording = False

    def login(self, use_usb_credentials=False):
        """
        در این تابع، در صورتی که use_usb_credentials=True باشد،
        از اعتبارسنجی اختصاصی USB (متغیرهای usb_username و usb_password) استفاده می‌شود.
        در غیر این صورت از اعتبارسنجی پیش‌فرض استفاده می‌شود.
        """
        try:
            url = "https://backend.shaz.ai/token/"
            if use_usb_credentials:
                if not self.usb_username or not self.usb_password:
                    logging.error("اعتبارسنجی USB وارد نشده است.")
                    return False
                data = {"username": self.usb_username, "password": self.usb_password}
            else:
                data = {"username": self.username, "password": self.password}
            response = requests.post(url, data=data)
            if response.status_code == 200:
                self.token = response.json().get('access_token')
                return True
            else:
                logging.error(f"Échec de la connexion : {response.status_code}")
                return False
        except Exception as e:
            logging.error(f"Erreur de connexion : {str(e)}")
            return False

    def send_to_backend(self, audio_file):
        """
        ارسال فایل ضبط شده به سرور با استفاده از اعتبارسنجی پیش‌فرض
        """
        try:
            if not self.token and not self.login(use_usb_credentials=False):
                self.error.emit("Authentification échouée")
                return
            url = "https://backend.shaz.ai/upload-audio/"
            headers = {"Authorization": f"Bearer {self.token}"}
            with open(audio_file, 'rb') as f:
                files = {'file': ('recording.wav', f, 'audio/wav')}
                response = requests.post(url, files=files, headers=headers)
            if response.status_code == 200:
                data = response.json()
                transcription = data.get('transcription', '')
                self.finished.emit(transcription)
            elif response.status_code == 401:
                if self.login(use_usb_credentials=False):
                    return self.send_to_backend(audio_file)
                else:
                    self.error.emit("Authentification échouée")
            else:
                error_msg = f"Erreur du serveur : {response.status_code} - {response.text}"
                logging.error(error_msg)
                self.error.emit(error_msg)
        except Exception as e:
            error_msg = f"Erreur d’upload : {str(e)}"
            logging.error(error_msg)
            self.error.emit(error_msg)

    def send_file_to_backend(self, file_path):
        """
        ارسال یک فایل (مثلاً از USB) به سرور.
        در صورت ارسال موفق (کد 200)، فایل اصلی حذف شده و به پوشه sent منتقل می‌شود.
        """
        try:
            if not self.token and not self.login(use_usb_credentials=True):
                logging.error("Authentification USB échouée lors de l'envoi du fichier.")
                return False
            url = "https://backend.shaz.ai/upload-audio/"
            headers = {"Authorization": f"Bearer {self.token}"}
            filename = os.path.basename(file_path)
            mime_type = 'audio/wav' if filename.lower().endswith('.wav') else 'application/octet-stream'
            with open(file_path, 'rb') as f:
                files = {'file': (filename, f, mime_type)}
                response = requests.post(url, files=files, headers=headers)
            if response.status_code == 200:
                logging.info(f"Fichier {filename} envoyé avec succès.")
                self.move_file_to_sent(file_path)
                return True
            elif response.status_code == 401:
                if self.login(use_usb_credentials=True):
                    return self.send_file_to_backend(file_path)
                else:
                    logging.error("Authentification USB échouée lors de l'envoi du fichier.")
                    return False
            else:
                logging.error(f"Erreur du serveur lors de l'envoi du fichier {filename} : {response.status_code} - {response.text}")
                return False
        except Exception as e:
            logging.error(f"Erreur lors de l'envoi du fichier {file_path} : {str(e)}")
            return False

    def move_file_to_sent(self, file_path):
        """
        انتقال فایل ارسال شده به پوشه sent در همان ریشه‌ی درایو.
        پس از انتقال، فایل اصلی حذف می‌شود.
        """
        try:
            drive_root = os.path.splitdrive(file_path)[0] + os.sep
            sent_folder = os.path.join(drive_root, "sent")
            if not os.path.exists(sent_folder):
                os.makedirs(sent_folder)
            destination = os.path.join(sent_folder, os.path.basename(file_path))
            shutil.move(file_path, destination)
            logging.info(f"فایل به پوشه sent منتقل شد: {destination}")
        except Exception as e:
            logging.error(f"خطا در انتقال فایل {file_path} به پوشه sent : {str(e)}")


class USBWatcher(QThread):
    """
    این کلاس به بررسی درایوهای متصل شده به سیستم می‌پردازد.
    در صورت شناسایی درایوی که پوشه‌ای مطابق با الگوی دلخواه (مثلاً شامل 'DJI_Audio_')
    داشته باشد، فایل‌های داخل آن پوشه به صورت خودکار ارسال می‌شوند.
    """
    def __init__(self, recorder, poll_interval=5):
        super().__init__()
        self.recorder = recorder
        self.poll_interval = poll_interval
        self.already_processed = set()
        self.running = True

    def run(self):
        logging.info("شروع نظارت USB.")
        while self.running:
            try:
                partitions = psutil.disk_partitions(all=False)
                for partition in partitions:
                    if 'removable' in partition.opts.lower() or partition.fstype == '':
                        mountpoint = partition.mountpoint
                        try:
                            for entry in os.listdir(mountpoint):
                                if fnmatch.fnmatch(entry, '*DJI_Audio_*'):
                                    folder_path = os.path.join(mountpoint, entry)
                                    if folder_path not in self.already_processed and os.path.isdir(folder_path):
                                        logging.info(f"شناسایی پوشه {folder_path} در USB. آغاز ارسال فایل‌ها.")
                                        if not self.recorder.usb_username or not self.recorder.usb_password:
                                            logging.error("اعتبارسنجی USB برای ارسال فایل وارد نشده است.")
                                            continue
                                        self.process_usb_folder(folder_path)
                                        self.already_processed.add(folder_path)
                        except Exception as e:
                            logging.error(f"خطا در بررسی درایو {mountpoint}: {str(e)}")
            except Exception as e:
                logging.error(f"خطا در نظارت USB: {str(e)}")
            time.sleep(self.poll_interval)

    def process_usb_folder(self, folder_path):
        for root, dirs, files in os.walk(folder_path):
            for file in files:
                file_path = os.path.join(root, file)
                logging.info(f"ارسال فایل: {file_path}")
                success = self.recorder.send_file_to_backend(file_path)
                if success:
                    logging.info(f"فایل {file} با موفقیت ارسال و به پوشه sent منتقل شد.")
                else:
                    logging.error(f"ارسال فایل {file} با خطا مواجه شد.")

    def stop(self):
        self.running = False


class CredentialDialog(QDialog):
    """
    دیالوگ برای دریافت یوزرنیم و پسورد اختصاصی USB از کاربر
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("تنظیم اعتبارسنجی USB")
        self.username = None
        self.password = None
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout()
        user_label = QLabel("یوزرنیم:")
        self.user_input = QLineEdit()
        pass_label = QLabel("پسورد:")
        self.pass_input = QLineEdit()
        self.pass_input.setEchoMode(QLineEdit.Password)
        btn_box = QHBoxLayout()
        btn_ok = QPushButton("تایید")
        btn_cancel = QPushButton("انصراف")
        btn_ok.clicked.connect(self.accept)
        btn_cancel.clicked.connect(self.reject)
        btn_box.addWidget(btn_ok)
        btn_box.addWidget(btn_cancel)
        layout.addWidget(user_label)
        layout.addWidget(self.user_input)
        layout.addWidget(pass_label)
        layout.addWidget(self.pass_input)
        layout.addLayout(btn_box)
        self.setLayout(layout)

    def accept(self):
        self.username = self.user_input.text().strip()
        self.password = self.pass_input.text().strip()
        if not self.username or not self.password:
            QMessageBox.warning(self, "خطا", "لطفاً یوزرنیم و پسورد را وارد نمایید.")
            return
        super().accept()


class SystemTrayApp:
    def __init__(self):
        self.app = QApplication(sys.argv)
        self.recorder = AudioRecorder()
        self.load_usb_credentials()
        self.recorder.finished.connect(self.on_transcription_received)
        self.recorder.error.connect(self.show_error)
        self.usb_watcher = USBWatcher(self.recorder)
        self.usb_watcher.start()
        self.record_hotkey = 'shift+alt+r'
        self.stop_hotkey = 'shift+alt+s'
        self.tray = QSystemTrayIcon()
        self.tray.setIcon(self.create_icon())
        self.tray.setVisible(True)
        self.menu = QMenu()
        self.menu.addAction(f"Démarrer l'enregistrement ({self.record_hotkey})", self.start_recording)
        self.menu.addAction(f"Arrêter l'enregistrement ({self.stop_hotkey})", self.stop_recording)
        self.menu.addSeparator()
        self.menu.addAction("تنظیم اعتبارسنجی USB", self.configure_usb_credentials)
        self.menu.addAction("Configurer les raccourcis", self.configure_hotkeys)
        self.menu.addSeparator()
        self.menu.addAction("Quitter", self.quit_app)
        self.tray.setContextMenu(self.menu)
        keyboard.add_hotkey(self.record_hotkey, self.start_recording)
        keyboard.add_hotkey(self.stop_hotkey, self.stop_recording)
        self.tray.showMessage(
            "Enregistreur Audio",
            f"Démarrage:\n- ضبط صدا: {self.record_hotkey}\n- توقف ضبط: {self.stop_hotkey}",
            QSystemTrayIcon.Information,
            3000
        )

    def create_icon(self):
        from PyQt5.QtGui import QPixmap, QPainter, QColor
        pixmap = QPixmap(32, 32)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setBrush(QColor(255, 0, 0))
        painter.drawEllipse(0, 0, 32, 32)
        painter.end()
        return QIcon(pixmap)

    def start_recording(self):
        self.tray.showMessage("Enregistrement Audio", "Enregistrement démarré...", QSystemTrayIcon.Information, 1000)
        self.recorder.start_recording()

    def stop_recording(self):
        self.tray.showMessage("Enregistrement Audio", "Enregistrement arrêté...", QSystemTrayIcon.Information, 1000)
        self.recorder.stop_recording()

    def on_transcription_received(self, text):
        pyperclip.copy(text)
        keyboard.press_and_release('ctrl+v')
        self.tray.showMessage("Succès", "Le texte reconnu a été copié et collé !", QSystemTrayIcon.Information, 2000)

    def show_error(self, error_msg):
        self.tray.showMessage("Erreur", error_msg, QSystemTrayIcon.Critical, 3000)

    def configure_usb_credentials(self):
        """
        نمایش دیالوگ برای تنظیم یوزرنیم و پسورد اختصاصی برای ارسال فایل‌های USB.
        در صورت تایید، اطلاعات در فایل usb_credentials.json ذخیره می‌شود.
        """
        dialog = CredentialDialog()
        if dialog.exec_() == QDialog.Accepted:
            self.recorder.usb_username = dialog.username
            self.recorder.usb_password = dialog.password
            self.save_usb_credentials()
            self.tray.showMessage("تنظیم اعتبارسنجی", "اعتبارسنجی USB تنظیم شد.", QSystemTrayIcon.Information, 3000)

    def load_usb_credentials(self):
        """بارگذاری اطلاعات USB از فایل در صورت وجود"""
        if os.path.exists(CREDENTIALS_FILE):
            try:
                with open(CREDENTIALS_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.recorder.usb_username = data.get("usb_username")
                    self.recorder.usb_password = data.get("usb_password")
                    logging.info("اطلاعات USB از فایل بارگذاری شد.")
            except Exception as e:
                logging.error(f"خطا در بارگذاری اطلاعات USB: {str(e)}")

    def save_usb_credentials(self):
        """ذخیره اطلاعات USB در فایل"""
        data = {
            "usb_username": self.recorder.usb_username,
            "usb_password": self.recorder.usb_password
        }
        try:
            with open(CREDENTIALS_FILE, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4)
            logging.info("اطلاعات USB ذخیره شدند.")
        except Exception as e:
            logging.error(f"خطا در ذخیره اطلاعات USB: {str(e)}")

    def configure_hotkeys(self):
        parent_widget = self.app.activeWindow()
        new_record_hotkey, ok_record = QInputDialog.getText(
            parent_widget,
            "Configurer le raccourci pour démarrer l'enregistrement",
            f"Raccourci actuel : {self.record_hotkey}\nVeuillez saisir le nouveau raccourci :"
        )
        if ok_record and new_record_hotkey.strip():
            new_stop_hotkey, ok_stop = QInputDialog.getText(
                parent_widget,
                "Configurer le raccourci pour arrêter l'enregistrement",
                f"Raccourci actuel : {self.stop_hotkey}\nVeuillez saisir le nouveau raccourci :"
            )
            if ok_stop and new_stop_hotkey.strip():
                try:
                    keyboard.remove_hotkey(self.record_hotkey)
                except Exception as e:
                    logging.warning(f"Impossible de supprimer l'ancien raccourci d'enregistrement : {e}")
                try:
                    keyboard.remove_hotkey(self.stop_hotkey)
                except Exception as e:
                    logging.warning(f"Impossible de supprimer l'ancien raccourci d'arrêt : {e}")
                self.record_hotkey = new_record_hotkey.strip().lower()
                self.stop_hotkey = new_stop_hotkey.strip().lower()
                try:
                    keyboard.add_hotkey(self.record_hotkey, self.start_recording)
                except Exception as e:
                    logging.error(f"Erreur lors de l'ajout du nouveau raccourci d'enregistrement : {e}")
                    self.tray.showMessage("Erreur", "Erreur lors de l'ajout du nouveau raccourci pour démarrer l'enregistrement !", QSystemTrayIcon.Critical, 3000)
                try:
                    keyboard.add_hotkey(self.stop_hotkey, self.stop_recording)
                except Exception as e:
                    logging.error(f"Erreur lors de l'ajout du nouveau raccourci d'arrêt : {e}")
                    self.tray.showMessage("Erreur", "Erreur lors de l'ajout du nouveau raccourci pour arrêter l'enregistrement !", QSystemTrayIcon.Critical, 3000)
                self.menu.clear()
                self.menu.addAction(f"Démarrer l'enregistrement ({self.record_hotkey})", self.start_recording)
                self.menu.addAction(f"Arrêter l'enregistrement ({self.stop_hotkey})", self.stop_recording)
                self.menu.addSeparator()
                self.menu.addAction("تنظیم اعتبارسنجی USB", self.configure_usb_credentials)
                self.menu.addAction("Configurer les raccourcis", self.configure_hotkeys)
                self.menu.addSeparator()
                self.menu.addAction("Quitter", self.quit_app)
                self.tray.setContextMenu(self.menu)
                self.tray.showMessage("Raccourcis modifiés",
                                      f"Démarrer : {self.record_hotkey}\nArrêter : {self.stop_hotkey}",
                                      QSystemTrayIcon.Information, 3000)

    def quit_app(self):
        self.recorder.stop_recording()
        self.usb_watcher.stop()
        self.usb_watcher.wait()
        self.tray.hide()
        self.app.quit()

    def run(self):
        self.app.exec_()


if __name__ == "__main__":
    main_app = SystemTrayApp()
    main_app.run()
