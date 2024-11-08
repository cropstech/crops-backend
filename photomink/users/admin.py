from django.contrib import admin

# Register your models here.
from photomink.users.models import CustomUser
from django.http import HttpResponse
from django.contrib.auth import get_user_model
import csv, datetime

User = get_user_model()

def export_to_csv(modeladmin, request, queryset):
    opts = modeladmin.model._meta
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment;' 'filename={}.csv'.format(opts)
    writer = csv.writer(response)
    fields = [field for field in opts.get_fields() if not field.many_to_many and not field.one_to_many]
    # Write a first row with header information
    writer.writerow([field.name for field in fields])
    # Write data rows
    for obj in queryset:
        data_row = []
        for field in fields:
            value = getattr(obj, field.name)
            if isinstance(value, datetime.datetime):
                value = value.strftime('%d/%m/%Y')
            data_row.append(value)
        writer.writerow(data_row)

    return response

export_to_csv.short_description = 'Export to CSV'  #short description


# class BrandInline(admin.TabularInline):
#     model = Brand
#     verbose_name = "Brands by user"
#     show_change_link = True
#     fields = ['name', 'created', 'last_updated']
#     readonly_fields = ['name', 'created', 'last_updated']
#     extra = 0
#     can_delete = False
    

class CustomUserAdmin(admin.ModelAdmin):
    list_display = ('first_name', 'last_name', 'email', 'date_joined', 'last_login', 'email_verified', 'is_staff', 'beta_access')
    list_display_links = ('first_name', 'last_name', 'email')
    search_fields = ['first_name', 'last_name', 'email']
    actions = [export_to_csv]
    inlines = [
        # BrandInline,
    ]
    

admin.site.register(CustomUser, CustomUserAdmin)
