from datetime import UTC, datetime
from types import SimpleNamespace

from sekretariat.tasks import TaskQueue


def test_enqueue_posts_to_internal_endpoint_with_oidc():
    created = []
    client = SimpleNamespace(create_task=lambda parent, task: created.append((parent, task)))
    queue = TaskQueue(client, "projects/p/locations/l/queues/q", "https://web.run.app/", "sa@p.iam")

    queue.enqueue("L1")

    parent, task = created[0]
    assert parent == "projects/p/locations/l/queues/q"
    assert task.http_request.url == "https://web.run.app/internal/process/L1"
    assert task.http_request.oidc_token.service_account_email == "sa@p.iam"
    assert task.http_request.oidc_token.audience == "https://web.run.app"


def test_notify_is_scheduled_for_later():
    created = []
    client = SimpleNamespace(create_task=lambda parent, task: created.append(task))
    queue = TaskQueue(client, "projects/p/locations/l/queues/q", "https://web.run.app", "sa@p.iam")

    queue.notify("dom1", datetime(2026, 10, 12, 8, 2, tzinfo=UTC))

    [task] = created
    assert task.http_request.url == "https://web.run.app/internal/notify/dom1"
    assert task.http_request.oidc_token.audience == "https://web.run.app"
    assert task.schedule_time.timestamp() == datetime(2026, 10, 12, 8, 2, tzinfo=UTC).timestamp()
