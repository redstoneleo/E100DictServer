import requests
import re
from bs4 import BeautifulSoup

# icibaInnerHTMLRe = re.compile(r'<div class="in-base">(.+?)</li>', re.DOTALL)  # surrogate的翻译结果里会有\n，而后面的re.search默认不能跨行搜索，所以才DOTALL使得配置末尾结果
icibaInnerHTMLRe = re.compile(r"dict.innerHTML='(.+)';", re.DOTALL)  # surrogate的翻译结果里会有\n，而后面的re.search默认不能跨行搜索，所以才DOTALL使得配置末尾结果
# icibaPhoneticSymbol = re.compile(r'"EN-US[\\]">(.+?)</strong>')
# icibaSuggestRe = re.compile(r'">(.+?)</div>', re.DOTALL)  # 建议搜索的结果的匹配模式，positioned的情况
requestsSession = requests.Session()  # if you’re making several requests to the same host, the underlying TCP connection will be reused, which can result in a significant performance increase

phoneticSymbolRe = re.compile(r'\[(.+?)\]')


def youdaoSearch(queryText):  # http://www.iciba.com/teaching%20post  比较全，待测速度；positioned，huayi没有音标，但是iciba搜索有音标；
  # queryUrl = 'http://dict-co.iciba.com/api/dictionary.php?w={}&type=json&key=96731B04071B4A35D80AE892279B3D23'.format(queryText)#Hilbert无结果
  queryUrl = 'http://dict.youdao.com/search?q={}'.format(queryText)  # 任务：queryText放到配置文件，翻译innerHTML、空格（前面已经过滤掉了）无结果

  response = requestsSession.get(queryUrl)  # 任务 断网提示吧
  repliedText = response.text  # .replace('\\', '') 任务irritating 音标会出问题
  # print(repliedText)
  # print(repr(repliedText))  # response.history,

  #####用BeautifulSoup的解决方法#######
  result = {'dictKeyText':queryText}  # {'ukPhoneticSymbol': '', 'usPhoneticSymbol': ''}  # 如果不加这两项，对于没有音标的返回的是None，None不能写入数据库，所以value这里写 ''
  soup = BeautifulSoup(repliedText, "html.parser")  # 因为是从HTML里获取的HTML，这里.replace('\\', '')是转义
  symbolElement = soup.find(id='phrsListTab')  # soup.find(class_ = 'in-base')
  # print('youdaoSearch---------------', queryText, symbolElement.get_text("★", strip=True))
  if symbolElement:
    try:
      definitionElement=symbolElement.find(class_='trans-container')
      chineseDefinition=definitionElement.get_text("\n", strip=True).rsplit('[', maxsplit=1)[0]#split去除词形变换，如：[ 复数 goods 比较级 better 最高级 best ]
      # print('chineseDefinition---------------',chineseDefinition)
      result.update({'chineseDefinition':chineseDefinition})
    except (AttributeError) as e:
      print('chineseDefinition-------IndexError--------',queryText,e)

    else:
    # try:

      phoneticElement=symbolElement.find(class_='baav')

      phoneticText=phoneticElement.get_text("★",strip=True).replace('[','').replace(']','')#replace去除音标外围的[]
      # print('phoneticText---------------',phoneticText)
    
      phoneticList=phoneticText.split('★')[1::2]
      if phoneticList:#B movie就没有音标
        if len(phoneticList)==2:
          ukPhoneticSymbol,usPhoneticSymbol=phoneticList
        else:
          ukPhoneticSymbol=usPhoneticSymbol=phoneticList[0]

        result.update({'ukPhoneticSymbol':ukPhoneticSymbol, 'usPhoneticSymbol': ukPhoneticSymbol})
    # except (IndexError,AttributeError) as e:
    #   print('phoneticText-------IndexError--------',queryText,e)



  return result


if __name__ == "__main__":
  for i in [
      'Aprils',
      'B movie',
      'blotted',
      'blobs',
      'pileup',
      'Britain',
      'good',
      'United States',

      'trichion',
      'want',
      'position',
      'positioned',
      'brexit'

  ]:  #
    # print(icibaTranslate(i),)
    print(youdaoSearch(i))
  # baiduText2audio('v. 放置；确定…的位置（position的过去分词）')
