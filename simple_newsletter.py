"""
SIMPLE FINANCIAL NEWSLETTER AUTOMATION
Automated daily financial newsletter using Google News + Gemini AI

What this does:
1. Scrapes news from Google News RSS feeds (no API key needed)
2. Asks Gemini AI to summarize with your portfolio context
3. Sends styled HTML email to your inbox
4. Saves newsletter to archive folder
"""

import os
import smtplib
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from bs4 import BeautifulSoup
import markdown

# Determine the base directory of the script
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

import requests
from google import genai
from dotenv import load_dotenv
import gspread
from google.oauth2.service_account import Credentials

# Load your API keys from .env file
load_dotenv()

# =============================================================================
# CONFIGURATION - Update these values or use .env file
# =============================================================================

# Gemini API Key (get one at https://aistudio.google.com/apikey)
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY', 'your-gemini-api-key-here')

# Email Configuration (Gmail SMTP)
# For Gmail, create an App Password: https://myaccount.google.com/apppasswords
EMAIL_ADDRESS = os.getenv('EMAIL_ADDRESS', 'your-email@gmail.com')
EMAIL_APP_PASSWORD = os.getenv('EMAIL_APP_PASSWORD', 'your-app-password-here')
EMAIL_RECIPIENT = os.getenv('EMAIL_RECIPIENT', 'recipient@gmail.com')

# User Portfolio (loaded from Google Sheets, or set manually below)
USER_PORTFOLIO = []

# Google News RSS Feed URLs (customize categories as needed)
GOOGLE_NEWS_FEEDS = {
    "World": "https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNRGx1YlY4U0FtVnVHZ0pWVXlnQVAB?hl=en-US&gl=US&ceid=US:en",
    "Business": "https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNRGx6TVdZU0FtVnVHZ0pWVXlnQVAB?hl=en-US&gl=US&ceid=US:en",
    "Technology": "https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNRGRqTVhZU0FtVnVHZ0pWVXlnQVAB?hl=en-US&gl=US&ceid=US:en",
    "Stock Markets": "https://news.google.com/rss/search?q=stock%20markets&hl=en-US&gl=US&ceid=US:en",
    "Cryptocurrency": "https://news.google.com/rss/topics/CAAqJAgKIh5DQkFTRUFvS0wyMHZNSFp3YWpSZlloSUNaVzRvQUFQAQ?hl=en-US&gl=US&ceid=US:en",
}

# Google Sheets Configuration (optional - for dynamic portfolio)
GOOGLE_SHEET_NAME = os.getenv('GOOGLE_SHEET_NAME', 'Your-Portfolio-Sheet-Name')
PORTFOLIO_TAB_NAME = os.getenv('PORTFOLIO_TAB_NAME', 'Sheet1')
PORTFOLIO_COLUMNS = [2]  # Column B (tickers column)

CREDENTIALS_FILE = os.path.join(BASE_DIR, "service_account.json")


# ============================================================================
# STEP 0: GOOGLE SHEETS SETUP (Optional)
# ============================================================================

def authenticate_gsheet():
    """Authenticate with Google Sheets"""
    print("🔑 Step 0: Authenticating with Google Sheets...")

    if not os.path.exists(CREDENTIALS_FILE):
        print(f"⚠️ Warning: {CREDENTIALS_FILE} not found. Skipping Google Sheets integration.")
        return None

    try:
        scope = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
        creds = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=scope)
        gc = gspread.authorize(creds)
        print("✓ Connected to Google Sheets")
        return gc
    except Exception as e:
        print(f"❌ Error authenticating: {e}")
        return None

def get_portfolio_from_sheet(gc):
    """Read portfolio from Google Sheet"""
    print("📈 Reading dynamic portfolio from Google Sheet...")
    global USER_PORTFOLIO

    try:
        sh = gc.open(GOOGLE_SHEET_NAME)
        try:
            worksheet = sh.worksheet(PORTFOLIO_TAB_NAME)
        except:
            worksheet = sh.sheet1
            print(f"⚠️ Warning: '{PORTFOLIO_TAB_NAME}' tab not found, using first tab.")

        all_tickers = []
        for col in PORTFOLIO_COLUMNS:
            tickers = worksheet.col_values(col)
            all_tickers.extend(tickers)

        # Clean up list (remove empty and headers)
        clean_tickers = []
        for t in all_tickers:
            t = t.strip() if t else ''
            if t and t.lower() not in ['ticker', 'symbol', 'asset', 'stock', '']:
                clean_tickers.append(t)

        if clean_tickers:
            USER_PORTFOLIO[:] = clean_tickers
            print(f"✓ Loaded {len(clean_tickers)} assets from sheet: {', '.join(clean_tickers)}")
        else:
            USER_PORTFOLIO[:] = ["ERROR: No portfolio data found in Google Sheet"]
            print("❌ Sheet columns were empty!")

    except Exception as e:
        USER_PORTFOLIO[:] = [f"ERROR: Could not load portfolio - {e}"]
        print(f"❌ Error reading portfolio: {e}")


# ============================================================================
# STEP 1: FETCH NEWS FROM GOOGLE NEWS RSS FEEDS
# ============================================================================

def fetch_rss_feed(url, category):
    """Fetch articles from a Google News RSS feed"""
    try:
        response = requests.get(url, timeout=15)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'lxml-xml')

        articles = []
        items = soup.find_all('item')

        for item in items[:8]:  # Limit to 8 per category
            try:
                title_elem = item.find('title')
                link_elem = item.find('link')
                source_elem = item.find('source')
                pub_date_elem = item.find('pubDate')

                if not title_elem or not link_elem:
                    continue

                articles.append({
                    'title': title_elem.text.strip(),
                    'url': link_elem.text.strip(),
                    'source': source_elem.text.strip() if source_elem else 'Unknown',
                    'published': pub_date_elem.text.strip() if pub_date_elem else '',
                    'category': category
                })

            except Exception:
                continue

        return articles

    except Exception as e:
        print(f"   ❌ Error fetching {category}: {e}")
        return []


def is_article_fresh(pub_date_str, max_age_hours=24):
    """Check if article was published within the last N hours"""
    if not pub_date_str:
        return True

    try:
        pub_date = parsedate_to_datetime(pub_date_str)
        cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
        return pub_date >= cutoff
    except Exception:
        return True


def get_news():
    """Get latest news from Google News RSS feeds (last 24 hours only)"""

    print("📰 Step 1: Fetching news from Google News...")
    print(f"   📅 Filtering for articles from the last 24 hours")

    all_articles = []

    for category, url in GOOGLE_NEWS_FEEDS.items():
        print(f"   Fetching: {category}")

        articles = fetch_rss_feed(url, category)
        all_articles.extend(articles)
        print(f"   ✓ Found {len(articles)} articles")

    # Filter to only fresh articles (last 24 hours)
    fresh_articles = [a for a in all_articles if is_article_fresh(a.get('published', ''))]

    # De-duplicate articles by title
    seen_titles = set()
    unique_articles = []
    for article in fresh_articles:
        title_key = article.get('title', '').lower().strip()
        if title_key and title_key not in seen_titles:
            seen_titles.add(title_key)
            unique_articles.append(article)

    print(f"✓ Total: {len(all_articles)} fetched → {len(fresh_articles)} fresh → {len(unique_articles)} unique\n")
    return unique_articles


# ============================================================================
# STEP 2: PREPARE NEWS FOR AI
# ============================================================================

def prepare_news_text(articles):
    """Turn articles into text for AI to read"""

    print("📝 Step 2: Preparing news for AI...")

    if not articles:
        return "No news articles found."

    news_text = "# Latest News from Google News\n\n"

    for i, article in enumerate(articles[:25], 1):
        news_text += f"## Article {i}: {article.get('title', 'No title')}\n"
        news_text += f"Category: {article.get('category', 'General')}\n"
        news_text += f"Source: {article.get('source', 'Unknown')}\n"
        news_text += f"URL: {article.get('url', '')}\n"
        news_text += "\n---\n\n"

    print(f"✓ Prepared {min(len(articles), 25)} articles for AI\n")
    return news_text


# ============================================================================
# STEP 3: ASK GEMINI AI TO SUMMARIZE
# ============================================================================

def summarize_with_gemini(news_text):
    """Ask Gemini to create a newsletter"""

    print("🤖 Step 3: Asking Gemini AI to summarize...")

    api_key = GEMINI_API_KEY

    if not api_key or api_key == 'your-gemini-api-key-here':
        print("❌ ERROR: GEMINI_API_KEY not configured")
        return "Error: No Gemini API key"

    # Configure Gemini client
    client = genai.Client(api_key=api_key)

    portfolio_string = "\n".join([f"- {item}" for item in USER_PORTFOLIO])

    prompt = f"""You are a high-level Geopolitical Macro Strategist.
**Style:** Conversational, raw, insightful. "Real talk" only. No fluff.
**Data:** You MUST include precise numbers (Yields, Basis Points, P/E ratios, specific Ticker movement) from the text.
**Perspective:** Filter for LONG-TERM signal vs. short-term noise.

Input Text:
{news_text}

*** USER PORTFOLIO & STRATEGY ***
{portfolio_string}
**********************

Create a concise "Geopolitical Heat Check" newsletter:

## 🎤 The Bit (The Macro Thesis)
(One sharp sentence. The single most important structural shift driving the market right now. Ignore the noise.)

## 🌍 The Setup (Top 5 High-Impact Stories)
(Focus on stories that shift economic reality over the next 1-5 years. ALWAYS include 1 cryptocurrency-related news story, 1 stock market story)

For each story use this EXACT format:

### **Headline Here**

4 sentences max explaining the leverage point. What does this actually mean? Why should I care?

**The Data:** Hard numbers from the text (Revenue impact, supply chain %, rate shifts).

👉 [Read more](USE THE ACTUAL URL FROM THE ARTICLE)

## 💼 Bag Check (Portfolio Stress Test)
(Cross-reference the news strictly against the "User Portfolio" list above.)
* **Direct Hit:** List specific tickers from the portfolio that are directly affected.
* **The Verdict:** [Thesis Intact / Thesis Broken / Buy the Dip]
* **The Logic:** Analyze the correlation. If the news is bad for the sector but good for the specific asset, explain why. Distinguish between a temporary price drop and a fundamental business break.

## 🔔 The Playbook (Actionable Moves)
(Bullet points: 3 specific strategic moves. Hedge? Accumulate? Sit on hands?)

---
**Constraint:** Be brief. If the news is just noise for a long-term holder, explicitly say "Just noise. Keep holding."
**IMPORTANT:** Each "Read more" link MUST be the actual URL from the input articles, not a placeholder.
"""

    try:
        response = client.models.generate_content(
            model='gemini-3-flash-preview',
            contents=prompt
        )

        print("✓ Gemini created the newsletter!\n")
        return response.text

    except Exception as e:
        print(f"❌ Error from Gemini: {e}")
        return f"Error creating newsletter: {e}"


# ============================================================================
# STEP 4: SAVE THE NEWSLETTER
# ============================================================================

def save_newsletter(content):
    """Save newsletter to a file"""

    print("💾 Step 4: Saving newsletter...")

    # Create archive folder if it doesn't exist
    archive_dir = os.path.join(BASE_DIR, "archive")
    os.makedirs(archive_dir, exist_ok=True)

    # Create filename with today's date
    today = datetime.now().strftime('%Y-%m-%d')
    filename = os.path.join(archive_dir, f"newsletter_{today}.md")

    with open(filename, 'w') as f:
        f.write(f"# Financial Newsletter - {today}\n\n")
        f.write(content)

    print(f"✓ Saved to: {filename}\n")
    return filename


# ============================================================================
# STEP 5: SEND EMAIL
# ============================================================================

def markdown_to_html(md_content):
    """Convert markdown to styled HTML for email"""
    html_body = markdown.markdown(md_content, extensions=['extra'])

    html_template = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <style>
            body {{
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                line-height: 1.6;
                color: #333;
                max-width: 800px;
                margin: 0 auto;
                padding: 20px;
            }}
            h1 {{
                color: #1a1a1a;
                border-bottom: 2px solid #ff6b35;
                padding-bottom: 10px;
            }}
            h2 {{
                color: #2d3748;
                margin-top: 30px;
            }}
            a {{
                color: #3182ce;
            }}
            strong {{
                color: #1a1a1a;
            }}
            ul {{
                padding-left: 20px;
            }}
            li {{
                margin-bottom: 8px;
            }}
            hr {{
                border: none;
                border-top: 1px solid #e2e8f0;
                margin: 20px 0;
            }}
        </style>
    </head>
    <body>
        {html_body}
    </body>
    </html>
    """
    return html_template


def send_email(content):
    """Send newsletter via email"""
    print("📧 Step 5: Sending email...")

    if EMAIL_ADDRESS == 'your-email@gmail.com':
        print("⚠️ Email not configured. Skipping email send.")
        return False

    try:
        msg = MIMEMultipart('alternative')
        today = datetime.now().strftime('%Y-%m-%d')
        msg['Subject'] = f"🔥 Geopolitical Heat Check - {today}"
        msg['From'] = EMAIL_ADDRESS
        msg['To'] = EMAIL_RECIPIENT

        text_part = MIMEText(content, 'plain')
        html_content = markdown_to_html(content)
        html_part = MIMEText(html_content, 'html')

        msg.attach(text_part)
        msg.attach(html_part)

        with smtplib.SMTP('smtp.gmail.com', 587) as server:
            server.starttls()
            server.login(EMAIL_ADDRESS, EMAIL_APP_PASSWORD)
            server.sendmail(EMAIL_ADDRESS, EMAIL_RECIPIENT, msg.as_string())

        print(f"✓ Email sent to {EMAIL_RECIPIENT}\n")
        return True

    except Exception as e:
        print(f"❌ Error sending email: {e}")
        return False


# ============================================================================
# MAIN FUNCTION - RUN EVERYTHING
# ============================================================================

def main():
    """Run the complete newsletter automation"""

    print("\n" + "="*60)
    print("🚀 SIMPLE FINANCIAL NEWSLETTER AUTOMATION")
    print("="*60 + "\n")

    # Step 0: GSheet Auth (optional)
    gc = authenticate_gsheet()

    if gc:
        get_portfolio_from_sheet(gc)
    elif not USER_PORTFOLIO:
        # Default portfolio if no Google Sheets
        USER_PORTFOLIO[:] = ["AAPL", "GOOGL", "MSFT", "SPY", "BTC"]
        print(f"📋 Using default portfolio: {', '.join(USER_PORTFOLIO)}\n")

    # Step 1: Get news
    articles = get_news()

    if not articles:
        print("❌ No articles found. Check your internet connection.")
        return

    # Step 2: Prepare for AI
    news_text = prepare_news_text(articles)

    # Step 3: Summarize with AI
    newsletter = summarize_with_gemini(news_text)

    # Step 4: Save it
    filename = save_newsletter(newsletter)

    # Step 5: Send email
    send_email(newsletter)

    # Done!
    print("="*60)
    print("✅ DONE! Newsletter generated!")
    print("="*60)
    print(f"\nFile saved: {filename}")
    if EMAIL_ADDRESS != 'your-email@gmail.com':
        print(f"Email sent to: {EMAIL_RECIPIENT}")
    if gc:
        print(f"Portfolio loaded from: {GOOGLE_SHEET_NAME}")
    print("\n")


# ============================================================================
# RUN IT!
# ============================================================================

if __name__ == "__main__":
    main()
