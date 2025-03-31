from django.contrib import admin
from main.models import Workspace, WorkspaceMember, Asset, AssetAnalysis

# Register your models here.

class WorkspaceMemberInline(admin.TabularInline):
    model = WorkspaceMember
    extra = 1
    
class WorkspaceAdmin(admin.ModelAdmin):
    list_display = ('name', 'id', 'created_at', 'updated_at')
    search_fields = ['name', 'id']
    inlines = [WorkspaceMemberInline]

class RoleAdmin(admin.ModelAdmin):
    list_display = ('name', 'workspace', 'is_custom')
    search_fields = ['name', 'workspace__name']
    
class WorkspaceMemberAdmin(admin.ModelAdmin):
    list_display = ('user__email', 'user__last_name', 'workspace', 'role', 'joined_at')
    search_fields = ['user__email', 'user__last_name', 'workspace__name']
    
class AssetAdmin(admin.ModelAdmin):
    list_display = ('name', 'id', 'workspace', 'status', 'date_created', 'date_modified', 'date_uploaded')
    search_fields = ['name', 'id', 'workspace__name']
    ordering = ['-date_uploaded']
    readonly_fields = ('id', 'date_modified', 'date_uploaded')
    
class AssetAnalysisAdmin(admin.ModelAdmin):
    list_display = ('asset', 'created_at', 'updated_at')
    search_fields = ['asset__name']
    ordering = ['-created_at']

admin.site.register(Workspace, WorkspaceAdmin)
admin.site.register(WorkspaceMember, WorkspaceMemberAdmin)
admin.site.register(Asset, AssetAdmin)
admin.site.register(AssetAnalysis, AssetAnalysisAdmin)
