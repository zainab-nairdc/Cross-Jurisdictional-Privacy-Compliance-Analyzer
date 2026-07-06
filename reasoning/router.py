# router.py
# lightweight query classifier. takes a user question, decides which of the
# four routes to send it down (comparative / compliance / extraction /
# general). uses tiny example-based nearest neighbour matching — no llm
# call, no api dependency.

import asyncio
import threading

import numpy as np
from sentence_transformers import SentenceTransformer
from sklearn.neighbors import NearestNeighbors

from .config import cfg


# example queries per route. the classifier embeds these once, then matches
# new queries by cosine distance and majority-votes the route. add more
# examples here if you see a route that's getting consistently misclassified.
_ROUTE_EXAMPLES = {
    "comparative": [
        "compare data protection laws in bahrain and kuwait",
        "differences between GDPR and PDPL article 12",
        "how does india's DPDP differ from kuwait's DPPR",
    ],
    "compliance": [
        "is this policy compliant with central bank guidelines",
        "check if our SOP meets article 5 requirements",
        "does BBK's retention schedule satisfy bahrain PDPL",
    ],
    "extraction": [
        "list all penalties mentioned in the cybercrime law",
        "extract deadlines from the licensing policy",
        "what are the breach notification timeframes across all regulations",
    ],
    "general": [
        "what does article 7 say about consent",
        "explain the purpose of this regulation",
        "summarise the data protection law of bahrain",
    ],
}


class QueryRouter:
    """holds the embedded route examples and answers classify() calls.
    one instance per process, lazily built on first use."""

    def __init__(self, model_name: str):
        self.model = SentenceTransformer(model_name)
        self._build_index()

    def _build_index(self):
        texts: list[str] = []
        labels: list[str] = []
        for route, examples in _ROUTE_EXAMPLES.items():
            for ex in examples:
                texts.append(ex)
                labels.append(route)
        embeddings = self.model.encode(texts, normalize_embeddings=True)
        self.nn = NearestNeighbors(n_neighbors=3, metric="cosine")
        self.nn.fit(embeddings)
        self.label_map = {i: labels[i] for i in range(len(labels))}
        self.texts = texts

    def classify(self, query: str) -> str:
        """sync version. takes a query, returns one of the four route names."""
        emb = self.model.encode([query], normalize_embeddings=True)[0]
        dists, idxs = self.nn.kneighbors([emb])
        # weighted vote — closer examples count more. 1e-6 prevents div by zero
        # when the query exactly matches a training example.
        votes: dict[str, float] = {}
        for d, idx in zip(dists[0], idxs[0]):
            label = self.label_map[int(idx)]
            votes[label] = votes.get(label, 0.0) + (1.0 / (d + 1e-6))
        return max(votes, key=votes.get)


_router_instance: QueryRouter | None = None
_router_lock = threading.Lock()


async def classify_query(query: str, model: str | None = None) -> str:
    """async entry point used by orchestrator.route_node. lazy-loads the
    classifier on first call (thread-safe). the actual work is sync, so we
    offload it to a thread to keep the event loop unblocked."""
    global _router_instance
    if _router_instance is None:
        with _router_lock:
            if _router_instance is None:
                _router_instance = QueryRouter(model or cfg.routing.classifier_model)
    return await asyncio.to_thread(_router_instance.classify, query)
