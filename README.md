# AiRename-Image
## Example
<img src=https://github.com/2445868686/AiRename-Image/assets/50979290/2b4ab9ed-a93f-4839-8bc3-3f3240879813 width=40% />
<img src=https://github.com/2445868686/AiRename-Image/assets/50979290/d38d04b4-79d5-4972-ae38-326307d08f7e width=40% />

Import Eagle, which can automatically recognize labels

![Eagle](https://github.com/2445868686/AiRename-Image/assets/50979290/168df7fd-8c49-4666-acf4-b5255dfd63cb)

## Start
### Clone the repository
```
git clone https://github.com/2445868686/AiRename-Image.git
```
```
cd AiRename-Image
```
```
pip install -r requirements.txt
```
### Configure the AiRename
Open config.json and edit the url and selector properties to match your needs.
```python
{
    "Api_key": "sk-xxxxxxxxxxxxxxxxxxxxxx",
    "Base_url":"https://api.openai.com/v1/chat/completions",
    "Source_folder": "/Users/mac-mini-03/Desktop/test",
    "Proxy_quality":0.8,  #Automatic pre compression ratio for images that are too large
    "Model": "gpt-4-vision-preview",
    "Option": ture, #If it is 'true' , rename the source file; If it is 'false' , the new file will be stored in a subdirectory named 'Finish' in the current directory.
    "Prompt": "Summarize the content of the image in one sentence,no more than 10 words"
  }
```
### Run
```
python main.py
```
