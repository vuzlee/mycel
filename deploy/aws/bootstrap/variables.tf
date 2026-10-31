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
