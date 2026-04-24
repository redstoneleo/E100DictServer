import os
from peewee import *
import openpyxl

word2rank={}
def extractCtrip(excelFilePath):
    thirdPartyWorkbook = openpyxl.load_workbook(excelFilePath)
    thirdPartyWorksheet = thirdPartyWorkbook['1 lemmas']

    for index, rowData in enumerate(thirdPartyWorksheet.iter_rows(min_row=2, values_only=True)):  # min_row (int) – smallest row index (1-based index);任务：记一下总数，方便后面搞进度条
        print(index, rowData)
        try:
            word2rank[rowData[1]]=rowData[0]
            
        except AttributeError as e:
            print('exception----------',index, e)

extractCtrip('wordFrequency.xlsx')

# print(word2rank)
import json


# Save to disk with encoding
with open('word2rank.json', 'w', encoding='utf-8') as f:
    json.dump(word2rank, f)

# Load from disk with encoding
with open('word2rank.json', 'r', encoding='utf-8') as f:
    loaded_list = json.load(f)

print(loaded_list)