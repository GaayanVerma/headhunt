# Tushar Jain — Candidate Profile

## Personal Info

| Field | Value |
|---|---|
| Full Name | Tushar Jain |
| Email | tusharjainn1@gmail.com |
| Phone | +91-7877894975 |
| Location | Bengaluru, Karnataka, India |
| LinkedIn | https://www.linkedin.com/in/tushar-jain-1003/ |
| Open to Work | Yes — SDE-2, Backend Engineer, AI Platform Engineer, Full-Stack Engineer |
| Birthday | March 10 |

---

## Summary

AI Engineer with 3+ years of experience building production RAG systems, agentic workflows, and backend infrastructure. Currently at Pixis AI on PRISM — an AI-powered marketing platform serving 50+ enterprise brands. Previously built a bond trading platform at Dexif (₹5,000+ Cr annual transactions), was Founding Engineer at Senu (0-to-1 satellite imagery + healthcare app), and interned at Amazon AWS. ACM ICPC Asia Regionalist (AIR 97).

---

## Education

| Institution | Degree | Years |
|---|---|---|
| BITS Pilani, Pilani Campus | B.E. (Hons.), Computer Science | 2019 – 2023 |

---

## Work Experience

### Pixis AI — Software Engineer | Bengaluru | Aug 2025 – Present (11 mos)
- Built PRISM's Prompt Library: versioned repo of 200+ prompts with semantic search (OpenAI embeddings + pgvector) across 9 ad-platform integrations, eliminating prompt sprawl
- Built Campaign Portfolio tracking system for CSMs — 2.5M+ campaign records, 70% reduction in manual reporting time
- Implemented scoped RAG layer for brand/account context (PDFs, Sheets, websites, internal instructions) supporting 50+ enterprise brands

### Dexif — Software Engineer | Noida | Feb 2024 – Aug 2025 (1 yr 7 mos)
- Led backend for bond trading platform: 30,000+ bonds, INR 5,000+ Cr annual transactions
- Automated KYC onboarding for 200,000+ clients
- Built real-time broker/RM chat over WebSockets for 1,000+ active brokers
- Shipped financial modules eliminating 30 hrs/week of manual reconciliation

### Senu — Founding Engineer | Bengaluru | Jun 2023 – Jan 2024 (8 mos)
- First engineering hire; built satellite-imagery analysis tool using SAM-based custom segmentation across 10+ geospatial workflows (Figma to cloud deployment)
- Drove healthcare pivot in under 6 weeks: shipped longevity mobile app with LLM personalization, 2 EHR integrations, 3 health tracker devices, 50+ beta users

### InMobi — Analyst Intern | Bengaluru | Jan 2023 – Jun 2023 (6 mos)

### Amazon AWS — SDE Intern | Bengaluru | Jun 2022 – Aug 2022 (3 mos)
- Automated Jenkins pipeline for daily TPC-DS benchmarking on Presto — surfaced regressions 5 days earlier than prior weekly process
- Built Python utility comparing 100+ benchmark runs, reducing divergence investigation from hours to minutes for the EMR Presto team

### DeepBlink — Research Intern | Remote (US) | Jun 2021 – Dec 2021 (7 mos)

### Hertztech Solutions — ML Engineer Intern | Remote

---

## Projects

### AgentLens *(Python, LangGraph, FastAPI, pgvector, LangSmith, React)*
- LangGraph agentic RAG with hybrid retrieval, reflection-based gap recovery, claim verification, and SSE streaming for grounded, low-latency responses
- Semantic query caching, prompt-injection guardrails, LangSmith tracing for observability

### CodeSentinel *(Python, QLoRA, vLLM, LangGraph, FastAPI)*
- Multi-agent PR review system with GitHub webhook orchestration, structured review outputs, QLoRA fine-tuning, vLLM-compatible model serving
- Custom eval harness tracking precision, recall, F1, latency, and GPT-4o-as-judge scores

---

## Skills

| Category | Skills |
|---|---|
| AI/LLM | LangChain, LangGraph, RAG, Agentic Workflows, LangSmith, OpenAI API, MCP, PyTorch, Prompt Engineering |
| Languages | Python, SQL, TypeScript/JavaScript, Java |
| Backend | FastAPI, Django, Node.js, Express.js, REST APIs, Microservices, Distributed Systems, Kafka |
| Frontend | React, Next.js |
| Databases | MySQL, PostgreSQL, MongoDB, Redis, pgvector |
| Cloud & Infra | AWS, Docker, Kubernetes, CI/CD |

---

## Achievements

| Achievement | Detail | Year |
|---|---|---|
| ACM ICPC | AIR 97 — Asia Regional Contest, Kanpur-Mathura Site | 2021 |
| KVPY Fellowship (Govt. of India) | Top 1000 out of 150,000 candidates | 2019 |
| NTSE Scholarship (Govt. of India) | Top 1000 out of 1,000,000 candidates | 2017 |

---

## Technical Round Review

### What He Showed

**Production ownership on PRISM (Pixis)**
He identified the actual pain — people hand-copying brand knowledge, ingestion was a black box — and built for correctness, not just retrieval. Scoping and precedence rules because one brand account spans many campaigns, processing states, idempotent sources with stable IDs. That kind of thinking is what you want from someone touching production data.

**Genuine retrieval depth on AgentLens**
Walked the loop cleanly. Used RRF for fusion because it beats raw score merging, and said the reflection step fires on evidence completeness rather than plain similarity — the right distinction, not something you parrot.

**Sharp banking/compliance answer**
Extract to structured JSON, cross-check against the term sheet, treat a conflict as a hallucination signal, pull the supporting span from page metadata. His line: *"no citation, no covenant"* — plus dedup, HITL, and no falling back on general knowledge. That is the grounding discipline compliance work needs.

**Career narrative**
Coherent story across the job hops — each move builds on the last. Optimizes for ownership and the problem, not title or stability.

---

### What We Didn't Get

**Evaluation (open box — JD priority)**
The GPT-4o-judge harness in CodeSentinel is unverified. He didn't get tested on how he built the label set or how he'd catch a biased judge. Close this next round.

**Semantic cache claim unproven**
He explained SSE streaming and async generators well, and knew when WebSockets fit better, but never described a cache key schema or the false-hit risk on semantic similarity thresholds.

