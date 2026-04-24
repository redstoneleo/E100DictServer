# -*- coding: utf-8 -*-

from re import split
import requests,base64,json

import fastcrc,split_file

def calculate_crc16_genibus(file_path):
    with open(file_path, "rb") as file:
    	file_bytes=file.read()

    crc16_genibus_value =fastcrc.crc16.genibus(file_bytes)
    return crc16_genibus_value


# print("crc16_genibus value:", crc16_genibus_value)

from requests import Request, Session
# server_url='http://e100.feing.com.cn'
# server_url='http://127.0.0.1:8000'

s = Session()
file_path = "天.pcm"
split_file.split_file(file_path)
for i in range(3):

	r = requests.post(f'{server_url}/dicts/audio2enText/', 
	# r = requests.post(f'{server_url}/dicts/audio2text/', 

	# r = requests.post('https://httpbin.org/post', 
	# 	data={#'chunk_index': '2',
	# 	'chunk_count':3,
	# 	'hash': crc16_genibus_value},
	# 	files = {'file': open(f'file_part{i+1}.pcm', 'rb')}#r'C:\Users\22815\Downloads\tts.pcm'
	# 	)

	json={#'chunk_index': '2',
	'chunk_count':3,
	'hash': calculate_crc16_genibus(file_path),
	'file': base64.b64encode(open(f'file_part{i+1}.pcm',  'rb').read()).decode('utf8'),#[44:]
	'rate':16000
	},
	)

	print(r.text)
	repliedJson=r.json()
	


# file_path = "太阳.pcm"
# # r = requests.post('http://e100.feing.com.cn/dicts/audio2enText/', 
# r = requests.post('http://127.0.0.1:8000/dicts/audio2enText/', 

# # r = requests.post('https://httpbin.org/post', 
# # 	data={#'chunk_index': '2',
# # 	'chunk_count':3,
# # 	'hash': crc16_genibus_value},
# # 	files = {'file': open(f'file_part{i+1}.pcm', 'rb')}#r'C:\Users\22815\Downloads\tts.pcm'
# # 	)

# 	json={#'chunk_index': '2',
# 	'chunk_count':1,
# 	'hash': calculate_crc16_genibus(file_path),
# 	'file': base64.b64encode(open(file_path, 'rb').read()).decode('utf8'),#[44:]
# 	'rate':16000
# 	},
# 	)

# print(r.text)



r = requests.post(f'{server_url}/dicts/enDict/', 
# r = requests.post(f'{server_url}/dicts/enDict/', 
# 	data={#'chunk_index': '2',
# 	'chunk_count':3,
# 	'hash': crc16_genibus_value},
# 	files = {'file': open(f'file_part{i+1}.pcm', 'rb')}#r'C:\Users\22815\Downloads\tts.pcm'
# 	)

json={#'chunk_index': '2',
'word':'schoolbag',
},
)

print(r.text)
repliedJson=r.json()

if 'speech' in repliedJson:
	decoded_text = base64.b64decode(repliedJson['speech'])
	with open('speech.wav', 'wb') as f:
	    f.write(decoded_text)

	repliedJson['speech']=f'{repliedJson['speech'][0:100]}......'
	print(repliedJson)
else:
	print(repliedJson)