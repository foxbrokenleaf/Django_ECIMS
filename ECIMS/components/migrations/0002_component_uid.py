import uuid

from django.db import migrations, models


def fill_component_uid(apps, schema_editor):
    """为历史元件逐条生成唯一标识符，避免旧数据使用同一个默认值。"""
    Component = apps.get_model("components", "Component")
    for component in Component.objects.filter(uid__isnull=True).iterator():
        component.uid = uuid.uuid4()
        component.save(update_fields=["uid"])


class Migration(migrations.Migration):

    dependencies = [
        ("components", "0001_initial"),
    ]

    operations = [
        # 先加可空字段，再回填，最后收紧为唯一非空，兼容已有数据。
        migrations.AddField(
            model_name="component",
            name="uid",
            field=models.UUIDField(
                editable=False, null=True, verbose_name="唯一标识符ID"
            ),
        ),
        migrations.RunPython(fill_component_uid, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="component",
            name="uid",
            field=models.UUIDField(
                default=uuid.uuid4,
                editable=False,
                unique=True,
                verbose_name="唯一标识符ID",
            ),
        ),
    ]
