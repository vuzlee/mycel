output "state_bucket" {
  value = aws_s3_bucket.state.id
}

output "reaper_topic" {
  value = aws_sns_topic.reaper.arn
}

output "name_servers" {
  description = "Set these four at the registrar."
  value       = aws_route53_zone.app.name_servers
}

output "certificate_arn" {
  value = aws_acm_certificate.app.arn
}
