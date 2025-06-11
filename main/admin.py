from django.contrib import admin
from django.db import models
from main.models import (
    Workspace, WorkspaceMember, Asset, AssetAnalysis, Board, BoardAsset,
    CustomField, CustomFieldOption, CustomFieldValue, AIActionResult,
    CustomFieldOptionAIAction
)

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
    
class BoardAssetInline(admin.TabularInline):
    model = BoardAsset
    extra = 1
    autocomplete_fields = ['board']

class AssetAdmin(admin.ModelAdmin):
    list_display = ('name', 'id', 'workspace', 'status', 'date_created', 'date_modified', 'date_uploaded')
    search_fields = ['name', 'id', 'workspace__name']
    ordering = ['-date_uploaded']
    readonly_fields = ('id', 'date_modified', 'date_uploaded')
    list_filter = ('status', 'file_type')
    inlines = [BoardAssetInline]
    
    def get_boards(self, obj):
        return ", ".join([board.name for board in obj.boards.all()])
    get_boards.short_description = 'Boards'
        
class AssetAnalysisAdmin(admin.ModelAdmin):
    list_display = ('asset', 'created_at', 'updated_at')
    search_fields = ['asset__name']
    ordering = ['-created_at']

class BoardAdmin(admin.ModelAdmin):
    list_display = ('name', 'id', 'workspace', 'created_at', 'updated_at')
    search_fields = ['name', 'id', 'workspace__name']
    ordering = ['-created_at']

class BoardAssetAdmin(admin.ModelAdmin):
    list_display = ('board', 'asset', 'added_at', 'added_by')
    search_fields = ['board__name', 'asset__name']
    ordering = ['-added_at']

class CustomFieldOptionInline(admin.TabularInline):
    model = CustomFieldOption
    extra = 1

class CustomFieldAdmin(admin.ModelAdmin):
    list_display = ('title', 'workspace', 'field_type', 'order')
    list_filter = ('workspace', 'field_type')
    search_fields = ['title', 'description', 'workspace__name']
    ordering = ['workspace', 'order']
    inlines = [CustomFieldOptionInline]

class CustomFieldOptionAIActionInline(admin.TabularInline):
    model = CustomFieldOptionAIAction
    extra = 1

class CustomFieldOptionAdmin(admin.ModelAdmin):
    list_display = ('label', 'field', 'order')
    list_filter = ('field__workspace', 'field')
    search_fields = ['label', 'field__title']
    ordering = ['field', 'order']
    inlines = [CustomFieldOptionAIActionInline]

class CustomFieldValueAdmin(admin.ModelAdmin):
    list_display = ('field', 'content_type', 'get_value_display')
    list_filter = ('field__workspace', 'field', 'content_type')
    search_fields = ['field__title']
    
    def get_value_display(self, obj):
        value = obj.get_value()
        if isinstance(value, models.QuerySet):
            return ', '.join(str(v) for v in value)
        return str(value) if value else '-'
    get_value_display.short_description = 'Value'

class AIActionResultAdmin(admin.ModelAdmin):
    list_display = ('action', 'field_value', 'status', 'created_at', 'completed_at')
    list_filter = ('action', 'status')
    search_fields = ['field_value__field__title']
    ordering = ['-created_at']
    readonly_fields = ('created_at', 'completed_at')

admin.site.register(Workspace, WorkspaceAdmin)
admin.site.register(WorkspaceMember, WorkspaceMemberAdmin)
admin.site.register(Asset, AssetAdmin)
admin.site.register(AssetAnalysis, AssetAnalysisAdmin)
admin.site.register(Board, BoardAdmin)
admin.site.register(BoardAsset, BoardAssetAdmin)
admin.site.register(CustomField, CustomFieldAdmin)
admin.site.register(CustomFieldOption, CustomFieldOptionAdmin)
admin.site.register(CustomFieldValue, CustomFieldValueAdmin)
admin.site.register(AIActionResult, AIActionResultAdmin)
