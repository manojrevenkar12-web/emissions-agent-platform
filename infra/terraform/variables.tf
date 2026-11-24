variable "env" {
  description = "Environment name: dev, staging or prod."
  type        = string
  validation {
    condition     = contains(["dev", "staging", "prod"], var.env)
    error_message = "env must be dev, staging or prod."
  }
}

variable "location" {
  description = "Azure region."
  type        = string
  default     = "germanywestcentral"
}

variable "image_tag" {
  description = "Container image tag to deploy (the git SHA)."
  type        = string
}

variable "api_keys_json" {
  description = "JSON list of {key_sha256, subject, role, tenant}; hashes only, never keys."
  type        = string
  sensitive   = true
}

variable "anthropic_api_key" {
  description = "Key for the hosted model."
  type        = string
  sensitive   = true
}

variable "datadog_api_key" {
  description = "Datadog API key for the agent sidecar and the provider."
  type        = string
  sensitive   = true
}

variable "datadog_app_key" {
  description = "Datadog application key for monitors."
  type        = string
  sensitive   = true
}

variable "datadog_site" {
  description = "Datadog site, e.g. datadoghq.eu."
  type        = string
  default     = "datadoghq.eu"
}

variable "min_replicas" {
  description = "Minimum API replicas."
  type        = number
  default     = 1
}

variable "max_replicas" {
  description = "Maximum API replicas."
  type        = number
  default     = 6
}
