# Standalone Deployment Options for Neo4j MCP Server

## Purpose

This document evaluates three AWS container deployment options for running the Neo4j MCP server outside of AWS Bedrock AgentCore. As documented in M2M.md, the bearer token authentication approach works when the MCP server runs in an environment without an intermediate authentication layer consuming the HTTP Authorization header.

The three options evaluated are:
- AWS App Runner
- Amazon ECS on Fargate
- Amazon EKS (Elastic Kubernetes Service)

Each option is assessed for suitability as a long-running HTTP service, with particular attention to scaling behavior, operational complexity, cost implications, and limitations.

---

## AWS App Runner

### Overview

AWS App Runner is a fully managed service designed to deploy containerized web applications and APIs with minimal infrastructure configuration. It automatically handles deployment, scaling, load balancing, and TLS termination. The service pulls container images from Amazon ECR and exposes them via HTTPS endpoints without requiring VPC configuration or load balancer setup.

### Advantages

**Operational Simplicity**

App Runner requires the least operational overhead of the three options. Deployment involves specifying a container image and a few configuration parameters. AWS handles networking, load balancing, certificate management, and scaling automatically. There is no VPC to configure, no load balancer to provision, and no cluster to manage.

**Automatic HTTPS Endpoints**

Every App Runner service receives an automatically provisioned HTTPS endpoint with a valid TLS certificate. No additional configuration is required for secure communication. This simplifies deployment for HTTP-based services like the MCP server.

**Built-in Auto-Scaling**

App Runner automatically scales the number of container instances based on incoming request traffic. Scaling happens without manual intervention and responds to traffic patterns in real time.

**Integrated Deployment Pipeline**

App Runner can automatically rebuild and redeploy when source code changes or when new container images are pushed to ECR. This reduces the need for external CI/CD tooling for simple deployments.

### Disadvantages

**No Scale to Zero**

App Runner does not support scaling to zero instances. The service always maintains at least one provisioned instance, even when receiving no traffic. This means you pay for idle capacity continuously. For services with sporadic or unpredictable traffic patterns, this represents wasted cost compared to truly serverless options.

The scale-to-zero feature is the most requested enhancement on the App Runner roadmap, with over 543 upvotes on the GitHub issue tracker, but AWS has not announced a timeline for implementation.

**120-Second Request Timeout**

App Runner enforces a hard limit of 120 seconds for HTTP request processing. This timeout includes the time for the application to read the request body, process it, and write the complete response. The timeout cannot be extended.

For the MCP server, this timeout is likely sufficient for most database operations. However, complex Cypher queries or large result sets could potentially exceed this limit. Additionally, if future MCP protocol extensions require long-polling or streaming responses, the 120-second limit would be problematic.

**Limited Configuration Options**

App Runner intentionally abstracts away infrastructure details, which means limited control over networking, security groups, and other low-level settings. You cannot attach the service to your own VPC without using App Runner's VPC Connector feature, which adds complexity and cost. Custom domain configuration requires additional manual steps.

**Cold Start Behavior**

Although App Runner maintains provisioned instances to eliminate cold starts, there is still a one-minute minimum charge for vCPU resources each time a provisioned instance starts processing requests. For truly idle services, this means the first request after a period of inactivity incurs additional cost.

**Regional Availability**

App Runner is not available in all AWS regions. This could be a limitation for organizations with data residency requirements or users in regions where App Runner is not offered.

### Pricing Model

App Runner uses a dual pricing model:

- **Provisioned Instances**: You pay for memory usage of all provisioned instances, regardless of whether they are actively handling requests. The rate is approximately $0.007 per GB-hour in most regions.

- **Active Instances**: When instances actively process requests, you pay for both vCPU and memory. There is a one-minute minimum charge for vCPU each time an instance becomes active.

For a service running with 2 GB memory that handles intermittent traffic, monthly costs typically range from $25 to $50, depending on traffic patterns. High-volume services requiring multiple concurrent instances can cost $100 or more per month.

### Suitability for Neo4j MCP Server

App Runner is well-suited for deploying the Neo4j MCP server when:
- Operational simplicity is the primary concern
- The service receives consistent traffic (no scale-to-zero requirement)
- All MCP operations complete within 120 seconds
- Cost is acceptable given the always-on minimum instance requirement

App Runner is less suitable when:
- The service has highly sporadic traffic with long idle periods
- Cost optimization is critical and scale-to-zero is required
- Complex VPC networking is needed for Neo4j connectivity
- Request processing may exceed 120 seconds

---

## Amazon ECS on Fargate

### Overview

Amazon Elastic Container Service (ECS) is AWS's native container orchestration platform. When combined with the Fargate launch type, ECS runs containers without requiring management of underlying EC2 instances. Unlike App Runner, ECS provides fine-grained control over networking, load balancing, and service configuration while still abstracting away server management.

### Advantages

**Long-Running Service Support**

ECS Fargate services can run indefinitely without timeout restrictions on the service itself. Unlike App Runner's 120-second request timeout, ECS services behind an Application Load Balancer can handle requests up to the ALB's idle timeout limit (default 60 seconds, configurable up to 4000 seconds). For requests that do not involve an ALB, there is no inherent timeout on how long a container can run.

This makes ECS Fargate suitable for MCP operations that may take longer to complete, such as complex graph traversals or large data exports.

**Scale to Zero Capability**

ECS services can scale to zero running tasks. By configuring Application Auto Scaling with a minimum capacity of zero, the service can terminate all tasks when there is no traffic. A scheduled scaling action or target tracking policy can bring tasks back when demand increases.

However, scaling to zero requires explicit configuration and typically involves either scheduled scaling (for predictable traffic patterns) or integration with AWS Lambda and Step Functions to detect traffic and scale up. There is no built-in automatic scale-to-zero on inactivity like Google Cloud Run provides.

**VPC Integration**

ECS Fargate tasks run within your VPC, giving full control over network architecture. Tasks can run in private subnets, access resources via VPC endpoints, and communicate with databases in the same VPC without traversing the public internet. Security groups provide fine-grained network access control.

For Neo4j deployments where the database runs in a VPC (either self-hosted on EC2 or via VPC peering with Aura), ECS Fargate's networking capabilities simplify secure connectivity.

**Flexible Load Balancing**

ECS integrates with Application Load Balancers and Network Load Balancers. This enables advanced routing, path-based routing, health checks, and custom connection timeouts. You can configure multiple target groups, implement blue-green deployments, and use weighted routing for gradual rollouts.

**Service Discovery**

ECS integrates with AWS Cloud Map for service discovery, enabling other services to locate the MCP server via DNS without hardcoding IP addresses or load balancer URLs.

### Disadvantages

**Operational Complexity**

ECS requires significantly more configuration than App Runner. A production deployment typically involves:
- VPC with public and private subnets across multiple availability zones
- NAT Gateway or VPC endpoints for private subnet internet access
- Application Load Balancer with target groups and listeners
- ECS cluster, task definition, and service configuration
- IAM roles for task execution and task roles
- Security groups for ALB, tasks, and any VPC endpoints
- CloudWatch log groups for container logging
- Auto-scaling policies for the service

This complexity translates to more time for initial setup and ongoing maintenance burden. Teams unfamiliar with these components face a steeper learning curve.

**No Native Scale-to-Zero**

While ECS can scale to zero, it requires explicit configuration and does not automatically detect idle periods. You must implement your own mechanism to detect when the service should scale down and back up. Common approaches include:
- Scheduled scaling actions for predictable traffic patterns
- Lambda functions triggered by CloudWatch alarms to adjust desired count
- Third-party tools that monitor traffic and manage scaling

Without this additional engineering, ECS will maintain at least the minimum task count continuously.

**Cold Start Latency**

When scaling from zero or when new tasks launch, Fargate tasks experience cold start latency. The container image must be pulled from ECR (unless cached), and the application must initialize. For Go applications like the Neo4j MCP server, this is typically 10-30 seconds, but can be longer for larger images or applications with lengthy startup procedures.

**Task Retirement**

AWS periodically retires Fargate tasks for maintenance and patching. The default retirement wait period is 7 days (configurable up to 14 days), after which tasks are terminated and replaced. Well-designed services handle this gracefully, but applications with long-running connections or significant local state may experience disruption.

**VPC Endpoint Costs**

Running Fargate tasks in private subnets without NAT Gateway requires VPC endpoints for ECR, S3, CloudWatch Logs, and Secrets Manager. Each interface endpoint costs approximately $7.20 per month per availability zone, plus data processing charges. For a production setup with multiple endpoints across two or three availability zones, this adds $50-100+ per month in networking costs alone.

### Pricing Model

ECS itself has no additional charge; you pay only for the compute and networking resources consumed:

- **Fargate Compute**: Charged per vCPU-hour and GB-hour based on configured task resources. Prices vary by region but are approximately $0.04048 per vCPU-hour and $0.004445 per GB-hour in US regions.

- **Load Balancer**: Application Load Balancer costs approximately $16-25 per month plus data processing charges.

- **NAT Gateway or VPC Endpoints**: NAT Gateway costs approximately $32 per month plus data processing. VPC endpoints cost approximately $7.20 per month per endpoint per availability zone.

For a continuously running service with 0.5 vCPU and 1 GB memory, compute costs are approximately $20-25 per month. Adding ALB and networking costs brings the total to $60-100+ per month for a production-ready configuration.

Fargate is significantly more expensive than running containers on EC2 instances directly (estimates suggest 6-10x higher compute costs), but eliminates server management overhead.

### Suitability for Neo4j MCP Server

ECS on Fargate is well-suited for deploying the Neo4j MCP server when:
- Fine-grained control over networking is required
- The Neo4j database runs in a VPC and private connectivity is needed
- Request processing may exceed 120 seconds
- The team has AWS infrastructure experience or existing ECS deployments
- Scale-to-zero is acceptable with additional configuration work

ECS on Fargate is less suitable when:
- Operational simplicity is the primary concern
- The team lacks AWS networking and ECS experience
- Budget constraints preclude the additional networking infrastructure costs
- Automatic scale-to-zero without custom engineering is required

---

## Amazon EKS (Elastic Kubernetes Service)

### Overview

Amazon EKS is a managed Kubernetes service that runs the Kubernetes control plane across multiple availability zones. EKS can run workloads on EC2 instances, Fargate, or a combination of both. It provides the full Kubernetes API and ecosystem, enabling portable, highly configurable container orchestration.

### Advantages

**Full Kubernetes Ecosystem**

EKS provides access to the complete Kubernetes ecosystem, including Helm charts, operators, custom resource definitions, and the vast library of Kubernetes-native tools. Organizations already using Kubernetes in other environments can apply their existing knowledge, configurations, and tooling.

**Portability**

Kubernetes workloads are portable across cloud providers and on-premises environments. An MCP server deployment running on EKS could be migrated to Google GKE, Azure AKS, or self-hosted Kubernetes with minimal modification. This reduces vendor lock-in compared to ECS or App Runner.

**Advanced Scaling with Karpenter**

Karpenter is a Kubernetes-native node provisioner that provides just-in-time compute capacity. Unlike the Kubernetes Cluster Autoscaler, Karpenter can provision nodes in seconds and select optimal instance types based on workload requirements. Combined with the Kubernetes Horizontal Pod Autoscaler, this enables sophisticated scaling strategies.

**Scale-to-Zero Capability**

Kubernetes natively supports scaling deployments to zero replicas. Combined with KEDA (Kubernetes Event-Driven Autoscaling), workloads can scale based on HTTP traffic, queue depth, or custom metrics. When scaled to zero, no pods run and no compute resources are consumed.

However, implementing scale-to-zero requires running KEDA and configuring ScaledObjects, adding operational complexity. Additionally, Karpenter must run continuously (typically on Fargate) to provision nodes when pods need to scale up.

**Long-Running Service Support**

Kubernetes services have no inherent timeout restrictions. Pods can run indefinitely, and connection timeouts are configurable at the ingress controller or service mesh level. This provides maximum flexibility for MCP operations of any duration.

**Multi-Tenancy and Isolation**

Kubernetes namespaces provide logical separation between workloads. Combined with network policies, pod security policies, and RBAC, EKS supports sophisticated multi-tenant architectures where the MCP server can coexist with other services in the same cluster.

### Disadvantages

**Highest Operational Complexity**

EKS requires the most expertise to deploy and operate correctly. Beyond the VPC and networking requirements shared with ECS, Kubernetes introduces:
- Control plane configuration and version management
- Node group or Fargate profile configuration
- Kubernetes manifests (Deployments, Services, Ingress, ConfigMaps, Secrets)
- Ingress controller installation and configuration (AWS Load Balancer Controller, nginx, etc.)
- Cluster add-ons management (CoreDNS, kube-proxy, VPC CNI)
- Kubernetes RBAC policies
- Monitoring and logging integration (Prometheus, Grafana, or CloudWatch Container Insights)

Teams without Kubernetes experience face a significant learning curve. Even experienced teams report that EKS requires substantial ongoing maintenance compared to simpler alternatives.

**Control Plane Cost**

EKS charges $0.10 per hour ($74 per month) for each cluster's control plane, regardless of the number of workloads running. This fixed cost applies even if the cluster runs no pods. For organizations running multiple clusters, this cost compounds significantly.

**Fargate Profile Limitations**

When running EKS workloads on Fargate (rather than EC2 nodes), several Kubernetes features are unavailable:
- DaemonSets cannot run on Fargate nodes (each pod runs on its own isolated node)
- Privileged containers are not supported
- HostNetwork and HostPort are not supported
- Persistent storage is limited to Amazon EFS (no EBS support)
- Maximum pod size is 4 vCPU and 30 GB memory
- GPU workloads are not supported

These limitations may not affect the Neo4j MCP server directly, but restrict what other workloads can share the cluster.

**No Native Pod Identity on Fargate**

EKS Fargate does not support EKS Pod Identity (the newer approach to IAM authentication). Workloads on Fargate must use IAM Roles for Service Accounts (IRSA), which requires additional configuration including an OIDC provider for the cluster.

**Complexity of Scale-to-Zero**

While Kubernetes supports scaling to zero, achieving true scale-to-zero with automatic wake-up requires significant additional tooling:
- KEDA for event-driven autoscaling
- Karpenter running on Fargate to provision nodes on demand
- Custom CronJobs or controllers to manage scaling schedules

One documented approach involves running Karpenter on Fargate with CronJobs that manipulate Karpenter's provisioner configuration to scale nodes to zero on schedule. This works but adds operational complexity and potential failure modes.

**Version Management Burden**

Kubernetes releases new versions approximately three times per year, and EKS requires clusters to run supported versions. Upgrading involves updating the control plane, node groups (or Fargate platform version), and potentially modifying manifests for deprecated APIs. This creates ongoing maintenance burden regardless of workload changes.

### Pricing Model

EKS pricing includes:

- **Control Plane**: $0.10 per hour ($74 per month) per cluster

- **Compute (Fargate)**: Same pricing as ECS Fargate, approximately $0.04048 per vCPU-hour and $0.004445 per GB-hour

- **Compute (EC2)**: Standard EC2 pricing, significantly cheaper than Fargate but requires node management

- **Networking**: Same VPC endpoint and NAT Gateway costs as ECS when running in private subnets

- **Add-ons**: Some EKS add-ons have additional costs; others are free

For a minimal EKS deployment with one small workload on Fargate, expect costs of $100-150 per month when including the control plane, compute, load balancing, and networking. EC2-based nodes can reduce compute costs but add management overhead.

Compared to ECS, the additional $74 per month control plane fee may not be significant for production workloads, but makes EKS disproportionately expensive for small or experimental deployments.

### Suitability for Neo4j MCP Server

EKS is well-suited for deploying the Neo4j MCP server when:
- The organization already operates Kubernetes clusters and has expertise
- Portability across cloud providers is important
- The MCP server will coexist with other Kubernetes workloads in the same cluster
- Advanced scaling strategies (KEDA, Karpenter) are needed
- The team values Kubernetes ecosystem tooling (Helm, operators, service mesh)

EKS is less suitable when:
- The MCP server is the only or primary workload
- The team lacks Kubernetes experience
- Operational simplicity is prioritized
- Budget constraints make the control plane fee significant
- Rapid initial deployment is required

---

## Comparison Summary

### Scale-to-Zero Capability

| Service | Native Scale-to-Zero | Implementation Complexity |
|---------|---------------------|---------------------------|
| App Runner | No | Not available; minimum 1 instance always runs |
| ECS Fargate | Yes (with configuration) | Moderate; requires auto-scaling configuration or custom Lambda-based scaling |
| EKS | Yes (with KEDA/Karpenter) | High; requires KEDA, Karpenter on Fargate, and careful configuration |

### Long-Running Service Support

| Service | Request/Connection Timeout | Service Lifetime |
|---------|---------------------------|------------------|
| App Runner | 120 seconds (hard limit) | Unlimited (service runs continuously) |
| ECS Fargate | Configurable via ALB (up to 4000 seconds) | Unlimited (tasks run until stopped or retired) |
| EKS | Configurable via ingress controller | Unlimited (pods run until terminated) |

All three services support indefinitely running services. The distinction is in request timeout limits, which affects individual MCP operations. App Runner's 120-second limit is the most restrictive.

### Operational Complexity

| Service | Initial Setup | Ongoing Maintenance | Required Expertise |
|---------|---------------|--------------------|--------------------|
| App Runner | Low (minutes) | Minimal | Basic container knowledge |
| ECS Fargate | Moderate (hours) | Low-Moderate | AWS VPC, IAM, ECS concepts |
| EKS | High (days) | High | Kubernetes, AWS networking, cluster management |

### Cost Structure (Approximate Monthly, Small Workload)

| Service | Compute (Always-On) | Networking | Control Plane | Total |
|---------|--------------------| -----------|---------------|-------|
| App Runner | $25-50 | Included | None | $25-50 |
| ECS Fargate | $20-25 | $50-100 | None | $70-125 |
| EKS (Fargate) | $20-25 | $50-100 | $74 | $145-200 |

These estimates assume a small workload (0.5 vCPU, 1 GB memory) running continuously. Actual costs vary based on traffic, region, and specific configuration.

### Feature Summary

| Feature | App Runner | ECS Fargate | EKS |
|---------|------------|-------------|-----|
| VPC Integration | Optional (VPC Connector) | Native | Native |
| Custom Domains | Manual configuration | Via ALB | Via Ingress |
| TLS Termination | Automatic | Via ALB | Via Ingress/ALB |
| Service Discovery | Not available | AWS Cloud Map | Kubernetes DNS |
| Deployment Strategies | Rolling | Rolling, Blue-Green | Rolling, Blue-Green, Canary |
| Health Checks | HTTP | HTTP, TCP, Command | HTTP, TCP, Command |
| Secrets Management | Secrets Manager, Parameter Store | Secrets Manager, Parameter Store | Kubernetes Secrets, Secrets Manager |
| Portability | AWS-only | AWS-only | Multi-cloud |

---

## Recommendation for Neo4j MCP Server

### For Simplicity: AWS App Runner

If the primary goals are rapid deployment and minimal operational overhead, App Runner is the best choice. The 120-second request timeout is likely sufficient for most MCP operations against Neo4j, and the always-on instance ensures consistent response times without cold start delays.

Accept that scale-to-zero is not available, and budget for the continuous minimum instance cost. This is a reasonable trade-off for teams that prioritize simplicity over cost optimization.

### For Balance: Amazon ECS on Fargate

If VPC integration is required (for example, connecting to Neo4j running in a private subnet), or if MCP operations may exceed 120 seconds, ECS Fargate provides the necessary flexibility without the full complexity of Kubernetes.

ECS requires more initial configuration but offers better long-term control over networking and scaling. Scale-to-zero is achievable with additional configuration, making it suitable for cost-conscious deployments with variable traffic.

### For Kubernetes Environments: Amazon EKS

If the organization already operates Kubernetes clusters or requires workload portability across cloud providers, EKS makes sense. The MCP server can run alongside other services in existing clusters, sharing infrastructure costs and operational tooling.

Avoid EKS solely for the MCP server deployment if no other Kubernetes workloads exist. The operational overhead and control plane cost are difficult to justify for a single service.

---

## Conclusion

All three services can successfully host the Neo4j MCP server as a long-running HTTP service where bearer token authentication works without the AgentCore Authorization header conflict.

The choice depends on organizational context:
- Teams prioritizing simplicity should choose App Runner
- Teams needing VPC integration or flexible timeouts should choose ECS Fargate
- Teams with existing Kubernetes expertise and infrastructure should choose EKS

None of the services provides automatic scale-to-zero that matches the simplicity of Google Cloud Run. Organizations with highly sporadic traffic and strong cost sensitivity may find all three options more expensive than desired during idle periods.

---

## Sources

- [AWS App Runner Pricing](https://aws.amazon.com/apprunner/pricing/)
- [AWS App Runner Auto Scaling](https://docs.aws.amazon.com/apprunner/latest/dg/manage-autoscaling.html)
- [App Runner Scale to Zero Feature Request (GitHub)](https://github.com/aws/apprunner-roadmap/issues/9)
- [App Runner Request Timeout Discussion (AWS re:Post)](https://repost.aws/questions/QUnozEpub5Tnq-ilmrB4l2Sg/aws-app-runner-what-exactly-does-the-timeout-limit-documentation-mean)
- [Amazon ECS Task Networking for Fargate](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/fargate-task-networking.html)
- [ECS Fargate Task Maintenance and Retirement](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/task-maintenance.html)
- [ECS vs EKS Comparison (CloudZero)](https://www.cloudzero.com/blog/ecs-vs-eks/)
- [EKS Fargate Limitations](https://docs.aws.amazon.com/eks/latest/userguide/fargate.html)
- [Scale-to-Zero with Karpenter (AWS Blog)](https://aws.amazon.com/blogs/containers/manage-scale-to-zero-scenarios-with-karpenter-and-serverless/)
- [Karpenter Best Practices (EKS Documentation)](https://docs.aws.amazon.com/eks/latest/best-practices/karpenter.html)
- [EKS Pricing Guide](https://www.devzero.io/blog/eks-pricing)

---

*Document completed: 2026-01-07*
