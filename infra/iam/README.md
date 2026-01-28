# KaaS ESO IAM Role

This Terraform config creates the IAM role used by the External Secrets Operator (ESO)
service account in the shared KaaS cluster.

## Prereqs
- AWS credentials for the target account
- Permissions boundary policy available (default: `atmos-iam-boundary-POLICY`)

## Usage

```bash
cd infra/iam
terraform init

# Option A: you already created the OIDC provider in this account
terraform apply \
  -var="oidc_provider_arn=arn:aws:iam::<ACCOUNT_ID>:oidc-provider/oidc.eks.us-west-2.amazonaws.com/id/257CD7A69AC4446FAA02098C09C32FD6"

# Option B: create the OIDC provider with Terraform
terraform apply -var="create_oidc_provider=true"
```

After apply, update `k8s/eso.yaml` with the output role ARN:

```
eks.amazonaws.com/role-arn: <eso_role_arn>
```
