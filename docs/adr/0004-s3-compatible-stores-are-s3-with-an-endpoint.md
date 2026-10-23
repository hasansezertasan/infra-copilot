# S3-compatible stores are the s3 backend with an endpoint

## Context and Problem Statement

The object-storage steps assumed AWS for `s3`: `aws` calls without an endpoint, a required
DynamoDB lock table and IAM role ARNs. copier-infra now renders `state_backend: s3` with an
optional `state_endpoint` for Cloudflare R2 and MinIO, so the Skills could not operate on it.

## Considered Options

* A separate `r2` backend: rejected, it renders the same Terraform `s3` backend and the list
  of providers would grow without bound.
* Hand-edit around the checks: rejected, the Skills would report setup as verified when it
  is not.

## Decision Outcome

`STATE_ENDPOINT` non-empty turns the AWS-only parts of the `s3` path into their
S3-compatible form: `--endpoint-url` on `aws`, no lock table (`use_lockfile`), static
bucket-scoped keys instead of OIDC roles, and `-lock=false` plan jobs.

Cloudflare R2 (and only R2: MinIO and other stores still need versioning enabled) implements neither `PutBucketVersioning` nor `PutPublicAccessBlock`. The
`state-bucket` check therefore proves only existence, the missing versioning is recorded as
a locked "State history" decision, and `backend-identity-trust` has the human confirm that
no `r2.dev` URL or custom domain is attached. A compensating state backup is possible later.
