from django.urls import path

from project_apps.api.views import WorkflowCreateAPIView, WorkflowExecuteAPIView

urlpatterns = [
    path('workflow', WorkflowCreateAPIView.as_view()),
    path('workflow/execute/<uuid:workflow_uuid>', WorkflowExecuteAPIView.as_view()),
]
