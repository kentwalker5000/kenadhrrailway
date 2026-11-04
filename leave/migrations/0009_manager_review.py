from django.db import migrations, models
import django.db.models.deletion


def grant_hr_permission(apps, schema_editor):
    ContentType = apps.get_model("contenttypes", "ContentType")
    Permission = apps.get_model("auth", "Permission")
    Group = apps.get_model("auth", "Group")
    content_type, _ = ContentType.objects.get_or_create(app_label="leave", model="leaverequest")
    permission, _ = Permission.objects.get_or_create(content_type=content_type, codename="final_approve_leaverequest", defaults={"name": "Can give final HR approval after manager review"})
    for group in Group.objects.filter(name__in=["Admin", "HR Manager"]):
        group.permissions.add(permission)


class Migration(migrations.Migration):
    dependencies = [("leave", "0008_leaverequest_leaverequest_dates_idx_and_more")]
    operations = [
        migrations.AlterModelOptions(name="leaverequest", options={"ordering": ["-id"], "verbose_name": "Leave Request", "verbose_name_plural": "Leave Requests", "permissions": (("can_view_on_leave", "Can View On Leave"), ("final_approve_leaverequest", "Can give final HR approval after manager review"))}),
        migrations.CreateModel(name="LeaveManagerReview", fields=[
            ("id", models.AutoField(primary_key=True, serialize=False)),
            ("reviewed_at", models.DateTimeField(auto_now=True)),
            ("request_signature", models.CharField(max_length=64)),
            ("leave_request", models.OneToOneField(to="leave.leaverequest", related_name="manager_review", on_delete=django.db.models.deletion.CASCADE)),
            ("reviewed_by", models.ForeignKey(to="employee.employee", on_delete=django.db.models.deletion.PROTECT)),
        ]),
        migrations.RunPython(grant_hr_permission, migrations.RunPython.noop),
    ]
