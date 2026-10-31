module "eks" {
  source  = "terraform-aws-modules/eks/aws"
  version = "21.29.0"

  name               = var.name
  kubernetes_version = var.kubernetes_version
  vpc_id             = module.vpc.vpc_id
  subnet_ids         = module.vpc.public_subnets

  # Private access is how the node reaches the API; public only from the owner (#11).
  endpoint_private_access      = true
  endpoint_public_access       = true
  endpoint_public_access_cidrs = [var.owner_cidr]

  # The SSO role that applies is the admin, by access entry (#13).
  enable_cluster_creator_admin_permissions = true

  # No KMS key and no control-plane logs: both outlive a destroy (#20).
  encryption_config           = null
  create_kms_key              = false
  enabled_log_types           = []
  create_cloudwatch_log_group = false

  addons = {
    vpc-cni = {
      before_compute = true
      # The chart's NetworkPolicy is what makes FORWARDED_ALLOW_IPS "*" safe (#12).
      configuration_values = jsonencode({ enableNetworkPolicy = "true" })
    }
    kube-proxy     = {}
    coredns        = {}
    metrics-server = {}
  }

  eks_managed_node_groups = {
    main = {
      ami_type       = "AL2023_x86_64_STANDARD"
      instance_types = [var.instance_type]
      min_size       = 1
      max_size       = 1
      desired_size   = 1

      block_device_mappings = {
        xvda = {
          device_name = "/dev/xvda"
          ebs = {
            volume_size           = 60
            volume_type           = "gp3"
            delete_on_termination = true
          }
        }
      }
    }
  }
}
