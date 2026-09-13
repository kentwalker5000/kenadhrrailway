from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("whatsapp", "0002_whatsappcredientials_meta_app_secret")]
    operations = [
        migrations.AlterField(
            model_name="whatsappcredientials",
            name="meta_app_secret",
            field=models.CharField(
                max_length=255, blank=True, default="", verbose_name="App Secret",
                help_text=(
                    "Meta app secret, used to verify the X-Hub-Signature-256 header on "
                    "incoming webhook calls. Without it KenadHr cannot tell a real "
                    "delivery from a forged one, so unsigned payloads are rejected. "
                    "Find it under App Settings > Basic in the Meta developer console."
                ),
            ),
        ),
    ]
