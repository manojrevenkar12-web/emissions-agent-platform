# 0007 Azure Container Apps, PostgreSQL Flexible Server, Key Vault, Datadog sidecar

## Decision
The API runs on Azure Container Apps in a VNet-integrated environment, with a user-assigned identity that pulls from ACR and reads Key Vault secrets. PostgreSQL Flexible Server has private access only and requires TLS. A Datadog Agent sidecar receives OTLP traces from the API and scrapes `/metrics`. Monitors are defined once in `deploy/datadog/monitors.yml` and created by Terraform. State is in Azure Storage per environment.

## Consequences
No credentials in code or images; secrets rotate in Key Vault. Container Apps scales on concurrent HTTP requests. An AKS cluster would only pay off with more services than this one.
