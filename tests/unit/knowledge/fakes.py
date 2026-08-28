from hashlib import sha256

from ia_mcp.knowledge.models import ParsedPage, PreparedChunk
from ia_mcp.knowledge.ports import ParseError


def embed_text(text: str, dim: int = 32) -> tuple[float, ...]:
    vector = [0.0] * dim
    for token in text.lower().split():
        index = int(sha256(token.encode("utf-8")).hexdigest(), 16) % dim
        vector[index] += 1.0
    norm = sum(value * value for value in vector) ** 0.5
    if norm == 0:
        return tuple(vector)
    return tuple(value / norm for value in vector)


class FakeParser:
    async def parse(self, payload: bytes) -> tuple[ParsedPage, ...]:
        if payload == b"FAULT":
            raise ParseError("parse_failed", "Document could not be parsed.")
        text = payload.decode("utf-8")
        pages = text.split("\f") if "\f" in text else [text]
        return tuple(
            ParsedPage(page=index + 1, text=page.strip())
            for index, page in enumerate(pages)
            if page.strip()
        )


class FakeChunker:
    async def chunk(self, pages: tuple[ParsedPage, ...]) -> tuple[PreparedChunk, ...]:
        return tuple(
            PreparedChunk(page=page.page, position=0, text=page.text)
            for page in pages
        )


class FakeEmbedding:
    async def embed(self, texts: tuple[str, ...]) -> tuple[tuple[float, ...], ...]:
        return tuple(embed_text(text) for text in texts)


class DownEmbedding:
    async def embed(self, texts: tuple[str, ...]) -> tuple[tuple[float, ...], ...]:
        del texts
        raise RuntimeError("embedding provider down")
