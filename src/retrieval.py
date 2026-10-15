"""Local dense retrieval over context notes using bge-small-en-v1.5 + ChromaDB.

This module is for observability / trace only; it does NOT decide verdicts.
"""

import json
import sys
from pathlib import Path

import chromadb
import pandas as pd
from chromadb.config import Settings
from sentence_transformers import SentenceTransformer

if __name__ == "__main__" and __package__ is None:
    sys.path.insert(0, str(Path(__file__).parent.parent))

from src.baselines import add_baselines
from src.flagging import find_candidates, load_params
from src.load import load_shipments
from src.notes import load_notes_registry
from src.weekly import build_weekly_costs


INDEX_PATH = Path(__file__).parent.parent / "data" / "chroma_index"
OUTPUT_PATH = Path(__file__).parent.parent / "outputs" / "retrieval_trace.jsonl"
MODEL_NAME = "BAAI/bge-small-en-v1.5"
COLLECTION_NAME = "notes"


def get_model() -> SentenceTransformer:
    """Load the local embedding model (downloads on first use)."""
    return SentenceTransformer(MODEL_NAME)


def get_client(path: Path | str | None = None) -> chromadb.PersistentClient:
    """Return a persisted Chroma client."""
    if path is None:
        path = INDEX_PATH
    return chromadb.PersistentClient(
        path=str(path),
        settings=Settings(anonymized_telemetry=False),
    )


def build_index(
    model: SentenceTransformer,
    client: chromadb.PersistentClient,
    registry: dict | None = None,
) -> chromadb.Collection:
    """Embed all notes and store them in a Chroma collection with cosine distance."""
    if registry is None:
        registry = load_notes_registry()

    try:
        client.delete_collection(COLLECTION_NAME)
    except Exception:
        pass

    collection = client.create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )

    ids = list(registry.keys())
    documents = [entry["source_text"] for entry in registry.values()]
    metadatas = [
        {"note_id": note_id, "polarity": entry["polarity"]}
        for note_id, entry in registry.items()
    ]
    embeddings = model.encode(documents, normalize_embeddings=True).tolist()

    collection.add(
        ids=ids,
        documents=documents,
        embeddings=embeddings,
        metadatas=metadatas,
    )
    return collection


def _format_week(week_of: pd.Timestamp | str) -> str:
    if isinstance(week_of, pd.Timestamp):
        return week_of.strftime("%Y-%m-%d")
    return week_of


def retrieve_for_candidate(
    route: str,
    week_of: pd.Timestamp | str,
    model: SentenceTransformer,
    collection: chromadb.Collection,
    top_k: int = 3,
) -> tuple[list[dict], list[dict]]:
    """Score all notes for a candidate and return the top-k (ties broken by note_id)."""
    week_str = _format_week(week_of)
    query = f"{route} freight cost rise week of {week_str}"

    query_embedding = model.encode([query], normalize_embeddings=True).tolist()
    results = collection.query(
        query_embeddings=query_embedding,
        n_results=collection.count(),
        include=["distances", "metadatas"],
    )

    scored = []
    for note_id, distance, metadata in zip(
        results["ids"][0], results["distances"][0], results["metadatas"][0]
    ):
        # Cosine distance -> cosine similarity
        similarity = 1.0 - float(distance)
        scored.append(
            {
                "note_id": note_id,
                "score": round(similarity, 9),
                "polarity": metadata["polarity"],
            }
        )

    # Sort by score descending, then note_id ascending for deterministic ties.
    scored.sort(key=lambda x: (-x["score"], x["note_id"]))
    return scored[:top_k], scored


def build_retrieval_trace(
    candidates: pd.DataFrame,
    model: SentenceTransformer,
    collection: chromadb.Collection,
) -> list[dict]:
    """Build one trace record per candidate."""
    trace = []
    for _, row in candidates.iterrows():
        route = row["route"]
        week_of = row["week_of"]
        week_str = _format_week(week_of)
        top3, all_scores = retrieve_for_candidate(route, week_of, model, collection)
        trace.append(
            {
                "route": route,
                "week_of": week_str,
                "query": f"{route} freight cost rise week of {week_str}",
                "top_3": top3,
                "all_scores": all_scores,
            }
        )
    return trace


def write_trace(trace: list[dict], path: Path | str | None = None) -> None:
    if path is None:
        path = OUTPUT_PATH
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for record in trace:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")


def main() -> None:
    params = load_params()
    t_own = params["flagging"]["t_own"]

    shipments = load_shipments()
    weekly = add_baselines(build_weekly_costs(shipments))
    candidates = find_candidates(weekly, t_own=t_own)

    registry = load_notes_registry()
    model = get_model()
    client = get_client()
    collection = build_index(model, client, registry)

    trace = build_retrieval_trace(candidates, model, collection)
    write_trace(trace)
    print(f"Wrote retrieval trace for {len(trace)} candidates to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
