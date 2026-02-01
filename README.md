# 📰 AI Financial Newsletter Automation

Automated daily financial newsletter that scrapes Google News, summarizes with Gemini AI, and emails you a personalized market briefing based on your portfolio.

## Features

- 🌐 **Google News RSS** - Pulls fresh news from 5 categories (World, Business, Tech, Markets, Crypto)
- 🤖 **Gemini AI** - Generates insightful macro analysis with customizable personality
- 📊 **Portfolio Integration** - Optional Google Sheets connection for dynamic portfolio tracking
- 📧 **Email Delivery** - Sends styled HTML newsletter to your inbox
- ⏰ **Daily Scheduling** - Run automatically every morning with launchd/cron
- 📁 **Archive** - Saves all newsletters to `archive/` folder
- 🎨 **Customizable** - External prompt, email template, and news categories

## What's New

- **External Configuration Files** - Prompt (`prompt.txt`) and email template (`email_template.html`) are now separate files for easy customization
- **Optional Portfolio** - Works without Google Sheets - skips portfolio sections automatically
- **Legal Disclaimer** - Auto-appended to every newsletter
- **New Gemini SDK** - Uses the latest `google-genai` package (not deprecated `google.generativeai`)

## Sample Output

```
## 🎤 The Bit (The Macro Thesis)
The Fed's hawkish pivot signals higher-for-longer rates, making cash king and growth stocks vulnerable.

## 🌍 The Setup (Top 5 High-Impact Stories)

### **Fed Signals No Rate Cuts Until 2025**
The Fed just threw cold water on rate cut hopes. Powell's latest comments suggest...

**The Data:** 10Y Treasury yield at 4.5%, Fed funds rate unchanged at 5.25-5.50%

👉 [Read more](https://news.google.com/...)

## 💼 Bag Check (Portfolio Stress Test)
* **Direct Hit:** AAPL, GOOGL, QQQ
* **The Verdict:** Thesis Intact
* **The Logic:** Tech valuations compress but fundamentals remain strong...

## 🔔 The Playbook (Actionable Moves)
* Hold cash position - wait for better entry points
* Accumulate on 10%+ dips in quality names
* Avoid speculative growth until rate clarity

---
*Disclaimer: This newsletter is for informational purposes only...*
```

> **Note:** Portfolio sections ("Bag Check" and "Playbook") are automatically skipped if no portfolio is configured.

## Quick Start

### 1. Clone the repo
```bash
git clone https://github.com/Dimpros/ai-financial-newsletter.git
cd ai-financial-newsletter
```

### 2. Install dependencies
```bash
pip install -r requirements.txt
```

### 3. Configure environment
```bash
cp .env.example .env
# Edit .env with your API keys
```

### 4. Run it
```bash
python simple_newsletter.py
```

## Configuration

### Required: Gemini API Key
1. Go to [Google AI Studio](https://aistudio.google.com/apikey)
2. Create an API key
3. Add to `.env`: `GEMINI_API_KEY=your-key-here`

### Optional: Gmail SMTP
1. Enable 2FA on your Google Account
2. Create an [App Password](https://myaccount.google.com/apppasswords)
3. Add to `.env`:
   ```
   EMAIL_ADDRESS=your-email@gmail.com
   EMAIL_APP_PASSWORD=your-16-char-app-password
   EMAIL_RECIPIENT=recipient@gmail.com
   ```

### Optional: Google Sheets Portfolio
1. Create a Google Cloud project
2. Enable Google Sheets API
3. Create a service account and download `service_account.json`
4. Share your spreadsheet with the service account email
5. Add to `.env`:
   ```
   GOOGLE_SHEET_NAME=Your-Portfolio-Sheet
   PORTFOLIO_TAB_NAME=Sheet1
   ```

## Daily Scheduling

### macOS (launchd) - Recommended
```bash
# Create the plist file
cat > ~/Library/LaunchAgents/com.newsletter.daily.plist << 'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.newsletter.daily</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/bin/python3</string>
        <string>/path/to/simple_newsletter.py</string>
    </array>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>9</integer>
        <key>Minute</key>
        <integer>0</integer>
    </dict>
    <key>StandardOutPath</key>
    <string>/path/to/newsletter.log</string>
    <key>StandardErrorPath</key>
    <string>/path/to/newsletter_error.log</string>
</dict>
</plist>
EOF

# Load the job
launchctl load ~/Library/LaunchAgents/com.newsletter.daily.plist
```

### Linux/macOS (cron)
```bash
# Edit crontab
crontab -e

# Add this line (runs at 9 AM daily)
0 9 * * * /usr/bin/python3 /path/to/simple_newsletter.py >> /path/to/newsletter.log 2>&1
```

## Customization

### AI Prompt (`prompt.txt`)
Edit `prompt.txt` to change the newsletter personality, structure, or style. Uses `{news_text}` and `{portfolio_string}` placeholders.

### Email Template (`email_template.html`)
Edit `email_template.html` to customize the email styling. Uses `{content}` placeholder for the newsletter body.

### News Categories
Edit `GOOGLE_NEWS_FEEDS` in the script to add/remove categories:
```python
GOOGLE_NEWS_FEEDS = {
    "World": "https://news.google.com/rss/topics/...",
    "Business": "https://news.google.com/rss/topics/...",
    # Add more categories...
}
```

## Project Structure

```
.
├── simple_newsletter.py    # Main script
├── prompt.txt              # AI prompt template (customizable)
├── email_template.html     # Email styling (customizable)
├── requirements.txt        # Python dependencies
├── .env.example            # Environment template
├── .env                    # Your config (git-ignored)
├── service_account.json    # Google Sheets credentials (git-ignored)
└── archive/                # Saved newsletters
    └── newsletter_2026-02-01.md
```

## License

MIT License - feel free to use and modify.

## Contributing

PRs welcome! Ideas for improvement:
- Multiple email recipients
- Slack/Discord integration
- Web dashboard
- Historical trend analysis
- Support for other LLMs (Claude, GPT-4, etc.)
