import openpyxl,json

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

if __name__ == '__main__':
	extractCtrip('wordFrequency.xlsx')
	word2rank={}
	print(word2rank.keys()&{'albus', 'white', 'albicans', 'off-white'})
	# extractMeituan('美团订单.xlsx')