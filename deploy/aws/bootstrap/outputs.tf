output "state_bucket" {
  value = aws_s3_bucket.state.id
}

output "reaper_topic" {
  value = aws_sns_topic.reaper.arn
}
