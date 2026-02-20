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
PORTFOLIO_HISTORY_TAB = os.getenv('PORTFOLIO_HISTORY_TAB', 'Sheet2')

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


def get_portfolio_history(gc):
    """Read portfolio history from Sheet2, pre-calculate stats per ticker,
    and return a clean summary for the AI. Also sets USER_PORTFOLIO from latest snapshot."""
    print("📊 Reading portfolio history from Sheet2...")
    global USER_PORTFOLIO

    try:
        sh = gc.open(GOOGLE_SHEET_NAME)
        try:
            worksheet = sh.worksheet(PORTFOLIO_HISTORY_TAB)
        except:
            print(f"⚠️ Warning: '{PORTFOLIO_HISTORY_TAB}' tab not found. Skipping history.")
            return ""

        rows = worksheet.get_all_records()

        if not rows:
            print("⚠️ No history data found in Sheet2.")
            return ""

        # Build a dict: {ticker: {date: value}}
        from collections import defaultdict
        ticker_history = defaultdict(dict)
        all_dates = set()

        for row in rows:
            date = str(row.get('date', '')).strip()
            ticker = str(row.get('ticker', '')).strip()
            value = row.get('value', '')
            if not ticker or not date:
                continue
            try:
                value = float(str(value).replace(',', '').replace('$', ''))
            except (ValueError, TypeError):
                continue
            ticker_history[ticker][date] = value
            all_dates.add(date)

        if not ticker_history:
            print("⚠️ No valid data parsed from Sheet2.")
            return ""

        sorted_dates = sorted(all_dates)
        latest_date = sorted_dates[-1]
        earliest_date = sorted_dates[0]

        # Find dates for 7d and 30d lookback
        from datetime import datetime, timedelta
        try:
            latest_dt = datetime.strptime(latest_date, '%Y-%m-%d')
        except ValueError:
            try:
                latest_dt = datetime.strptime(latest_date, '%d/%m/%Y')
            except ValueError:
                latest_dt = None

        def find_closest_date(target_dt, dates):
            """Find the closest available date to target"""
            if not target_dt:
                return None
            closest = None
            min_diff = float('inf')
            for d in dates:
                try:
                    dt = datetime.strptime(d, '%Y-%m-%d')
                except ValueError:
                    try:
                        dt = datetime.strptime(d, '%d/%m/%Y')
                    except ValueError:
                        continue
                diff = abs((dt - target_dt).days)
                if diff < min_diff:
                    min_diff = diff
                    closest = d
            return closest

        date_7d = find_closest_date(latest_dt - timedelta(days=7), sorted_dates) if latest_dt else None
        date_30d = find_closest_date(latest_dt - timedelta(days=30), sorted_dates) if latest_dt else None

        # Calculate total portfolio value on latest date
        total_latest = sum(
            vals.get(latest_date, 0)
            for vals in ticker_history.values()
        )

        # Set USER_PORTFOLIO from latest snapshot tickers
        latest_tickers = [t for t, vals in ticker_history.items() if latest_date in vals]
        if latest_tickers:
            USER_PORTFOLIO[:] = latest_tickers
            print(f"✓ Current portfolio ({latest_date}): {', '.join(latest_tickers)}")

        # Build pre-calculated summary per ticker
        summary_lines = []
        for ticker in sorted(ticker_history.keys()):
            vals = ticker_history[ticker]
            current_val = vals.get(latest_date)
            first_val = vals.get(earliest_date)

            if current_val is None:
                status = "CLOSED/SOLD (not in latest snapshot)"
                summary_lines.append(f"- {ticker}: {status}")
                continue

            # % weight in portfolio
            weight_pct = (current_val / total_latest * 100) if total_latest else 0

            # % change overall (first date → latest)
            overall_pct = ((current_val - first_val) / first_val * 100) if first_val else None

            # % change last 7 days
            val_7d = vals.get(date_7d) if date_7d else None
            pct_7d = ((current_val - val_7d) / val_7d * 100) if val_7d else None

            # % change last 30 days
            val_30d = vals.get(date_30d) if date_30d else None
            pct_30d = ((current_val - val_30d) / val_30d * 100) if val_30d else None

            # Peak value and drawdown
            peak_val = max(vals.values())
            peak_date = max(vals, key=vals.get)
            drawdown_pct = ((current_val - peak_val) / peak_val * 100) if peak_val else 0

            # Build line
            line = f"- {ticker}: {weight_pct:.1f}% of portfolio"
            if overall_pct is not None:
                line += f" | {overall_pct:+.1f}% since {earliest_date}"
            if pct_7d is not None:
                line += f" | {pct_7d:+.1f}% (7d)"
            if pct_30d is not None:
                line += f" | {pct_30d:+.1f}% (30d)"
            if drawdown_pct < -10:
                line += f" | ⚠️ {drawdown_pct:.1f}% from peak ({peak_date})"
            elif peak_date == latest_date:
                line += f" | 🏆 At all-time high"

            summary_lines.append(line)

        # Identify biggest winner and loser
        movers = []
        for ticker, vals in ticker_history.items():
            first_val = vals.get(earliest_date)
            current_val = vals.get(latest_date)
            if first_val and current_val:
                movers.append((ticker, (current_val - first_val) / first_val * 100))

        movers.sort(key=lambda x: x[1], reverse=True)

        # Build final output
        history_text = f"## Portfolio Analysis (as of {latest_date})\n"
        history_text += f"Data range: {earliest_date} → {latest_date} ({len(sorted_dates)} snapshots)\n\n"
        history_text += "### Per-Ticker Stats (weight | overall change | 7d | 30d)\n"
        history_text += "\n".join(summary_lines)

        if movers:
            history_text += f"\n\n### Top Performer: {movers[0][0]} ({movers[0][1]:+.1f}% overall)"
            history_text += f"\n### Worst Performer: {movers[-1][0]} ({movers[-1][1]:+.1f}% overall)"

        print(f"✓ Pre-calculated stats for {len(ticker_history)} tickers across {len(sorted_dates)} snapshots")
        return history_text

    except Exception as e:
        print(f"❌ Error reading portfolio history: {e}")
        return ""


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

def summarize_with_gemini(news_text, portfolio_history=""):
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
    final_prompt = prompt_template.format(
        news_text=news_text,
        portfolio_string=portfolio_string,
        portfolio_history=portfolio_history if portfolio_history else "No historical data available."
    )

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

    # Load HTML template from external file
    template_file = os.path.join(BASE_DIR, "email_template.html")
    try:
        with open(template_file, 'r') as f:
            html_template = f.read()
        # Use replace instead of format to avoid CSS brace conflicts
        return html_template.replace('{content}', html_body)
    except FileNotFoundError:
        # Fallback to basic template if file not found
        print(f"⚠️ Warning: {template_file} not found. Using basic template.")
        return f"<html><body>{html_body}</body></html>"


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

    # Read Portfolio history from Sheet2 (also extracts current tickers)
    portfolio_history = ""
    if gc:
        portfolio_history = get_portfolio_history(gc)

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
    newsletter = summarize_with_gemini(news_text, portfolio_history)
    
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
