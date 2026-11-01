variable "region" {
  type    = string
  default = "eu-west-2"
}

variable "profile" {
  type    = string
  default = "mycel"
}

variable "owner_email" {
  description = "Budget alerts and reaper notices go here."
  type        = string
}

variable "budget_limits" {
  description = "One monthly budget per amount, in USD, counted before credits."
  type        = list(number)
  default     = [10, 20]
}

variable "domain" {
  description = "Bought elsewhere; its name servers point at the zone in dns.tf."
  type        = string
  default     = "mycel.sbs"
}

variable "wait_for_cert" {
  description = "false until the registrar points at the zone, or apply waits on the certificate."
  type        = bool
  default     = false
}
