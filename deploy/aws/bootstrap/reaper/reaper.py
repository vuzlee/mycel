"""Delete an EKS cluster tagged `mycel-session` once its `mycel-expires` has passed.

Node groups go first; the cluster goes on a later run, once it has none left.
Without a readable `mycel-expires` (an apply by hand), it expires 4 h after creation.
"""

import os
from datetime import UTC, datetime, timedelta

import boto3

eks = boto3.client("eks")
sns = boto3.client("sns")


DEFAULT_LIFE = timedelta(hours=4)


def expired(tags: dict[str, str], created: datetime, now: datetime) -> bool:
    if "mycel-session" not in tags:
        return False
    try:
        expires = datetime.fromisoformat(tags["mycel-expires"].replace("Z", "+00:00"))
    except (KeyError, ValueError):
        expires = created + DEFAULT_LIFE
    return expires <= now


def reap(name: str) -> str | None:
    """What was started, or None while a node group is still going."""
    groups = eks.list_nodegroups(clusterName=name)["nodegroups"]
    if not groups:
        eks.delete_cluster(name=name)
        return f"{name}: deleting the cluster"
    started = []
    for group in groups:
        status = eks.describe_nodegroup(clusterName=name, nodegroupName=group)["nodegroup"][
            "status"
        ]
        if status != "DELETING":
            eks.delete_nodegroup(clusterName=name, nodegroupName=group)
            started.append(group)
    return f"{name}: deleting node groups {', '.join(started)}" if started else None


def handler(event: object, context: object) -> list[str]:
    now = datetime.now(UTC)
    acted = []
    for name in eks.list_clusters()["clusters"]:
        cluster = eks.describe_cluster(name=name)["cluster"]
        if cluster["status"] == "DELETING" or not expired(
            cluster.get("tags", {}), cluster["createdAt"], now
        ):
            continue
        if note := reap(name):
            acted.append(note)
    if acted:
        sns.publish(
            TopicArn=os.environ["TOPIC_ARN"],
            Subject="mycel reaper acted",
            Message="\n".join(acted),
        )
    print(acted or "nothing expired")
    return acted
