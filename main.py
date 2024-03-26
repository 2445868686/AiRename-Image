from openai import OpenAI
from PIL import Image
import io
import cairosvg
import re
import base64
import requests
import shutil
import sys
import os
import json
from PyQt5.QtWidgets import QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QSpinBox, QPushButton, QTextEdit, QCheckBox, QMessageBox, QFileDialog
from PyQt5.QtCore import QThread, pyqtSignal, pyqtSlot
from PyQt5.QtGui import QIcon, QMouseEvent


# Function to encode the image
def encode_image(image_path):
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode('utf-8')
    
def remove_punctuation_at_end(sentence):
    # 使用正则表达式匹配句子末尾的标点符号并删除
    return re.sub(r'[。？！，、；：“”‘’《》（）【】『』「」\[\]\.,;:"\'?!(){}<>]+$', '', sentence)

def compress_and_encode_image(image_path, quality=85, max_size=(1080, 1080)):
    """
    压缩并编码图片为Base64字符串，并自动处理特定格式。
    参数：
    - image_path: 原始图片路径。
    - quality: 输出图片质量，默认为85。
    - max_size: 输出图片最大尺寸，默认为(1080, 1080)。
    返回：
    - base64_encoded: 图片的Base64编码字符串。
    - mime_type: 图片的MIME类型。
    """
    with Image.open(image_path) as img:
        img.thumbnail(max_size)

        # 处理webp图像或其他需要特别处理的格式
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

    return base64_encoded, mime_type


def process_images(config, output_text_signal):
    try:
        output_text_signal.emit("图片重命名已开始：")

        # 加载配置参数
        api_key = config['Api_key']
        base_url = config['Base_url']
        source_folder = config['Source_folder']
        Proxy_quality = config['Proxy_quality']
        gpt_model = config['Model']
        Prompt = config['Prompt']
        Option = config['Option']
        # 如果目标文件夹不存在，则创建它

        # 图像文件扩展名
        suffix_name = ('.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.tif', '.webp', '.heif', '.heic', '.svg')

        start_number = 0
        quality_value = min(95, max(1, int(Proxy_quality * 10)))

        for root, dirs, files in os.walk(source_folder):   
             # 在进入下一级目录之前，过滤掉不需要遍历的目录（如 "tmp"）
            dirs[:] = [d for d in dirs if d != 'tmp']
            for filename in files:
            # 检查文件是否是图片
                if filename.lower().endswith(suffix_name):
                    relative_path = os.path.relpath(root, source_folder)
                    image_path = os.path.join(source_folder, relative_path.lstrip('.'), filename)
                    print(f"1.{image_path}")
                    # 获取图像格式
                    image_format = os.path.splitext(filename)[1][1:] 
                    print(f"2.{image_format}")

                    if image_format.lower() == "svg":
                        tmp_folder = os.path.join(root, 'tmp')  # 在当前目录创建 Finish 文件夹
                        if not os.path.exists(tmp_folder):
                                os.makedirs(tmp_folder)
                        # 使用 CairoSVG 将 SVG 转换为 PNG
                        output_png_filename = os.path.splitext(filename)[0] + ".png"  # 获取不带扩展名的文件名并添加.png
                        output_png_path = os.path.join(tmp_folder, output_png_filename)  # 定义输出PNG文件的路径

                        cairosvg.svg2png(url=image_path, write_to=output_png_path)
                        tmp_image_path = output_png_path  # 更新 image_path
                        #tmp_image_format = "PNG"  # 更新 image_format

                        # 这里假设您已经有适当的方法来将PNG图像转换为Base64，以下仅为示例
                        base64_image, mime_type = compress_and_encode_image(tmp_image_path, quality=quality_value, max_size=(512, 512))
                       # with open(tem_image_path, "rb") as img_file:
                         #   base64_image = base64.b64encode(img_file.read()).decode('utf-8')
                    else:
                        # 使用 compress_and_encode_image 函数处理其他格式的图像
                        base64_image, mime_type = compress_and_encode_image(image_path, quality=quality_value, max_size=(512, 512))

                    #base64_image = compress_and_encode_image(image_path, output_format=image_format, quality=quality_value, max_size=(512, 512))
                    start_number += 1 
                     
                    headers = {
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {api_key}"
                    }

                    payload = {
                        "model": gpt_model,
                        "messages": [
                            {
                                "role": "user",
                                "content": [
                                    {
                                        "type": "text",
                                        "text": Prompt
                                    },
                                    {
                                        "type": "image_url",
                                        "image_url": {
                                            "url": f"data:{mime_type};base64,{base64_image}"
                                        }
                                    }
                                ]
                            }
                        ],
                        "max_tokens": 300
                    }

                    response = requests.post(base_url, headers=headers, json=payload)
                    print(f"4.{response.status_code}")
                    try:
                        if response.status_code == 200:
                            response_data = response.json()
                            if 'choices' in response_data and len(response_data['choices']) > 0 and 'message' in response_data['choices'][0] and 'content' in response_data['choices'][0]['message']:
                                new_name = response_data['choices'][0]['message']['content']
                                new_filename = f'{remove_punctuation_at_end(new_name)}.{image_format}'
                                if Option :
                                    new_file = os.path.join(source_folder, relative_path, new_filename)
                                    os.replace(image_path, new_file)
                                else:                      
                                    destination_folder = os.path.join(root, 'Finish')  # 在当前目录创建 Finish 文件夹
                                    if not os.path.exists(destination_folder):
                                        os.makedirs(destination_folder)
                                    new_file = os.path.join(destination_folder, new_filename)
                                    shutil.copy(image_path, new_file)   
            #                    processed_count += 1
                                output_text_signal.emit(f'第{start_number}张图片重命名完成：{new_name}')
                                continue
                    # 如果响应状态码不是200或缺少必要的数据，则打印错误并跳过此图片
                        output_text_signal.emit(f"{response.status_code},无法处理第{start_number}张图片")
                    except Exception as e:
                        output_text_signal.emit(f"处理图片时发生错误：{e}，跳过第{start_number}张图片。")

    except Exception as e:
        output_text_signal.emit(f"运行过程中发生错误: {e}")
    output_text_signal.emit(f"{start_number}张图片重命名完成")
    temp_folder_path = os.path.join(root, 'tmp')  # temp文件夹的路径
    if os.path.exists(temp_folder_path):
        shutil.rmtree(temp_folder_path)
        
class MainLogicThread(QThread):
    def __init__(self, gui, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.gui = gui  # 存储 gui 实例
        self._stop_requested = False  # 添加停止请求标志
        
    def run(self):
        try:
            process_images(self.gui.config, self.gui.thread.output_text)
        except Exception as e:
            self.gui.thread.output_text.emit(f"发生错误: {str(e)}")
        self.finished.emit()

    def stop(self):  # 添加停止方法
        self._stop_requested = True

    finished = pyqtSignal()
    output_text = pyqtSignal(str)  # 添加信号用于传递输出文本


# 自定义的QLineEdit类，用于点击时打开文件夹选择对话框
class FolderLineEdit(QLineEdit):
    def __init__(self, update_callback, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.update_callback = update_callback  # 保存传入的更新配置的回调函数

    def mousePressEvent(self, event: QMouseEvent):
        super().mousePressEvent(event)
        self.openFolderDialog()

    def openFolderDialog(self):
        directory = QFileDialog.getExistingDirectory(self, "选择文件夹")
        if directory:  # 确保用户选择了文件夹
            self.setText(directory)  # 更新输入框显示路径
            if self.update_callback:  # 如果存在回调函数，则调用它更新配置
                self.update_callback('Source_folder', directory)


class ConfigGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.thread = MainLogicThread(self)
        self.thread.finished.connect(self.on_main_logic_finished)
        self.thread.output_text.connect(self.update_output_text)
        self.setWindowTitle('AiRename-Image')
        self.setGeometry(100, 100, 400, 400)  # 设置初始大小
        self.centerWindow()  # 调用centerWindow方法来居中窗口
        self.widget = QWidget(self)
        self.setCentralWidget(self.widget)
        self.layout = QVBoxLayout()

        self.config_path = 'config.json'
        self.config = self.load_config()

        self.init_ui()
        self.widget.setLayout(self.layout)
        self.start_button.clicked.connect(self.start_main_logic)


    def centerWindow(self):
            # 获取屏幕尺寸和窗口尺寸
            screen = QApplication.primaryScreen().geometry()
            windowSize = self.geometry()

            # 计算窗口左上角的新位置
            left = (screen.width() - windowSize.width()) / 2
            top = (screen.height() - windowSize.height()) / 2

            # 移动窗口
            self.move(int(left), int(top)) 

    def load_config(self):
        if os.path.exists(self.config_path):
            with open(self.config_path, 'r') as file:
                return json.load(file)
        return {}
    
    def init_ui(self):
        # 初始化UI控件

        # Api_key
        self.create_label_and_line_edit('Api_key')

        # Base_url
        self.create_label_and_line_edit('Base_url')
        
        # Source_folder选择
        self.source_folder_label = QLabel('Source_folder')
        self.layout.addWidget(self.source_folder_label)
        
        self.source_folder_edit = FolderLineEdit(self.update_config, self)
        self.source_folder_edit.setText(self.config.get('Source_folder', ''))
        self.source_folder_edit.setReadOnly(True)  # 设置为只读
        self.layout.addWidget(self.source_folder_edit)

        # Prompt - 将其移动到Source folder和Model之间
        self.create_prompt_editor()

        # Model和Proxy_quality放在一行，放在Prompt下方
        model_proxy_layout = QHBoxLayout()
        self.model_label = QLabel('Model')
        self.model_edit = QLineEdit(self)
        self.model_edit.setText(self.config.get('Model', ''))
        self.model_edit.setReadOnly(True)  # 设置为只读
        model_proxy_layout.addWidget(self.model_label)
        model_proxy_layout.addWidget(self.model_edit)

        self.proxy_quality_label = QLabel('Proxy_quality')
        self.proxy_quality_spin = QSpinBox()
        self.proxy_quality_spin.setRange(0, 100)
        self.proxy_quality_spin.setValue(int(self.config.get('Proxy_quality', 0) * 100))
        self.proxy_quality_spin.valueChanged.connect(lambda: self.update_config('Proxy_quality', self.proxy_quality_spin.value() / 100))
        model_proxy_layout.addWidget(self.proxy_quality_label)
        model_proxy_layout.addWidget(self.proxy_quality_spin)

        self.layout.addLayout(model_proxy_layout)

        # Option - 将其放在Model和Proxy_quality的下方
        self.create_option_checkbox()
        
        # 将开始按钮移到最后添加
        self.start_button = QPushButton("Start", self)
        self.start_button.clicked.connect(self.start_main_logic)
        self.layout.addWidget(self.start_button)

        # 添加用于显示输出信息的文本框
        self.output_text_box = QTextEdit(self)
        self.output_text_box.setReadOnly(True)  # 设置为只读
        self.layout.addWidget(self.output_text_box)

    def select_source_folder(self):
        directory = QFileDialog.getExistingDirectory(self, "选择文件夹")
        if directory:  # 确保用户选择了文件夹
            self.config['Source_folder'] = directory
            self.source_folder_edit.setText(directory)  # 更新QLineEdit显示路径
            self.update_config()

    
    def create_prompt_editor(self):
        label = QLabel('Prompt')
        self.layout.addWidget(label)
        self.prompt_text_edit = QTextEdit()
        self.prompt_text_edit.setText(self.config.get('Prompt', ''))
        self.prompt_text_edit.textChanged.connect(lambda: self.update_config('Prompt', self.prompt_text_edit.toPlainText()))
        self.layout.addWidget(self.prompt_text_edit)

    def create_option_checkbox(self):
        self.option_check = QCheckBox("Option,Check to rename current file; otherwise, save new in 'Finish' subdirectory.")
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
            self.start_button.setText("Stop")  # 更改按钮文本
            self.thread.start()
        else:
            self.thread.stop()  # 请求停止线程


    @pyqtSlot(str)
    def update_output_text(self, text):
        self.output_text_box.append(text)  # 将输出文本追加到文本框

    def on_main_logic_finished(self):
        QMessageBox.information(self, "完成", f"图片重命名已完成！")
        self.start_button.setText("Start")  # 恢复按钮文本
    
    def create_label_and_line_edit(self, key):
        label = QLabel(key)
        self.layout.addWidget(label)
        line_edit = QLineEdit(self)
        line_edit.setText(str(self.config.get(key, '')))
        line_edit.textChanged.connect(lambda: self.update_config(key, line_edit.text()))
        self.layout.addWidget(line_edit)

def main():
    app = QApplication(sys.argv)
    ex = ConfigGUI()
    ex.show()
    sys.exit(app.exec_())

if __name__ == '__main__':
    main()
    
