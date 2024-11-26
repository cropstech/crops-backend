from functools import wraps
from django.shortcuts import get_object_or_404
from .models import Workspace, WorkspaceMember
from .utils import create_error_response

def check_workspace_permission(min_role):
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(request, workspace_id, *args, **kwargs):
            workspace = get_object_or_404(Workspace, id=workspace_id)
            try:
                member = WorkspaceMember.objects.get(
                    workspace=workspace,
                    user=request.user
                )
            except WorkspaceMember.DoesNotExist:
                return create_error_response("You are not a member of this workspace")
            
            role_levels = {
                WorkspaceMember.Role.COMMENTER: 0,
                WorkspaceMember.Role.EDITOR: 1,
                WorkspaceMember.Role.ADMIN: 2
            }
            
            if role_levels[member.role] < role_levels[min_role]:
                return create_error_response("Insufficient permissions")
            
            kwargs['workspace'] = workspace
            kwargs['member'] = member
            return view_func(request, workspace_id=workspace_id, *args, **kwargs)
        return _wrapped_view
    return decorator 