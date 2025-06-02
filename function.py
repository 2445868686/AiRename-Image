# function.py
from PIL import Image
import io
import concurrent.futures
import re
import base64
import requests
import shutil
import os
import json
import threading
# Note: 'sys' and 'datetime' from original full script are not directly used in these functions.
# 'QApplication' from PyQt5 is not used here.

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
    try:
        with Image.open(image_path) as img:
            img.thumbnail(max_size)
            # Ensure image is in a mode that can be saved with quality if JPEG, or handle PNG
            if img.mode in ('RGBA', 'LA', 'P') and (img.format != 'JPEG' and img.format != 'WEBP'): # Convert to RGB for JPEG if has alpha
                if img.format != 'PNG': # PNG can handle alpha
                    img = img.convert('RGB')

            if img.format == 'WEBP' or img.mode == 'RGBA' or img.format == 'GIF': # Favor PNG for transparency/animation
                output_format = 'PNG'
                mime_type = 'image/png'
            else:
                output_format = img.format if img.format != 'JPEG' else 'JPEG'
                mime_type = f'image/{output_format.lower()}'
            
            img_bytes = io.BytesIO()
            save_params = {}
            if output_format == 'JPEG':
                save_params['quality'] = quality
                save_params['progressive'] = True 
                save_params['optimize'] = True    
            elif output_format == 'PNG':
                save_params['optimize'] = True
            elif output_format == 'WEBP': 
                 save_params['quality'] = quality


            if output_format == 'JPEG' and img.mode == 'RGBA': 
                img_to_save = img.convert('RGB')
                img_to_save.save(img_bytes, format=output_format, **save_params)
            else:
                img.save(img_bytes, format=output_format, **save_params)

            img_bytes.seek(0)
            base64_encoded = base64.b64encode(img_bytes.read()).decode('utf-8')
        return base64_encoded, mime_type, output_format
    except FileNotFoundError:
        raise 
    except Exception as e:
        raise RuntimeError(f"Error during image compression/encoding for {image_path}: {e}")


def get_unique_filename(filepath):
    """
    检查filepath是否存在，若存在则在文件名后追加序号，直到获取一个不重复的文件名
    """
    base, ext = os.path.splitext(filepath)
    counter = 1
    new_filepath = filepath
    while os.path.exists(new_filepath):
        new_filepath = f"{base}_{counter}{ext}" 
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

def process_image(image_path, config, output_text_signal_emit, stop_event, success_counter, failure_counter, num_counter, active_counter):
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
        image_quality_percent = int(config.get('Image_quality_percent', 85))
        quality_value = min(95, max(1, image_quality_percent))

        original_format = os.path.splitext(image_path)[1][1:].upper()
        if not original_format: original_format = "PNG" 

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

        response = requests.post(base_url, headers=headers, json=data, timeout=60) 
        response.raise_for_status()
        response_data = response.json()

        if 'choices' in response_data and len(response_data['choices']) > 0 and \
           isinstance(response_data['choices'][0].get('message'), dict) and \
           response_data['choices'][0]['message'].get('content'):
            result_text = response_data['choices'][0]['message']['content']
            result_text = sanitize_filename(result_text)
            new_name = f"{result_text}.{original_format.lower()}"
            
            output_mode = config.get('output_mode', 'finish_subfolder')
            
            if output_mode == 'custom':
                target_dir = config.get('custom_output_folder', '')
                if not target_dir:
                    output_text_signal_emit(f"错误：自定义输出文件夹未在配置中正确设置。跳过 {os.path.basename(image_path)}")
                    failure_counter.increment(); num_counter.increment(); active_counter.decrement(); return
            elif output_mode == 'in_place':
                target_dir = os.path.dirname(image_path)
            else: 
                target_dir = os.path.join(os.path.dirname(image_path), 'Finish')
            
            if not os.path.exists(target_dir):
                try:
                    os.makedirs(target_dir, exist_ok=True)
                except OSError as e:
                    output_text_signal_emit(f"创建文件夹失败 '{target_dir}': {e}. 跳过 {os.path.basename(image_path)}")
                    failure_counter.increment(); num_counter.increment(); active_counter.decrement(); return

            target_path = os.path.join(target_dir, new_name)
            target_path = get_unique_filename(target_path)
            
            operation_verb = ""
            if output_mode == 'in_place':
                shutil.move(image_path, target_path) 
                operation_verb = "在原位置重命名"
            else: 
                shutil.copy2(image_path, target_path)
                operation_verb = "复制并重命名到新位置"

            success_counter.increment()
            num_counter.increment() 
            output_text_signal_emit(f"第{num_counter.get_value()}张图片处理完成：{os.path.basename(image_path)} 已{operation_verb}为 {target_dir}")
        else:
            failure_counter.increment()
            num_counter.increment() 
            output_text_signal_emit(f"API响应无效或内容为空 ({os.path.basename(image_path)}): {response_data.get('error', response_data)}")

    except FileNotFoundError:
        failure_counter.increment(); num_counter.increment()
        output_text_signal_emit(f"错误：文件未找到 {os.path.basename(image_path)}")
    except requests.exceptions.RequestException as e:
        failure_counter.increment(); num_counter.increment()
        output_text_signal_emit(f"HTTP请求失败 ({os.path.basename(image_path)}): {e}")
    except RuntimeError as e: 
        failure_counter.increment(); num_counter.increment()
        output_text_signal_emit(f"图像处理内部错误 ({os.path.basename(image_path)}): {e}")
    except Exception as e:
        failure_counter.increment(); num_counter.increment()
        output_text_signal_emit(f"处理图片时发生未知错误 ({os.path.basename(image_path)}): {e}")
    finally:
        active_counter.decrement()


def process_images_concurrently(config, output_text_signal_emit, stop_event, active_counter, gui_num_counter):
    source_folder = config["Source_folder"]
    if not source_folder or not os.path.isdir(source_folder):
        output_text_signal_emit(f"错误：源文件夹 '{source_folder}' 无效或未设置。")
        return 0, 0, 0 

    suffix_name = ('.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.tif', '.webp', '.heif', '.heic', '.svg')
    image_paths = [os.path.join(source_folder, filename)
                   for filename in os.listdir(source_folder)
                   if filename.lower().endswith(suffix_name) and os.path.isfile(os.path.join(source_folder, filename))]
    
    if not image_paths:
        output_text_signal_emit("提示：在源文件夹中没有找到符合条件的图片文件。") # MODIFIED HERE
        return 0, 0, 0

    success_counter = Counter()
    failure_counter = Counter()
    
    output_text_signal_emit(f"开始处理{len(image_paths)}张图片，线程数: {config.get('Max_workers', 5)}")
    output_text_signal_emit(f"模型：{config['Model']}")
    output_text_signal_emit(f"图片质量设置：{config.get('Image_quality_percent', 85)}%")
    output_mode_display = {
        'finish_subfolder': "保存在 'Finish' 子文件夹",
        'in_place': "在原位置重命名",
        'custom': "保存到自定义文件夹"
    }
    output_text_signal_emit(f"输出模式：{output_mode_display.get(config.get('output_mode', 'finish_subfolder'), '未知')}")
    if config.get('output_mode') == 'custom':
        output_text_signal_emit(f"自定义输出文件夹：{config.get('custom_output_folder')}")

    with concurrent.futures.ThreadPoolExecutor(max_workers=config.get("Max_workers", 5)) as executor:
        futures = {executor.submit(process_image, image_path, config, output_text_signal_emit, stop_event, 
                                     success_counter, failure_counter, gui_num_counter, active_counter): image_path 
                   for image_path in image_paths}
        
        try:
            for future in concurrent.futures.as_completed(futures):
                if stop_event.is_set():
                    for f_cancel in futures:
                        if not f_cancel.done(): f_cancel.cancel()
                    output_text_signal_emit("停止信号已接收，正在取消剩余任务...")
                    break 
                try:
                    future.result() 
                except concurrent.futures.CancelledError:
                    output_text_signal_emit("一个任务被取消。")
                except Exception:
                    pass 
        except KeyboardInterrupt:
            output_text_signal_emit("检测到键盘中断！正在尝试停止...")
            stop_event.set()
            for f_cancel in futures:
                 if not f_cancel.done(): f_cancel.cancel()
            
            # if hasattr(executor, '_threads'): # This check might be problematic if _threads is not always present
            #     for thread in executor._threads:
            #         if thread.is_alive():
            #             pass 
            # Check for Python version for executor.shutdown options
            # Ensure sys is imported if this part is critical, though it's commented out in the original problem context
            # For now, assuming sys import is handled elsewhere or this specific version check isn't strictly needed for the fix
            # if sys.version_info >= (3, 9):
            #     executor.shutdown(wait=True, cancel_futures=True)
            # else:
            #     executor.shutdown(wait=True)
            executor.shutdown(wait=True) # Simplified shutdown
            output_text_signal_emit("所有活动线程已尝试停止。")

    return len(image_paths), success_counter.get_value(), failure_counter.get_value()
