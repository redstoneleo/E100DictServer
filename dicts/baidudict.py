import requests
import time
import re
import json
import hashlib
from datetime import datetime
# import urllib.parse
# from PyQt5.QtCore import *
# from PyQt5.QtGui import *
# from PyQt5.QtWidgets import *
# url = 'http://www.le.com/ptv/vplay/2098908.html?ch=baidu_ald'
from bs4 import BeautifulSoup
from PyQt5.QtCore import *
from PyQt5.QtGui import *
from PyQt5.QtWidgets import *
from PyQt5.QtQml import *
import time
import sys
# import execjs


def getAccessToken():
    # 第一组，这两组没有什么区别
    queryUrl = 'https://openapi.baidu.com/oauth/2.0/token'

    response = requestsSession.post(queryUrl, data={'grant_type': 'client_credentials', 
        'client_id': 'mfIsL4vkdA0OCyzXNdfKg9mO', 
        'client_secret': 'Gjpl1gxz3G2bvqDFGcrPoN7M5K6Zv4IH'
        })
    # 第二组
    # response = requestsSession.post('https://fanyi-api.baidu.com/api/trans/vip/translate',
    #                                 data={'q': queryText, 'from': 'en', 'to': 'zh', 'appid': 20230924001828481, 'salt': 0,
    #                                       'sign': hashlib.md5('20171230000110602{}0bQmQoHkqU56g54GV2cMA'.format(queryText).encode('utf8')).hexdigest()
    #                                       })

    repliedJson = response.json()
    print(repliedJson)  #, '-------百度翻译官方API 有54003问题-------', repliedJson["trans_result"][0]["dst"] , repliedJson["trans_result"]["data"][0]["dst"]   54003表示请求频率超限，请降低您的请求频率。对于标准版服务，您的QPS（每秒请求量）=1，如需更大频率，请先进行身份认证，认证通过后可切换为高级版（适用于个人，QPS=10）或尊享版（适用于企业，QPS=100）
    # return repliedJson["trans_result"][0]["dst"]


headers = {
    'Accept': '*/*',
    'Accept-Encoding': 'gzip, deflate, br',
    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
    'Connection': 'keep-alive',
    # 'Content-Length': '148',
    'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
    # 要改
    'Cookie': 'locale=zh; BAIDUID=EFFE8933C0010BE3E939FC0F4AD76530:FG=1; BDRCVFR[9lyhvNTRjAR]=mk3SLVN4HKm; BIDUPSID=EFFE8933C0010BE3E939FC0F4AD76530; PSTM=1560842111; delPer=0; REALTIME_TRANS_SWITCH=1; FANYI_WORD_SWITCH=1; HISTORY_SWITCH=1; SOUND_SPD_SWITCH=1; SOUND_PREFER_SWITCH=1; pgv_pvi=2273208320; pgv_si=s901625856; BDUSS=Y0Njlicy1tOVJvbXVFY0dPdFlLZ09FVmUtTFNBd2lIclpXU20tMlNLaH5jVEZkSVFBQUFBJCQAAAAAAAAAAAEAAAAv-TMgcmVkc3RvbmVfNAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAH~kCV1~5AldT0; cflag=13%3A3; BDRCVFR[x8BbixF69DD]=mk3SLVN4HKm; BDRCVFR[dG2JNJb_ajR]=mk3SLVN4HKm; ZD_ENTRY=empty; Hm_lvt_64ecd82404c51e03dc91cb9e8c025574=1560842130,1560908689,1561087669,1561262819; BDORZ=B490B5EBF6F3CD402E515D22BCDA1598; Hm_lpvt_64ecd82404c51e03dc91cb9e8c025574=1561470732; yjs_js_security_passport=87a701006e400d4f2048cc82782e52901f8c5c25_1561470776_js; to_lang_often=%5B%7B%22value%22%3A%22en%22%2C%22text%22%3A%22%u82F1%u8BED%22%7D%2C%7B%22value%22%3A%22zh%22%2C%22text%22%3A%22%u4E2D%u6587%22%7D%5D; from_lang_often=%5B%7B%22value%22%3A%22dan%22%2C%22text%22%3A%22%u4E39%u9EA6%u8BED%22%7D%2C%7B%22value%22%3A%22zh%22%2C%22text%22%3A%22%u4E2D%u6587%22%7D%2C%7B%22value%22%3A%22en%22%2C%22text%22%3A%22%u82F1%u8BED%22%7D%5D; PSINO=7; H_PS_PSSID=1460_21088_18559_29135_29238_28519_29098_29131_28833_29221_20719',
    'Host': 'fanyi.baidu.com',
    'Origin': 'https://fanyi.baidu.com',
    'Referer': 'https://fanyi.baidu.com/',
    # 要改
    'User-Agent': 'Mozilla/5.0 (Windows NT 6.1) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/74.0.3729.169 Safari/537.36',
    'X-Requested-With': 'XMLHttpRequest',
}


def baiduTranslateLite(queryText):
    # queryUrl = 'http://api.fanyi.baidu.com/api/trans/vip/translate'
    # appid = '20171230000110602'
    # q = queryText
    # salt = '0'#random.randint(32768, 65536)

    # response = requestsSession.post(queryUrl, data={'q': q, 'from': 'en', 'to': 'zh', 'appid': appid, 'salt': salt,
    #                                          'sign':hashlib.md5((appid + q + salt + 'bQmQoHkqU56g54GV2cMA').encode('utf8')).hexdigest()})

    response = requestsSession.post('https://fanyi.baidu.com/transapi',  # 这个API vest没有音标，似乎适合于只要意思
                                    data={'query': queryText, 'from': 'en', 'to': 'zh', 'source': 'txt'}, headers=headers)

    # print('response.text------', response.text,)
    repliedJson = response.json()
    try:
        resultJson = json.loads(repliedJson["result"])

    except KeyError:  # private correspondence的情况
        translation = repliedJson['data'][0]["dst"]
        return {'word': queryText,
                'chineseDefinition': translation}
    else:
        content = resultJson['content']
        # print(resultJson)
        # print(content[0].get('mean'))
        result = []
        for definition in content[0].get('mean'):
            partOfSpeech = definition.get('pre')
            if partOfSpeech:
                result.append('{} {}'.format(partOfSpeech, ';  '.join(definition['cont'].keys())))
            else:  # private correspondence  就没有词性
                result.append(';  '.join(definition['cont'].keys()))

        # print(result)
        phonicList = resultJson.get('voice')
        if phonicList:
            return {'word': queryText,
                    'ukPhoneticSymbol': phonicList[0].get('en_phonic').strip('[]'),
                    'usPhoneticSymbol': phonicList[1].get('us_phonic').strip('[]'),  # 'private correspondence'有网络释义,无音标，所以用get
                    'chineseDefinition': '\n'.join(result)}
        else:  # JS的情况
            return {'word': queryText,
                    'chineseDefinition': '\n'.join(result)}


js = """
function a(r, o) {
    for (var t = 0; t < o.length - 2; t += 3) {
        var a = o.charAt(t + 2);
        a = a >= "a" ? a.charCodeAt(0) - 87 : Number(a),
        a = "+" === o.charAt(t + 1) ? r >>> a: r << a,
        r = "+" === o.charAt(t) ? r + a & 4294967295 : r ^ a
    }
    return r
}
var C = null;
var token = function(r, _gtk) {
    var o = r.length;
    o > 30 && (r = "" + r.substr(0, 10) + r.substr(Math.floor(o / 2) - 5, 10) + r.substring(r.length, r.length - 10));
    var t = void 0,
    t = null !== C ? C: (C = _gtk || "") || "";
    for (var e = t.split("."), h = Number(e[0]) || 0, i = Number(e[1]) || 0, d = [], f = 0, g = 0; g < r.length; g++) {
        var m = r.charCodeAt(g);
        128 > m ? d[f++] = m: (2048 > m ? d[f++] = m >> 6 | 192 : (55296 === (64512 & m) && g + 1 < r.length && 56320 === (64512 & r.charCodeAt(g + 1)) ? (m = 65536 + ((1023 & m) << 10) + (1023 & r.charCodeAt(++g)), d[f++] = m >> 18 | 240, d[f++] = m >> 12 & 63 | 128) : d[f++] = m >> 12 | 224, d[f++] = m >> 6 & 63 | 128), d[f++] = 63 & m | 128)
    }
    for (var S = h,
    u = "+-a^+6",
    l = "+-3^+b+-f",
    s = 0; s < d.length; s++) S += d[s],
    S = a(S, u);

    return S = a(S, l),
    S ^= i,
    0 > S && (S = (2147483647 & S) + 2147483648),
    S %= 1e6,
    S.toString() + "." + (S ^ h)
}
"""
# with open(r'D:\BaiduYunDownload\编程\Python\baidudict.js')as f:
#     js = f.read()

# jsFunction = execjs.compile(js)

requestsSession = requests.Session()


def baiduOnlineDict(queryText):  # 百度翻译全抓接口;在词典里用起来太慢了
    sign = jsFunction.call('token', queryText, '320305.131321201')  # 要改 window.gtk
    # print(sign)
    data = {
        'from': 'en',  # 输入的语言
        'to': 'zh',  # 需要输出的语言
        'query': queryText,  # 需要翻译的词或句子
        'transtype': 'realtime',  # 常量
        'simple_means_flag': '3',  # 常量
        'sign': sign,  # 由query生成的一个数字
        'token': 'db6f6c014e7a665ee4430cdcd6bd95a7',  # 常量，和浏览器里的一样 要改 token: '
    }
    response = requestsSession.post('https://fanyi.baidu.com/v2transapi', data=data, headers=headers)  # headers也要和浏览器里的一样
    # print('response.text------', response.text)

    try:
        repliedJson = response.json()

        dictResult = repliedJson.get("dict_result")
        # print(not dictResult, dictResult)

        if not dictResult:  # 句子的时候字典没结果,teaching posts也没有结果,有的只是翻译结果，
            # print('baiduTranslate   翻译', queryText)  # , repliedJson["trans_result"]["data"][0]["dst"]
            return {'chineseDefinition': repliedJson["trans_result"]["data"][0]["dst"],
                    'word': repliedJson["trans_result"]["data"][0]["src"],
                    'extra': response.text,
                    'provider': '百度翻译'}

        simpleMeans = dictResult.get("simple_means")  # goody-two-shoes无simple_means，所以get
        if not simpleMeans:
            # print(repliedJson["dict_result"]["oxford"]["entry"][0]["data"])
            return {'chineseDefinition': repliedJson["dict_result"]["oxford"]["entry"][0]["data"][-1]["data"][-1]["chText"],  # 任务 redevelopments
                    'word': repliedJson["trans_result"]["data"][0]["src"],
                    'extra': response.text}
        result = []
        # print(simpleMeans["word_name"])  # response.history,
        # print(simpleMeans["symbols"][0]['parts'])
        for part in simpleMeans["symbols"][0]['parts']:  # 单词释义，可以包含空格'   good '
            # print(part)
            phoneticSymbol = part.get("part")  # queryText = 'private correspondence'的时候无'part'，有'part_name'
            if phoneticSymbol:
                result.append('{} {}'.format(phoneticSymbol, ';  '.join(part["means"])))  # ';  '里面的空格起到分割意项的作用，方便阅读,用的英文的分隔符;，因为比中文；显得更小，不占空间
            else:  # 如果不用if else分开，private correspondence的翻译结果因为前面的'{} {}'.format，所以会有一个空格
                result.append(';  '.join(part["means"]))  # part["means"]是一个list，这里的join可以将其转化为str
                # print(result)

        # print('baiduTranslate  字典\n', simpleMeans["word_name"], result, simpleMeans["symbols"][0]['ph_en'])
        return {'word': simpleMeans["word_name"],
                'usPhoneticSymbol': simpleMeans["symbols"][0].get('ph_am'),  # 'private correspondence'有网络释义,无音标，所以用get
                'ukPhoneticSymbol': simpleMeans["symbols"][0].get('ph_en'),
                'chineseDefinition': '\n'.join(result),
                'extra': response.text}
    except Exception as e:
        print(queryText, e)
        # raise e


if __name__ == "__main__":
    getAccessToken()

    # for i in [
    #     # "'em",
    #     # '-d',
    #     # 'He who pays the piper calls the tune',
    #     # 'impedance',
    #     # 'JS',
    #     # 'blackouts',
    #     # 'like a hot knife through butter',
    #     # 'saw',
    #     # 'seize',
    #     # 'fenced',
    #     # 'deploy',
    #     # 'innings',
    #     # 'goody-two-shoes',
    #     # 'nitrospan',
    #     # 'teaching posts',  # 只有翻译结果
    #     # 'private correspondence',  # 有网络释义
    #     # 'want',
    #     # 'ATM',
    #     # 'African-American',
    #     # 'If I had my druthers',
    #     'position', 'positioned', 'brexit','self-starter'
    # ]:
    #     # r = baiduOnlineDict(i)
    #     # r = baiduTranslateLite(i)
    #     r = baiduTranslate(i)
    #     print(r)
