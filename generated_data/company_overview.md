# Company Overview: Redwood Inference

## Company name + 1‑liner
**Redwood Inference** is a developer-first platform for running and optimizing large language model (LLM) inference across hosted, dedicated, and private deployments.

## Mission and thesis
**Mission:** Make high-performance, reliable LLM inference accessible to every engineering team.

**Thesis:** As LLM capabilities and open model ecosystems expand, competitive advantage shifts from model ownership to *serving*: latency, cost, reliability, deployment flexibility, and operational tooling. The winners will provide a unified runtime and developer experience that makes inference predictable and economical across rapidly changing hardware and model landscapes.

## Company overview (what it does)
Redwood Inference provides an inference platform that lets developers ship LLM-powered applications with consistent performance across multiple deployment modes:
- **Hosted API** for fastest time-to-value
- **Dedicated capacity** for predictable throughput and data isolation
- **Private deployment** (VPC and on-prem options) for regulated workloads

The platform focuses on production-grade inference (throughput, latency, reliability), model lifecycle management for serving (versioning, rollouts), and tooling to reduce unit costs while maintaining output quality.

## Who the company serves
Primary users are **software engineers and ML engineers** building LLM features into products. Typical customers include:
- **AI-native startups** and fast-growing SaaS companies that need a PLG-friendly API with strong performance
- **Mid-market and enterprise product teams** requiring SLAs, security controls, and predictable capacity
- **Platform teams** that want standardized inference across business units

Geography: North America and Europe, with growing APAC usage via cloud regions and partners.

## Product surface area and key features
### 1) Redwood API (hosted inference)
- Simple REST/SDK interface for text generation, chat, embeddings, and reranking
- Model catalog with curated open models and Redwood-verified performance profiles
- Streaming responses, function/tool calling, and structured output support
- Built-in rate limiting, quotas, and usage analytics

### 2) Redwood Dedicated (reserved capacity)
- Dedicated GPU pools with predictable throughput and data isolation
- Configurable autoscaling policies and burst capacity options
- SLA-backed uptime and latency targets

### 3) Redwood Private (VPC/on-prem deployment)
- Private control plane with customer-managed networking
- Optional on-prem package for regulated or air-gapped environments
- Key management integrations (KMS/HSM) and audit logs

### 4) Redwood Console (observability + operations)
- Token-level cost and latency breakdowns
- Per-route/model dashboards, tracing hooks, and error analysis
- Rollouts: canary deploys, A/B tests, and automatic fallback policies

### 5) Redwood Optimize (cost/performance toolkit)
- Intelligent batching/caching configuration suggestions
- Model and quantization recommendations by workload
- Quality monitoring and regression alerts tied to prompt sets/evals

## How the core product/technology works
Redwood’s platform combines a high-throughput serving runtime with an orchestration layer:

- **Serving runtime:** A GPU-optimized inference engine supporting modern attention optimizations, continuous batching, KV cache management, and quantization-friendly execution paths.
- **Compilation and kernel selection:** The runtime selects optimized kernels based on model architecture, sequence length distribution, and hardware.
- **Smart routing:** Requests can be routed by policy (latency, cost, region, customer tier), with automated fallback to compatible model variants when capacity is constrained.
- **Caching and batching:** Automatic prefix/KV caching and workload-aware batching reduce per-token cost while preserving latency SLOs.
- **Deployment abstraction:** A consistent API and config layer across hosted, dedicated, and private deployments. Customers can pin model versions and rollout policies independent of underlying infrastructure.

## Interesting differentiations
- **Production-first developer experience:** Fast onboarding, strong docs/SDKs, transparent performance benchmarks, and first-class evals to prevent quality regressions.
- **Unified inference across environments:** Same interface and operational tooling for hosted, dedicated, and private deployments.
- **Cost-aware performance controls:** Clear levers (batching, cache, quantization profiles, routing policies) with measurable unit economics impact.
- **Reliability and graceful degradation:** Built-in fallbacks (model variants, regions, capacity tiers) to keep applications online.

## Business model and revenue streams
- **Usage-based pricing** for the hosted API (per-token and per-embedding unit).
- **Reserved capacity contracts** for Dedicated (monthly/annual commits).
- **Enterprise licensing and support** for Private deployments (platform fee + support tier).
- **Add-ons:** advanced observability retention, compliance packages, and premium SLAs.

## Go-to-market strategy
Redwood is **PLG-led** with an engineering-centric motion:
- Self-serve sign-up, free credits, and quickstart templates
- Strong open-source/community engagement via reference apps and evaluation harnesses
- Content and benchmarks focused on real production workloads (latency/cost)
- Gradual expansion to **sales-assisted enterprise** for Dedicated and Private, triggered by usage thresholds and security/SLA needs
- Cloud marketplace listings and select channel partnerships for regulated industries

## Size of the team, funding history, and key departments
**Team size:** ~150 employees.

**Organization (high level):**
- Engineering (serving runtime, infra, reliability, platform)
- Product (API/console, enterprise features, pricing/packaging)
- Developer experience (SDKs, docs, solutions engineering)
- Research/Applied ML (inference optimization, evals, model onboarding)
- Go-to-market (growth, sales, partnerships)
- Security & compliance
- Customer support and success

**Funding:** Series C-backed.
- Seed (2019–2020): early team and prototype
- Series A (2021): expand hosted API and initial enterprise readiness
- Series B (2022–2023): scale capacity, improve runtime performance, launch Dedicated
- Series C (2024): accelerate Private deployments, compliance, and global regions

## Positioning in the market and competitive landscape
**Positioning:** Redwood Inference is positioned as a **developer-first inference platform** optimized for *production economics*—helping teams balance cost, latency, and reliability while keeping deployment options open.

**Competitive landscape:**
- **General cloud AI platforms** offering managed model endpoints and GPU services
- **LLM API providers** focused on simplicity and model access
- **Inference infrastructure vendors** offering self-hosted runtimes and orchestration

Redwood differentiates by combining a high-performance runtime with an opinionated, observable production platform and flexible deployment modes—aimed at teams who want control over inference economics without building and operating the full stack themselves.
