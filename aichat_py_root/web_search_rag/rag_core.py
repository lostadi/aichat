# rag_core.py for AIChat Integration

import os
import sys
import time
import random
import json
import traceback
import yaml
from urllib.parse import quote_plus, urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from langchain_community.vectorstores import FAISS
from langchain_ollama import OllamaLLM
from langchain_ollama import OllamaEmbeddings
from langchain.prompts import PromptTemplate
from langchain_core.documents import Document
from langchain.text_splitter import RecursiveCharacterTextSplitter

# --- Configuration Loading ---
CONFIG_PATH = os.path.expanduser("~/.config/aichat/config.yaml")

def load_config():
    config = {
        "searxng_url": "http://localhost:8080",
        "ollama_model": "huihui_ai/jan-nano-abliterated:latest",
        "ollama_embedding_model": "nomic-embed-text",
        "chunk_size": 1000,
        "chunk_overlap": 200,
        "k_retriever": 20, # Reduced from 200 for CLI speed
        "k_context": 10,   # Reduced from 50 for CLI speed
    }
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, 'r') as f:
                yaml_conf = yaml.safe_load(f)
                # Look for 'websearch' key or fallback to top-level clients
                if 'websearch' in yaml_conf:
                    ws = yaml_conf['websearch']
                    config["searxng_url"] = ws.get("searxng_url", config["searxng_url"])
                    if "ollama" in ws:
                         config["ollama_model"] = ws["ollama"].get("model", config["ollama_model"])
                         config["ollama_embedding_model"] = ws["ollama"].get("embedding_model", config["ollama_embedding_model"])
                
                # Also check clients for ollama/openai-compatible to infer defaults if not in websearch
                # (Skipping complex inference for now to keep it simple, relying on defaults or explicit websearch config)
        except Exception as e:
            print(f"Warning: Error loading config from {CONFIG_PATH}: {e}")
    return config

CONF = load_config()

SEARXNG_URL = CONF["searxng_url"]
SEARXNG_MAX_RESULTS = 20
REQUEST_TIMEOUT = 10
USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/97.0.4692.71 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/97.0.4692.71 Safari/537.36',
]

# --- Initialize LangChain Components ---
llm = OllamaLLM(model=CONF["ollama_model"])
embeddings = OllamaEmbeddings(model=CONF["ollama_embedding_model"])
text_splitter = RecursiveCharacterTextSplitter(chunk_size=CONF["chunk_size"], chunk_overlap=CONF["chunk_overlap"], length_function=len)

def make_polite_request(url):
    headers = {'User-Agent': random.choice(USER_AGENTS)}
    time.sleep(random.uniform(0.1, 0.3))
    try:
        response = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        return response
    except Exception as e:
        # print(f"Error fetching {url}: {e}") # Sshh, quiet for CLI unless verbose
        return None

def discover_urls(query):
    # Simple discovery without LLM expansion for speed in CLI
    params = {'q': query, 'format': 'json', 'pageno': 1}
    try:
        resp = requests.get(f"{SEARXNG_URL.rstrip('/')}/search", params=params, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        results = []
        if "results" in data:
            for res in data["results"][:SEARXNG_MAX_RESULTS]:
                url = res.get('url')
                if url and url.startswith(('http', 'https')):
                    results.append({'title': res.get('title'), 'href': url})
        return results
    except Exception as e:
        print(f"SearXNG Error: {e}")
        return []

def fetch_and_scrape(urls):
    docs = []
    # Limit scraping to top 5 for speed
    for item in urls[:5]:
        resp = make_polite_request(item['href'])
        if resp:
            soup = BeautifulSoup(resp.content, 'html.parser')
            # Kill script and style elements
            for script in soup(["script", "style", "nav", "footer", "header"]):
                script.extract()
            text = soup.get_text(separator=' ', strip=True)
            if text:
                docs.append({"title": item['title'], "source": item['href'], "page_content": text[:10000]})
    return docs

def rag_pipeline(query):
    print(f"Searching web for: {query}...")
    urls = discover_urls(query)
    if not urls:
        return "No results found from SearXNG."
    
    print(f"Found {len(urls)} results. Scraping top 5...")
    scraped_data = fetch_and_scrape(urls)
    if not scraped_data:
        return "Failed to scrape any content."

    # Chunking
    all_texts = []
    all_metadatas = []
    for doc in scraped_data:
        chunks = text_splitter.split_text(doc["page_content"])
        for chunk in chunks:
            all_texts.append(chunk)
            all_metadatas.append({"source": doc["source"], "title": doc["title"]})
            
    if not all_texts:
        return "No text content extracted."

    print(f"Indexing {len(all_texts)} chunks...")
    vectorstore = FAISS.from_texts(all_texts, embeddings, metadatas=all_metadatas)
    
    retriever = vectorstore.as_retriever(search_kwargs={"k": CONF["k_retriever"]})
    context_docs = retriever.invoke(query)
    
    print("Generating answer...")
    context_text = "\n\n".join([d.page_content for d in context_docs[:CONF["k_context"]]])
    
    prompt = PromptTemplate.from_template(
        "Based on the following context, answer the question.\n\n"
        "Context:\n{context}\n\n"
        "Question: {question}\n\n"
        "Answer:"
    )
    
    chain = prompt | llm
    answer = chain.invoke({"context": context_text, "question": query})
    
    # Format sources
    sources = set()
    for doc in context_docs[:CONF["k_context"]]:
        sources.add(f"- {doc.metadata['title']}: {doc.metadata['source']}")
    
    return f"{answer}\n\n**Sources:**\n" + "\n".join(sources)

if __name__ == "__main__":
    if len(sys.argv) > 1:
        query = " ".join(sys.argv[1:])
        print(rag_pipeline(query))
    else:
        print("Usage: python rag_core.py <query>")
