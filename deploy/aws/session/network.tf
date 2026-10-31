data "aws_availability_zones" "here" {
  state = "available"
}

# Two public subnets because EKS wants two AZs; no NAT, so a node needs its own
# public address to pull images (#9, #11a).
module "vpc" {
  source  = "terraform-aws-modules/vpc/aws"
  version = "6.7.3"

  name                    = var.name
  cidr                    = "10.42.0.0/16"
  azs                     = slice(data.aws_availability_zones.here.names, 0, 2)
  public_subnets          = ["10.42.0.0/20", "10.42.16.0/20"]
  map_public_ip_on_launch = true
  enable_nat_gateway      = false
}
