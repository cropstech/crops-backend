from django.contrib import admin
from photomink.main.models import Workspace, WorkspaceMember

# Register your models here.

class WorkspaceAdmin(admin.ModelAdmin):
    list_display = ('name', 'created_at', 'updated_at')
    search_fields = ['name',]

class RoleAdmin(admin.ModelAdmin):
    list_display = ('name', 'workspace', 'is_custom')
    search_fields = ['name', 'workspace__name']
    
class WorkspaceMemberAdmin(admin.ModelAdmin):
    list_display = ('user', 'workspace', 'role', 'joined_at')
    search_fields = ['user__first_name', 'user__last_name', 'user__email', 'workspace__name']

admin.site.register(Workspace, WorkspaceAdmin)
admin.site.register(WorkspaceMember, WorkspaceMemberAdmin)

