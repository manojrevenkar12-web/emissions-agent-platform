output "api_url" {
  description = "Public URL of the API."
  value       = "https://${azurerm_container_app.api.ingress[0].fqdn}"
}

output "registry" {
  description = "Container registry login server."
  value       = azurerm_container_registry.this.login_server
}

output "key_vault" {
  description = "Key Vault holding the service's secrets."
  value       = azurerm_key_vault.this.name
}
