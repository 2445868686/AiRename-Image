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
### Configure the AiRename
Open config.json and edit the url and selector properties to match your needs.
```
{
    "Api_key": "sk-xxxxxxxxxxxxxxxxxxxxxx",
    "Base_url":"https://api.openai.com",
    "Source_folder": "/Users/mac-mini-03/Desktop/test",
    "Destination_folder": "/Users/mac-mini-03/Desktop/finish",
    "Model": "gpt-4-vision-preview",
    "Prompt": "Summarize the content of the image in one sentence, no more than 10 words"
  }
```
### Run
```
cd AiRename-Image
python main.py
```
