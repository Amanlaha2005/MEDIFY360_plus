from sentence_transformers import SentenceTransformer
import faiss
import numpy as np

# 🔥 GLOBAL VARIABLES
model = None
index = None
chunks = None


# 🔥 LOAD MODEL ONLY WHEN NEEDED
def get_model():
    global model
    if model is None:
        model = SentenceTransformer('all-MiniLM-L6-v2')
    return model


# 🔥 LOAD KNOWLEDGE ONLY ONCE
def load_knowledge():
    global index, chunks

    if index is not None:
        return index, chunks

    with open("main/data/mental_health.txt", "r", encoding="utf-8") as f:
        text = f.read()

    chunks = text.split("\n")

    model = get_model()
    embeddings = model.encode(chunks)

    index = faiss.IndexFlatL2(embeddings.shape[1])
    index.add(np.array(embeddings))

    return index, chunks


# 🔥 SEARCH FUNCTION
def search_knowledge(query, k=3):

    model = get_model()
    index, chunks = load_knowledge()

    q_embed = model.encode([query])
    D, I = index.search(np.array(q_embed), k)

    results = [chunks[i] for i in I[0]]
    return " ".join(results)