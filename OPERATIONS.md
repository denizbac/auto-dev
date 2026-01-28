# Auto-Dev - Operations Guide (KaaS/EKS)

This document explains how to operate Auto-Dev on the shared KaaS (EKS) cluster.

## Quick Reference

```bash
# Namespace
kubectl get pods -n <namespace>

# Apply manifests
kubectl apply -k k8s/

# Rollouts
kubectl rollout status deployment/auto-dev-dashboard -n <namespace>

# Logs
kubectl logs deployment/auto-dev-dashboard -n <namespace> --tail=200
```

Key conventions:
- Ingress class: `nginx`
- Ingress host must be `*.kaas.nimbus.amgen.com`
- NetworkPolicy uses Cilium (default-deny)
- Secrets are synced via External Secrets Operator (ESO)

---

## 1. Access & Cluster Context

- Use the shared KaaS kubeconfig stored locally (e.g., `config.yaml`, ignored by Git).
- Ensure you are targeting the correct namespace for Auto-Dev.

```bash
kubectl config get-contexts
kubectl config use-context <kaas-context>
```

---

## 2. Ingress & DNS (KaaS)

KaaS uses the nginx ingress controller, which fronts an AWS ALB.

Requirements:
- Ingress annotation: `kubernetes.io/ingress.class: nginx`
- Hostname: `*.kaas.nimbus.amgen.com` only

Sample (see `k8s/ingress.yaml`):

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  annotations:
    kubernetes.io/ingress.class: nginx
spec:
  rules:
  - host: auto-dev.kaas.nimbus.amgen.com
```

If you need a custom subdomain, contact `amgensre@amgen.com`.

---

## 3. Network Policy (Cilium)

Cilium is default-deny on shared clusters. You must allow:
- same-namespace traffic
- traffic from `nginx-ingress` namespace (ingress controller)
- DNS from `kube-system`

Sample policy (see `k8s/networkpolicy.yaml`):

```yaml
apiVersion: cilium.io/v2
kind: CiliumNetworkPolicy
metadata:
  name: allow-across-ns
spec:
  endpointSelector: {}
  ingress:
  - fromEndpoints:
    - {}
  - fromEndpoints:
    - matchLabels:
        "k8s:io.kubernetes.pod.namespace": nginx-ingress
  - fromEndpoints:
    - matchLabels:
        "k8s:io.kubernetes.pod.namespace": kube-system
```

If another namespace must reach your services, both namespaces need compatible policies.

---

## 4. Secrets Management (ESO)

KaaS uses External Secrets Operator (ESO) with AWS Secrets Manager.

High-level steps:
1. Create OIDC identity provider in your AWS account for the KaaS cluster.
   - OIDC provider ARN: `arn:aws:iam::684002232065:oidc-provider/oidc.eks.us-west-2.amazonaws.com/id/257CD7A69AC4446FAA02098C09C32FD6`
2. Create IAM policy for Secrets Manager access.
3. Create IAM role with trust to the KaaS OIDC provider (attach required permissions boundary).
4. Create a ServiceAccount annotated with the role ARN.
5. Create a `SecretStore` and `ExternalSecret` in your namespace.

Example manifests are in `k8s/eso.yaml`.

IAM setup is managed in `infra/iam/` (Terraform) to create the ESO role.

Additional secret for registry pulls:
- Create a Kubernetes image pull secret named `auto-dev-registry-cred` using your GitLab creds.
- Example (use a GitLab PAT with `read_registry`):

```bash
kubectl create secret docker-registry auto-dev-registry-cred \
  --docker-server=<gitlab-registry-host> \
  --docker-username=<gitlab-username> \
  --docker-password=<gitlab-pat> \
  --docker-email=<email> \
  -n <namespace>
```

---

## 5. Deployment (Local by default)

For now, deployments are applied from your local kubeconfig:

Storage note:
- PostgreSQL, Redis, and Qdrant use PVCs with the cluster’s default EBS storage class.
- Each deployment mounts its own persistent `/auto-dev/data` PVC (per-pod, not shared).

```bash
kubectl apply -k k8s/
kubectl rollout status deployment/auto-dev-dashboard -n <namespace>
```

If you want GitLab CI deployments later:
- Provide a CI `KUBE_CONFIG_B64` variable and keep `.gitlab-ci.yml` deploy stage enabled.

---

## 6. Logs & Monitoring

Use Kubernetes-native tooling:

```bash
kubectl get pods -n <namespace>
kubectl logs deployment/auto-dev-dashboard -n <namespace> --tail=200
kubectl describe pod <pod> -n <namespace>
```

Cluster logging is managed by KaaS; CloudWatch log groups will be platform-managed (new names, not `/ecs/*`).

---

## 7. Troubleshooting

- Ingress not reachable: verify DNS host ends with `.kaas.nimbus.amgen.com` and nginx ingress class.
- Pods not talking: verify CiliumNetworkPolicy allows ingress from `nginx-ingress` and `kube-system`.
- Secrets missing: verify ESO SecretStore/ExternalSecret and AWS IAM role trust/permissions.
- Pods crash-looping: check `kubectl logs` and `kubectl describe` events.
