# ui.py
import sys
import os
import json
import threading 
import shutil # For rmtree in cleanup

from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
                             QSpinBox, QPushButton, QTextEdit, QCheckBox, QMessageBox, QFileDialog, QComboBox, QGroupBox,
                             QRadioButton, QTabWidget)
from PyQt5.QtCore import QThread, pyqtSignal, pyqtSlot, QTimer, Qt
from PyQt5.QtGui import QMouseEvent, QFontMetrics # Added QFontMetrics

from function import Counter, process_images_concurrently

class FolderLineEdit(QLineEdit):
    def __init__(self, config_key, update_callback, parent=None, *args, **kwargs):
        super().__init__(parent, *args, **kwargs)
        self.config_key = config_key
        self.update_callback = update_callback

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton and self.isEnabled():
            self.openFolderDialog()
            event.accept() 
        else:
            super().mousePressEvent(event)

    def openFolderDialog(self):
        parent_widget = self.parent() 
        current_path = self.text()
        if not os.path.isdir(current_path): 
            current_path = os.path.expanduser("~")

        directory = QFileDialog.getExistingDirectory(parent_widget, "选择文件夹", current_path)
        if directory:
            self.setText(directory)
            if self.update_callback:
                self.update_callback(self.config_key, directory)

class MainLogicThread(QThread):
    finished = pyqtSignal(bool) 
    output_text = pyqtSignal(str)
    
    def __init__(self, gui, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.gui = gui 
        self.stop_event = threading.Event()
        self.active_counter = Counter() 

    def run(self):
        is_stopped_manually = False
        try:
            self.stop_event.clear()
            
            total_found, success_count, failure_count = process_images_concurrently(
                self.gui.config, 
                self.output_text.emit, 
                self.stop_event, 
                self.active_counter,
                self.gui.num_counter_ref 
            )
            
            processed_attempts = self.gui.num_counter_ref.get_value()
            
            if self.stop_event.is_set():
                is_stopped_manually = True
                self.output_text.emit("任务被用户停止。")
            
            if total_found > 0 :
                 self.output_text.emit(f"任务总结：共发现{total_found}张图片。处理尝试{processed_attempts}张，成功{success_count}张，失败{failure_count}张。")
            elif not is_stopped_manually: # Only show this if not stopped and no images were found/processed
                 if total_found == 0 and processed_attempts == 0 : # Check if any images were found initially
                    # The message "提示：在源文件夹中没有找到符合条件的图片文件。" is already emitted by process_images_concurrently
                    pass # Avoid redundant "未处理任何图片" if specific "no files found" message was shown.
                 else: # If images were found but none processed due to other reasons (e.g. all failed before first success)
                    self.output_text.emit("任务完成：未处理任何图片（可能由于处理前停止或全部处理失败）。")


        except Exception as e:
            self.output_text.emit(f"主逻辑线程发生错误: {str(e)}")
            is_stopped_manually = False 
        finally:
            self.finished.emit(is_stopped_manually or self.stop_event.is_set())

    def stop(self):
        self.output_text.emit("正在发送停止信号...")
        self.stop_event.set()

    def active_count(self):
        return self.active_counter.get_value()

class ConfigGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.thread = MainLogicThread(self)
        self.thread.finished.connect(self.on_main_logic_finished)
        self.thread.output_text.connect(self.update_output_text)
        
        self.setWindowTitle('图片批量AI重命名-HEIBA')
        # 调整初始窗口大小
        self.setGeometry(100, 100, 500, 600) # 略微减小初始大小
        self.centerWindow()
        
        self.num_counter_ref = Counter() 

        self.config_path = 'config.json' 
        self.config = self.load_config()

        self.widget = QWidget(self)
        self.setCentralWidget(self.widget)
        self.layout = QVBoxLayout() 

        self.init_ui() 
        
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_progress_after_stop_request)
        
        self.widget.setLayout(self.layout) 
        self.apply_style()
        
        # 设置窗口的最小尺寸
        self.setMinimumSize(500, 600) 

    def centerWindow(self):
        try:
            screen_geometry = QApplication.primaryScreen().availableGeometry()
            window_geometry = self.geometry()
            x = (screen_geometry.width() - window_geometry.width()) // 2
            y = (screen_geometry.height() - window_geometry.height()) // 2
            self.move(x, y)
        except AttributeError: 
            pass

    def load_config(self):
        default_config = {
            'Base_url': 'https://yunwu.ai', 
            'Api_key': '', 'Model': 'gpt-4o-mini',
            'Image_quality_percent': 85, 'Max_workers': 5, 'Source_folder': '',
            'Prompt': '请识别图片内容并用中文命名，要求：1.简洁(不超过10个字)。2.准确。3.不包含任何标点及特殊符号。', 
            'output_mode': 'finish_subfolder', 'custom_output_folder': ''
        }
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, 'r', encoding='utf-8') as file:
                    loaded_config = json.load(file)
                
                final_config = default_config.copy() 
                final_config.update(loaded_config)

                if 'Option' in final_config: del final_config['Option']
                if 'Proxy_quality' in final_config:
                    if 'Image_quality_percent' not in loaded_config and isinstance(final_config.get('Proxy_quality'), float):
                         final_config['Image_quality_percent'] = int(final_config['Proxy_quality'] * 100)
                    del final_config['Proxy_quality']
                
                final_config['Image_quality_percent'] = int(final_config.get('Image_quality_percent', default_config['Image_quality_percent']))
                final_config['Max_workers'] = int(final_config.get('Max_workers', default_config['Max_workers']))

                return final_config
            except json.JSONDecodeError:
                QMessageBox.warning(self, "配置错误", f"配置文件 {self.config_path} 格式错误，将使用默认配置。")
                return default_config
            except Exception as e:
                QMessageBox.warning(self, "配置加载错误", f"加载配置文件时出错: {e}。将使用默认配置。")
                return default_config
        return default_config

    def init_ui(self):
        self.tab_widget = QTabWidget()
        self.tab_widget.tabBar().setExpanding(True) 

        self.main_operations_tab = QWidget()
        self.configuration_tab = QWidget()  

        self.main_operations_layout = QVBoxLayout(self.main_operations_tab)
        self.configuration_layout = QVBoxLayout(self.configuration_tab)

        # --- "配置" Tab Content ---
        api_group = QGroupBox("API 配置")
        api_layout = QVBoxLayout()
        base_url_label = QLabel("Base URL:")
        self.base_url_edit = QLineEdit()
        self.base_url_edit.setPlaceholderText("https://api.openai.com")
        self.base_url_edit.setText(self.config.get('Base_url', 'https://yunwu.ai'))
        self.base_url_edit.textChanged.connect(lambda text: self.update_config('Base_url', text.strip()))
        api_layout.addWidget(base_url_label)
        api_layout.addWidget(self.base_url_edit)
        api_key_label = QLabel("API 密钥:")
        self.api_key_edit = QLineEdit()
        self.api_key_edit.setText(self.config.get('Api_key', ''))
        self.api_key_edit.setEchoMode(QLineEdit.Password)
        self.api_key_edit.textChanged.connect(lambda text: self.update_config('Api_key', text.strip()))
        api_layout.addWidget(api_key_label)
        api_layout.addWidget(self.api_key_edit)
        show_key_checkbox = QCheckBox("显示 API Key")
        show_key_checkbox.toggled.connect(self.toggle_api_key_visibility)
        api_layout.addWidget(show_key_checkbox)
        api_group.setLayout(api_layout)
        self.configuration_layout.addWidget(api_group)

        param_group = QGroupBox("参数设置")
        param_layout = QHBoxLayout()
        self.model_combo = QComboBox(self)
        self.model_combo.addItems(["gpt-4.1-nano-2025-04-14","gpt-4.1-mini-2025-04-14","gpt-4.1-2025-04-14","gpt-4o-mini", "gpt-4o",])
        self.model_combo.setCurrentText(self.config.get('Model', 'gpt-4o-mini'))
        self.model_combo.currentTextChanged.connect(lambda text: self.update_config('Model', text))
        param_layout.addWidget(QLabel("模型:"))
        param_layout.addWidget(self.model_combo)
        self.image_quality_spin = QSpinBox()
        self.image_quality_spin.setRange(1, 95)
        self.image_quality_spin.setValue(int(self.config.get('Image_quality_percent', 85)))
        self.image_quality_spin.setToolTip("图片压缩质量 (1-95)。主要影响JPEG。")
        self.image_quality_spin.valueChanged.connect(lambda value: self.update_config('Image_quality_percent', value))
        param_layout.addWidget(QLabel("图片质量:")) 
        param_layout.addWidget(self.image_quality_spin)
        self.max_workers_spin = QSpinBox()
        self.max_workers_spin.setRange(1, 100)
        self.max_workers_spin.setValue(int(self.config.get('Max_workers', 5)))
        self.max_workers_spin.valueChanged.connect(lambda value: self.update_config('Max_workers', value))
        param_layout.addWidget(QLabel("线程数:"))
        param_layout.addWidget(self.max_workers_spin)
        param_group.setLayout(param_layout)
        self.configuration_layout.addWidget(param_group)

        output_dest_group = QGroupBox("输出目标设置")
        output_dest_layout = QVBoxLayout()
        self.radio_finish_subfolder = QRadioButton("保存在原图文件夹下的 'Finish' 子文件夹")
        self.radio_rename_in_place = QRadioButton("直接在原图文件夹中重命名")
        custom_folder_hbox = QHBoxLayout()
        self.radio_custom_folder = QRadioButton("保存到指定文件夹:")
        self.custom_output_folder_edit = FolderLineEdit('custom_output_folder', self.update_config, self)
        self.custom_output_folder_edit.setPlaceholderText("点击选择自定义输出文件夹")
        self.custom_output_folder_edit.setText(self.config.get('custom_output_folder', ''))
        self.custom_output_folder_edit.setReadOnly(True)
        custom_folder_hbox.addWidget(self.radio_custom_folder)
        custom_folder_hbox.addWidget(self.custom_output_folder_edit)
        output_dest_layout.addWidget(self.radio_finish_subfolder)
        output_dest_layout.addWidget(self.radio_rename_in_place)
        output_dest_layout.addLayout(custom_folder_hbox)
        output_dest_group.setLayout(output_dest_layout)
        self.configuration_layout.addWidget(output_dest_group)
        self.radio_finish_subfolder.toggled.connect(self.on_output_option_changed)
        self.radio_rename_in_place.toggled.connect(self.on_output_option_changed)
        self.radio_custom_folder.toggled.connect(self.on_output_option_changed)
        current_output_mode = self.config.get('output_mode', 'finish_subfolder')
        if current_output_mode == 'finish_subfolder': self.radio_finish_subfolder.setChecked(True)
        elif current_output_mode == 'in_place': self.radio_rename_in_place.setChecked(True)
        elif current_output_mode == 'custom': self.radio_custom_folder.setChecked(True)
        else: self.radio_finish_subfolder.setChecked(True); self.update_config('output_mode', 'finish_subfolder')
        self.custom_output_folder_edit.setEnabled(self.radio_custom_folder.isChecked())
        self.configuration_layout.addStretch(1)

        # --- "主操作" Tab Content ---
        folder_group_layout = QHBoxLayout() 
        folder_label = QLabel("图片文件夹:")
        self.source_folder_edit = FolderLineEdit('Source_folder', self.update_config, self)
        self.source_folder_edit.setPlaceholderText("点击选择图片所在的文件夹")
        self.source_folder_edit.setText(self.config.get('Source_folder', ''))
        self.source_folder_edit.setReadOnly(True)
        folder_group_layout.addWidget(folder_label)
        folder_group_layout.addWidget(self.source_folder_edit)
        folder_group = QGroupBox("源文件选择") 
        folder_group.setLayout(folder_group_layout) 
        self.main_operations_layout.addWidget(folder_group)

        prompt_group_layout = QVBoxLayout() 
        prompt_label = QLabel("提示词 (Prompt):")
        self.prompt_text_edit = QTextEdit()
        default_prompt = '请识别图片内容并用中文命名，要求：1.简洁(不超过10个字)。2.准确。3.不包含任何标点及特殊符号。'
        self.prompt_text_edit.setPlaceholderText(default_prompt)
        self.prompt_text_edit.setText(self.config.get('Prompt', default_prompt))
        font_metrics = QFontMetrics(self.prompt_text_edit.font())
        self.prompt_text_edit.setMinimumHeight(font_metrics.lineSpacing() * 4 + 10)
        self.prompt_text_edit.textChanged.connect(lambda: self.update_config('Prompt', self.prompt_text_edit.toPlainText()))
        prompt_group_layout.addWidget(prompt_label)
        prompt_group_layout.addWidget(self.prompt_text_edit)
        prompt_container_group = QGroupBox("AI 提示词设定")
        prompt_container_group.setLayout(prompt_group_layout)
        self.main_operations_layout.addWidget(prompt_container_group)
        
        log_group_layout = QVBoxLayout()
        # log_label = QLabel("日志:") # REMOVED as per request
        self.output_text_box = QTextEdit(self) 
        self.output_text_box.setReadOnly(True)
        # log_group_layout.addWidget(log_label) # REMOVED as per request
        log_group_layout.addWidget(self.output_text_box)
        log_container_group = QGroupBox("运行日志") # GroupBox title serves as the label
        log_container_group.setLayout(log_group_layout)
        self.main_operations_layout.addWidget(log_container_group)
        self.main_operations_layout.setStretchFactor(log_container_group, 1) # Ensure this group (and log box) expands

        self.start_button = QPushButton("开始处理", self) 
        self.start_button.clicked.connect(self.start_main_logic)
        self.main_operations_layout.addWidget(self.start_button)

        self.tab_widget.addTab(self.main_operations_tab, "主操作")
        self.tab_widget.addTab(self.configuration_tab, "配置")
        self.layout.addWidget(self.tab_widget)

    def on_output_option_changed(self, checked):
        sender = self.sender() 
        if sender.isChecked(): 
            mode = None
            if sender == self.radio_finish_subfolder: 
                mode = 'finish_subfolder'; self.custom_output_folder_edit.setEnabled(False)
            elif sender == self.radio_rename_in_place: 
                mode = 'in_place'; self.custom_output_folder_edit.setEnabled(False)
            elif sender == self.radio_custom_folder: 
                mode = 'custom'; self.custom_output_folder_edit.setEnabled(True)
            if mode and self.config.get('output_mode') != mode: 
                self.update_config('output_mode', mode)

    def toggle_api_key_visibility(self, checked):
        self.api_key_edit.setEchoMode(QLineEdit.Normal if checked else QLineEdit.Password)
    
    def update_config(self, key=None, value=None):
        if key is not None: 
            self.config[key] = value
        try:
            with open(self.config_path, 'w', encoding='utf-8') as file: 
                json.dump(self.config, file, indent=4, ensure_ascii=False)
        except Exception as e:
            if hasattr(self, 'output_text_box'): 
                 self.output_text_box.append(f"错误：无法保存配置文件 {self.config_path}: {e}")
            else: 
                 print(f"错误：无法保存配置文件 {self.config_path}: {e}")


    def start_main_logic(self):
        self.output_text_box.clear() 
        source_folder = self.config.get('Source_folder', '')
        if not source_folder or not os.path.isdir(source_folder):
            QMessageBox.warning(self, "配置错误", "请选择一个有效的源文件夹。"); self.output_text_box.append("错误：源文件夹未选择或无效。"); return
        if not self.config.get('Api_key', '').strip():
            QMessageBox.warning(self, "配置错误", "请输入有效的 API Key。"); self.output_text_box.append("错误：API Key 未设置。"); return
        if self.config.get('output_mode') == 'custom':
            custom_folder = self.config.get('custom_output_folder', '')
            if not custom_folder:
                QMessageBox.warning(self, "配置错误", "请选择自定义输出文件夹。"); self.custom_output_folder_edit.openFolderDialog();
                if not self.config.get('custom_output_folder', ''): self.output_text_box.append("错误：自定义输出文件夹仍未选择。"); return 
            
            current_custom_folder = self.config.get('custom_output_folder', '') 
            if current_custom_folder and not os.path.isdir(current_custom_folder): 
                try: os.makedirs(current_custom_folder, exist_ok=True); self.output_text_box.append(f"提示：自定义输出文件夹 '{current_custom_folder}' 已创建。")
                except OSError as e: 
                    QMessageBox.warning(self, "配置错误", f"无法创建自定义输出文件夹 '{current_custom_folder}': {e}"); 
                    self.output_text_box.append(f"错误：无法创建自定义输出文件夹 '{current_custom_folder}'"); return
        
        self.num_counter_ref.value = 0 

        if self.start_button.text() == "开始处理":
            self.start_button.setText("停止处理"); self.thread.start()
        else:
            self.output_text_box.append("状态：正在请求停止任务..."); self.thread.stop() # Added "状态：" for consistency
            self.timer.start(200); self.start_button.setEnabled(False)
    
    def update_progress_after_stop_request(self):
        active_threads = self.thread.active_count()
        if active_threads == 0:
            self.timer.stop(); 
            self.start_button.setEnabled(True); self.start_button.setText("开始处理")
            self.output_text_box.append("状态：所有活动任务已完成，处理已停止。") # Added "状态："
            if not self.thread.isRunning():
                 self.on_main_logic_finished(stopped_manually=True)
        else: self.output_text_box.append(f"状态：等待 {active_threads} 个活动任务完成...") # Added "状态："

    @pyqtSlot(str)
    def update_output_text(self, text):
        self.output_text_box.append(text); 
        self.output_text_box.ensureCursorVisible() 
        QApplication.processEvents() 
    
    @pyqtSlot(bool) 
    def on_main_logic_finished(self, stopped_manually=False):
        if not self.timer.isActive(): 
            self.start_button.setText("开始处理"); self.start_button.setEnabled(True)
        
        source_folder = self.config.get('Source_folder')
        if source_folder and os.path.isdir(source_folder):
             # Clean up logic for .airenametmp seems specific and can be kept as is.
             for root, dirs, files_unused in os.walk(source_folder, topdown=False): 
                 if '.airenametmp' in dirs:
                     tmp_dir_to_remove = os.path.join(root, '.airenametmp')
                     try:
                         shutil.rmtree(tmp_dir_to_remove)
                         self.output_text_box.append(f"提示：临时文件夹 {tmp_dir_to_remove} 已清理。")
                     except Exception as e:
                         self.output_text_box.append(f"警告：清理临时文件夹 {tmp_dir_to_remove} 失败: {e}")
                 # This condition might be redundant if .airenametmp is always a direct child of source_folder
                 # or handled by the above. Keeping for now as per original logic.
                 if os.path.basename(root) == '.airenametmp' and os.path.dirname(root).startswith(source_folder):
                     try:
                         if os.path.exists(root): 
                            shutil.rmtree(root)
                            self.output_text_box.append(f"提示：临时文件夹 {root} 已清理。")
                     except Exception as e:
                         self.output_text_box.append(f"警告：清理临时文件夹 {root} 失败: {e}")


        msg_title = "已停止" if stopped_manually else "完成"
        msg_text = "图片重命名任务已停止。" if stopped_manually else "图片重命名任务已处理完毕！"
        QMessageBox.information(self, msg_title, f"{msg_text} 查看日志获取详细信息。")
    
    def closeEvent(self, event):
        if self.thread.isRunning():
            if QMessageBox.question(self, '退出确认', "处理仍在进行中。确定退出吗？",
                                       QMessageBox.Yes | QMessageBox.No, QMessageBox.No) == QMessageBox.Yes:
                self.thread.stop(); self.update_config(); event.accept()
            else: event.ignore(); return
        else: self.update_config(); event.accept()
    
    def apply_style(self):
        self.setStyleSheet("""
            QMainWindow {
                background-color: #F8F9FA; 
                font-family: "Segoe UI", Arial, sans-serif;
            }
            QTabWidget::pane { 
                border-top: 1px solid #E0E0E0; 
                background-color: #FFFFFF; 
            }
            QTabBar::tab {
                background: #F1F3F5; 
                border: 1px solid #E0E0E0;
                border-bottom: none; 
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
                padding: 8px 18px; 
                margin-right: 1px;
                color: #555555; 
            }
            QTabBar::tab:selected {
                background: #FFFFFF; 
                border-color: #E0E0E0;
                border-bottom-color: #FFFFFF; 
                color: #000000; 
            }
            QTabBar::tab:!selected:hover {
                background: #E9ECEF; 
                color: #333333;
            }
            QGroupBox {
                border: 1px solid #E0E0E0; 
                border-radius: 8px; 
                margin-top: 10px; 
                padding: 10px; 
                background-color: #FFFFFF; 
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                padding: 3px 8px; 
                color: #333333; 
                font-size: 14px; 
                font-weight: bold;
            }
            QLabel {
                font-size: 14px;
                color: #212529; 
                padding-top: 4px; 
                margin-bottom: 3px; 
            }
            QLineEdit, QSpinBox, QComboBox { 
                padding: 8px;
                border: 1px solid #CED4DA; 
                border-radius: 6px; 
                font-size: 14px;
                background-color: #FFFFFF; 
                color: #212529; 
            }
            QTextEdit { 
                padding: 8px;
                border: 1px solid #CED4DA; 
                border-radius: 6px; 
                font-size: 14px;
                background-color: #FFFFFF; 
                color: #212529; 
            }
            QLineEdit:focus, QTextEdit:focus, QSpinBox:focus, QComboBox:focus {
                border-color: #28A745; 
            }
            QPushButton {
                background-color: #28A745; 
                color: #FFFFFF; 
                padding: 10px 20px;
                border: none;
                border-radius: 6px; 
                font-size: 15px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #218838; 
            }
            QPushButton:disabled {
                background-color: #E9ECEF; 
                color: #6C757D; 
            }
            QCheckBox, QRadioButton {
                font-size: 14px;
                spacing: 8px;
                color: #212529; 
            }
            QTextEdit[readOnly="true"] { 
                background-color: #F8F9FA; 
                color: #212529; 
                border: 1px solid #CED4DA; 
                border-radius: 6px; 
            }
        """)
