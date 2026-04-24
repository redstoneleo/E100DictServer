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


# Initialize the database
db = SqliteDatabase('wordFrequency.db')

class LemmaRank(Model):
    rank = IntegerField(unique=True)
    lemma = CharField()

    def __str__(self):
        return f'{self.lemma} with rank {self.rank}'

    class Meta:
        database = db
        table_name = 'lemmaRank'

# Connect to the database and create the table
db.connect()
try:
    db.create_tables([LemmaRank])

except IntegrityError as exc:#如果表格存在就会出错，safe参数设置也不起作用，故如此
    print(exc.args)
    col = exc.args[0].split(': ')[-1]
    print(col)


def upsert_lemma(rank, lemma):
    lemma_entry=LemmaRank.create(rank=rank,lemma=lemma)

    # lemma_entry.lemma = lemma
    # lemma_entry.save()

# Example to add a record
for word,rank in word2rank.items():
    upsert_lemma(rank, word)


# Query the database
for item in LemmaRank.select():
    print(f'Rank: {item.rank}, Lemma: {item.lemma}')

db.close()