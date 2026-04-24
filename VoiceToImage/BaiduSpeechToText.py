import requests
import uuid
import json
import base64

requestsSession = requests.Session()

CLIENT_ID = str(uuid.getnode())


def getAccessToken_ProAPI():
    """Access Token for Baidu Pro API (valid for a month)."""
    queryUrl = 'https://openapi.baidu.com/oauth/2.0/token'

    response = requestsSession.post(queryUrl, data={
        'grant_type': 'client_credentials',
        'client_id': 'mfIsL4vkdA0OCyzXNdfKg9mO',
        'client_secret': 'Gjpl1gxz3G2bvqDFGcrPoN7M5K6Zv4IH'
    })

    repliedJson = response.json()
    print(repliedJson)
    return repliedJson.get("access_token")


def speechToText_ProAPI(file_bytes, rate=16000):
    file_content = file_bytes
    url = "https://vop.baidu.com/pro_api"

    payload = {
        "format": "pcm",
        "rate": rate,
        'channel': 1,
        "cuid": CLIENT_ID,
        "token": getAccessToken_ProAPI(),
        "dev_pid": 80001,
        'speech': base64.b64encode(file_content).decode('utf8'),
        'len': len(file_content)
    }
    headers = {
        'Content-Type': 'application/json'
    }

    response = requests.request("POST", url, headers=headers, json=payload)

    repliedJson = response.json()
    print(repliedJson)
    return repliedJson


def create_lst_task(speech_url, format='wav', pid=80001, rate=16000):
    """
    Create long speech asynchronous transcription task.
    https://ai.baidu.com/ai-doc/SPEECH/Klbxern8v
    """
    url = "https://aip.baidubce.com/rpc/2.0/aasr/v1/create"
    token = getAccessToken_ProAPI()

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
    Query long speech asynchronous transcription results.
    task_ids: list of task_id strings
    """
    url = "https://aip.baidubce.com/rpc/2.0/aasr/v1/query"
    token = getAccessToken_ProAPI()

    params = {"access_token": token}
    payload = {
        "task_ids": task_ids
    }

    response = requestsSession.post(url, params=params, json=payload)
    return response.json()


def getAccessToken():
    queryUrl = 'http://aip.baidubce.com/oauth/2.0/token'

    response = requestsSession.post(queryUrl, data={
        'grant_type': 'client_credentials',
        'client_id': 'mfIsL4vkdA0OCyzXNdfKg9mO',
        'client_secret': 'Gjpl1gxz3G2bvqDFGcrPoN7M5K6Zv4IH'
    })

    repliedJson = response.json()
    return repliedJson.get("access_token")


def speechToText(file_bytes, rate=16000):
    file_content = file_bytes
    url = "https://vop.baidu.com/server_api"

    payload = {
        "format": "pcm",
        "rate": rate,
        'channel': 1,
        "cuid": CLIENT_ID,
        "token": getAccessToken(),
        "dev_pid": 1537,
        'speech': base64.b64encode(file_content).decode('utf8'),
        'len': len(file_content)
    }
    headers = {
        'Content-Type': 'application/json'
    }

    response = requests.request("POST", url, headers=headers, json=payload)

    repliedJson = response.json()
    print(repliedJson)
    return repliedJson


if __name__ == '__main__':
    # Example usage: read a local PCM file and transcribe
    with open('白色的.pcm', 'rb') as f:
        file_content = f.read()
    print(speechToText(file_content))
