# -*- coding: utf-8 -*-

import requests,base64
import subprocess
import fastcrc

def calculate_crc16_genibus(file_path):
    with open(file_path, "rb") as file:
    	file_bytes=file.read()

    crc16_genibus_value =fastcrc.crc16.genibus(file_bytes)
    return crc16_genibus_value


# print("crc16_genibus value:", crc16_genibus_value)

from requests import Request, Session
requestSession = Session()
server_url='http://e600.feing.com.cn'
# server_url='http://localhost:8000'
# server_url='http://47.107.238.252:8000'
while True:
	file_path =input("请输入pcm语音路径：")
	# file_path =r'F:\BaiduNetdiskDownload\ConsumerSoftwareProject\E100DictServer\dicts\白色的.pcm'
	# subprocess.run("cls", shell=True, check=True)
	if not file_path:
		break


	r = requests.post(f'{server_url}/dicts/audio2enText/', 
	# r = requests.post(f'{server_url}/dicts/audio2enText/', 

	# r = requests.post('https://httpbin.org/post', 
	# 	data={#'chunk_index': '2',
	# 	'chunk_count':3,
	# 	'hash': crc16_genibus_value},
	# 	files = {'file': open(f'file_part{i+1}.pcm', 'rb')}#r'C:\Users\22815\Downloads\tts.pcm'
	# 	)

	json={#'chunk_index': '2',
	'chunk_count':1,
	'hash': calculate_crc16_genibus(file_path),
	'file': base64.b64encode(open(file_path,  'rb').read()).decode('utf8'),#[44:]
	'rate':16000
	},
	)


	print(r.text)
	repliedJson=r.json()
	# print(repliedJson)
	print(f'识别出来的语音中文是：{repliedJson["dictKeyText"]}')
	print('对应的英文单词有：')
	wordList=repliedJson['wordList']
	if len(wordList)>1:
		for index, word in enumerate(wordList):
			print(f'{index}. {word}')

		wordIndex =int(input("请输入要查看的单词意思的序号："))
	elif len(wordList)==1:
		wordIndex =0
	else:
		print('没有任何结果，请把情况报告给开发者')
		continue

	word=wordList[wordIndex]
	

	r = requests.post(f'{server_url}/dicts/enDict/', 
	# r = requests.post(f'{server_url}/dicts/enDict/', 
	# 	data={#'chunk_index': '2',
	# 	'chunk_count':3,
	# 	'hash': crc16_genibus_value},
	# 	files = {'file': open(f'file_part{i+1}.pcm', 'rb')}#r'C:\Users\22815\Downloads\tts.pcm'
	# 	)

	json={#'chunk_index': '2',
	'word':word,
	},
	)


	repliedJson=r.json()

	if 'speech' in repliedJson:
		decoded_text = base64.b64decode(repliedJson['speech'])
		with open('speech.wav', 'wb') as f:
		    f.write(decoded_text)

		repliedJson['speech']=f'{repliedJson['speech'][0:100]}......'
		print(repliedJson)
	else:
		print(repliedJson)
