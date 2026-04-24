import requests,uuid
import json,base64
requestsSession = requests.Session()


CLIENT_ID=str(uuid.getnode())

def getAccessToken_ProAPI():#任务 Access Token 有效期为一个月，开发者需要对 Access Token的有效性进行判断，如果Access Token过期可以重新获取。
    queryUrl = 'https://openapi.baidu.com/oauth/2.0/token'

    response = requestsSession.post(queryUrl, data={'grant_type': 'client_credentials', 
        'client_id': 'mfIsL4vkdA0OCyzXNdfKg9mO', 
        'client_secret': 'Gjpl1gxz3G2bvqDFGcrPoN7M5K6Zv4IH'
        })

    repliedJson = response.json()
    print(repliedJson)  #, '-------百度翻译官方API 有54003问题-------', repliedJson["trans_result"][0]["dst"] , repliedJson["trans_result"]["data"][0]["dst"]   54003表示请求频率超限，请降低您的请求频率。对于标准版服务，您的QPS（每秒请求量）=1，如需更大频率，请先进行身份认证，认证通过后可切换为高级版（适用于个人，QPS=10）或尊享版（适用于企业，QPS=100）
    return repliedJson["access_token"]



# access_token=getAccessToken()

def speechToText_ProAPI(file_bytes,rate=16000):
    file_content=file_bytes
    url = "https://vop.baidu.com/pro_api"
    
    payload = {
        "format": "pcm",
        "rate": rate,
        'channel': 1,
        "cuid":CLIENT_ID ,
        "token": getAccessToken(),
        "dev_pid":80001,
        'speech':base64.b64encode(file_content).decode('utf8'),
        'len':len(file_content)
    }
    headers = {
        'Content-Type': 'application/json'
    }
    
    response = requests.request("POST", url, headers=headers, json=payload)
    
    repliedJson = response.json()
    print(repliedJson)  #repliedJson, '-------百度翻译官方API 有54003问题-------', repliedJson["trans_result"][0]["dst"] , repliedJson["trans_result"]["data"][0]["dst"]   54003表示请求频率超限，请降低您的请求频率。对于标准版服务，您的QPS（每秒请求量）=1，如需更大频率，请先进行身份认证，认证通过后可切换为高级版（适用于个人，QPS=10）或尊享版（适用于企业，QPS=100）
    
    # text=repliedJson["result"][0][0:-1]#是为了去掉末尾的句号.strip()
    return repliedJson
    

def create_lst_task(speech_url, format='wav', pid=80001, rate=16000):
    """
    创建长语音异步转写任务
    https://ai.baidu.com/ai-doc/SPEECH/Klbxern8v
    """
    url = "https://aip.baidubce.com/rpc/2.0/aasr/v1/create"
    token = getAccessToken()
    
    params = {"access_token": token}
    payload = {
        "speech_url": speech_url,
        "format": format,
        "pid": pid,
        "rate": rate
    }
    
    response = requestsSession.post(url, params=params, json=payload)
    return response.json()

def query_lst_task(task_ids):
    """
    查询长语音异步转写结果
    task_ids: list of task_id strings
    """
    url = "https://aip.baidubce.com/rpc/2.0/aasr/v1/query"
    token = getAccessToken()
    
    params = {"access_token": token}
    payload = {
        "task_ids": task_ids
    }
    
    response = requestsSession.post(url, params=params, json=payload)
    return response.json()
    

def getAccessToken():#任务 Access Token 有效期为一个月，开发者需要对 Access Token的有效性进行判断，如果Access Token过期可以重新获取。
    queryUrl = 'http://aip.baidubce.com/oauth/2.0/token'

    response = requestsSession.post(queryUrl, data={'grant_type': 'client_credentials', 
        'client_id': 'mfIsL4vkdA0OCyzXNdfKg9mO', 
        'client_secret': 'Gjpl1gxz3G2bvqDFGcrPoN7M5K6Zv4IH'
        })

    repliedJson = response.json()
    # print(repliedJson)  #, '-------百度翻译官方API 有54003问题-------', repliedJson["trans_result"][0]["dst"] , repliedJson["trans_result"]["data"][0]["dst"]   54003表示请求频率超限，请降低您的请求频率。对于标准版服务，您的QPS（每秒请求量）=1，如需更大频率，请先进行身份认证，认证通过后可切换为高级版（适用于个人，QPS=10）或尊享版（适用于企业，QPS=100）
    return repliedJson["access_token"]


def speechToText(file_bytes,rate=16000):
    file_content=file_bytes
    url = "https://vop.baidu.com/server_api"
    
    payload = {
        "format": "pcm",
        "rate": rate,
        'channel': 1,
        "cuid":CLIENT_ID ,
        "token": getAccessToken(),
        "dev_pid":1537,
        'speech':base64.b64encode(file_content).decode('utf8'),
        'len':len(file_content)
    }
    headers = {
        'Content-Type': 'application/json'
    }
    
    response = requests.request("POST", url, headers=headers, json=payload)
    
    repliedJson = response.json()
    print(repliedJson)  #repliedJson, '-------百度翻译官方API 有54003问题-------', repliedJson["trans_result"][0]["dst"] , repliedJson["trans_result"]["data"][0]["dst"]   54003表示请求频率超限，请降低您的请求频率。对于标准版服务，您的QPS（每秒请求量）=1，如需更大频率，请先进行身份认证，认证通过后可切换为高级版（适用于个人，QPS=10）或尊享版（适用于企业，QPS=100）
    
    # text=repliedJson["result"][0][0:-1]#是为了去掉末尾的句号.strip()
    return repliedJson
    


if __name__ == '__main__':
    # file_content=open(r'C:\Users\22815\Downloads\tts.pcm', 'rb')#.read()
    file_content=open('白色的.pcm', 'rb').read()
    speechToText(file_content)
    # speechToText_ProAPI(file_content)
