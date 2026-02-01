"""
SIMPLE FINANCIAL NEWSLETTER AUTOMATION
Step-by-step guide included below

What this does:
1. Scrapes news from Google News (no API key needed)
2. Asks Gemini AI to summarize it
3. Saves result to a file (you can email it later)
"""

import os
import re
import smtplib
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from bs4 import BeautifulSoup
import markdown

# Determine the base directory of the script
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Install these first: pip install requests google-generativeai python-dotenv beautifulsoup4
import requests
from google import genai
from dotenv import load_dotenv
import gspread
from google.oauth2.service_account import Credentials

# Load your API keys from .env file
load_dotenv()

# API Keys (can also be set in .env file)
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY', 'your-gemini-api-key-here')

# Email Configuration (Gmail SMTP)
EMAIL_ADDRESS = os.getenv('EMAIL_ADDRESS', 'your-email@gmail.com')
EMAIL_APP_PASSWORD = os.getenv('EMAIL_APP_PASSWORD', 'your-app-password-here')
EMAIL_RECIPIENT = os.getenv('EMAIL_RECIPIENT', 'recipient@gmail.com')

# User Portfolio (loaded from Google Sheets)
USER_PORTFOLIO = []

# Google News RSS Feed URLs (much more reliable than scraping)
GOOGLE_NEWS_FEEDS = {
    "World": "https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNRGx1YlY4U0FtVnVHZ0pWVXlnQVAB?hl=en-US&gl=US&ceid=US:en",
    "Business": "https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNRGx6TVdZU0FtVnVHZ0pWVXlnQVAB?hl=en-US&gl=US&ceid=US:en",
    "Technology": "https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNRGRqTVhZU0FtVnVHZ0pWVXlnQVAB?hl=en-US&gl=US&ceid=US:en",
    "Stock Markets": "https://news.google.com/rss/search?q=stock%20markets&hl=en-US&gl=US&ceid=US:en",
    "Cryptocurrency": "https://news.google.com/rss/topics/CAAqJAgKIh5DQkFTRUFvS0wyMHZNSFp3YWpSZlloSUNaVzRvQUFQAQ?hl=en-US&gl=US&ceid=US:en",
}

# Google Sheets Configuration
GOOGLE_SHEET_NAME = os.getenv('GOOGLE_SHEET_NAME', 'Your-Portfolio-Sheet-Name')
PORTFOLIO_TAB_NAME = os.getenv('PORTFOLIO_TAB_NAME', 'Sheet1')
PORTFOLIO_COLUMNS = [2]  # Column B only (tickers)

CREDENTIALS_FILE = os.path.join(BASE_DIR, "service_account.json")


# ============================================================================
# STEP 0: GOOGLE SHEETS SETUP
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
    """Read portfolio from Google Sheet (from multiple columns)"""
    print("📈 Reading dynamic portfolio from Google Sheet...")
    global USER_PORTFOLIO

    try:
        sh = gc.open(GOOGLE_SHEET_NAME)
        # Try to open specific tab, otherwise first one
        try:
            worksheet = sh.worksheet(PORTFOLIO_TAB_NAME)
        except:
            worksheet = sh.sheet1
            print(f"⚠️ Warning: '{PORTFOLIO_TAB_NAME}' tab not found, using first tab.")

        # Get values from specified columns (B & C)
        all_tickers = []
        for col in PORTFOLIO_COLUMNS:
            tickers = worksheet.col_values(col)
            all_tickers.extend(tickers)

        # Clean up list (remove empty and headers only - keep duplicates for different exchanges)
        clean_tickers = []
        for t in all_tickers:
            t = t.strip() if t else ''
            if t and t.lower() not in ['ticker', 'symbol', 'asset', 'stock', '']:
                clean_tickers.append(t)

        if clean_tickers:
            USER_PORTFOLIO[:] = clean_tickers  # Update global list in-place
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
        return True  # Include articles without date (assume fresh)

    try:
        # Parse RFC 2822 date format (e.g., "Sat, 31 Jan 2026 18:49:40 GMT")
        pub_date = parsedate_to_datetime(pub_date_str)
        cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
        return pub_date >= cutoff
    except Exception:
        return True  # Include if we can't parse the date


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

    # De-duplicate articles by title (same story appears in multiple feeds)
    seen_titles = set()
    unique_articles = []
    for article in fresh_articles:
        # Normalize title for comparison (lowercase, strip whitespace)
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

    for i, article in enumerate(articles[:25], 1):  # Use first 25 articles
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
    
    # Your Gemini API key
    api_key = GEMINI_API_KEY

    if not api_key:
        print("❌ ERROR: GEMINI_API_KEY not configured")
        return "Error: No Gemini API key"
    
    # Configure Gemini client
    client = genai.Client(api_key=api_key)

    # Load prompt from external file
    prompt_file = os.path.join(BASE_DIR, "prompt.txt")
    try:
        with open(prompt_file, 'r') as f:
            prompt_template = f.read()
    except FileNotFoundError:
        print(f"❌ ERROR: {prompt_file} not found")
        return "Error: Prompt file not found"

    # Fill in the placeholders
    portfolio_string = "\n".join([f"- {item}" for item in USER_PORTFOLIO])
    final_prompt = prompt_template.format(news_text=news_text, portfolio_string=portfolio_string)

    try:
        # Ask Gemini
        response = client.models.generate_content(
            model='gemini-3-flash-preview',
            contents=final_prompt
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
    
    # Save to file
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
    # Convert markdown to HTML
    html_body = markdown.markdown(md_content, extensions=['extra'])

    # Wrap in simple, clean HTML template
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

    try:
        # Create message
        msg = MIMEMultipart('alternative')
        today = datetime.now().strftime('%Y-%m-%d')
        msg['Subject'] = f"🔥 Geopolitical Heat Check - {today}"
        msg['From'] = EMAIL_ADDRESS
        msg['To'] = EMAIL_RECIPIENT

        # Plain text version
        text_part = MIMEText(content, 'plain')

        # HTML version
        html_content = markdown_to_html(content)
        html_part = MIMEText(html_content, 'html')

        # Attach both versions (email client will choose the best one)
        msg.attach(text_part)
        msg.attach(html_part)

        # Send via Gmail SMTP (uses STARTTLS on port 587)
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

    # Read Portfolio from Sheet (optional)
    if gc:
        get_portfolio_from_sheet(gc)

    # If no portfolio loaded, use placeholder message
    if not USER_PORTFOLIO or USER_PORTFOLIO[0].startswith("ERROR"):
        USER_PORTFOLIO[:] = ["Portfolio not configured - general market analysis only"]
        print("📋 No portfolio configured. Proceeding with general market analysis.\n")
    
    # Step 1: Get news
    articles = get_news()
    
    if not articles:
        print("❌ No articles found. Check your API key and try again.")
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
    print("✅ DONE! Newsletter generated and emailed!")
    print("="*60)
    print(f"\nFile saved: {filename}")
    print(f"Email sent to: {EMAIL_RECIPIENT}")
    if gc:
        print(f"Portfolio loaded from: {GOOGLE_SHEET_NAME}")
    print("\n")


# ============================================================================
# RUN IT!
# ============================================================================

if __name__ == "__main__":
    main()
