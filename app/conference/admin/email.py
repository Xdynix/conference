from django.contrib import admin

from app.conference.models import EmailSendLog


@admin.register(EmailSendLog)
class EmailSendLogAdmin(admin.ModelAdmin[EmailSendLog]):
    list_display = ("correlation_id", "conference", "sender", "send_time")
    list_filter = ("conference",)
    list_select_related = ("conference", "sender")
    autocomplete_fields = ("conference", "sender")
    readonly_fields = ("uid", "create_time", "update_time")
    search_fields = ("correlation_id",)
