---
type: Guide
title: Product Definition
---

# infra-copilot

<!-- truth: start -->
Agent-first, human-in-the-loop infrastructure bootstrap and maintenance workflows.

**Purpose:** Bootstrap and maintain Terraform, HCP Terraform, Cloudflare, and GitHub infrastructure through conversational agent skills.

**Core value:** State is never assumed - every run re-derives it by executing each step's check. The phase-tagged step manifest with explicit checks makes workflows resumable.

**Architecture:** Four action skills (setup, import, add, status) are thin routers over one hub skill (infra-copilot), whose references/ directory owns the behavior. Host packages are adapters and must never become a second behavioral authority.
<!-- truth: end -->

## Target users

- Infrastructure engineers bootstrapping new Terraform-managed repositories
- Platform teams adopting existing cloud resources into Terraform
- Operations teams maintaining multi-provider infrastructure

## Key workflows

1. **Setup** - Bootstrap a new infrastructure repository with HCP Terraform workspace, Cloudflare zone, and GitHub provider
2. **Import** - Adopt pre-existing cloud resources into Terraform management
3. **Add** - Add new resources to an existing managed repository
4. **Status** - Report current infrastructure state through manifest-defined checks
