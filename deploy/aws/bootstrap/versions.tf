# Applied once, never destroyed (HLD 123 #14, #19): the state bucket the session root
# keeps its state in, the budgets, and the reaper that must outlive any cluster it reaps.
# Its own state stays local: it holds nothing that cannot be imported again.

terraform {
  required_version = ">= 1.11"
  required_providers {
    aws     = { source = "hashicorp/aws", version = "~> 6.71" }
    archive = { source = "hashicorp/archive", version = "~> 2.7" }
  }
}

provider "aws" {
  region  = var.region
  profile = var.profile
  default_tags { tags = { "mycel-bootstrap" = "true" } }
}
