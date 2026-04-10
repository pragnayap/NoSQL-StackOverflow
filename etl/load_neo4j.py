import os
import sys
import pandas as pd
from dotenv import load_dotenv
from neo4j import GraphDatabase
from tqdm import tqdm

# config
load_dotenv()
NEO4J_URI  = os.getenv("NEO4J_URI")
NEO4J_USER = os.getenv("NEO4J_USER",     "neo4j")
NEO4J_PASS = os.getenv("NEO4J_PASSWORD")
DATA_DIR   = os.getenv("DATA_DIR",       "./data/stacksample")
NEO4J_QUESTION_LIMIT = 20_000
BATCH_SIZE           = 500

# helpers

def chunked(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i : i + n]


def run_batched(driver, cypher, rows, desc):
    #Opens a fresh session per batch — prevents Aura connection timeouts
    for batch in tqdm(list(chunked(rows, BATCH_SIZE)), desc=f"  {desc}"):
        with driver.session() as s:
            s.run(cypher, rows=batch)


# cleanup — wipe database before each run

def cleanup(session):
    total_deleted = 0
    while True:
        result = session.run("""
            MATCH (n)
            WITH n LIMIT 10000
            DETACH DELETE n
            RETURN count(n) AS deleted
        """)
        deleted = result.single()["deleted"]
        total_deleted += deleted
        if deleted == 0:
            break
    print(f"  Cleanup: {total_deleted:,} nodes removed.")


# read CSVs

def read_csvs():
    print(f"[Neo4j ETL] Reading CSVs (limit={NEO4J_QUESTION_LIMIT:,}) …")
    questions = pd.read_csv(
        os.path.join(DATA_DIR, "Questions.csv"),
        encoding="latin-1",
        nrows=NEO4J_QUESTION_LIMIT,
        usecols=["Id", "OwnerUserId", "CreationDate", "ClosedDate", "Score", "Title"],
    )

    answers = pd.read_csv(
        os.path.join(DATA_DIR, "Answers.csv"),
        encoding="latin-1",
        usecols=["Id", "OwnerUserId", "CreationDate", "ParentId", "Score"],
    )
    answers = answers[answers["ParentId"].isin(questions["Id"].values)]

    tags = pd.read_csv(
        os.path.join(DATA_DIR, "Tags.csv"),
        encoding="latin-1",
        usecols=["Id", "Tag"],
    )
    tags = tags[tags["Id"].isin(questions["Id"].values)]

    # Estimate relationships before loading
    est_asked    = int(questions["OwnerUserId"].notna().sum())
    est_answered = int(answers["OwnerUserId"].notna().sum())
    est_provided = est_answered
    est_answers  = len(answers)
    est_tagged   = len(tags)
    est_cooccur  = tags["Tag"].nunique() * 2
    est_total    = est_asked + est_answered + est_provided + est_answers + est_tagged + est_cooccur

    if est_total > 380_000:
        sys.exit(f"  ERROR: ~{est_total:,} relationships would exceed Aura Free limit. Reduce NEO4J_QUESTION_LIMIT.")

    return questions, answers, tags


# Cypher templates

CONSTRAINTS = [
    "CREATE CONSTRAINT user_id_unique     IF NOT EXISTS FOR (u:User)     REQUIRE u.id IS UNIQUE",
    "CREATE CONSTRAINT question_id_unique IF NOT EXISTS FOR (q:Question) REQUIRE q.id IS UNIQUE",
    "CREATE CONSTRAINT answer_id_unique   IF NOT EXISTS FOR (a:Answer)   REQUIRE a.id IS UNIQUE",
    "CREATE CONSTRAINT tag_name_unique    IF NOT EXISTS FOR (t:Tag)       REQUIRE t.name IS UNIQUE",
]

LOAD_QUESTIONS = """
UNWIND $rows AS r
MERGE (q:Question {id: r.qid})
SET   q.title         = r.title,
      q.score         = r.score,
      q.creation_date = r.creation_date,
      q.is_closed     = r.is_closed
WITH  q, r
WHERE r.owner_id IS NOT NULL
MERGE (u:User {id: r.owner_id})
MERGE (u)-[:ASKED]->(q)
"""

LOAD_TAGS = """
UNWIND $rows AS r
MATCH  (q:Question {id: r.qid})
MERGE  (t:Tag {name: r.tag})
MERGE  (q)-[:TAGGED]->(t)
"""

LOAD_ANSWERS = """
UNWIND $rows AS r
MERGE  (a:Answer {id: r.aid})
SET    a.score         = r.score,
       a.creation_date = r.creation_date
WITH   a, r
MATCH  (q:Question {id: r.qid})
MERGE  (a)-[:ANSWERS]->(q)
WITH   a, q, r
WHERE  r.owner_id IS NOT NULL
MERGE  (u:User {id: r.owner_id})
MERGE  (u)-[:ANSWERED]->(q)
MERGE  (u)-[:PROVIDED]->(a)
"""

BUILD_COOCCURRENCE = """
MATCH (t1:Tag)<-[:TAGGED]-(q:Question)-[:TAGGED]->(t2:Tag)
WHERE elementId(t1) < elementId(t2)
WITH  t1, t2, count(q) AS w
WHERE w >= 5
MERGE (t1)-[r:CO_OCCURS_WITH]-(t2)
SET   r.weight = w
"""


# load graph

def load_graph(questions, answers, tags):
    if not NEO4J_URI or not NEO4J_PASS:
        sys.exit("[Neo4j ETL] ERROR: NEO4J_URI or NEO4J_PASSWORD not set in .env")

    print(f"\n[Neo4j ETL] Connecting to Aura …")
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASS))
    print(f"[Neo4j ETL] Connected. Loading {NEO4J_QUESTION_LIMIT:,} questions …")

    # wipe existing data first
    with driver.session() as s:
        cleanup(s)

    # constraints
    with driver.session() as s:
        for cq in CONSTRAINTS:
            try:
                s.run(cq)
            except Exception:
                pass

    # questions + ASKED edges
    q_rows = [
        {
            "qid"          : int(r["Id"]),
            "title"        : str(r["Title"]),
            "score"        : int(r["Score"]),
            "creation_date": str(r["CreationDate"]),
            "is_closed"    : not pd.isna(r["ClosedDate"]),
            "owner_id"     : None if pd.isna(r["OwnerUserId"])
                                  else int(r["OwnerUserId"]),
        }
        for _, r in questions.iterrows()
    ]
    run_batched(driver, LOAD_QUESTIONS, q_rows, "Questions + Users")

    # tags + TAGGED edges
    t_rows = [
        {"qid": int(r["Id"]), "tag": r["Tag"]}
        for _, r in tags.iterrows()
    ]
    run_batched(driver, LOAD_TAGS, t_rows, "Tags          ")

    # answers + ANSWERED / PROVIDED / ANSWERS edges
    a_rows = [
        {
            "aid"          : int(r["Id"]),
            "qid"          : int(r["ParentId"]),
            "score"        : int(r["Score"]),
            "creation_date": str(r["CreationDate"]),
            "owner_id"     : None if pd.isna(r["OwnerUserId"])
                                  else int(r["OwnerUserId"]),
        }
        for _, r in answers.iterrows()
    ]
    run_batched(driver, LOAD_ANSWERS, a_rows, "Answers       ")

    # tag co-occurrence edges
    with driver.session() as s:
        s.run(BUILD_COOCCURRENCE)

    #  final counts
    with driver.session() as s:
        counts = {
            label: s.run(f"MATCH (n:{label}) RETURN count(n) AS c").single()["c"]
            for label in ["User", "Question", "Answer", "Tag"]
        }
        rel_count = s.run("MATCH ()-[r]->() RETURN count(r) AS c").single()["c"]

    print(f"\n  Nodes  : {sum(counts.values()):,}  "
          f"(Users {counts['User']:,} · Questions {counts['Question']:,} · "
          f"Answers {counts['Answer']:,} · Tags {counts['Tag']:,})")
    print(f"  Rels   : {rel_count:,} / 400,000 limit")
    driver.close()
    print(" Neo4j load complete.")


#  main

if __name__ == "__main__":
    questions, answers, tags = read_csvs()
    load_graph(questions, answers, tags)