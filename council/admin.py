from django.contrib import admin

from council.models import CouncilDocument, CouncilLibraryFolder, CouncilMember


@admin.register(CouncilMember)
class CouncilMemberAdmin(admin.ModelAdmin):
    list_display = ("full_name", "role", "email", "term_start", "term_end", "company_id", "is_active")
    list_filter = ("role", "is_active", "company_id")
    search_fields = ("full_name", "email", "organisation")


@admin.register(CouncilLibraryFolder)
class CouncilLibraryFolderAdmin(admin.ModelAdmin):
    list_display = ("name", "access_level", "company_id", "is_active")
    list_filter = ("access_level", "is_active", "company_id")
    search_fields = ("name", "description")
    filter_horizontal = ("allowed_users", "allowed_groups")


@admin.register(CouncilDocument)
class CouncilDocumentAdmin(admin.ModelAdmin):
    list_display = ("title", "member", "folder", "expires_on", "company_id", "created_at")
    list_filter = ("company_id", "expires_on")
    search_fields = ("title", "description", "member__full_name", "folder__name")
