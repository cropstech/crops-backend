from django.contrib import admin
from main.models import Workspace, WorkspaceMember, Asset, AssetAnalysis, Board, BoardAsset

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

admin.site.register(Workspace, WorkspaceAdmin)
admin.site.register(WorkspaceMember, WorkspaceMemberAdmin)
admin.site.register(Asset, AssetAdmin)
admin.site.register(AssetAnalysis, AssetAnalysisAdmin)
admin.site.register(Board, BoardAdmin)
admin.site.register(BoardAsset, BoardAssetAdmin)
