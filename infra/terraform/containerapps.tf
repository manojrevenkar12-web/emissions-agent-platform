resource "azurerm_container_app_environment" "this" {
  name                           = "cae-${local.name}"
  resource_group_name            = azurerm_resource_group.this.name
  location                       = azurerm_resource_group.this.location
  log_analytics_workspace_id     = azurerm_log_analytics_workspace.this.id
  infrastructure_subnet_id       = azurerm_subnet.apps.id
  internal_load_balancer_enabled = false
  tags                           = local.tags
}

resource "azurerm_container_app" "api" {
  name                         = "ca-${local.name}-api"
  resource_group_name          = azurerm_resource_group.this.name
  container_app_environment_id = azurerm_container_app_environment.this.id
  revision_mode                = "Single"
  tags                         = local.tags

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.api.id]
  }

  registry {
    server   = azurerm_container_registry.this.login_server
    identity = azurerm_user_assigned_identity.api.id
  }

  dynamic "secret" {
    for_each = azurerm_key_vault_secret.this
    content {
      name                = secret.key
      key_vault_secret_id = secret.value.versionless_id
      identity            = azurerm_user_assigned_identity.api.id
    }
  }

  ingress {
    external_enabled = true
    target_port      = 8000
    transport        = "http"
    traffic_weight {
      latest_revision = true
      percentage      = 100
    }
  }

  template {
    min_replicas = var.min_replicas
    max_replicas = var.max_replicas

    http_scale_rule {
      name                = "http"
      concurrent_requests = "40"
    }

    container {
      name   = "api"
      image  = "${azurerm_container_registry.this.login_server}/emissions-agent-platform:${var.image_tag}"
      cpu    = 0.5
      memory = "1Gi"

      env {
        name  = "EAP_ENV"
        value = var.env
      }
      env {
        name  = "EAP_MODEL"
        value = "claude"
      }
      env {
        name        = "EAP_DATABASE_URL"
        secret_name = "database-url"
      }
      env {
        name        = "EAP_KEYS_JSON"
        secret_name = "api-keys"
      }
      env {
        name        = "ANTHROPIC_API_KEY"
        secret_name = "anthropic-api-key"
      }
      env {
        name  = "OTEL_EXPORTER_OTLP_ENDPOINT"
        value = "http://localhost:4318"
      }

      liveness_probe {
        transport = "HTTP"
        port      = 8000
        path      = "/healthz"
      }

      readiness_probe {
        transport = "HTTP"
        port      = 8000
        path      = "/healthz"
      }
    }

    # Datadog Agent sidecar: receives OTLP traces and scrapes /metrics
    container {
      name   = "datadog-agent"
      image  = "gcr.io/datadoghq/agent:7"
      cpu    = 0.25
      memory = "0.5Gi"

      env {
        name        = "DD_API_KEY"
        secret_name = "datadog-api-key"
      }
      env {
        name  = "DD_SITE"
        value = var.datadog_site
      }
      env {
        name  = "DD_ENV"
        value = var.env
      }
      env {
        name  = "DD_OTLP_CONFIG_RECEIVER_PROTOCOLS_HTTP_ENDPOINT"
        value = "0.0.0.0:4318"
      }
      env {
        name  = "DD_APM_ENABLED"
        value = "true"
      }
    }
  }
}
