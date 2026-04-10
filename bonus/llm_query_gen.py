
import os
import json
from dotenv import load_dotenv
from groq import Groq
from pymongo import MongoClient
from neo4j import GraphDatabase

load_dotenv()

# clients
groq_client  = Groq(api_key=os.getenv("GROQ_API_KEY"))
mongo_client = MongoClient(os.getenv("MONGO_URI"))
mongo_col    = mongo_client[os.getenv("MONGO_DB", "stackoverflow")]["questions"]
neo4j_driver = GraphDatabase.driver(
    os.getenv("NEO4J_URI"),
    auth=(os.getenv("NEO4J_USER", "neo4j"), os.getenv("NEO4J_PASSWORD"))
)

MODEL    = "llama-3.3-70b-versatile"   
EVIDENCE = []
SEP      = "─" * 60


# system prompts

CYPHER_SYSTEM = """You are a Neo4j Cypher expert.

Graph schema:
  Nodes        : User {id}
               | Question {id, title, score, creation_date, is_closed}
               | Answer   {id, score, creation_date}
               | Tag      {name}
  Relationships: (User)-[:ASKED]->(Question)
                 (User)-[:ANSWERED]->(Question)
                 (User)-[:PROVIDED]->(Answer)
                 (Answer)-[:ANSWERS]->(Question)
                 (Question)-[:TAGGED]->(Tag)
                 (Tag)-[:CO_OCCURS_WITH {weight}]-(Tag)

Rules:
- Return ONLY the Cypher query, no explanation, no markdown fences.
- Always end with LIMIT 10 unless the question specifies otherwise.
- Use elementId() instead of id() for node comparison."""

MONGO_SYSTEM = """You are a MongoDB aggregation expert.

Collection: stackoverflow.questions
Document shape:
{
  _id, title, body, score, creation_date, closed_date, is_closed,
  owner_user_id, tags: [str], answer_count, top_answer_score,
  answers: [{ answer_id, owner_user_id, score, creation_date }]
}

Rules:
- Return ONLY a valid Python list for an aggregation pipeline.
- No explanation, no markdown fences, no variable assignment.
- Always include a $limit of 10 at the end."""

INSIGHT_SYSTEM = """You are a data analyst summarising query results 
from a Stack Overflow dataset (2008-2016).
Given a question and its results, write 2-3 sentences of plain-English insight.
Be specific — mention actual values from the results.
No bullet points, no headers, just concise prose."""

COMMUNITY_SYSTEM = """You are a technology analyst.
Given a list of programming tags from the same graph community,
return ONLY valid JSON: {"name": "...", "description": "..."}
name: 3-6 words. description: one sentence. No markdown."""


# ── Groq helper

def ask_groq(system, user, label):
    print(f"\n{SEP}\n  {label}\n{SEP}")
    print(f"  Q: {user[:100]}")

    response = groq_client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system",  "content": system},
            {"role": "user",    "content": user},
        ],
        temperature=0.1,
        max_tokens=512,
    )
    answer = response.choices[0].message.content.strip()
    tokens_in  = response.usage.prompt_tokens
    tokens_out = response.usage.completion_tokens

    EVIDENCE.append({
        "label":         label,
        "system_prompt": system,
        "user_prompt":   user,
        "response":      answer,
        "model":         MODEL,
        "input_tokens":  tokens_in,
        "output_tokens": tokens_out,
    })
    return answer


# execution helpers

def run_cypher(cypher):
    """Execute Cypher against Neo4j, return list of dicts."""
    try:
        with neo4j_driver.session() as s:
            result = s.run(cypher)
            return [dict(r) for r in result]
    except Exception as e:
        return [{"error": str(e)}]


def run_mongo(pipeline_str):
    """Parse pipeline string and execute against MongoDB, return list of dicts."""
    try:
        pipeline = eval(pipeline_str)   # safe — LLM output is a list literal
        return list(mongo_col.aggregate(pipeline, allowDiskUse=True))
    except Exception as e:
        return [{"error": str(e)}]


def fmt_results(rows, max_rows=5):
    """Format result rows for feeding back to LLM."""
    if not rows:
        return "No results returned."
    preview = rows[:max_rows]
    lines   = [str(r) for r in preview]
    if len(rows) > max_rows:
        lines.append(f"... ({len(rows) - max_rows} more rows)")
    return "\n".join(lines)


# pipeline: question → query → execute → insight

def cypher_pipeline(question, label):
    """Full pipeline for a Neo4j question."""
    # Step 1: generate Cypher
    cypher = ask_groq(CYPHER_SYSTEM, question, f"{label} — Generate Cypher")
    print(f"\n  Generated Cypher:\n  {cypher[:200]}")

    # Step 2: execute
    rows = run_cypher(cypher)
    print(f"  Executed → {len(rows)} rows")

    # Step 3: generate insight
    insight_prompt = (
        f"Question: {question}\n\n"
        f"Query results:\n{fmt_results(rows)}"
    )
    insight = ask_groq(INSIGHT_SYSTEM, insight_prompt, f"{label} — Insight")
    print(f"\n  Insight: {insight[:200]}")

    return {
        "label":    label,
        "question": question,
        "query":    cypher,
        "db":       "neo4j",
        "results":  rows[:10],
        "insight":  insight,
    }


def mongo_pipeline(question, label):
    """Full pipeline for a MongoDB question."""
    # Step 1: generate pipeline
    pipeline_str = ask_groq(MONGO_SYSTEM, question, f"{label} — Generate Pipeline")
    print(f"\n  Generated Pipeline:\n  {pipeline_str[:200]}")

    # Step 2: execute
    rows = run_mongo(pipeline_str)
    print(f"  Executed → {len(rows)} rows")

    # Step 3: generate insight
    insight_prompt = (
        f"Question: {question}\n\n"
        f"Query results:\n{fmt_results(rows)}"
    )
    insight = ask_groq(INSIGHT_SYSTEM, insight_prompt, f"{label} — Insight")
    print(f"\n  Insight: {insight[:200]}")

    return {
        "label":    label,
        "question": question,
        "query":    pipeline_str,
        "db":       "mongodb",
        "results":  [str(r) for r in rows[:10]],
        "insight":  insight,
    }


def name_communities(communities):
    """Name each Louvain community using Groq."""
    named = []
    for i, tags in enumerate(communities, 1):
        raw = ask_groq(
            COMMUNITY_SYSTEM,
            f"Tags: {', '.join(tags)}",
            f"Community Naming #{i}",
        )
        try:
            parsed = json.loads(raw)
        except Exception:
            parsed = {"name": "Unknown", "description": raw}
        named.append({
            "community_id":    i,
            "tags":            tags,
            "llm_name":        parsed.get("name"),
            "llm_description": parsed.get("description"),
        })
        print(f"  Community #{i}: {parsed.get('name')}")
    return named


# main

def main():

    print("so_analytics — Groq End-to-End LLM Pipeline")
    print(f"  Model : {MODEL}")
    print(f"  Tasks : 3 Cypher  |  2 MongoDB  |  6 community names")

    results = []

    # Cypher pipelines
    cypher_questions = [
        ("Find all users who answered Python questions within 10 minutes "
         "of them being posted. Return user_id and count of such fast answers.",
         "Cypher #1 — Fast Python Answerers"),

        ("Find the top 10 tags that appear most frequently alongside "
         "the 'javascript' tag, ordered by co-occurrence weight.",
         "Cypher #2 — JavaScript Tag Neighbourhood"),

        ("Find users who answered questions tagged with both 'python' and 'java'. "
         "Return user_id, python answer count, java answer count.",
         "Cypher #3 — Python–Java Bridge Users"),
    ]
    for question, label in cypher_questions:
        results.append(cypher_pipeline(question, label))

    # MongoDB pipelines
    mongo_questions = [
        ("Find the top 10 tags where questions have the highest average score. "
         "Only include tags with at least 100 questions.",
         "MongoDB #1 — Highest Scoring Tags"),

        ("For each year, return the total questions asked and the percentage "
         "that were closed.",
         "MongoDB #2 — Annual Closure Rate"),
    ]
    for question, label in mongo_questions:
        results.append(mongo_pipeline(question, label))

    # Community naming
    print(f"\n{SEP}\n  Community Naming (Louvain clusters)\n{SEP}")
    sample_communities = [
        ["javascript", "jquery", "html", "css", "angular", "react", "node.js", "typescript"],
        ["python", "pandas", "numpy", "matplotlib", "scikit-learn", "django", "flask"],
        ["java", "spring", "maven", "hibernate", "android", "gradle"],
        ["sql", "mysql", "postgresql", "database", "sqlite", "oracle"],
        ["c#", ".net", "asp.net", "wpf", "entity-framework", "linq"],
        ["aws", "docker", "kubernetes", "linux", "bash", "terraform"],
    ]
    community_names = name_communities(sample_communities)

    # Save evidence
    output = {
        "model":             MODEL,
        "pipeline_results":  results,
        "community_names":   community_names,
        "raw_evidence":      EVIDENCE,
        "stats": {
            "total_api_calls":    len(EVIDENCE),
            "total_input_tokens": sum(e["input_tokens"]  for e in EVIDENCE),
            "total_output_tokens":sum(e["output_tokens"] for e in EVIDENCE),
        },
    }

    out_path = "llm_evidence.json"
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2, default=str)

    #  Summary 
    print(f"\n{'='*60}")
    print(f" Pipeline complete.  Results → {out_path}")
    print(f"{'='*60}")
    print(f"  API calls      : {output['stats']['total_api_calls']}")
    print(f"  Input tokens   : {output['stats']['total_input_tokens']:,}")
    print(f"  Output tokens  : {output['stats']['total_output_tokens']:,}")
    print(f"\n  Pipelines run  : {len(results)} (queries generated + executed + summarised)")
    print(f"  Communities    : {len(community_names)} named")

    neo4j_driver.close()
    mongo_client.close()


if __name__ == "__main__":
    main()