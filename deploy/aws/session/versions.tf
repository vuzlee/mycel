# Applied by `stack.sh aws up`, destroyed by `down`: VPC, EKS, one node (HLD 123).
# State sits in the bootstrap bucket; `up` passes its name with -backend-config.

terraform {
  required_version = ">= 1.11"
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 6.71" }
  }
  backend "s3" {
    key          = "session.tfstate"
    region       = "eu-west-2"
    use_lockfile = true
  }
}

provider "aws" {
  region  = var.region
  profile = var.profile
  default_tags { tags = { "mycel-session" = var.name } }
  # Written by `up` and `extend` with the AWS CLI; an apply must not put it back (#22).
  ignore_tags { keys = ["mycel-expires"] }
}
