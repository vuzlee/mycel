# mycel.sbs answers from Route 53 (HLD 128). The domain is bought at Hostinger; its
# name servers there point at this zone, so the zone is never destroyed: a new one
# gets new name servers.

resource "aws_route53_zone" "app" {
  name = var.domain
}

# Free; DNS-validated in the zone above, so it renews on its own.
resource "aws_acm_certificate" "app" {
  domain_name               = var.domain
  subject_alternative_names = ["*.${var.domain}"]
  validation_method         = "DNS"
  lifecycle { create_before_destroy = true }
}

# The apex and the wildcard ask for the same record; one is enough. Keyed on the
# domain, which is known before the certificate exists.
resource "aws_route53_record" "cert" {
  zone_id         = aws_route53_zone.app.zone_id
  name            = one(local.cert_record).resource_record_name
  type            = one(local.cert_record).resource_record_type
  records         = [one(local.cert_record).resource_record_value]
  ttl             = 300
  allow_overwrite = true
}

locals {
  cert_record = [for o in aws_acm_certificate.app.domain_validation_options : o if o.domain_name == var.domain]
}

# Waits until AWS sees the record, which needs the name servers moved first.
resource "aws_acm_certificate_validation" "app" {
  count                   = var.wait_for_cert ? 1 : 0
  certificate_arn         = aws_acm_certificate.app.arn
  validation_record_fqdns = [aws_route53_record.cert.fqdn]
}
