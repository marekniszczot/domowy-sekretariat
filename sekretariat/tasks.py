"""Enqueue letter processing on Cloud Tasks (retries and backoff come from the queue)."""

from google.cloud import tasks_v2


class TaskQueue:
    def __init__(
        self,
        client: tasks_v2.CloudTasksClient,
        queue: str,
        base_url: str,
        service_account: str,
    ):
        self._client = client
        self._queue = queue  # projects/<p>/locations/<l>/queues/<q>
        self._base_url = base_url.rstrip("/")
        self._service_account = service_account

    def enqueue(self, letter_id: str) -> None:
        self._client.create_task(
            parent=self._queue,
            task=tasks_v2.Task(
                http_request=tasks_v2.HttpRequest(
                    url=f"{self._base_url}/internal/process/{letter_id}",
                    http_method=tasks_v2.HttpMethod.POST,
                    oidc_token=tasks_v2.OidcToken(
                        service_account_email=self._service_account,
                        audience=self._base_url,
                    ),
                )
            ),
        )
