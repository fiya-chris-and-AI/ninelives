"""
Embedding call, behind a provider switch.

Default: local sentence-transformers. Optional: Titan Embeddings on
Bedrock. Swap by setting EMBEDDING_PROVIDER=bedrock in .env.ninelives —
no other code changes. The CockroachDB vector index is the point of the
demo, not the embedding vendor.
"""
import config

_local_model = None


def embed(text: str) -> list[float]:
    if config.EMBEDDING_PROVIDER == "local":
        return _embed_local(text)
    elif config.EMBEDDING_PROVIDER == "bedrock":
        return _embed_bedrock(text)
    raise ValueError(f"unknown EMBEDDING_PROVIDER: {config.EMBEDDING_PROVIDER}")


def _embed_local(text: str) -> list[float]:
    global _local_model
    if _local_model is None:
        from sentence_transformers import SentenceTransformer

        _local_model = SentenceTransformer(config.LOCAL_EMBEDDING_MODEL)
    return _local_model.encode(text, normalize_embeddings=True).tolist()


def _embed_bedrock(text: str) -> list[float]:
    import json
    import boto3

    client = boto3.client("bedrock-runtime", region_name=config.BEDROCK_REGION_PRIMARY)
    body = json.dumps({"inputText": text, "dimensions": config.EMBEDDING_DIM})
    response = client.invoke_model(modelId=config.BEDROCK_EMBEDDING_MODEL_ID, body=body)
    payload = json.loads(response["body"].read())
    return payload["embedding"]
