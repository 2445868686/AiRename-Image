from datetime import datetime
from PIL import Image
import io
import concurrent.futures
import re
import base64
import requests
import shutil
import sys
import os
import json
import threading
# import cairosvg
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
                             QSpinBox, QPushButton, QTextEdit, QCheckBox, QMessageBox, QFileDialog, QComboBox, QGroupBox)
from PyQt5.QtCore import QThread, pyqtSignal, pyqtSlot, QTimer
from PyQt5.QtGui import QIcon, QMouseEvent

def sanitize_filename(filename):
    """
    清除文件名中非法的字符，Windows系统中不允许出现下列字符：\ / : * ? " < > |
    """
    filename = filename.strip().strip('"')
    return re.sub(r'[\\/:*?"<>|]', '', filename)

def encode_image(image_path):
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode('utf-8')

def remove_punctuation_at_end(sentence):
    return re.sub(r'[。？！，、；：“”‘’《》（）【】『』「」\[\]\.,;:"\'?!(){}<>]+$', '', sentence)

def compress_and_encode_image(image_path, quality=85, max_size=(1080, 1080)):
    with Image.open(image_path) as img:
        img.thumbnail(max_size)
        if img.format == 'WEBP' or img.mode == 'RGBA':
            output_format = 'PNG'
            mime_type = 'image/png'
        else:
            output_format = img.format if img.format != 'JPEG' else 'JPEG'
            mime_type = f'image/{output_format.lower()}'
        img_bytes = io.BytesIO()
        img.save(img_bytes, format=output_format, quality=quality)
        img_bytes.seek(0)
        base64_encoded = base64.b64encode(img_bytes.read()).decode('utf-8')
    return base64_encoded, mime_type, output_format

def get_unique_filename(filepath):
    """
    检查filepath是否存在，若存在则在文件名后追加序号，直到获取一个不重复的文件名
    """
    base, ext = os.path.splitext(filepath)
    counter = 1
    new_filepath = filepath
    while os.path.exists(new_filepath):
        new_filepath = f"{base}{counter}{ext}"
        counter += 1
    return new_filepath

class Counter:
    def __init__(self):
        self.value = 0
        self.lock = threading.Lock()
    def increment(self):
        with self.lock:
            self.value += 1
    def decrement(self):
        with self.lock:
            self.value -= 1
    def get_value(self):
        with self.lock:
            return self.value

def process_image(image_path, config, output_text_signal, stop_event, success_counter, failure_counter, num_counter, active_counter):
    try:
        if stop_event.is_set():
            return
        active_counter.increment()
        api_key = config['Api_key']
        base_url = (
            f"{config['Base_url'].strip().rstrip('/')}/v1/chat/completions"
            if config.get('Base_url', '').strip()
            else "https://yunwu.ai/v1/chat/completions"
        )
        prompt = config['Prompt']
        option = config['Option']
        quality_value = min(95, max(1, int(config['Proxy_quality'] * 10)))
        original_format = os.path.splitext(image_path)[1][1:].upper()  # 获取原始图像格式

        if original_format.lower() == "svg":
            tmp_folder = os.path.join(os.path.dirname(image_path), '.airenametmp')
            if os.path.exists(tmp_folder):
                shutil.rmtree(tmp_folder)
            if not os.path.exists(tmp_folder):
                os.makedirs(tmp_folder)
            output_png_filename = os.path.splitext(os.path.basename(image_path))[0] + ".png"
            output_png_path = os.path.join(tmp_folder, output_png_filename)
            # cairosvg.svg2png(url=image_path, write_to=output_png_path)
            encoded_image, mime_type, image_format = compress_and_encode_image(output_png_path, quality=quality_value, max_size=(512, 512))
        else:
            encoded_image, mime_type, image_format = compress_and_encode_image(image_path, quality=quality_value, max_size=(512, 512))
        
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        data = {
            "model": config["Model"],
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{encoded_image}"}}
                    ]
                }
            ],
            "max_tokens": 300
        }

        print("请求URL:", base_url)
        print("请求头:", headers)
        print("请求数据:", json.dumps(data, indent=4))

        response = requests.post(base_url, headers=headers, json=data)
        response.raise_for_status()
        response_data = response.json()

        if 'choices' in response_data and len(response_data['choices']) > 0:
            result = response_data['choices'][0]['message']['content']
            print("原始返回结果:", result)
            if result and result[-1] in [')', '）']:
                result = result[:-1]
            result = sanitize_filename(result)
            new_name = f"{result}.{original_format.lower()}"
            
            if option:
                relative_path = os.path.relpath(os.path.dirname(image_path), config["Source_folder"])
                target_dir = os.path.join(config["Source_folder"], relative_path)
            else:
                target_dir = os.path.join(os.path.dirname(image_path), 'Finish')
                if not os.path.exists(target_dir):
                    os.makedirs(target_dir)
            
            target_path = os.path.join(target_dir, new_name)
            target_path = get_unique_filename(target_path)
            os.replace(image_path, target_path)
            success_counter.increment()
            num_counter.increment()
            output_text_signal.emit(f"第{num_counter.value}张图片处理完成：{os.path.basename(target_path)}")
        else:
            failure_counter.increment()
            num_counter.increment()
            output_text_signal.emit(f"API响应中缺少'choices'字段或'choices'为空: {response_data}")

    except requests.exceptions.RequestException as e:
        failure_counter.increment()
        num_counter.increment()
        output_text_signal.emit(f"HTTP请求失败: {e}")
    except Exception as e:
        failure_counter.increment()
        num_counter.increment()
        output_text_signal.emit(f"处理图片时发生错误: {e}")
    finally:
        active_counter.decrement()

def process_images_concurrently(config, output_text_signal, stop_event, active_counter):
    source_folder = config["Source_folder"]
    suffix_name = ('.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.tif', '.webp', '.heif', '.heic', '.svg')
    image_paths = [os.path.join(source_folder, filename)
                   for filename in os.listdir(source_folder)
                   if filename.lower().endswith(suffix_name)]
    
    success_counter = Counter()
    failure_counter = Counter()
    num_counter = Counter()

    output_text_signal.emit(f"开始处理{len(image_paths)}张图片，线程数: {config.get('Max_workers', 5)}")
    output_text_signal.emit(f"模型：{config['Model']}")
    with concurrent.futures.ThreadPoolExecutor(max_workers=config.get("Max_workers", 5)) as executor:
        futures = {executor.submit(process_image, image_path, config, output_text_signal, stop_event, 
                                     success_counter, failure_counter, num_counter, active_counter): image_path 
                   for image_path in image_paths}
        for future in concurrent.futures.as_completed(futures):
            if stop_event.is_set():
                break
            try:
                future.result()
            except Exception as exc:
                output_text_signal.emit(f'生成异常: {exc}')
    return len(image_paths), success_counter.value, failure_counter.value

class MainLogicThread(QThread):
    finished = pyqtSignal()
    output_text = pyqtSignal(str)
    
    def __init__(self, gui, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.gui = gui
        self.stop_event = threading.Event()
        self.active_counter = Counter()
    def run(self):
        try:
            self.stop_event.clear()
            total, success, failure = process_images_concurrently(self.gui.config, self.gui.thread.output_text, self.stop_event, self.active_counter)
            self.gui.thread.output_text.emit(f"任务完成：共有{total}张图片，成功{success}张，失败{total-success}张。")
        except Exception as e:
            self.gui.thread.output_text.emit(f"发生错误: {str(e)}")
        self.finished.emit()
    def stop(self):
        self.stop_event.set()
    def active_count(self):
        return self.active_counter.get_value()

class FolderLineEdit(QLineEdit):
    def __init__(self, update_callback, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.update_callback = update_callback
    def mousePressEvent(self, event: QMouseEvent):
        super().mousePressEvent(event)
        self.openFolderDialog()
    def openFolderDialog(self):
        directory = QFileDialog.getExistingDirectory(self, "选择文件夹")
        if directory:
            self.setText(directory)
            if self.update_callback:
                self.update_callback('Source_folder', directory)

class ConfigGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.thread = MainLogicThread(self)
        self.thread.finished.connect(self.on_main_logic_finished)
        self.thread.output_text.connect(self.update_output_text)
        self.setWindowTitle('图片批量AI重命名')
        self.setGeometry(100, 100, 700, 600)
        self.centerWindow()
        self.widget = QWidget(self)
        self.setCentralWidget(self.widget)
        self.layout = QVBoxLayout()

        self.config_path = 'config.json'
        self.config = self.load_config()

        self.init_ui()

        self.start_button = QPushButton("开始", self)
        self.start_button.clicked.connect(self.start_main_logic)
        self.layout.addWidget(self.start_button)
        
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_progress)
        self.widget.setLayout(self.layout)
        self.apply_style()

    def centerWindow(self):
        screen = QApplication.primaryScreen().geometry()
        windowSize = self.geometry()
        left = (screen.width() - windowSize.width()) / 2
        top = (screen.height() - windowSize.height()) / 2
        self.move(int(left), int(top))

    def load_config(self):
        if os.path.exists(self.config_path):
            with open(self.config_path, 'r') as file:
                return json.load(file)
        return {}

    def init_ui(self):
        # API 配置组：Base URL 与 API Key
        api_group = QGroupBox("")
        api_layout = QVBoxLayout()
        
        # Base URL
        base_url_label = QLabel("Base URL:")
        self.base_url_edit = QLineEdit()
        self.base_url_edit.setPlaceholderText("https://api.openai.com")
        self.base_url_edit.setText(self.config.get('Base_url', ''))
        self.base_url_edit.textChanged.connect(lambda text: self.update_config('Base_url', text))
        api_layout.addWidget(base_url_label)
        api_layout.addWidget(self.base_url_edit)
        
        # API Key 与显示切换
        api_key_label = QLabel("API 密钥:")
        self.api_key_edit = QLineEdit()
        self.api_key_edit.setText(self.config.get('Api_key', ''))
        self.api_key_edit.setEchoMode(QLineEdit.Password)  # 默认密文
        self.api_key_edit.textChanged.connect(lambda text: self.update_config('Api_key', text))
        show_key_checkbox = QCheckBox("显示 API Key")
        show_key_checkbox.toggled.connect(self.toggle_api_key_visibility)
        api_layout.addWidget(api_key_label)
        api_layout.addWidget(self.api_key_edit)
        api_layout.addWidget(show_key_checkbox)
        
        api_group.setLayout(api_layout)
        self.layout.addWidget(api_group)
        
        # 参数设置组：Model、Proxy Quality、Max Workers 同行
        param_group = QGroupBox("")
        param_layout = QHBoxLayout()
        
        self.model_combo = QComboBox(self)
        self.model_combo.addItems(["gpt-4o-mini-2024-07-18","gpt-4o-2024-11-20", 
                                   "gpt-4-turbo-2024-04-09", "gpt-4.5-preview-2025-02-27"])
        self.model_combo.setCurrentText(self.config.get('Model', 'gpt-4o-mini-2024-07-18'))
        self.model_combo.currentTextChanged.connect(lambda text: self.update_config('Model', text))
        param_layout.addWidget(QLabel("模型:"))
        param_layout.addWidget(self.model_combo)
        
        self.proxy_quality_spin = QSpinBox()
        self.proxy_quality_spin.setRange(0, 100)
        self.proxy_quality_spin.setValue(int(self.config.get('Proxy_quality', 0) * 100))
        self.proxy_quality_spin.valueChanged.connect(lambda value: self.update_config('Proxy_quality', value / 100))
        param_layout.addWidget(QLabel("代理质量:"))
        param_layout.addWidget(self.proxy_quality_spin)
        
        self.max_workers_spin = QSpinBox()
        self.max_workers_spin.setRange(1, 100)
        self.max_workers_spin.setValue(self.config.get('Max_workers', 5))
        self.max_workers_spin.valueChanged.connect(lambda value: self.update_config('Max_workers', value))
        param_layout.addWidget(QLabel("线程数:"))
        param_layout.addWidget(self.max_workers_spin)
        
        param_group.setLayout(param_layout)
        self.layout.addWidget(param_group)
        
        # 源文件夹选择
        folder_group = QGroupBox("")
        folder_layout = QVBoxLayout()
        self.source_folder_edit = FolderLineEdit(self.update_config, self)
        self.source_folder_edit.setText(self.config.get('Source_folder', ''))
        self.source_folder_edit.setReadOnly(True)
        folder_layout.addWidget(QLabel("文件夹:"))
        folder_layout.addWidget(self.source_folder_edit)
        folder_group.setLayout(folder_layout)
        self.layout.addWidget(folder_group)
        
        # Prompt 与 Option 设置
        prompt_group = QGroupBox("")
        prompt_layout = QVBoxLayout()
        self.prompt_text_edit = QTextEdit()
        self.prompt_text_edit.setText(self.config.get('Prompt', ''))
        self.prompt_text_edit.textChanged.connect(lambda: self.update_config('Prompt', self.prompt_text_edit.toPlainText()))
        prompt_layout.addWidget(QLabel("提示词:"))
        prompt_layout.addWidget(self.prompt_text_edit)
        self.option_check = QCheckBox("Option (勾选后直接重命名当前文件，否则移动到 'Finish' 文件夹)")
        self.option_check.setChecked(self.config.get('Option', False))
        self.option_check.stateChanged.connect(lambda: self.update_config('Option', self.option_check.isChecked()))
        prompt_layout.addWidget(self.option_check)
        prompt_group.setLayout(prompt_layout)
        self.layout.addWidget(prompt_group)
        
        # 输出区域
        output_group = QGroupBox("")
        output_layout = QVBoxLayout()
        self.output_text_box = QTextEdit(self)
        self.output_text_box.setReadOnly(True)
        output_layout.addWidget(self.output_text_box)
        output_group.setLayout(output_layout)
        self.layout.addWidget(output_group)
    
    def toggle_api_key_visibility(self, checked):
        if checked:
            self.api_key_edit.setEchoMode(QLineEdit.Normal)
        else:
            self.api_key_edit.setEchoMode(QLineEdit.Password)
    
    def update_config(self, key=None, value=None):
        if key and value is not None:
            self.config[key] = value
        with open(self.config_path, 'w') as file:
            json.dump(self.config, file, indent=4)
    
    def start_main_logic(self):
        if self.start_button.text() == "开始":
            self.start_button.setText("停止")
            self.thread.start()
        else:
            self.thread.stop()
            self.timer.start(1000)
            self.start_button.setEnabled(False)
    
    def update_progress(self):
        self.output_text_box.append("当前任务完成后停止,请稍等。。。")
        if self.thread.active_count() == 0:
            self.timer.stop()
            self.start_button.setEnabled(True)
            self.start_button.setText("开始")
    
    @pyqtSlot(str)
    def update_output_text(self, text):
        self.output_text_box.append(text)
    
    def on_main_logic_finished(self):
        self.timer.stop()
        tmp_folder = os.path.join(self.config['Source_folder'], '.airenametmp')
        if os.path.exists(tmp_folder):
            shutil.rmtree(tmp_folder)
        QMessageBox.information(self, "完成", "图片重命名已完成！")
        self.start_button.setText("开始")
    
    def closeEvent(self, event):
        with open(self.config_path, 'w') as file:
            json.dump(self.config, file, indent=4)
        event.accept()
    
    def apply_style(self):
        # 简单的样式美化，您可根据需要进行调整
        self.setStyleSheet("""
            QMainWindow {
                background-color: #f0f0f0;
            }
            QGroupBox {
                border: 1px solid #cccccc;
                border-radius: 5px;
                margin-top: 10px;
                font-weight: bold;
                background-color: #ffffff;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top center;
                padding: 0 3px;
            }
            QLabel {
                font-size: 14px;
                color: #333333;
            }
            QLineEdit, QTextEdit, QSpinBox, QComboBox {
                padding: 5px;
                border: 1px solid #cccccc;
                border-radius: 3px;
                font-size: 14px;
                background-color: #fcfcfc;
            }
            QPushButton {
                background-color: #4CAF50;
                color: white;
                padding: 10px;
                border: none;
                border-radius: 5px;
                font-size: 16px;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
            QCheckBox {
                font-size: 14px;
            }
        """)

def main():
    with open("config.json", "r") as file:
        config = json.load(file)
    app = QApplication(sys.argv)
    ex = ConfigGUI()
    ex.show()
    sys.exit(app.exec_())

if __name__ == '__main__':
    main()
