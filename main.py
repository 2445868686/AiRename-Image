from openai import OpenAI
from PIL import Image
import json
import io
import re
import base64
import requests
import shutil
import os

# Function to encode the image
def encode_image(image_path):
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode('utf-8')
     
def remove_punctuation_at_end(sentence):
    # 使用正则表达式匹配句子末尾的标点符号并删除
    return re.sub(r'[。？！，、；：“”‘’《》（）【】『』「」\[\]\.,;:"\'?!(){}<>]+$', '', sentence)

def compress_and_encode_image(image_path, output_format='JPEG', quality=85, max_size=(1080, 1080)):
    """
    压缩并编码图片为Base64字符串。
    参数：
    - image_path: 原始图片路径。
    - output_format: 输出图片格式，默认为'JPEG'。
    - quality: 输出图片质量，范围为1（最差）到95（最佳），默认为85。
    - max_size: 输出图片最大尺寸，以元组(width, height)表示，默认为(1080, 1080)。
    """
    # 打开并调整图片大小
    with Image.open(image_path) as img:
        # 按比例缩小图片，保持长宽比
        img.thumbnail(max_size)
        
        # 将图片保存到字节流中，而不是文件中
        img_bytes = io.BytesIO()
        img.save(img_bytes, format=output_format, quality=quality)
        
        # 将字节流编码为Base64字符串
        img_bytes.seek(0)  # 移动到流的开始处
        base64_encoded = base64.b64encode(img_bytes.read()).decode('utf-8')
        
    return base64_encoded

# 加载配置文件
with open('config.json', 'r') as config_file:
    config = json.load(config_file)

# 从配置文件中获取参数
api_key = config['Api_key']
base_url = config['Base_url']
source_folder = config['Source_folder']
destination_folder = os.path.join(source_folder, 'Finish')
Proxy_quality =config['Proxy_quality']
gpt_model = config['Model']
Prompt = config['Prompt']

# 如果目标文件夹不存在，则创建它
if not os.path.exists(destination_folder):
    os.makedirs(destination_folder)

suffix_name = ('.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.tif', '.webp', '.heif', '.heic',  '.svg')
start_number = 0
quality_value = min(95, max(1, int(Proxy_quality * 10)))
#processed_count = 0
# 遍历原始文件夹中的所有文件

for filename in os.listdir(source_folder):
    # 检查文件是否是图片
    if filename.lower().endswith(suffix_name):
        image_path = os.path.join(source_folder, filename)
        base64_image = compress_and_encode_image(image_path, output_format='JPEG', quality=quality_value, max_size=(512, 512))
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
                                "url": f"data:image/jpeg;base64,{base64_image}"
                            }
                        }
                    ]
                }
            ],
            "max_tokens": 300
        }

        response = requests.post(base_url, headers=headers, json=payload)
        try:
            if response.status_code == 200:
                response_data = response.json()
                if 'choices' in response_data and len(response_data['choices']) > 0 and 'message' in response_data['choices'][0] and 'content' in response_data['choices'][0]['message']:
                    new_name = response_data['choices'][0]['message']['content']
                    new_filename = f'{remove_punctuation_at_end(new_name)}.jpg'
                    new_file = os.path.join(destination_folder, new_filename)
                    shutil.copy(image_path, new_file)
#                    processed_count += 1
                    print(f'第{start_number}张图片重命名完成：{new_name}')
                    continue
            # 如果响应状态码不是200或缺少必要的数据，则打印错误并跳过此图片
            print(f"无法处理第{start_number}张图片")
        except Exception as e:
            print(f"处理图片时发生错误：{e}，跳过第{start_number}张图片。")


print('图片重命名完成')


