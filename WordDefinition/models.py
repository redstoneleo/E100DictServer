from django.db import models


class WordDefinition(models.Model):
    word = models.CharField(max_length=30, unique=True)  # 可能会有句子;Django强制要有max_length;CharFields must define a 'm ax_length' attribute.
    lemma = models.CharField(max_length=30, blank=True, null=True)  # 数据库强制要求不能空；You are trying to add a non-nullable field 'lemma' to worddefinition without a d efault; we can't do that (the database needs something to populate existing rows ).
    usPhoneticSymbol = models.CharField(max_length=30, blank=True, null=True)  # 从数据库层面操作，可以为空应该设置null=True
    ukPhoneticSymbol = models.CharField(max_length=30, blank=True, null=True)
    chineseDefinition = models.TextField(blank=True, null=True)
    # rawInfo = models.TextField(blank=True, null=True)  # 必须要加才行

    def __str__(self):
        return '{}'.format(self.word)
