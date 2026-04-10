import os
import sys
import pandas as pd
from datetime import datetime
from dotenv import load_dotenv
from pymongo import MongoClient, UpdateOne, ASCENDING
from tqdm import tqdm

# load env variables
load_dotenv()
MONGO_URI  = os.getenv("MONGO_URI")
MONGO_DB   = os.getenv("MONGO_DB",        "stackoverflow")
DATA_DIR   = os.getenv("DATA_DIR",        "./data/stacksample")
LIMIT      = int(os.getenv("QUESTION_LIMIT", 50_000))
BATCH_SIZE = 500

# helper functions

def parse_date(val):
    if pd.isna(val):
        return None
    try:
        return datetime.fromisoformat(str(val).rstrip("Z"))
    except Exception:
        return None


def chunked(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i : i + n]


# reading CSVs 

def read_csvs():
    print(f"[MongoDB ETL] Reading CSVs from {DATA_DIR}  (limit={LIMIT:,}) …")

    questions = pd.read_csv(
        os.path.join(DATA_DIR, "Questions.csv"),
        encoding="latin-1",
        nrows=LIMIT,
        usecols=["Id", "OwnerUserId", "CreationDate", "ClosedDate", "Score", "Title", "Body"],
    )

    answers = pd.read_csv(
        os.path.join(DATA_DIR, "Answers.csv"),
        encoding="latin-1",
        usecols=["Id", "OwnerUserId", "CreationDate", "ParentId", "Score", "Body"],
    )
    # keeping only answers belonging to our 50 k questions
    answers = answers[answers["ParentId"].isin(questions["Id"].values)]

    tags = pd.read_csv(
        os.path.join(DATA_DIR, "Tags.csv"),
        encoding="latin-1",
        usecols=["Id", "Tag"],
    )
    tags = tags[tags["Id"].isin(questions["Id"].values)]

    print(f"  Questions : {len(questions):>8,}")
    print(f"  Answers   : {len(answers):>8,}")
    print(f"  Tag rows  : {len(tags):>8,}")
    return questions, answers, tags


#  building documents

def build_docs(questions, answers, tags):
    print("[MongoDB ETL] Building documents …")

    ans_grp = answers.groupby("ParentId")
    tag_grp = tags.groupby("Id")
    docs    = []

    for _, row in tqdm(questions.iterrows(), total=len(questions), desc="  Building"):
        qid = int(row["Id"])

        # embedded answers (sorted best-first)
        embedded_answers = []
        if qid in ans_grp.groups:
            for _, ar in ans_grp.get_group(qid).iterrows():
                embedded_answers.append({
                    "answer_id"     : int(ar["Id"]),
                    "owner_user_id" : None if pd.isna(ar["OwnerUserId"]) else int(ar["OwnerUserId"]),
                    "score"         : int(ar["Score"]),
                    "creation_date" : parse_date(ar["CreationDate"]),
                    "body"          : str(ar["Body"])[:500],
                })
        embedded_answers.sort(key=lambda x: x["score"], reverse=True)

        # tags list
        question_tags = []
        if qid in tag_grp.groups:
            question_tags = tag_grp.get_group(qid)["Tag"].tolist()

        closed_date = parse_date(row["ClosedDate"])
        docs.append({
            "_id"             : qid,
            "title"           : str(row["Title"]),
            "body"            : str(row["Body"])[:500],
            "score"           : int(row["Score"]),
            "creation_date"   : parse_date(row["CreationDate"]),
            "closed_date"     : closed_date,
            "is_closed"       : closed_date is not None,
            "owner_user_id"   : None if pd.isna(row["OwnerUserId"]) else int(row["OwnerUserId"]),
            "tags"            : question_tags,
            "answer_count"    : len(embedded_answers),
            "top_answer_score": embedded_answers[0]["score"] if embedded_answers else None,
            "answers"         : embedded_answers,
        })

    return docs


# inserting into Atlas

def insert_docs(docs):
    if not MONGO_URI:
        sys.exit("[MongoDB ETL] ERROR: MONGO_URI not set in .env")

    print(f"\n[MongoDB ETL] Connecting to Atlas …")
    client = MongoClient(MONGO_URI)
    col    = client[MONGO_DB]["questions"]

    # indexes (we create indexes before inserting data to speed up upserts)
    col.create_index([("tags",           ASCENDING)])
    col.create_index([("creation_date",  ASCENDING)])
    col.create_index([("owner_user_id",  ASCENDING)])
    col.create_index([("score",          ASCENDING)])
    col.create_index([("is_closed",      ASCENDING)])
    print("  Indexes ensured.")

    # batch upsert
    upserted = modified = 0
    for batch in tqdm(list(chunked(docs, BATCH_SIZE)), desc="  Inserting"):
        ops    = [UpdateOne({"_id": d["_id"]}, {"$set": d}, upsert=True) for d in batch]
        result = col.bulk_write(ops, ordered=False)
        upserted += result.upserted_count
        modified += result.modified_count

    total = client[MONGO_DB]["questions"].count_documents({})
    print(f"\n[MongoDB ETL] Done.")
    print(f"  Upserted : {upserted:,}")
    print(f"  Modified : {modified:,}")
    print(f"  Total docs in collection : {total:,}")
    client.close()


#  main execution

if __name__ == "__main__":
    questions, answers, tags = read_csvs()
    docs = build_docs(questions, answers, tags)
    insert_docs(docs)
    print("\nMongoDB load complete.")