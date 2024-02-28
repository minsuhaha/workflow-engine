from time import time

import docker, orjson as json
from docker.errors import ImageNotFound, APIError
from celery import shared_task
from requests.exceptions import ReadTimeout, ConnectionError

from project_apps.constants import JOB_STATUS_RUNNING, JOB_STATUS_SUCCESS, JOB_STATUS_FAIL, WORKFLOW_STATUS_FAIL
from project_apps.repository.history_repository import HistoryRepository
from project_apps.service.workflow_manage import WorkflowManager


@shared_task
def job_execute(workflow_uuid, history_uuid, job_uuid):
    client = docker.from_env()
    workflow_manager = WorkflowManager()
    history_repo = HistoryRepository()

    if workflow_manager.check_workflow_status(workflow_uuid) == WORKFLOW_STATUS_FAIL:
        return

    job_data = workflow_manager.find_job_data(workflow_uuid, job_uuid)
    if not job_data:    
        return

    try:
        if not workflow_manager.update_job_status(workflow_uuid, job_uuid, JOB_STATUS_RUNNING):
            return
        image = client.images.pull(job_data['image'])
        parameters = job_data.get('parameters', '{}')
        environment = json.loads(parameters.replace("'", "\""))
        timeout = job_data['timeout']
        retries = job_data['retries']
        if not timeout:
            timeout = 60
        
        for _ in range(retries+1):
            start_time = time()
            container = client.containers.run(image, detach=True, environment=environment)
            workflow_manager.add_container_to_running_list(workflow_uuid, container.id)
            while True:
                if time() - start_time > timeout:
                    container.remove(force=True)
                    break

                container.reload()
                if container.attrs['State']['Status'] in ['exited','dead']:
                    if container.attrs['State']['ExitCode'] == 0:
                        if not workflow_manager.update_job_status(workflow_uuid, job_uuid, JOB_STATUS_SUCCESS):
                            return
                        workflow_manager.handle_success(job_data, workflow_uuid, history_uuid, history_repo)
                        workflow_manager.remove_container_from_running_list(workflow_uuid, container.id)
                        container.remove()
                        return
                    else:
                        workflow_manager.remove_container_from_running_list(workflow_uuid, container.id)
                        container.remove(force=True)
                        break

        workflow_manager.update_job_status(workflow_uuid, job_uuid, JOB_STATUS_FAIL)
        workflow_manager.handle_failure(history_uuid, workflow_uuid, history_repo)

    except (ReadTimeout, ConnectionError, ImageNotFound, APIError) as e:
        workflow_manager.update_job_status(workflow_uuid, job_uuid, JOB_STATUS_FAIL)
        workflow_manager.handle_failure(history_uuid, workflow_uuid, history_repo)

    except Exception as e:
        workflow_manager.update_job_status(workflow_uuid, job_uuid, JOB_STATUS_FAIL)
        workflow_manager.handle_failure(history_uuid, workflow_uuid, history_repo)
