"""
RAG (Retrieval-Augmented Generation) for the symptom-agent service.
Uses Pinecone for vector search with Google Gemini embeddings via LangChain.
This is the only service that talks to Pinecone.
"""
import json
import logging
from typing import List, Optional, Dict, Any
from time import sleep

from pinecone import Pinecone, ServerlessSpec
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_google_genai import GoogleGenerativeAIEmbeddings

from shared.config import Settings, get_settings
from shared.schemas import Document, RetrievalResult


logger = logging.getLogger("healthlink.symptom.rag")


class EmbeddingClient:
    """Embedding client using LangChain Google GenAI Embeddings."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.model_name = settings.embedding_model_name

        self.embeddings = GoogleGenerativeAIEmbeddings(
            model=self.model_name,
            google_api_key=settings.gemini_api_key,
            task_type="retrieval_document"
        )

        self.query_embeddings = GoogleGenerativeAIEmbeddings(
            model=self.model_name,
            google_api_key=settings.gemini_api_key,
            task_type="retrieval_query"
        )

        logger.info(f"Embedding client initialized with model: {self.model_name}")

    def embed_text(self, text: str, is_query: bool = True) -> List[float]:
        if is_query:
            return self.query_embeddings.embed_query(text)
        return self.embeddings.embed_query(text)

    def embed_texts(self, texts: List[str]) -> List[List[float]]:
        return self.embeddings.embed_documents(texts)


class VectorStore:
    """Pinecone-based vector store for document retrieval."""

    def __init__(self, settings: Settings, embedding_client: EmbeddingClient):
        self.settings = settings
        self.embedding_client = embedding_client
        self.index_name = settings.pinecone_index_name

        self.pc = Pinecone(api_key=settings.pinecone_api_key)

        sample_embedding = self.embedding_client.embed_text("sample", is_query=False)
        self.dimension = len(sample_embedding)

        self.initialize_index()

        logger.info(f"Vector store initialized with Pinecone index: {self.index_name}")

    def initialize_index(self):
        existing_indexes = [index.name for index in self.pc.list_indexes()]

        if self.index_name not in existing_indexes:
            logger.info(f"Creating new Pinecone index: {self.index_name}")
            self.pc.create_index(
                name=self.index_name,
                dimension=self.dimension,
                metric="cosine",
                spec=ServerlessSpec(
                    cloud="aws",
                    region=self.settings.pinecone_environment or "us-east-1"
                )
            )
            sleep(1)

        self.index = self.pc.Index(self.index_name)
        logger.info(f"Connected to Pinecone index: {self.index_name}")

    def add_documents(self, documents: List[Document]) -> None:
        if not documents:
            return

        texts = [doc.content for doc in documents]

        logger.info(f"Generating embeddings for {len(texts)} documents")
        embeddings = self.embedding_client.embed_texts(texts)

        vectors = []
        for i, (doc, embedding) in enumerate(zip(documents, embeddings)):
            vector_id = f"doc_{i}_{hash(doc.content)}"
            metadata = {
                "content": doc.content,
                **(doc.metadata or {})
            }
            vectors.append({
                "id": vector_id,
                "values": embedding,
                "metadata": metadata
            })

        batch_size = 100
        for i in range(0, len(vectors), batch_size):
            batch = vectors[i:i + batch_size]
            self.index.upsert(vectors=batch)
            logger.info(f"Upserted batch {i // batch_size + 1} ({len(batch)} vectors)")

        logger.info(f"Added {len(documents)} documents to Pinecone index")

    def search(self, query: str, k: int = 5) -> RetrievalResult:
        query_embedding = self.embedding_client.embed_text(query, is_query=True)

        search_results = self.index.query(
            vector=query_embedding,
            top_k=k,
            include_metadata=True
        )

        results = []
        scores = []

        for match in search_results.matches:
            content = match.metadata.get("content", "")
            metadata = {k: v for k, v in match.metadata.items() if k != "content"}

            results.append(Document(content=content, metadata=metadata))
            scores.append(float(match.score))

        logger.info(f"Retrieved {len(results)} documents for query: {query[:50]}...")

        return RetrievalResult(documents=results, scores=scores, query=query)

    def get_stats(self) -> Dict[str, Any]:
        stats = self.index.describe_index_stats()
        return {
            "total_vector_count": stats.total_vector_count,
            "dimension": stats.dimension,
            "index_fullness": stats.index_fullness
        }


_embedding_client: Optional[EmbeddingClient] = None
_vector_store: Optional[VectorStore] = None


def get_embedding_client(settings: Settings) -> EmbeddingClient:
    global _embedding_client
    if _embedding_client is None:
        _embedding_client = EmbeddingClient(settings)
    return _embedding_client


def get_vector_store(settings: Settings) -> VectorStore:
    global _vector_store
    if _vector_store is None:
        embedding_client = get_embedding_client(settings)
        _vector_store = VectorStore(settings, embedding_client)
    return _vector_store


def chunk_text(text: str, chunk_size: int = 500, chunk_overlap: int = 50) -> List[str]:
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        length_function=len,
    )
    return splitter.split_text(text)


def load_knowledge_base(file_path: str, settings: Settings) -> None:
    """Load a knowledge base JSON file and index it into Pinecone."""
    logger.info(f"Loading knowledge base from {file_path}")

    try:
        with open(file_path, 'r') as f:
            data = json.load(f)

        documents = []

        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    content = item.get('content', '') or item.get('text', '')
                    metadata = {k: v for k, v in item.items() if k not in ['content', 'text']}
                else:
                    content = str(item)
                    metadata = {}

                if content:
                    chunks = chunk_text(content, settings.chunk_size, settings.chunk_overlap)
                    for chunk in chunks:
                        documents.append(Document(content=chunk, metadata=metadata))

        elif isinstance(data, dict):
            for key, value in data.items():
                content = value if isinstance(value, str) else json.dumps(value)
                documents.append(Document(content=content, metadata={"source": key}))

        vector_store = get_vector_store(settings)
        vector_store.add_documents(documents)

        logger.info(f"Loaded {len(documents)} document chunks into vector store")

    except Exception as e:
        logger.error(f"Failed to load knowledge base: {e}", exc_info=True)
        raise


def retrieve_relevant_docs(query: str, k: int = 5, settings: Optional[Settings] = None) -> RetrievalResult:
    if settings is None:
        settings = get_settings()

    vector_store = get_vector_store(settings)
    return vector_store.search(query, k)


def format_retrieval_context(retrieval_result: RetrievalResult, max_docs: int = 3) -> str:
    if not retrieval_result.documents:
        return ""

    context_parts = ["Relevant medical knowledge:"]

    for i, doc in enumerate(retrieval_result.documents[:max_docs]):
        context_parts.append(f"\n[Source {i+1}]")
        context_parts.append(doc.content)
        if doc.metadata:
            context_parts.append(f"Metadata: {json.dumps(doc.metadata)}")

    return "\n".join(context_parts)
