import requests,re,json,base64,sys,os

from io import BytesIO
from pydub import AudioSegment
import openpyxl
from django.http import HttpResponse,JsonResponse
from django.core.exceptions import ObjectDoesNotExist
from django.views.decorators.csrf import csrf_exempt


from WordDefinition.models import *
from .BaiduSpeechToText  import speechToText
from .youdaoDict  import youdaoZhToEn,youdaoEnDict
import fastcrc

word2rank={}
def extractCtrip(excelFilePath):
    thirdPartyWorkbook = openpyxl.load_workbook(excelFilePath)
    thirdPartyWorksheet = thirdPartyWorkbook['1 lemmas']

    for index, rowData in enumerate(thirdPartyWorksheet.iter_rows(min_row=2, values_only=True)):  # min_row (int) – smallest row index (1-based index);任务：记一下总数，方便后面搞进度条
        # print(index, rowData)
        try:
            word2rank[rowData[1]]=rowData[0]
            
        except AttributeError as e:
            print('exception----------',index, e)

# extractCtrip('./dicts/wordFrequency.xlsx')

with open('./dicts/word2rank.json', 'r', encoding='utf-8') as f:
    word2rank = json.load(f)

# print('word2rank--------------',word2rank)
requestsSession = requests.Session()

def ecdict(queryData):
    result = {}
    isSearchingWord = isinstance(queryData, str)
    if isSearchingWord:
        queryTextList = [queryData]
    else:  # 换词形查的情况
        queryTextList = queryData

    for word in queryTextList:
        try:
            # print('ecdict-----------',word)
            wordDefinition = WordDefinition.objects.using("ecdict").get(word=word)  # API这个单词转成小写就是另外一个意思了，所以不能轻易转小写;不用传小写了，因为candidateWordList里已经有小写了
        except ObjectDoesNotExist:  # If there are no results that match the query, get() will raise a DoesNotExist exception.
            print('ObjectDoesNotExist------------',word)
            # if isSearchingWord:
            #     return ecdict(getCandidateWordList(queryData))
        else:
            # print('ecdict-----------',word)
            if wordDefinition.chineseDefinition:  # OCR的时候ecdict没有结果，在这个条件判断下返回上面的{}，在conciseTranslate里bool后False，进而调用百度翻译
                result.update({
                    'dictKeyText': wordDefinition.word,
                    'chineseDefinition': wordDefinition.chineseDefinition,
                    'usPhoneticSymbol': wordDefinition.usPhoneticSymbol,
                    'ukPhoneticSymbol': wordDefinition.ukPhoneticSymbol
                })
                break
    return result  # 可以直接退出循环；有无结果均可返回值

def baiduTranslate(queryText):  # http://api.fanyi.baidu.com/api/trans/product/apidoc
    response = requestsSession.get(f'https://sp1.baidu.com/5b11fzupBgM18t7jm9iCKT-xh_/sensearch/selecttext?cb=jQuery1102014484401255543133_1618371963436&q={queryText}&_=1618371963437',
                                   # headers={'User-Agent': 'Mozilla/5.0 (Windows NT 6.1; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/86.0.4240.198 Safari/537.36',
                                   # 'Referer': f'https://www.baidu.com/s?tn=88093251_69_hao_pg&ie=utf-8&wd={queryText}',
                                   # 'Host': 'sp1.baidu.com'}
                                   )
    jsonText = re.search(r'.+?\((\{.+\})\)', response.text).group(1)  # requests.get(resourceUrl, headers={'User-Agent': userAgent, 'Referer': sourceUrl}).json()
    repliedJson = json.loads(jsonText)
    # print('baiduTranslate  翻译', queryText, '---',repliedJson)  #repliedJson["trans_result"][0]["dst"]
    try:
        return repliedJson["data"]["result"]
    except KeyError as e:
        return {}

hash2byteChunkList={}

if sys.platform.startswith('win'):
    os.putenv("PATH", r'F:\BaiduNetdiskDownload\SoftwareProject\EngkuDict\ffmpeg-shared')

def getPCMaudioBytesIO(url):
    response = requestsSession.get(url)

    # Load the audio file into memory
    audio_file = BytesIO(response.content)

    # Convert the audio file to WAV format
    audio = AudioSegment.from_file(audio_file, format="mp3")
    
    # pcm_audioBytesIO = BytesIO()
    # audio.export(pcm_audioBytesIO, format="wav", parameters=["-ar", "16000"])


        # 将音频转换为单声道
    audio = audio.set_channels(1)

    # 调整音频采样率为16kHz
    audio = audio.set_frame_rate(16000)

    # 将音频文件导出为 WAV 格式
    pcm_audioBytesIO = BytesIO()
    audio.export(pcm_audioBytesIO, format="wav")

    # 如果你需要获取音频数据，可以这样做
    pcm_audioBytesIO.seek(0)

    return pcm_audioBytesIO

@csrf_exempt#任务 了解用法
def audio2enText(request):
    myKey = None  # Initialize myKey to avoid NameError in except block
    try:
        received_json=json.loads(request.body)
        hash_received = received_json['hash']
        file = received_json['file']
        chunk_count = received_json['chunk_count']
        rate = received_json['rate']

        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0]
        else:
            ip = request.META.get('REMOTE_ADDR')

        # hash_received = int(request.POST['hash'])
        # file = request.POST['file']
        # chunk_count = int(request.POST['chunk_count'])

        myKey=f'{ip}{hash_received}'

        byteChunkList=hash2byteChunkList.setdefault(myKey,[])#如果没有就创建一个key：value
        byteChunkList.append(base64.b64decode(file))
        # print('比较------------',len(byteChunkList))#[0].read()

        if len(byteChunkList)==chunk_count:
            del hash2byteChunkList[myKey]
            # hash2byteChunkList.pop(myKey)

            file_bytes=b''.join(byteChunkList)
            crc16_genibus_value=fastcrc.crc16.genibus(file_bytes)
            if crc16_genibus_value==hash_received:
                repliedJson=speechToText(file_bytes,rate)
                if repliedJson["err_msg"]=='success.':
                    audio_text=repliedJson["result"][0][0:-1]#是为了去掉末尾的句号.strip()
                    print("audio_text-----------", audio_text)
                    if len(audio_text)>4:
                        resultDict={'errorCode':10003,'errorMsg':"The voice is too long, please keep it to four words or less."}
                    else:
                        # en_audio_text=baiduTranslate(audio_text).lower()
                        
                        # resultDict=ecdict(en_audio_text)
                        # if not resultDict:
                            
                        resultDict=youdaoZhToEn(audio_text)
                        # Filter wordList to only include words that exist in word2rank
                        filtered_words = list(set(resultDict['wordList']) & word2rank.keys())
                        if filtered_words:
                            resultDict['wordList'] = filtered_words
                        # Remove 'the ' prefix from words
                        resultDict['wordList']=list(map(lambda word:word.replace('the ',''),resultDict['wordList']))
    
                        # print(set(resultDict['wordList']),word2rank,resultDict['wordList'])
                        # resultDict['dictKeyText']=en_audio_text
                else:#百度系统方面的错误
                    resultDict={'errorCode':10005,'errorMsg':repliedJson["err_msg"]}
            else:
                resultDict={'errorCode':10002,'errorMsg':"File validation failed"}
        else:
            resultDict={'errorCode':10001,'errorMsg':"Please continue to upload files"}
    except Exception as e:
        # Only clean up if myKey was successfully created
        if myKey and myKey in hash2byteChunkList:
            del hash2byteChunkList[myKey]#出错的话就清除这个上传吧，以免让后续无法上传，总是出现"Please continue to upload files"
        resultDict={'errorCode':10004,'errorMsg':f'API exception:{str(e)}'}
    finally:
        return JsonResponse(resultDict)


@csrf_exempt#任务 了解用法
def enDict(request):
    received_json=json.loads(request.body)
    word = received_json['word']
    resultDict=youdaoEnDict(word)
    resultDict['speech']=base64.b64encode(getPCMaudioBytesIO("http://dict.youdao.com/dictvoice?audio={}&type=2".format(word)).read()).decode('utf8')
    return JsonResponse(resultDict)



@csrf_exempt#任务 了解用法
def audio2text(request):
    try:
        received_json=json.loads(request.body)
        hash_received = received_json['hash']
        file = received_json['file']
        chunk_count = received_json['chunk_count']

        # hash_received = int(request.POST['hash'])
        # file = request.POST['file']
        # chunk_count = int(request.POST['chunk_count'])

        
        byteChunkList=hash2byteChunkList.setdefault(hash_received,[])#如果没有就创建一个key：value
        byteChunkList.append(base64.b64decode(file))
        # print('audio_text------------',len(byteChunkList))#[0].read()

        if len(byteChunkList)==chunk_count:
            del hash2byteChunkList[hash_received]
            # hash2byteChunkList.pop(hash_received)

            file_bytes=b''.join(byteChunkList)
            crc16_genibus_value=fastcrc.crc16.genibus(file_bytes)
            if crc16_genibus_value==hash_received:
                repliedJson=speechToText(file_bytes)
                if repliedJson["err_msg"]=='success.':
                    audio_text=repliedJson["result"][0].split("打印",maxsplit=1)[-1][0:-1]#是为了去掉末尾的句号.strip()
                    print("audio_text-----------", audio_text)
                    resultDict={'audio_text':audio_text}
                    
                else:#百度系统方面的错误
                    resultDict={'errorMsg':repliedJson["err_msg"]}
            else:
                resultDict={'errorMsg':"File validation failed"}
        else:
            resultDict={'errorMsg':"Please continue to upload files"}
    except Exception as e:
        resultDict={'errorMsg':f'API exception:{str(e)}'}
    finally:
        return JsonResponse(resultDict)