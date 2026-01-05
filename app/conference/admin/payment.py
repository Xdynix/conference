from django.contrib import admin
from django.utils.translation import gettext_lazy as _

from app.conference.models import Payment, PaymentItem


class PaymentItemInline(admin.TabularInline[PaymentItem, Payment]):
    model = PaymentItem
    extra = 0
    autocomplete_fields = ("registration",)


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin[Payment]):
    date_hierarchy = "create_time"
    fieldsets = (
        (
            None,
            {
                "fields": (
                    "uid",
                    "conference",
                    "delete_time",
                    "type",
                    "method",
                )
            },
        ),
        (
            _("Amount"),
            {"fields": (("amount", "currency"),)},
        ),
        (
            _("Details"),
            {
                "fields": (
                    "reference",
                    "note",
                )
            },
        ),
        (
            _("Timestamps"),
            {
                "fields": (
                    "create_time",
                    "update_time",
                )
            },
        ),
    )
    inlines = (PaymentItemInline,)
    list_display = (
        "__str__",
        "method",
        "reference",
    )
    list_filter = ("type", "method", "currency", "conference")
    list_select_related = ("conference",)
    autocomplete_fields = ("conference",)
    readonly_fields = (
        "uid",
        "create_time",
        "update_time",
    )
    search_fields = (
        "reference",
        "note",
        "conference__name",
        "item__registration__reference_code",
    )
