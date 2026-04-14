## Redwood Inference — Key Initiatives & Roadmap

### Context & Framing
**Planning horizon:** 18 months, quarterly (Q1 2026–Q2 2027)

**Driving principles**
- **Production economics first:** improve $/token and p95 latency without sacrificing quality.
- **Reliability and graceful degradation:** design for predictable behavior under load, regional issues, and model regressions.
- **Unified experience across deployments:** same API surface, policy controls, and observability for Hosted, Dedicated, and Private.
- **Developer-first:** fast onboarding, clear benchmarks, strong SDKs/docs, and safe rollout mechanisms.
- **Enterprise-ready by default:** security controls, auditability, data residency options, and supportability.

**Strategic goals (18 months)**
- Reduce blended **cost per 1M output tokens by 30–40%** while maintaining or improving latency SLOs.
- Achieve **99.95%+** availability for Hosted and Dedicated; improve incident MTTR and customer-visible reliability.
- Expand enterprise adoption via Dedicated/Private by strengthening **security, compliance, and deployment automation**.
- Increase developer adoption and retention through better onboarding, evals, and operational tooling.

---

### Initiatives

#### 1) Next-Gen Serving Runtime Performance (Kernel + Scheduling)
**Description & scope:**
- Optimize the core inference engine: attention/kernel selection improvements, continuous batching heuristics, KV cache management, and prefill/decode scheduling.
- Expand support for newer GPU generations and improve performance stability across sequence-length distributions.
- Deliver consistent performance profiles that can be advertised and relied upon.

**Owner / team:** Serving Runtime Engineering + Applied ML (perf)

**Priority:** P0

**Key milestones (target dates):**
- **Q1 2026:** Runtime profiling baseline; top-5 bottlenecks identified; perf test suite expanded to representative workloads.
- **Q2 2026:** New scheduling policy for mixed workloads (short/long prompts); p95 latency improved by 15% on top hosted models.
- **Q3 2026:** Kernel auto-selection v2 shipped; throughput +20% on supported GPUs for common model families.
- **Q4 2026:** KV cache compaction/eviction improvements; reduced tail latencies under bursty traffic.
- **Q1 2027:** Hardware-specific tuning profiles; predictable perf across regions and instance types.
- **Q2 2027:** Runtime LTS channel for enterprise (pinned behavior, slower change rate).

**Dependencies / risks:**
- Risk of regressions in rare model architectures; mitigated by expanded conformance suite.
- Dependency on GPU supply/availability for benchmarking and rollout.
- Potential complexity creep—requires strict performance/maintainability gates.

---

#### 2) Cost Optimization Automation (Batching, Caching, Quantization Profiles)
**Description & scope:**
- Productize Redwood Optimize into actionable, safe recommendations with one-click/one-config application.
- Provide workload-aware batching/caching defaults; introduce quantization profiles by model and deployment mode.
- Add quality guardrails so cost reductions do not silently degrade outputs.

**Owner / team:** Optimize Product + Applied ML + Platform

**Priority:** P0

**Key milestones (target dates):**
- **Q1 2026:** Standardize cost model (compute, cache hit-rate, batching impact); publish internal unit economics dashboard.
- **Q2 2026:** “Optimization suggestions” beta in Console (batching/caching); rollback-safe config application.
- **Q3 2026:** Quantization profiles (e.g., INT8/FP8 where applicable) with opt-in per route; quality checks integrated.
- **Q4 2026:** Automated prompt-set regression checks tied to config changes; alerting + gated rollout.
- **Q1 2027:** Default “cost-efficient” policy bundle for Hosted customers; tiered recommendations by latency SLO.
- **Q2 2027:** Cross-deployment parity (Hosted/Dedicated/Private) for optimization guidance.

**Dependencies / risks:**
- Risk of quality degradation; requires robust eval coverage and customer opt-in controls.
- Some optimizations are hardware/model-family dependent.

---

#### 3) Reliability Program: SLOs, Incident Reduction, and Graceful Degradation
**Description & scope:**
- Formalize platform SLOs (availability, latency, error rate) by product tier.
- Improve multi-region failover, capacity protection, overload behavior, and fallback policies.
- Operational excellence: on-call maturity, runbooks, automated mitigation.

**Owner / team:** SRE + Core Platform

**Priority:** P0

**Key milestones (target dates):**
- **Q1 2026:** Define tiered SLOs; error-budget policy; top incident classes mapped to owners.
- **Q2 2026:** Region-level failover improvements; circuit breakers and load shedding for Hosted.
- **Q3 2026:** Dedicated customer SLO dashboards + customer-facing status transparency upgrades.
- **Q4 2026:** Automated fallback policies expanded (model variants, region routing) with customer-configurable controls.
- **Q1 2027:** MTTR reduced via automated diagnostics and playbooks; deploy-time reliability checks.
- **Q2 2027:** Target steady-state: Hosted and Dedicated at **99.95%+** availability (rolling 90-day).

**Dependencies / risks:**
- Capacity constraints can block reliability improvements.
- Fallback models may have behavior differences; requires clear customer expectations and opt-out.

---

#### 4) Unified Rollouts, A/B Testing, and Safe Model Lifecycle Management
**Description & scope:**
- Expand Console rollouts into a consistent model lifecycle system across Hosted, Dedicated, and Private.
- Support canary deployments, shadow traffic, A/B tests, and automatic rollback driven by latency/error/quality metrics.
- Improve model version pinning and change visibility.

**Owner / team:** Console Product + Platform Engineering

**Priority:** P1

**Key milestones (target dates):**
- **Q1 2026:** Standardize model version metadata and release notes format; customer-visible changelog.
- **Q2 2026:** Canary rollout workflow GA for Hosted; automated rollback on SLO breach.
- **Q3 2026:** A/B testing framework integrated with eval metrics; route-level policy controls.
- **Q4 2026:** Dedicated support for staged rollouts across reserved pools.
- **Q1 2027:** Private rollout controller (VPC) with audit logs and approval gates.
- **Q2 2027:** Unified rollout API/CLI for all deployment modes.

**Dependencies / risks:**
- Requires consistent telemetry (latency, errors, quality signals).
- Enterprise customers may require approval workflows and auditability.

---

#### 5) Enterprise Security & Compliance Foundation (Auditability + Key Management + Data Residency)
**Description & scope:**
- Strengthen controls required for larger enterprise and regulated customers.
- Improve audit logs, RBAC granularity, and customer-managed key integrations.
- Expand data residency and retention controls.

**Owner / team:** Security & Compliance + Platform

**Priority:** P1

**Key milestones (target dates):**
- **Q1 2026:** RBAC v2 requirements and design; audit log schema standardized.
- **Q2 2026:** Audit log export (SIEM-ready); KMS integrations hardened; retention controls in Console.
- **Q3 2026:** Data residency controls for Hosted (region pinning + enforcement); compliance reporting pack.
- **Q4 2026:** Private deployment hardening: secrets management, network policy templates.
- **Q1 2027:** Security posture monitoring + configuration drift detection for Private.
- **Q2 2027:** Compliance-ready evidence automation (continuous control monitoring outputs).

**Dependencies / risks:**
- Requires coordination with enterprise customers’ security teams.
- Data residency constraints can increase operational complexity and cost.

---

#### 6) Private Deployment Automation (VPC + On-Prem Packaging)
**Description & scope:**
- Reduce time-to-deploy and operational burden for Redwood Private.
- Provide reference architectures, IaC modules, upgrade paths, and health checks.
- Improve on-prem packaging for regulated/air-gapped customers.

**Owner / team:** Private Deployments Engineering + Solutions Engineering

**Priority:** P1

**Key milestones (target dates):**
- **Q1 2026:** Standard deployment reference architecture + Terraform modules (VPC) alpha.
- **Q2 2026:** Upgrade mechanism with rollback; private control plane observability minimum set.
- **Q3 2026:** On-prem installer improvements; offline artifact signing + verification.
- **Q4 2026:** Private “day-2 ops” toolkit: backup/restore, log export, capacity reporting.
- **Q1 2027:** Multi-cluster / multi-region private topology support (where applicable).
- **Q2 2027:** Time-to-first-production target: <30 days for standard VPC deployments.

**Dependencies / risks:**
- Highly variable customer environments; scope control is critical.
- Requires strong release engineering and support readiness.

---

#### 7) Developer Experience: SDKs, Quickstarts, and Usage Analytics
**Description & scope:**
- Improve PLG funnel and retention with best-in-class SDKs, docs, templates, and in-product guidance.
- Enhance usage analytics and cost visibility for engineers.

**Owner / team:** Developer Experience + Growth Product

**Priority:** P2

**Key milestones (target dates):**
- **Q1 2026:** SDK parity review (Python/TS/Go); unified auth + retries; improved streaming examples.
- **Q2 2026:** Quickstart templates for common use cases (RAG, agents/tool-calling, eval harness integration).
- **Q3 2026:** In-console usage insights: cost drivers by route/model; alerts for budget thresholds.
- **Q4 2026:** Self-serve performance benchmarking page per model + region.
- **Q1 2027:** Guided onboarding flows; “first production launch” checklist.
- **Q2 2027:** API ergonomics polish based on top support tickets; reduce time-to-first-success.

**Dependencies / risks:**
- Requires accurate telemetry and stable API behavior.
- Must avoid fragmentation across SDKs.

---

#### 8) Capacity & Fleet Management for Dedicated (Predictable Throughput + Autoscaling)
**Description & scope:**
- Improve reserved capacity planning, burst handling, and autoscaling for Dedicated customers.
- Provide clearer throughput guarantees and operational controls.

**Owner / team:** Infrastructure + Dedicated Product

**Priority:** P1

**Key milestones (target dates):**
- **Q1 2026:** Define throughput SLOs and capacity model for Dedicated tiers.
- **Q2 2026:** Burst capacity option design + implementation; guardrails to protect neighbors.
- **Q3 2026:** Autoscaling policies with customer-configurable bounds; predictive scaling signals.
- **Q4 2026:** Capacity reporting in Console; reservation utilization recommendations.
- **Q1 2027:** Dedicated multi-region active/active (select customers) feasibility + pilot.
- **Q2 2027:** Reduce Dedicated provision-to-ready time by 50% via automation.

**Dependencies / risks:**
- GPU procurement and lead times.
- Complexity in isolating noisy-neighbor effects while offering burst.

---

### Success Criteria

#### Initiative-level KPIs
1) **Next-Gen Serving Runtime Performance**
- p95 latency improvement on top workloads: **≥20%** by Q4 2026 (vs Q1 2026 baseline)
- Throughput improvement (tokens/sec/GPU) on supported fleets: **≥25%** by Q1 2027
- Performance regression rate: <1% of releases cause customer-impacting perf regression

2) **Cost Optimization Automation**
- Blended cost per 1M output tokens: **30–40% reduction** by Q2 2027
- Adoption: ≥30% of active Hosted customers use at least one optimization recommendation
- Quality guardrails: <2% of optimization changes require rollback due to quality regressions

3) **Reliability Program**
- Availability: **Hosted 99.95%+**, **Dedicated 99.95%+** (rolling 90-day) by Q2 2027
- MTTR: **50% reduction** from Q1 2026 baseline by Q1 2027
- Change failure rate: reduced by **30%** by Q4 2026

4) **Unified Rollouts & Model Lifecycle**
- Canary/rollback automation usage: ≥50% of production routes use rollout policies by Q2 2027
- Incidents caused by model upgrades: reduced by **40%** by Q2 2027
- Time to detect quality regression from rollout start: <30 minutes for routes with evals enabled

5) **Enterprise Security & Compliance**
- Audit log export adoption: ≥60% of enterprise accounts by Q1 2027
- RBAC coverage: 100% of sensitive actions gated by RBAC v2 by Q3 2026
- Evidence automation: reduce manual compliance evidence effort by **50%** by Q2 2027

6) **Private Deployment Automation**
- Median time-to-deploy (VPC standard): <30 days by Q2 2027
- Upgrade success rate: ≥95% upgrades completed without support escalation by Q1 2027

7) **Developer Experience**
- Time-to-first-success (from sign-up to first successful streaming call): improve by **30%** by Q1 2027
- Support ticket rate per 1k requests: down **20%** by Q2 2027

8) **Dedicated Capacity & Fleet Management**
- Provision-to-ready time: **50% reduction** by Q2 2027
- Reservation utilization: +15% improvement via recommendations by Q1 2027

#### Overall roadmap progress criteria
- Roadmap outcomes tracked quarterly with clear baselines and deltas for **cost, latency, availability, and adoption**.
- Each quarter ships at least **one material improvement** in (a) runtime economics or (b) reliability, while maintaining API stability.
- Enterprise growth readiness: Dedicated/Private deployments become more repeatable through standardized security controls and automation.
