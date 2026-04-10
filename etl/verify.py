import os
import sys
from dotenv import load_dotenv
from pymongo import MongoClient
from neo4j import GraphDatabase

load_dotenv()

MONGO_URI  = os.getenv("MONGO_URI")
MONGO_DB   = os.getenv("MONGO_DB",       "stackoverflow")
NEO4J_URI  = os.getenv("NEO4J_URI")
NEO4J_USER = os.getenv("NEO4J_USER",     "neo4j")
NEO4J_PASS = os.getenv("NEO4J_PASSWORD")

SEP = "─" * 52


def verify_mongodb():
    print(f"\n{'='*52}")
    print("  MongoDB Atlas — Verification")
    print(f"{'='*52}")

    if not MONGO_URI:
        print("  [SKIP] MONGO_URI not set"); return

    client = MongoClient(MONGO_URI)
    db     = client[MONGO_DB]
    col    = db["questions"]

    total      = col.count_documents({})
    closed     = col.count_documents({"is_closed": True})
    has_answers= col.count_documents({"answer_count": {"$gt": 0}})
    sample     = col.find_one({}, {"_id": 1, "title": 1, "tags": 1, "answer_count": 1})

    print(f"  Total documents     : {total:>8,}")
    print(f"  Closed questions    : {closed:>8,}  ({closed/max(total,1)*100:.1f}%)")
    print(f"  With ≥1 answer      : {has_answers:>8,}  ({has_answers/max(total,1)*100:.1f}%)")
    print(f"\n  Sample document:")
    print(f"    _id          : {sample['_id']}")
    print(f"    title        : {sample['title'][:60]}")
    print(f"    tags         : {sample['tags']}")
    print(f"    answer_count : {sample['answer_count']}")

    # index check
    indexes = [idx["name"] for idx in col.list_indexes()]
    print(f"\n  Indexes ({len(indexes)}) : {indexes}")

    client.close()


def verify_neo4j():
    print(f"\n{'='*52}")
    print("  Neo4j Aura — Verification")
    print(f"{'='*52}")

    if not NEO4J_URI or not NEO4J_PASS:
        print("  [SKIP] NEO4J_URI or NEO4J_PASSWORD not set"); return

    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASS))

    node_labels = ["User", "Question", "Answer", "Tag"]
    rel_types   = ["ASKED", "ANSWERED", "PROVIDED", "ANSWERS", "TAGGED", "CO_OCCURS_WITH"]

    with driver.session() as s:
        print("\n  Node counts:")
        for label in node_labels:
            count = s.run(f"MATCH (n:{label}) RETURN count(n) AS c").single()["c"]
            print(f"    {label:<12}: {count:>8,}")

        print("\n  Relationship counts:")
        for rel in rel_types:
            count = s.run(f"MATCH ()-[r:{rel}]->() RETURN count(r) AS c").single()["c"]
            print(f"    {rel:<20}: {count:>8,}")

        # Sample node
        sample = s.run(
            "MATCH (q:Question) RETURN q.id AS id, q.title AS title, q.score AS score LIMIT 1"
        ).single()
        if sample:
            print(f"\n  Sample Question node:")
            print(f"    id    : {sample['id']}")
            print(f"    title : {str(sample['title'])[:60]}")
            print(f"    score : {sample['score']}")

    driver.close()


if __name__ == "__main__":
    verify_mongodb()
    verify_neo4j()
    print(f"\n{'='*52}")
    print("Verification complete.")
    print(f"{'='*52}")
