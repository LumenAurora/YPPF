from django.db import migrations, models
from django.db.models import Count


def collapse_duplicate_openids(apps, schema_editor):
    pending_model = apps.get_model("generic", "PendingWechatBinding")
    duplicate_openids = (
        pending_model.objects.values("openid")
        .annotate(row_count=Count("id"))
        .filter(row_count__gt=1)
        .values_list("openid", flat=True)
    )
    for openid in list(duplicate_openids):
        bindings = list(
            pending_model.objects.filter(openid=openid).order_by(
                "-failed_attempts",
                "-expires_at",
                "nonce_digest",
            )
        )
        keeper = bindings[0]
        keeper.failed_attempts = max(
            binding.failed_attempts for binding in bindings
        )
        keeper.expires_at = max(binding.expires_at for binding in bindings)
        keeper.save(update_fields=["failed_attempts", "expires_at"])
        pending_model.objects.filter(openid=openid).exclude(pk=keeper.pk).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("generic", "0005_pendingwechatbinding"),
    ]

    operations = [
        migrations.RunPython(
            collapse_duplicate_openids,
            reverse_code=migrations.RunPython.noop,
        ),
        migrations.AlterField(
            model_name="pendingwechatbinding",
            name="openid",
            field=models.CharField(max_length=64, unique=True),
        ),
    ]
