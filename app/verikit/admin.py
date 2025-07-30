from django.contrib import admin

from app.verikit.models import EmailVerification


@admin.register(EmailVerification)
class EmailCodeVerificationAdmin(admin.ModelAdmin[EmailVerification]):
    date_hierarchy = "create_time"
    list_display = ("__str__", "create_time", "expire_time")
    list_filter = ("create_time", "expire_time", "verify_time")
    ordering = ("-create_time",)
    readonly_fields = ("code_salt", "code_hash")
    search_fields = ("email",)
