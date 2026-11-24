resource "azurerm_key_vault" "this" {
  name                       = "kv-${local.name}"
  resource_group_name        = azurerm_resource_group.this.name
  location                   = azurerm_resource_group.this.location
  tenant_id                  = data.azurerm_client_config.current.tenant_id
  sku_name                   = "standard"
  enable_rbac_authorization  = true
  purge_protection_enabled   = true
  soft_delete_retention_days = 30
  tags                       = local.tags
}

# the deploying identity writes secrets; the API identity only reads them
resource "azurerm_role_assignment" "kv_officer" {
  scope                = azurerm_key_vault.this.id
  role_definition_name = "Key Vault Secrets Officer"
  principal_id         = data.azurerm_client_config.current.object_id
}

resource "azurerm_role_assignment" "kv_reader" {
  scope                = azurerm_key_vault.this.id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = azurerm_user_assigned_identity.api.principal_id
}

locals {
  secrets = {
    "database-url"      = "postgresql+psycopg://eap_admin:${random_password.db.result}@${azurerm_postgresql_flexible_server.this.fqdn}:5432/eap?sslmode=require"
    "api-keys"          = var.api_keys_json
    "anthropic-api-key" = var.anthropic_api_key
    "datadog-api-key"   = var.datadog_api_key
  }
}

resource "azurerm_key_vault_secret" "this" {
  for_each     = local.secrets
  name         = each.key
  value        = each.value
  key_vault_id = azurerm_key_vault.this.id

  depends_on = [azurerm_role_assignment.kv_officer]
}
