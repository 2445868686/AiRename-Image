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
from PyQt5.QtGui import QMouseEvent, QFontMetrics

from function import Counter, process_images_concurrently, generate_excel_report, sanitize_filename

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

    # Modified constructor to accept current_config
    def __init__(self, gui, current_config, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.gui = gui
        self.current_config = current_config # Store the config for this run
        self.stop_event = threading.Event()
        self.active_counter = Counter()

    def run(self):
        is_stopped_manually = False
        try:
            self.stop_event.clear()

            # Use self.current_config instead of self.gui.config
            total_found, success_count, failure_count, collected_renaming_data = process_images_concurrently(
                self.current_config, # Use the config passed at instantiation
                self.output_text.emit,
                self.stop_event,
                self.active_counter,
                self.gui.num_counter_ref # This counter is managed by ConfigGUI, accessed via self.gui
            )

            processed_attempts = self.gui.num_counter_ref.get_value()

            if success_count > 0 and collected_renaming_data:
                # Use self.current_config for Excel report parameters
                source_folder = self.current_config.get('Source_folder')
                output_mode = self.current_config.get('output_mode', 'finish_subfolder')
                excel_output_path = source_folder

                if output_mode == 'custom':
                    custom_folder = self.current_config.get('custom_output_folder', '')
                    if custom_folder:
                        excel_output_path = custom_folder
                elif output_mode == 'finish_subfolder':
                    excel_output_path = os.path.join(source_folder, 'Finish')

                if not os.path.isdir(excel_output_path):
                    try:
                        os.makedirs(excel_output_path, exist_ok=True)
                        self.output_text.emit(f"提示：为Excel报告创建了文件夹 {excel_output_path}")
                    except Exception as e:
                        self.output_text.emit(f"警告：无法创建Excel报告的目标文件夹 {excel_output_path}: {e}。将尝试保存到源文件夹。")
                        excel_output_path = source_folder
                        if not os.path.isdir(excel_output_path) and source_folder:
                             try: os.makedirs(excel_output_path, exist_ok=True)
                             except Exception as fallback_e: self.output_text.emit(f"警告：无法创建源文件夹作为后备Excel报告路径: {fallback_e}")

                if os.path.isdir(excel_output_path):
                    source_folder_name = os.path.basename(source_folder.rstrip('/\\')) if source_folder else "image_processing"
                    # sanitize_filename is imported and available globally in this module's context if needed,
                    # but it's better if generate_excel_report handles its internal naming well.
                    # The function is imported from function.py so MainLogicThread can use it if it constructs the name itself.
                    base_excel_filename = f"商品标题.xlsx"
                    generate_excel_report(collected_renaming_data,
                                          excel_output_path,
                                          report_filename=base_excel_filename,
                                          output_text_signal_emit=self.output_text.emit)
                else:
                    self.output_text.emit(f"错误：无法确定Excel报告的有效保存路径。跳过Excel生成。")


            if self.stop_event.is_set():
                is_stopped_manually = True
                self.output_text.emit("任务被用户停止。")

            if total_found > 0 :
                 self.output_text.emit(f"任务总结：共发现{total_found}张图片。处理尝试{processed_attempts}张，成功{success_count}张，失败{failure_count}张。")
            elif not is_stopped_manually:
                 if total_found == 0 and processed_attempts == 0 :
                    pass
                 else:
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
        # self.thread is renamed to self.processing_thread and initialized to None
        self.processing_thread = None
        self.last_run_config = None # To store config used for the last run for cleanup

        # Signals will be connected when the thread is instantiated
        # self.thread.finished.connect(self.on_main_logic_finished)
        # self.thread.output_text.connect(self.update_output_text)

        self.setWindowTitle('图片批量AI重命名-HEIBA')
        self.setGeometry(100, 100, 500, 600)
        self.centerWindow()

        self.num_counter_ref = Counter() # This counter is for ConfigGUI

        self.config_path = 'config.json'
        self.config = self.load_config() # For initial UI population and saving

        self.widget = QWidget(self)
        self.setCentralWidget(self.widget)
        self.layout = QVBoxLayout()

        self.init_ui()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_progress_after_stop_request)

        self.widget.setLayout(self.layout)
        self.apply_style()

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
            'Base_url': '',
            'Api_key': '', 'Model': 'gpt-4.1-nano-2025-04-14',
            'Image_quality_percent': 80, 'Max_workers': 10, 'Source_folder': '',
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
        self.custom_output_folder_edit.setReadOnly(True) # Click to open dialog
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
        self.source_folder_edit.setReadOnly(True) # Click to open dialog
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
        self.output_text_box = QTextEdit(self)
        self.output_text_box.setReadOnly(True)
        log_group_layout.addWidget(self.output_text_box)
        log_container_group = QGroupBox("运行日志")
        log_container_group.setLayout(log_group_layout)
        self.main_operations_layout.addWidget(log_container_group)
        self.main_operations_layout.setStretchFactor(log_container_group, 1)

        self.start_button = QPushButton("开始处理", self)
        self.start_button.clicked.connect(self.start_main_logic)
        self.main_operations_layout.addWidget(self.start_button)

        self.tab_widget.addTab(self.main_operations_tab, "主操作")
        self.tab_widget.addTab(self.configuration_tab, "配置")
        self.layout.addWidget(self.tab_widget)

    def on_output_option_changed(self, checked):
        sender = self.sender()
        if sender.isChecked(): # Process only if a radio button becomes checked
            mode = None
            enable_custom_folder_edit = False
            if sender == self.radio_finish_subfolder:
                mode = 'finish_subfolder'
            elif sender == self.radio_rename_in_place:
                mode = 'in_place'
            elif sender == self.radio_custom_folder:
                mode = 'custom'
                enable_custom_folder_edit = True

            self.custom_output_folder_edit.setEnabled(enable_custom_folder_edit)
            if mode and self.config.get('output_mode') != mode: # Update config only if mode actually changes
                self.update_config('output_mode', mode)


    def toggle_api_key_visibility(self, checked):
        self.api_key_edit.setEchoMode(QLineEdit.Normal if checked else QLineEdit.Password)

    def update_config(self, key=None, value=None):
        if key is not None: # Update the internal self.config dictionary
            self.config[key] = value
        try: # Save the entire self.config dictionary to the JSON file
            with open(self.config_path, 'w', encoding='utf-8') as file:
                json.dump(self.config, file, indent=4, ensure_ascii=False)
        except Exception as e:
            log_widget = getattr(self, 'output_text_box', None)
            msg = f"错误：无法保存配置文件 {self.config_path}: {e}"
            if log_widget:
                log_widget.append(msg)
            else:
                print(msg)


    def start_main_logic(self):
        self.output_text_box.clear()

        # Gather current configuration directly from UI elements
        current_run_config = {
            'Base_url': self.base_url_edit.text().strip(),
            'Api_key': self.api_key_edit.text().strip(),
            'Model': self.model_combo.currentText(),
            'Image_quality_percent': self.image_quality_spin.value(),
            'Max_workers': self.max_workers_spin.value(),
            'Source_folder': self.source_folder_edit.text().strip(),
            'Prompt': self.prompt_text_edit.toPlainText().strip(),
            'custom_output_folder': self.custom_output_folder_edit.text().strip()
        }
        if self.radio_finish_subfolder.isChecked():
            current_run_config['output_mode'] = 'finish_subfolder'
        elif self.radio_rename_in_place.isChecked():
            current_run_config['output_mode'] = 'in_place'
        elif self.radio_custom_folder.isChecked():
            current_run_config['output_mode'] = 'custom'
        else: # Default or error case, though one should always be checked
            current_run_config['output_mode'] = 'finish_subfolder'


        # Validate using current_run_config
        source_folder = current_run_config['Source_folder']
        if not source_folder or not os.path.isdir(source_folder):
            QMessageBox.warning(self, "配置错误", "请选择一个有效的源文件夹。")
            self.output_text_box.append("错误：源文件夹未选择或无效。")
            return
        if not current_run_config['Api_key']:
            QMessageBox.warning(self, "配置错误", "请输入有效的 API Key。")
            self.output_text_box.append("错误：API Key 未设置。")
            return
        if current_run_config['output_mode'] == 'custom':
            custom_folder = current_run_config['custom_output_folder']
            if not custom_folder:
                QMessageBox.warning(self, "配置错误", "请选择自定义输出文件夹。")
                self.custom_output_folder_edit.openFolderDialog() # Attempt to open dialog
                current_run_config['custom_output_folder'] = self.custom_output_folder_edit.text().strip() # Re-fetch after dialog
                if not current_run_config['custom_output_folder']:
                    self.output_text_box.append("错误：自定义输出文件夹仍未选择。")
                    return

            # Ensure custom output folder exists or can be created
            # Note: This uses the potentially re-fetched custom_folder path
            active_custom_folder = current_run_config['custom_output_folder']
            if active_custom_folder and not os.path.isdir(active_custom_folder):
                try:
                    os.makedirs(active_custom_folder, exist_ok=True)
                    self.output_text_box.append(f"提示：自定义输出文件夹 '{active_custom_folder}' 已创建。")
                except OSError as e:
                    QMessageBox.warning(self, "配置错误", f"无法创建自定义输出文件夹 '{active_custom_folder}': {e}")
                    self.output_text_box.append(f"错误：无法创建自定义输出文件夹 '{active_custom_folder}'")
                    return

        self.num_counter_ref.value = 0 # Reset shared counter for the new run

        if self.start_button.text() == "开始处理":
            self.last_run_config = current_run_config # Store config for this run for cleanup
            self.processing_thread = MainLogicThread(self, self.last_run_config) # Pass the fresh config
            self.processing_thread.finished.connect(self.on_main_logic_finished)
            self.processing_thread.output_text.connect(self.update_output_text)

            self.start_button.setText("停止处理")
            self.processing_thread.start()
        else: # "停止处理" was clicked
            if self.processing_thread and self.processing_thread.isRunning():
                self.output_text_box.append("状态：正在请求停止任务...")
                self.processing_thread.stop()
                self.timer.start(200) # Check progress of stopping
                self.start_button.setEnabled(False) # Disable button until fully stopped
            else: # Should not happen if button is "停止处理" and thread not running, but reset
                self.start_button.setText("开始处理")
                self.start_button.setEnabled(True)


    def update_progress_after_stop_request(self):
        if not self.processing_thread: # Safety check
            self.timer.stop()
            self.start_button.setEnabled(True)
            self.start_button.setText("开始处理")
            return

        active_threads_in_logic = self.processing_thread.active_count()
        if active_threads_in_logic == 0:
            self.timer.stop()
            self.start_button.setEnabled(True)
            self.start_button.setText("开始处理")
            self.output_text_box.append("状态：所有活动任务已完成，处理已停止。")
            # The thread's 'finished' signal should call on_main_logic_finished.
            # If the thread is no longer running (it should have emitted 'finished'), this check is fine.
            if not self.processing_thread.isRunning():
                 # on_main_logic_finished should be called by the thread's finished signal.
                 # If it hasn't been, and the thread is truly stopped, this could be a fallback,
                 # but usually, the signal mechanism is preferred.
                 pass
        else:
            self.output_text_box.append(f"状态：等待 {active_threads_in_logic} 个活动任务完成...")

    @pyqtSlot(str)
    def update_output_text(self, text):
        self.output_text_box.append(text)
        self.output_text_box.ensureCursorVisible()
        QApplication.processEvents() # Process events to keep UI responsive

    @pyqtSlot(bool)
    def on_main_logic_finished(self, stopped_manually=False):
        # This method is called when the MainLogicThread emits its 'finished' signal.
        # Reset button state if timer wasn't involved or has already stopped.
        if not self.timer.isActive():
            self.start_button.setText("开始处理")
            self.start_button.setEnabled(True)

        # Cleanup temporary folders using the config from the run that just finished
        if hasattr(self, 'last_run_config') and self.last_run_config:
            source_folder = self.last_run_config.get('Source_folder')
            if source_folder and os.path.isdir(source_folder): # Check if still valid
                 # Clean up logic for .airenametmp
                 for root, dirs, files_unused in os.walk(source_folder, topdown=False):
                     if '.airenametmp' in dirs:
                         tmp_dir_to_remove = os.path.join(root, '.airenametmp')
                         try:
                             shutil.rmtree(tmp_dir_to_remove)
                             self.output_text_box.append(f"提示：临时文件夹 {tmp_dir_to_remove} 已清理。")
                         except Exception as e:
                             self.output_text_box.append(f"警告：清理临时文件夹 {tmp_dir_to_remove} 失败: {e}")
                     # This condition might be redundant if .airenametmp is always a direct child
                     # or handled by the above. Kept for consistency with original logic.
                     if os.path.basename(root) == '.airenametmp' and os.path.dirname(root).startswith(source_folder):
                         try:
                             if os.path.exists(root):
                                shutil.rmtree(root)
                                self.output_text_box.append(f"提示：临时文件夹 {root} 已清理。")
                         except Exception as e:
                             self.output_text_box.append(f"警告：清理临时文件夹 {root} 失败: {e}")
            else:
                 self.output_text_box.append("警告：无法获取上次运行的源文件夹路径，跳过临时文件清理。")
        else:
            self.output_text_box.append("警告：未找到上次运行的配置信息，无法进行临时文件清理。")


        msg_title = "已停止" if stopped_manually else "完成"
        msg_text = "图片重命名任务已停止。" if stopped_manually else "图片重命名任务已处理完毕！"
        QMessageBox.information(self, msg_title, f"{msg_text} 查看日志获取详细信息。")

    def closeEvent(self, event):
        self.update_config() # Save the latest UI state to config.json before exiting

        if self.processing_thread and self.processing_thread.isRunning():
            reply = QMessageBox.question(self, '退出确认', "处理仍在进行中。确定退出吗？",
                                       QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if reply == QMessageBox.Yes:
                self.processing_thread.stop() # Request stop
                # Consider self.processing_thread.wait(milliseconds) if graceful shutdown is critical
                # and can complete quickly. Otherwise, just accept and close.
                event.accept()
            else:
                event.ignore()
                return # Explicitly return if ignoring
        else:
            event.accept()

    def apply_style(self):
        # Stylesheet remains the same
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
