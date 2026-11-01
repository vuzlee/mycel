# The AWS Load Balancer Controller makes the ALB for https://mycel.sbs from the app's
# Ingress (HLD 128). Its role reaches the pod by Pod Identity: no OIDC provider to keep.
# Policy: the controller's own, v3.6.2, as published.

resource "aws_iam_policy" "lb_controller" {
  name   = "${var.name}-lb-controller"
  policy = file("${path.module}/lb-controller-policy.json")
}

resource "aws_iam_role" "lb_controller" {
  name = "${var.name}-lb-controller"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "pods.eks.amazonaws.com" }
      Action    = ["sts:AssumeRole", "sts:TagSession"]
    }]
  })
}

resource "aws_iam_role_policy_attachment" "lb_controller" {
  role       = aws_iam_role.lb_controller.name
  policy_arn = aws_iam_policy.lb_controller.arn
}

resource "aws_eks_pod_identity_association" "lb_controller" {
  cluster_name    = module.eks.cluster_name
  namespace       = "kube-system"
  service_account = "aws-load-balancer-controller"
  role_arn        = aws_iam_role.lb_controller.arn
}
