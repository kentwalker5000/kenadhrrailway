from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("pms", "0005_alter_period_period_name")]
    operations = [
        migrations.AddField(model_name="period", name="is_open", field=models.BooleanField(default=False, verbose_name="Open for reviews")),
        migrations.AddField(model_name="feedback", name="period", field=models.ForeignKey(null=True, blank=True, on_delete=django.db.models.deletion.PROTECT, related_name="reviews", to="pms.period", verbose_name="Review Period")),
        migrations.AddConstraint(model_name="feedback", constraint=models.UniqueConstraint(fields=("period", "employee_id"), name="unique_period_employee_review")),
    ]
