# Stack Overflow Knowledge Intelligence Platform

> **NoSQL Databases Homework 2**
> MongoDB Atlas · Neo4j Aura · Redis · Groq LLM · Docker

A Developer Knowledge Intelligence Platform that analyses 50,000 Stack Overflow questions using two complementary NoSQL databases — MongoDB for document analytics and Neo4j for graph-based relationship discovery — plus Redis as a caching layer and a Groq LLM end-to-end pipeline.

**Dataset:** https://www.kaggle.com/datasets/stackoverflow/stacksample

## Project Structure

```
so_analytics/
├── .env                        
├── .env.template               
├── requirements.txt            ← Python dependencies
├── docker-compose.yml          ← 7 microservices
├── Dockerfile                  ← single image for all services
├── orchestrate.py              ← one-command bonus runner
│
├── data/
│   └── stacksample/
│       ├── Questions.csv       ← download from Kaggle
│       ├── Answers.csv
│       └── Tags.csv
│
├── etl/
│   ├── load_mongodb.py         ← loads 50k questions into Atlas
│   ├── load_neo4j.py           ← loads 20k questions into Aura
│   └── verify.py               ← confirms counts in both DBs
│
├── analytics/
│   ├── mongo_queries.py        ← 8 aggregation pipelines
│   ├── neo4j_queries.py        ← 4 Cypher 
│   └── cypher_queries.cypher   ← browser reference
│
└── bonus/
    ├── redis_cache.py          ← Redis caching demo (3rd NoSQL)
    └── llm_query_gen.py        ← Groq end-to-end LLM pipeline (bonus criteria)
```

---

## Quick Start

### 1. Prerequisites

| Tool | Version | Install |
|------|---------|---------|
| Python | 3.10+ | python.org |
| Docker Desktop | latest | docker.com/products/docker-desktop |
| MongoDB Atlas | M0 free | cloud.mongodb.com |
| Neo4j Aura | Free | console.neo4j.io |
| Groq API key | Free | console.groq.com |

### 2. Clone and set up environment

```bash
# Navigate to project
cd so_analytics

# Create virtual environment
python3 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### 3. Configure credentials

```bash
cp .env.template .env
open -e .env                      # fill in your actual values
```

Required values in `.env`:
```
MONGO_URI=mongodb+srv://<user>:<pass>@<cluster>.mongodb.net/...
MONGO_DB=stackoverflow
NEO4J_URI=neo4j+s://<id>.databases.neo4j.io
NEO4J_USER=neo4j
NEO4J_PASSWORD=<your-aura-password>
REDIS_HOST=localhost
REDIS_PORT=6379
GROQ_API_KEY=gsk_...
DATA_DIR=./data/stacksample
QUESTION_LIMIT=50000
```

### 4. Download dataset

Download from https://www.kaggle.com/datasets/stackoverflow/stacksample and place the 3 CSV files:
```
data/stacksample/Questions.csv
data/stacksample/Answers.csv
data/stacksample/Tags.csv
```

---

## Running the Project

### Run order (bare Python — recommended)

```bash
# Step 1 — Start Redis
docker compose up -d redis

# Step 2 — Load data (run independently, either order)
python etl/load_mongodb.py        # ~5 min — 50k questions → Atlas
python etl/load_neo4j.py          # ~4 min — 20k questions → Aura

# Step 3 — Verify both databases loaded
python etl/verify.py

# Step 4 — Run analytics
python analytics/mongo_queries.py    # → mongo_results.json
python analytics/neo4j_queries.py    # → neo4j_results.json

# Step 5 — Run bonus
python bonus/redis_cache.py          # Redis caching demo
python bonus/llm_query_gen.py        # Groq LLM pipeline → llm_evidence.json

# Step 6 — Stop Redis
docker compose down
```

### Run via Docker microservices

```bash
# See all 7 defined services
docker compose config --services

# Start infrastructure
docker compose up -d redis

# Run ETL services
docker compose run --rm mongo-loader
docker compose run --rm neo4j-loader

# Run analytics services
docker compose up mongo-analytics neo4j-analytics

# Run bonus services
docker compose up redis-cache llm-pipeline

# Run everything
docker compose up

# Stop everything
docker compose down
```

### One-command bonus runner (orchestrate.py)

```bash
python orchestrate.py               # auto-detects Docker/Homebrew, runs all bonus
python orchestrate.py --skip-llm    # skip LLM if no API key
python orchestrate.py --no-cleanup  # leave Redis running after
```

---

## What Each Script Does

### ETL

| Script | What it does | Output |
|--------|-------------|--------|
| `etl/load_mongodb.py` | Reads 3 CSVs, builds denormalized documents (question + embedded answers + tags), bulk-upserts into Atlas `stackoverflow.questions` | 50,000 documents in ~165 MB |
| `etl/load_neo4j.py` | Creates constraints, loads User/Question/Answer/Tag nodes + 6 relationship types, builds CO_OCCURS_WITH tag edges | 143,072 nodes, 319,102 relationships |
| `etl/verify.py` | Queries both DBs for document/node counts and sample records | Console output |

### Analytics

| Script | What it does | Output |
|--------|-------------|--------|
| `analytics/mongo_queries.py` | Runs 8 aggregation pipelines (tag trends, score distribution, user activity, answer rates) | `mongo_results.json` |
| `analytics/neo4j_queries.py` | Runs 6 Cypher queries (connected users, tag co-occurrence, experts, shortest path, community detection, PageRank) | `neo4j_results.json` |
| `analytics/cypher_queries.cypher` | All Cypher queries formatted for Neo4j Browser copy-paste | — |

### Bonus

| Script | What it does | Output |
|--------|-------------|--------|
| `bonus/redis_cache.py` | Fetches top tags/users from MongoDB, caches using String/Hash/SortedSet, demos 35x speed-up | Console output |
| `bonus/llm_query_gen.py` | Groq pipeline: generates Cypher + MongoDB queries from English, auto-executes, summarises results | `llm_evidence.json` |

---

## MongoDB Schema

Denormalized document-per-question — answers and tags embedded inside each question:

```json
{
  "_id": 80,
  "title": "How do I sort a list in Python?",
  "score": 42,
  "creation_date": "2008-09-16T00:00:00",
  "is_closed": false,
  "owner_user_id": 26,
  "tags": ["python", "list", "sorting"],
  "answer_count": 3,
  "top_answer_score": 38,
  "answers": [
    {
      "answer_id": 123,
      "owner_user_id": 456,
      "score": 38,
      "creation_date": "2008-09-16T01:00:00"
    }
  ]
}
```

**Indexes:** tags, creation_date, owner_user_id, score, is_closed

---

## Neo4j Graph Model

```
(User)-[:ASKED]->(Question)
(User)-[:ANSWERED]->(Question)
(User)-[:PROVIDED]->(Answer)
(Answer)-[:ANSWERS]->(Question)
(Question)-[:TAGGED]->(Tag)
(Tag)-[:CO_OCCURS_WITH {weight}]-(Tag)
```

**Scale:** 20,000 questions loaded (Aura Free limit: 400,000 relationships)

---

## MongoDB Aggregation Pipelines

| # | Pipeline | Key Finding |
|---|----------|-------------|
| P1 | Top 20 most-used tags | c# leads with 6,370 questions |
| P2 | Avg score per tag (≥200 Qs) | Niche tags score higher on average |
| P3 | Questions per year trend | Peak volume in 2009 |
| P4 | Most active users by questions | Power-law distribution |
| P5 | Tags with highest answer rates | >95% for popular tags |
| P6 | Score distribution ($bucket) | 80% score between 0–5 |
| P7 | Closed vs open ratio by tag | Some tags have >10% closure rate |
| P8 | Top answerers by total score | Top user: 11,800+ points |

---

## Neo4j Cypher Queries

| # | Query | Key Finding |
|---|-------|-------------|
| Q1 | Most connected users | User 22656: 403 interactions |
| Q2 | Tag co-occurrence pairs | c#/.net: 740 shared questions |
| Q3 | Top experts per tag | User 22656: 3,825 pts in c# |
| Q4 | Shortest path between users | Users connected in 6 hops |

---

## Docker Microservices

7 independent services each with a single responsibility:

| Service | Role | Depends On |
|---------|------|-----------|
| `redis` | Infrastructure — persistent cache | — |
| `mongo-loader` | ETL — loads MongoDB Atlas | redis (healthy) |
| `neo4j-loader` | ETL — loads Neo4j Aura | redis (healthy) |
| `mongo-analytics` | Analytics — 8 pipelines | redis (healthy) |
| `neo4j-analytics` | Analytics — 6 queries | redis (healthy) |
| `redis-cache` | Bonus — caching demo | redis (healthy) |
| `llm-pipeline` | Bonus — Groq pipeline | redis (healthy) |

All services share the same Docker image and communicate over `so_analytics_network`.

---

## Key Findings

**MongoDB revealed:** c# is the most popular tag (6,370 questions). Question volume peaked in 2009. Top askers and top answerers are almost entirely different users — contributors specialise.

**Neo4j revealed:** c# is the gravitational hub of the Microsoft ecosystem — .net, asp.net, linq, winforms, xml, and vb.net all orbit around it with strong co-occurrence weights. Any two users are connected within 6 hops.

**The key insight:** MongoDB told us *what* is popular. Neo4j told us *why* — structural relationships invisible to documents.

---

## MongoDB vs Neo4j — Top 5 Observations

| # | Dimension | MongoDB | Neo4j |
|---|-----------|---------|-------|
| 1 | Free-tier scale | 50k docs / 165 MB | Hits 400k rel limit at 25k Qs |
| 2 | Relationship queries | $lookup: verbose | 2-line Cypher: intuitive |
| 3 | Bulk aggregation | Sub-second on 50k docs | Slower for counting/grouping |
| 4 | Structural insight | Tag trends visible | Ecosystem hub structure revealed |
| 5 | Query language | JSON pipeline: powerful but verbose | Cypher: declarative, readable |

---

## Technical Difficulties Solved

| Problem | Fix |
|---------|-----|
| Neo4j session timeout (60s idle limit on Aura) | Fresh session per batch in `run_batched()` |
| Aura 400k relationship limit | Pre-flight estimation + reduced to 20k questions |
| httpx/groq version conflict in Docker | Pinned `httpx==0.27.2` in requirements.txt |
| zsh glob expansion (`pymongo[srv]`) | Quoted: `pip install "pymongo[srv]"` |
| Docker volume permission on Desktop path | Moved project or added Desktop to Docker file sharing |

---

## References

- Dataset: https://www.kaggle.com/datasets/stackoverflow/stacksample
- MongoDB Atlas: https://cloud.mongodb.com
- MongoDB Charts: https://www.mongodb.com/docs/charts/
- Neo4j Aura: https://console.neo4j.io
- Neo4j Cypher Manual: https://neo4j.com/docs/cypher-manual/current/
- Groq API: https://console.groq.com
- Redis Commands: https://redis.io/commands/
- Docker Compose: https://docs.docker.com/compose/
