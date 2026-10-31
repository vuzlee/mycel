variable "region" {
  type    = string
  default = "eu-west-2"
}

variable "profile" {
  type    = string
  default = "mycel"
}

variable "name" {
  type    = string
  default = "mycel"
}

variable "owner_cidr" {
  description = "The owner's public address as a /32: the only one the EKS API answers."
  type        = string
}

# In standard support until 2027-12; a version in extended support costs $0.60/h.
variable "kubernetes_version" {
  type    = string
  default = "1.37"
}

# $0.221/h in London; no CPU credits to run out of, unlike t3.xlarge (checked 2026-11-01).
variable "instance_type" {
  type    = string
  default = "m7i-flex.xlarge"
}
