from django.db import models


class BookInfo(models.Model):
    """图书信息模型类"""

    # 书名：CharField，限制长度，且唯一
    title = models.CharField(
        max_length=20,
        unique=True,
        verbose_name='书名',
    )

    # 价格：DecimalField 保证金额精度
    price = models.DecimalField(
        max_digits=7,
        decimal_places=2,
        verbose_name='价格',
    )

    # 出版日期：DateField 只存日期
    publish_date = models.DateField(
        verbose_name='出版日期',
    )

    class Meta:
        db_table = 'book_info'              # 自定义数据库表名
        verbose_name = '图书信息'            # 后台显示的单数名称
        verbose_name_plural = '图书信息'     # 后台显示的复数名称
        ordering = ['-publish_date']         # 默认按出版日期降序排序

    def __str__(self):
        return self.title