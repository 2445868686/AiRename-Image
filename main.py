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
import cairosvg
from PyQt5.QtWidgets import QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QSpinBox, QPushButton, QTextEdit, QCheckBox, QMessageBox, QFileDialog, QComboBox
from PyQt5.QtCore import QThread, pyqtSignal, pyqtSlot, QTimer
from PyQt5.QtGui import QIcon, QMouseEvent

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
        base_url = config['Base_url']
        prompt = config['Prompt']
        option = config['Option']
        now = datetime.now()
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
            cairosvg.svg2png(url=image_path, write_to=output_png_path)
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
                        {
                            "type": "text",
                            "text": prompt
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{mime_type};base64,{encoded_image}"
                            }
                        }
                    ]
                }
            ],
            "max_tokens": 300
        }

        # 输出调试信息
        print("请求URL:", base_url)
        print("请求头:", headers)
        print("请求数据:", json.dumps(data, indent=4))

        response = requests.post(base_url, headers=headers, json=data)
        response.raise_for_status()
        response_data = response.json()

        if 'choices' in response_data and len(response_data['choices']) > 0:
            result = response_data['choices'][0]['message']['content']
            print(result)
            # 检查最后一个字符是否是')'或'）'
            if result[-1] not in [')', '）']:
                result = result[:-1]
            new_name = f"{result}.{original_format.lower()}"
            relative_path = os.path.relpath(os.path.dirname(image_path), config["Source_folder"])
            new_path = os.path.join(config["Source_folder"], relative_path, new_name)
            if option:
                os.replace(image_path, new_path)
            else:
                destination_folder = os.path.join(os.path.dirname(image_path), 'Finish')
                if not os.path.exists(destination_folder):
                    os.makedirs(destination_folder)
                new_file = os.path.join(destination_folder, new_name)
                os.replace(image_path, new_file)
            success_counter.increment()
            num_counter.increment()
            output_text_signal.emit(f"第{num_counter.value}张图片处理完成：{new_name}")
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
    image_paths = []
    max_workers = 5  # 设置最大并发线程数

    for root, dirs, files in os.walk(source_folder):
        dirs[:] = [d for d in dirs if d != '.airenametmp']
        for filename in files:
            if filename.lower().endswith(suffix_name):
                image_path = os.path.join(root, filename)
                image_paths.append(image_path)

    success_counter = Counter()
    failure_counter = Counter()
    num_counter = Counter()

    output_text_signal.emit(f"开始处理{len(image_paths)}张图片，线程:{max_workers}")
    output_text_signal.emit(f"模型：{config['Model']}")
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(process_image, image_path, config, output_text_signal, stop_event, success_counter, failure_counter, num_counter, active_counter): image_path for image_path in image_paths}
        for future in concurrent.futures.as_completed(futures):
            if stop_event.is_set():
                break
            try:
                future.result()
            except Exception as exc:
                output_text_signal.emit(f'生成异常: {exc}')
    return len(image_paths), success_counter.value, failure_counter.value

class MainLogicThread(QThread):
    def __init__(self, gui, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.gui = gui
        self.stop_event = threading.Event()
        self.active_counter = Counter()

    def run(self):
        try:
            self.stop_event.clear()  # 清除停止事件标志
            total, success, failure = process_images_concurrently(self.gui.config, self.gui.thread.output_text, self.stop_event, self.active_counter)
            self.gui.thread.output_text.emit(f"任务完成：共有{total}张图片，成功{success}张，失败{total-success}张。")
        except Exception as e:
            self.gui.thread.output_text.emit(f"发生错误: {str(e)}")
        self.finished.emit()

    def stop(self):
        self.stop_event.set()  # 设置停止事件标志

    def active_count(self):
        return self.active_counter.get_value()

    finished = pyqtSignal()
    output_text = pyqtSignal(str)

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
        self.setWindowTitle('AiRename-Image')
        self.setGeometry(100, 100, 400, 400)
        self.centerWindow()
        self.widget = QWidget(self)
        self.setCentralWidget(self.widget)
        self.layout = QVBoxLayout()
        self.config_path = 'config.json'
        self.config = self.load_config()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_progress)

        self.init_ui()
        self.widget.setLayout(self.layout)
        self.start_button = QPushButton("Start", self)
        self.start_button.clicked.connect(self.start_main_logic)
        self.layout.addWidget(self.start_button)

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
        self.create_label_and_line_edit('Api_key')
        self.create_label_and_line_edit('Base_url')
        self.source_folder_label = QLabel('Source_folder')
        self.layout.addWidget(self.source_folder_label)
        self.source_folder_edit = FolderLineEdit(self.update_config, self)
        self.source_folder_edit.setText(self.config.get('Source_folder', ''))
        self.source_folder_edit.setReadOnly(True)
        self.layout.addWidget(self.source_folder_edit)

        self.create_prompt_editor()

        model_proxy_layout = QHBoxLayout()
        self.model_label = QLabel('Model')
        model_proxy_layout.addWidget(self.model_label)
        self.model_combo = QComboBox(self)
        self.model_combo.addItems(["gpt-4o", "gpt-4-turbo", "gpt-4", "gpt-4-vision-preview"])
        self.model_combo.setCurrentText(self.config.get('Model', 'gpt-4o'))
        self.model_combo.currentTextChanged.connect(lambda: self.update_config('Model', self.model_combo.currentText()))
        model_proxy_layout.addWidget(self.model_combo)

        self.proxy_quality_label = QLabel('Proxy_quality')
        self.proxy_quality_spin = QSpinBox()
        self.proxy_quality_spin.setRange(0, 100)
        self.proxy_quality_spin.setValue(int(self.config.get('Proxy_quality', 0) * 100))
        self.proxy_quality_spin.valueChanged.connect(lambda: self.update_config('Proxy_quality', self.proxy_quality_spin.value() / 100))
        model_proxy_layout.addWidget(self.proxy_quality_label)
        model_proxy_layout.addWidget(self.proxy_quality_spin)

        self.layout.addLayout(model_proxy_layout)
        self.create_option_checkbox()
        self.output_text_box = QTextEdit(self)
        self.output_text_box.setReadOnly(True)
        self.layout.addWidget(self.output_text_box)

    def select_source_folder(self):
        directory = QFileDialog.getExistingDirectory(self, "选择文件夹")
        if directory:
            self.config['Source_folder'] = directory
            self.source_folder_edit.setText(directory)
            self.update_config()

    def create_prompt_editor(self):
        label = QLabel('Prompt')
        self.layout.addWidget(label)
        self.prompt_text_edit = QTextEdit()
        self.prompt_text_edit.setText(self.config.get('Prompt', ''))
        self.prompt_text_edit.textChanged.connect(lambda: self.update_config('Prompt', self.prompt_text_edit.toPlainText()))
        self.layout.addWidget(self.prompt_text_edit)

    def create_option_checkbox(self):
        self.option_check = QCheckBox("Option,Check to rename current file; otherwise, move to the 'Finish' subdirectory.")
        self.option_check.setChecked(self.config.get('Option', False))
        self.option_check.stateChanged.connect(lambda: self.update_config('Option', self.option_check.isChecked()))
        self.layout.addWidget(self.option_check)

    def update_config(self, key=None, value=None):
        if key and value is not None:
            self.config[key] = value
        with open(self.config_path, 'w') as file:
            json.dump(self.config, file, indent=4)

    def start_main_logic(self):
        if self.start_button.text() == "Start":
            self.start_button.setText("Stop")
            self.thread.start()
            
        else:
            self.thread.stop()
            self.timer.start(1000)  # 每秒更新一次进度
            self.start_button.setEnabled(False)  # 禁用按钮

    def update_progress(self):
        self.output_text_box.append(f"还有任务正在进行中,请稍等。。。")
        if self.thread.active_count() == 0:
            self.timer.stop()
            self.start_button.setEnabled(True)  # 启用按钮
            self.start_button.setText("Start")

    @pyqtSlot(str)
    def update_output_text(self, text):
        self.output_text_box.append(text)

    def on_main_logic_finished(self):
        self.timer.stop()
        tmp_folder = os.path.join(self.config['Source_folder'], '.airenametmp')
        if os.path.exists(tmp_folder):
            shutil.rmtree(tmp_folder)
        QMessageBox.information(self, "完成", f"图片重命名已完成！")
        self.start_button.setText("Start")

    def create_label_and_line_edit(self, key):
        label = QLabel(key)
        self.layout.addWidget(label)
        line_edit = QLineEdit(self)
        line_edit.setText(str(self.config.get(key, '')))
        line_edit.textChanged.connect(lambda: self.update_config(key, line_edit.text()))
        self.layout.addWidget(line_edit)

def main():
    with open("config.json", "r") as file:
        config = json.load(file)

    app = QApplication(sys.argv)
    ex = ConfigGUI()
    ex.show()
    sys.exit(app.exec_())

if __name__ == '__main__':
    main()
