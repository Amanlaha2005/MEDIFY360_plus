from sentence_transformers import SentenceTransformer
import faiss
import numpy as np

# load model
model = SentenceTransformer('all-MiniLM-L6-v2')

# load text
def load_knowledge():
    with open("main/data/mental_health.txt", "r", encoding="utf-8") as f:
        text = f.read()

    chunks = text.split("\n")

    embeddings = model.encode(chunks)

    index = faiss.IndexFlatL2(embeddings.shape[1])
    index.add(np.array(embeddings))

    return index, chunks, embeddings


index, chunks, embeddings = load_knowledge()


def search_knowledge(query, k=3):
    q_embed = model.encode([query])
    D, I = index.search(np.array(q_embed), k)

    results = [chunks[i] for i in I[0]]
    return " ".join(results)