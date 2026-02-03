# rag_core.py for AIChat Integration

import os
import sys
import time
import random
import json
import traceback
import yaml
import concurrent.futures
from urllib.parse import quote_plus, urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from langchain_community.vectorstores import FAISS
from langchain_ollama import OllamaLLM
from langchain_ollama import OllamaEmbeddings
from langchain_core.prompts import PromptTemplate
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

# --- Configuration Loading ---
CONFIG_PATH = os.path.expanduser("~/.config/aichat/config.yaml")

def load_config():
    config = {
        "searxng_url": "http://localhost:8080",
        "ollama_model": "huihui_ai/jan-nano-abliterated:latest",
        "ollama_embedding_model": "nomic-embed-text",
        "chunk_size": 1000,
        "chunk_overlap": 200,
        "k_retriever": 20,
        "k_context": 10,
    }
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, 'r') as f:
                yaml_conf = yaml.safe_load(f)
                if 'websearch' in yaml_conf:
                    ws = yaml_conf['websearch']
                    config["searxng_url"] = ws.get("searxng_url", config["searxng_url"])
                    if "ollama" in ws:
                         config["ollama_model"] = ws["ollama"].get("model", config["ollama_model"])
                         config["ollama_embedding_model"] = ws["ollama"].get("embedding_model", config["ollama_embedding_model"])
        except Exception as e:
            print(f"Warning: Error loading config from {CONFIG_PATH}: {e}")
    return config

CONF = load_config()

SEARXNG_URL = CONF["searxng_url"]
SEARXNG_MAX_RESULTS = 20
REQUEST_TIMEOUT = 10
# Max threads for parallel scraping
MAX_WORKERS = 10 
USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/97.0.4692.71 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/100.0.4896.127 Safari/537.36',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/98.0.4758.102 Safari/537.36',
]

# --- Initialize LangChain Components ---
llm = OllamaLLM(model=CONF["ollama_model"])
embeddings = OllamaEmbeddings(model=CONF["ollama_embedding_model"])
text_splitter = RecursiveCharacterTextSplitter(chunk_size=CONF["chunk_size"], chunk_overlap=CONF["chunk_overlap"], length_function=len)

def make_polite_request(url):
    headers = {'User-Agent': random.choice(USER_AGENTS)}
    try:
        response = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        return response
    except Exception:
        return None

def extract_text_from_html(html_content, url):
    """
    Extracts the main content from an HTML page using simple heuristics.
    Prioritizes <article>, <main>, or specific classes.
    """
    if not html_content:
        return ""
    
    soup = BeautifulSoup(html_content, 'html.parser')
    
    # Remove clutter
    for tag in soup(["script", "style", "nav", "footer", "header", "noscript", "iframe", "svg", "button", "input"]):
        tag.extract()
        
    # Heuristic: Try to find the main content container
    content = None
    
    # List of tags/classes to check for main content
    candidates = [
        soup.find('article'),
        soup.find('main'),
        soup.find('div', class_=lambda x: x and ('content' in x or 'post' in x or 'article' in x or 'body' in x) and not ('sidebar' in x or 'comment' in x)),
    ]
    
    for candidate in candidates:
        if candidate:
            text = candidate.get_text(separator=' ', strip=True)
            # Basic sanity check: is it long enough to be an article?
            if len(text) > 200:
                content = text
                break
    
    # Fallback to body if no refined content found
    if not content:
        content = soup.get_text(separator=' ', strip=True)
        
    return content

def scrape_url(item):
    """
    Helper function to scrape a single URL.
    Returns a dict with title, source, and page_content, or None on failure.
    """
    resp = make_polite_request(item['href'])
    if resp:
        text = extract_text_from_html(resp.content, item['href'])
        if text:
             # Limit individual page content size to avoid context overflow for massive pages
            return {"title": item['title'], "source": item['href'], "page_content": text[:15000]}
    return None

def discover_urls(query):
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

def fetch_and_scrape_parallel(urls):
    docs = []
    # Scrape top 8 results in parallel
    targets = urls[:8]
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_url = {executor.submit(scrape_url, item): item for item in targets}
        for future in concurrent.futures.as_completed(future_to_url):
            try:
                data = future.result()
                if data:
                    docs.append(data)
            except Exception:
                pass # Sshh, skip failures
                
    return docs

def rag_pipeline(query):
    print(f"Searching web for: {query}...")
    urls = discover_urls(query)
    if not urls:
        return "No results found from SearXNG."
    
    print(f"Found {len(urls)} results. parallel scraping top 8...")
    scraped_data = fetch_and_scrape_parallel(urls)
    
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

    print(f"Indexing {len(all_texts)} chunks from {len(scraped_data)} pages...")
    vectorstore = FAISS.from_texts(all_texts, embeddings, metadatas=all_metadatas)
    
    retriever = vectorstore.as_retriever(search_kwargs={"k": CONF["k_retriever"]})
    context_docs = retriever.invoke(query)
    
    print("Generating enriched answer...")
    context_text = "\n\n".join([f"[Source: {d.metadata['title']}]\n{d.page_content}" for d in context_docs[:CONF["k_context"]]])
    
    prompt = PromptTemplate.from_template(
        "You are a helpful research assistant. Answer the question based ONLY on the provided context.\n"
        "If the answer is not in the context, say you don't know.\n"
        "Cite your sources using [Title] notation where appropriate.\n\n"
        "Context:\n{context}\n\n"
        "Question: {question}\n\n"
        "Detailed Answer:"
    )
    
    chain = prompt | llm
    answer = chain.invoke({"context": context_text, "question": query})
    
    # Format sources list
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
