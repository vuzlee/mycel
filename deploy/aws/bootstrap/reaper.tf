# Every 15 min: a cluster tagged mycel-session past its mycel-expires loses its node
# groups, then itself on a later run (HLD 123 #18). Lambda, scheduler and logs sit in
# the free tier.

resource "aws_sns_topic" "reaper" {
  name = "mycel-reaper"
}

# AWS mails a confirmation link; nothing arrives until it is clicked.
resource "aws_sns_topic_subscription" "owner" {
  topic_arn = aws_sns_topic.reaper.arn
  protocol  = "email"
  endpoint  = var.owner_email
}

data "archive_file" "reaper" {
  type        = "zip"
  source_file = "${path.module}/reaper/reaper.py"
  output_path = "${path.module}/reaper.zip"
}

resource "aws_iam_role" "reaper" {
  name = "mycel-reaper"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "reaper" {
  role = aws_iam_role.reaper.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "eks:ListClusters", "eks:DescribeCluster", "eks:ListNodegroups", "eks:DescribeNodegroup",
          "eks:DeleteNodegroup", "eks:DeleteCluster",
        ]
        Resource = "*"
      },
      { Effect = "Allow", Action = "sns:Publish", Resource = aws_sns_topic.reaper.arn },
      {
        Effect   = "Allow"
        Action   = ["logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = "${aws_cloudwatch_log_group.reaper.arn}:*"
      },
    ]
  })
}

resource "aws_cloudwatch_log_group" "reaper" {
  name              = "/aws/lambda/mycel-reaper"
  retention_in_days = 7
}

resource "aws_lambda_function" "reaper" {
  function_name    = "mycel-reaper"
  role             = aws_iam_role.reaper.arn
  runtime          = "python3.13"
  handler          = "reaper.handler"
  filename         = data.archive_file.reaper.output_path
  source_code_hash = data.archive_file.reaper.output_base64sha256
  timeout          = 60
  environment {
    variables = { TOPIC_ARN = aws_sns_topic.reaper.arn }
  }
  depends_on = [aws_cloudwatch_log_group.reaper]
}

resource "aws_iam_role" "scheduler" {
  name = "mycel-reaper-scheduler"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "scheduler.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "scheduler" {
  role = aws_iam_role.scheduler.id
  policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Action = "lambda:InvokeFunction", Resource = aws_lambda_function.reaper.arn }]
  })
}

resource "aws_scheduler_schedule" "reaper" {
  name                = "mycel-reaper"
  schedule_expression = "rate(15 minutes)"
  flexible_time_window { mode = "OFF" }
  target {
    arn      = aws_lambda_function.reaper.arn
    role_arn = aws_iam_role.scheduler.arn
  }
}
