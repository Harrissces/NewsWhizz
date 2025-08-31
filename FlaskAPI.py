# FlaskAPI.py - Flask Backend for NEWSWHIZZ (MicroSaaS backend for Lovable)

from flask import Flask, request, jsonify, send_file, make_response
from flask_cors import CORS  
from gtts import gTTS
import openai
import os
import requests
from datetime import datetime
from dotenv import load_dotenv
import tempfile
import uuid

# Load environment variables first
load_dotenv()

# Initialize Flask app AFTER loading env vars
app = Flask(__name__)

# Enable CORS AFTER creating the app
CORS(app)  # ✅ Now this works because 'app' is defined

# Load API keys
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
NEWS_API_KEY = os.getenv("NEWS_API_KEY") or "809a78470dbf4902bcbba81cae58b192"

if not OPENAI_API_KEY:
    raise ValueError("Missing OPENAI_API_KEY in environment")

openai.api_key = OPENAI_API_KEY

# Language mapping for TTS
LANG_MAP = {"English": "en", "Tamil": "ta", "Hindi": "hi"}

# --- Utility: Fetch News ---
def fetch_news(category="general", region="in", limit=5):
    url = (
        f"https://newsapi.org/v2/top-headlines?"
        f"country={region}&category={category}&pageSize={limit}&apiKey={NEWS_API_KEY}"
    )
    try:
        resp = requests.get(url, timeout=10)
        data = resp.json()
        if data.get("status") == "ok" and data.get("articles"):
            return data["articles"]
        else:
            # Fallback
            q = f"{category} news"
            url2 = (
                f"https://newsapi.org/v2/everything?"
                f"q={q}&language=en&pageSize={limit}&apiKey={NEWS_API_KEY}"
            )
            resp2 = requests.get(url2, timeout=10)
            data2 = resp2.json()
            return data2.get("articles", [])
    except Exception as e:
        print(f"Error fetching news: {e}")
        return []

# --- Utility: Summarize with GPT ---
def summarize_article(article_text, language="English"):
    prompt = f"""
    Summarize the following news article into:
    1. A short paragraph of 2–3 complete sentences.
    2. Two bullet points highlighting the most important details.

    The summary must be in {language}.

    Article: {article_text}
    """
    try:
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=600,
            temperature=0.5,
            timeout=30
        )
        text = response.choices[0].message["content"].strip()
        return text
    except Exception as e:
        return f"⚠️ Error generating summary: {e}"

# --- Utility: Generate TTS ---
def generate_tts(text, lang_code="en"):
    try:
        tts = gTTS(text, lang=lang_code)
        # Use a temporary file with unique name
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
        tts.save(temp_file.name)
        temp_file.close()
        return temp_file.name
    except Exception as e:
        print(f"TTS failed: {e}")
        return None


# --- API Routes ---

@app.route("/health", methods=["GET"])
def health_check():
    return jsonify({"status": "healthy", "timestamp": datetime.utcnow().isoformat()}), 200


@app.route("/news", methods=["GET"])
def get_news():
    try:
        category = request.args.get("category", "general")
        region = request.args.get("region", "in")
        language = request.args.get("language", "English")
        limit = int(request.args.get("limit", 5))

        valid_categories = ["general", "business", "technology", "sports", "entertainment", "science", "health"]
        if category not in valid_categories:
            return jsonify({"error": "Invalid category"}), 400

        if language not in LANG_MAP:
            return jsonify({"error": "Unsupported language"}), 400

        articles = fetch_news(category, region, limit)
        if not articles:
            return jsonify({"message": "No news found", "articles": []}), 200

        processed_articles = []
        for article in articles:
            title = article.get("title", "Untitled")
            source = article.get("source", {}).get("name", "Unknown")
            content = article.get("description") or article.get("content") or title

            summary = summarize_article(content, language)

            processed_articles.append({
                "id": str(uuid.uuid4()),
                "title": title,
                "source": source,
                "summary": summary,
                "sentiment": "Neutral",
                "url": article.get("url"),
                "image": article.get("urlToImage"),
                "publishedAt": article.get("publishedAt")
            })

        return jsonify({
            "region": region,
            "category": category,
            "language": language,
            "total": len(processed_articles),
            "articles": processed_articles
        }), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/tts", methods=["POST"])
def get_tts():
    data = request.get_json()
    text = data.get("text")
    language = data.get("language", "English")

    if not text:
        return jsonify({"error": "Missing 'text' in request"}), 400

    lang_code = LANG_MAP.get(language, "en")

    temp_file_path = generate_tts(text, lang_code)
    if not temp_file_path:
        return jsonify({"error": "TTS generation failed"}), 500

    # Serve the file
    response = make_response(send_file(temp_file_path, mimetype="audio/mp3"))
    response.headers["X-Audio-File"] = os.path.basename(temp_file_path)

    # Delete file after sending
    @response.call_on_close
    def cleanup():
        try:
            os.remove(temp_file_path)
        except:
            pass

    return response


@app.route("/briefing", methods=["POST"])
def daily_briefing():
    data = request.get_json()
    category = data.get("category", "general")
    region = data.get("region", "in")
    language = data.get("language", "English")
    limit = data.get("limit", 5)

    articles = fetch_news(category, region, limit)
    if not articles:
        return jsonify({"error": "No articles available for briefing"}), 400

    summaries = [
        summarize_article(
            a.get("description") or a.get("content") or a["title"],
            language
        )
        for a in articles
    ]
    combined_summary = " ".join(summaries)
    intro = f"Good morning! Here are today's top {category} news from {region}. "
    full_text = intro + combined_summary

    temp_file_path = generate_tts(full_text, LANG_MAP.get(language, "en"))
    if not temp_file_path:
        return jsonify({"error": "Failed to generate audio briefing"}), 500

    response = make_response(send_file(temp_file_path, mimetype="audio/mp3"))
    response.headers["X-Audio-Type"] = "daily-briefing"

    @response.call_on_close
    def cleanup():
        try:
            os.remove(temp_file_path)
        except:
            pass

    return response


# --- Run the app ---
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)