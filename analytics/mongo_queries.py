import os
import json
from datetime import datetime
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv()

MONGO_URI = os.getenv("MONGO_URI")
MONGO_DB  = os.getenv("MONGO_DB", "stackoverflow")
SEP       = "=" * 60


def run_pipeline(col, title, pipeline):
    """Execute a pipeline, print results, return result list."""
    print(f"\n{SEP}\n  {title}\n{SEP}")
    results = list(col.aggregate(pipeline, allowDiskUse=True))
    for r in results[:15]:
        print(r)
    print(f"  → {len(results)} rows")
    return results


def safe_for_json(obj):
    """Make a result list JSON-serialisable (handle datetime)."""
    out = []
    for row in obj:
        safe_row = {}
        for k, v in row.items():
            safe_row[k] = v.isoformat() if isinstance(v, datetime) else v
        out.append(safe_row)
    return out


def main():
    client  = MongoClient(MONGO_URI)
    col     = client[MONGO_DB]["questions"]
    summary = []

    #  P1: Top 20 most-used tags
    results = run_pipeline(col, "P1 · Top 20 Most-Used Tags", [
        {"$unwind": "$tags"},
        {"$group":  {"_id": "$tags", "question_count": {"$sum": 1}}},
        {"$sort":   {"question_count": -1}},
        {"$limit":  20},
        {"$project":{"_id": 0, "tag": "$_id", "question_count": 1}},
    ])
    summary.append({"pipeline": "P1 - Top 20 Tags", "results": safe_for_json(results)})

    #  P2: Average score per tag (≥ 200 questions) 
    results = run_pipeline(col, "P2 · Average Question Score per Tag  (≥200 questions)", [
        {"$unwind": "$tags"},
        {"$group":  {
            "_id":            "$tags",
            "avg_score":      {"$avg": "$score"},
            "total_questions":{"$sum": 1},
        }},
        {"$match":  {"total_questions": {"$gte": 200}}},
        {"$sort":   {"avg_score": -1}},
        {"$limit":  20},
        {"$project":{
            "_id": 0, "tag": "$_id",
            "avg_score":       {"$round": ["$avg_score", 2]},
            "total_questions": 1,
        }},
    ])
    summary.append({"pipeline": "P2 - Avg Score per Tag", "results": safe_for_json(results)})

    #  P3: Questions per year (trend)
    results = run_pipeline(col, "P3 · Questions Asked per Year  (2008 – 2016 trend)", [
        {"$match":  {"creation_date": {"$ne": None}}},
        {"$group":  {
            "_id":      {"$year": "$creation_date"},
            "count":    {"$sum": 1},
            "avg_score":{"$avg": "$score"},
        }},
        {"$sort":   {"_id": 1}},
        {"$project":{
            "_id": 0, "year": "$_id",
            "count":     1,
            "avg_score": {"$round": ["$avg_score", 2]},
        }},
    ])
    summary.append({"pipeline": "P3 - Questions per Year", "results": safe_for_json(results)})

    # P4: Most active users by questions asked
    results = run_pipeline(col, "P4 · Most Active Users by Questions Asked", [
        {"$match":  {"owner_user_id": {"$ne": None}}},
        {"$group":  {
            "_id":           "$owner_user_id",
            "questions_asked": {"$sum": 1},
            "total_score":   {"$sum": "$score"},
            "avg_score":     {"$avg": "$score"},
        }},
        {"$sort":   {"questions_asked": -1}},
        {"$limit":  20},
        {"$project":{
            "_id": 0, "user_id": "$_id",
            "questions_asked": 1,
            "total_score":     1,
            "avg_score":       {"$round": ["$avg_score", 2]},
        }},
    ])
    summary.append({"pipeline": "P4 - Most Active Askers", "results": safe_for_json(results)})

    #  P5: Tags with highest answer rates
    results = run_pipeline(col, "P5 · Tags with Highest Answer Rates  (≥200 questions)", [
        {"$unwind": "$tags"},
        {"$group":  {
            "_id":        "$tags",
            "total":      {"$sum": 1},
            "has_answers":{"$sum": {"$cond": [{"$gt": ["$answer_count", 0]}, 1, 0]}},
        }},
        {"$match":  {"total": {"$gte": 200}}},
        {"$project":{
            "_id": 0, "tag": "$_id", "total": 1,
            "answer_rate_pct": {
                "$round": [{"$multiply": [{"$divide": ["$has_answers", "$total"]}, 100]}, 1]
            },
        }},
        {"$sort":   {"answer_rate_pct": -1}},
        {"$limit":  20},
    ])
    summary.append({"pipeline": "P5 - Answer Rates by Tag", "results": safe_for_json(results)})

    #  P6: Score distribution via $bucket 
    results = run_pipeline(col, "P6 · Question Score Distribution  ($bucket)", [
        {"$bucket": {
            "groupBy":    "$score",
            "boundaries": [-100, 0, 1, 5, 10, 25, 50, 100, 500, 10_000],
            "default":    "extreme",
            "output": {
                "count":       {"$sum": 1},
                "avg_answers": {"$avg": "$answer_count"},
            },
        }},
    ])
    summary.append({"pipeline": "P6 - Score Distribution", "results": safe_for_json(results)})

    #  P7: Closed vs open ratio by tag 
    results = run_pipeline(col, "P7 · Closed vs Open Question Ratio by Tag  (≥300 questions)", [
        {"$unwind": "$tags"},
        {"$group":  {
            "_id":    "$tags",
            "total":  {"$sum": 1},
            "closed": {"$sum": {"$cond": ["$is_closed", 1, 0]}},
        }},
        {"$match":  {"total": {"$gte": 300}}},
        {"$project":{
            "_id": 0, "tag": "$_id", "total": 1, "closed": 1,
            "closed_pct": {
                "$round": [{"$multiply": [{"$divide": ["$closed", "$total"]}, 100]}, 1]
            },
        }},
        {"$sort":   {"closed_pct": -1}},
        {"$limit":  20},
    ])
    summary.append({"pipeline": "P7 - Closed Ratio by Tag", "results": safe_for_json(results)})

    # P8: Top answerers by total answer score
    results = run_pipeline(col, "P8 · Top Answerers by Total Answer Score", [
        {"$unwind": "$answers"},
        {"$match":  {"answers.owner_user_id": {"$ne": None}}},
        {"$group":  {
            "_id":             "$answers.owner_user_id",
            "total_ans_score": {"$sum": "$answers.score"},
            "answers_given":   {"$sum": 1},
            "avg_ans_score":   {"$avg": "$answers.score"},
        }},
        {"$sort":   {"total_ans_score": -1}},
        {"$limit":  20},
        {"$project":{
            "_id": 0, "user_id": "$_id",
            "total_ans_score": 1,
            "answers_given":   1,
            "avg_ans_score":   {"$round": ["$avg_ans_score", 2]},
        }},
    ])
    summary.append({"pipeline": "P8 - Top Answerers", "results": safe_for_json(results)})

    # save 
    out_path = "mongo_results.json"
    with open(out_path, "w") as f:
        json.dump(summary, f, indent=2, default=str)

    print(f"\n{'='*60}")
    print(f"✅  All pipelines complete.  Results → {out_path}")
    print(f"{'='*60}")
    client.close()


if __name__ == "__main__":
    main()
