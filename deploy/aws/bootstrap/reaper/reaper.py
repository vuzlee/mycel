"""Delete an EKS cluster tagged `mycel-session` once its `mycel-expires` has passed.

Load balancers the cluster's controller made go first (they sit in the VPC Terraform
must delete later), then node groups; the cluster goes on a later run, once it has none.
Without a readable `mycel-expires` (an apply by hand), it expires 4 h after creation.
"""

import os
from datetime import UTC, datetime, timedelta

import boto3

eks = boto3.client("eks")
elb = boto3.client("elbv2")
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


def owned(tags: dict[str, str], cluster: str) -> bool:
    """Made by this session's load balancer controller, nothing else."""
    return "mycel-session" in tags and tags.get("elbv2.k8s.aws/cluster") == cluster

def tags_of(arns: list[str]) -> dict[str, dict[str, str]]:
    out = {}
    for i in range(0, len(arns), 20):  # the API takes 20 at a time
        for d in elb.describe_tags(ResourceArns=arns[i : i + 20])["TagDescriptions"]:
            out[d["ResourceArn"]] = {t["Key"]: t["Value"] for t in d["Tags"]}
    return out

def reap_balancers(name: str) -> list[str]:
    """Load balancers, then their target groups; names of what was deleted."""
    gone = []
    for kind, listing, key, delete in [
        ("load balancer", elb.describe_load_balancers, "LoadBalancers", elb.delete_load_balancer),
        ("target group", elb.describe_target_groups, "TargetGroups", elb.delete_target_group),
    ]:
        items = listing().get(key, [])
        arn_key = "LoadBalancerArn" if key == "LoadBalancers" else "TargetGroupArn"
        tags = tags_of([i[arn_key] for i in items])
        for item in items:
            arn = item[arn_key]
            if not owned(tags.get(arn, {}), name):
                continue
            try:
                delete(**{arn_key: arn})
                gone.append(f"{kind} {arn.rsplit('/', 2)[-2]}")
            except elb.exceptions.ResourceInUseException:
                pass  # its load balancer is still going; the next run gets it
    return gone

def reap(name: str) -> str | None:
    """What was started, or None while a node group is still going."""
    if balancers := reap_balancers(name):
        return f"{name}: deleting {', '.join(balancers)}"
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
