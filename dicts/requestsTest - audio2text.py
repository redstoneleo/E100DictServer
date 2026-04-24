# -*- coding: utf-8 -*-

import requests,base64,json

import fastcrc

def calculate_crc16_genibus(file_path):
    with open(file_path, "rb") as file:
    	file_bytes=file.read()

    crc16_genibus_value =fastcrc.crc16.genibus(file_bytes)
    return crc16_genibus_value

# Provide the file path to calculate its crc16_genibus value
file_path = "tts.pcm"
crc16_genibus_value = calculate_crc16_genibus(file_path)

# print("crc16_genibus value:", crc16_genibus_value)

from requests import Request, Session
s = Session()
	
for i in range(3):
	r = requests.post('http://e100.feing.com.cn/dicts/audio2text/', 
	# r = requests.post('http://127.0.0.1:8000/dicts/audio2text/', 
	
	# r = requests.post('https://httpbin.org/post', 
	# 	data={#'chunk_index': '2',
	# 	'chunk_count':3,
	# 	'hash': crc16_genibus_value},
	# 	files = {'file': open(f'file_part{i+1}.pcm', 'rb')}#r'C:\Users\22815\Downloads\tts.pcm'
	# 	)

		json={#'chunk_index': '2',
		'chunk_count':3,
		'hash': crc16_genibus_value,
		'file': json.dumps(base64.b64encode(open(f'file_part{i+1}.pcm', 'rb').read()).decode('utf8'))
		# base64.b64encode(open(f'file_part{i+1}.pcm', 'rb').read())
		},
		)

	print(r.text)
