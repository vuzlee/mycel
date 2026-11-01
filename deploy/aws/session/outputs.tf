output "cluster_name" {
  value = module.eks.cluster_name
}

output "region" {
  value = var.region
}

output "vpc_id" {
  value = module.vpc.vpc_id
}

output "public_subnet_cidrs" {
  description = "Where the ALB's addresses live; the api's NetworkPolicy lets them in."
  value       = module.vpc.public_subnets_cidr_blocks
}
