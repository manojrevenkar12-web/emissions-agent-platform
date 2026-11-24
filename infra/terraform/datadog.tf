# One source for monitors: deploy/datadog/monitors.yml
locals {
  monitors = { for m in yamldecode(file("${path.module}/../../deploy/datadog/monitors.yml")).monitors : m.name => m }
}

resource "datadog_monitor" "this" {
  for_each = local.monitors

  name     = "[${var.env}] ${each.value.name}"
  type     = each.value.type
  query    = replace(each.value.query, "$${env}", var.env)
  message  = "${each.value.message}\n\nRunbook: https://github.com/manojrevenkar12-web/emissions-agent-platform/blob/main/docs/RUNBOOK.md#${each.value.runbook}\n@${each.value.notify}"
  priority = each.value.priority
  tags     = ["service:emissions-agent-platform", "env:${var.env}", "team:ai-platform"]

  monitor_thresholds {
    critical = each.value.critical
    warning  = try(each.value.warning, null)
  }

  notify_no_data    = false
  renotify_interval = 60
}
