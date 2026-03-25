# 🇹🇷🇧🇬 Turkish/Bulgarian Border News Monitor — Setup Guide

## Prerequisites

### 1. Install Ollama (local LLM runner)
```bash
# Linux / macOS
curl -fsSL https://ollama.com/install.sh | sh

# Pull a model (llama3 recommended, ~4.7GB)
ollama pull llama3

# Or use a lighter model
ollama pull mistral
```

### 2. Install Python dependencies
```bash
pip install -r requirements.txt
```

---

## Telegram Bot Setup

1. Open Telegram and message **@BotFather**
2. Send `/newbot` and follow the prompts → copy your **Bot Token**
3. Start a chat with your new bot (send `/start`)
4. Get your **Chat ID** by visiting:
   ```
   https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates
   ```
   Look for `"chat": {"id": 123456789}` in the response

---

## Configuration

Set environment variables before running:

```bash
export TELEGRAM_BOT_TOKEN="123456789:ABCdef..."
export TELEGRAM_CHAT_ID="123456789"
export TELEGRAM_CHAT_IDS="123456789,987654321"   # optional multi-chat list
export OLLAMA_MODEL="llama3"          # or mistral, gemma2, etc.
export OLLAMA_BASE_URL="http://localhost:11434"
```

---

## Running

```bash
python border_news_monitor.py
```

Generate dashboard data for `docs/`:

```bash
python generate_web_data.py
```

To run in the background (Linux):
```bash
nohup python border_news_monitor.py > /dev/null 2>&1 &
```

### With systemd (auto-start on boot):
```ini
# /etc/systemd/system/border-monitor.service
[Unit]
Description=Turkish/Bulgarian Border News Monitor
After=network.target ollama.service

[Service]
ExecStart=/usr/bin/python3 /path/to/border_news_monitor.py
Environment=TELEGRAM_BOT_TOKEN=your_token
Environment=TELEGRAM_CHAT_ID=your_chat_id
Environment=OLLAMA_MODEL=llama3
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable --now border-monitor
```

---

## How It Works

1. Every **15 minutes**, the script fetches articles from 8 RSS feeds
2. Articles are **keyword-filtered** for Turkish/Bulgarian border relevance
3. New (unseen) articles are sent to your **local Ollama LLM** for a 2-3 sentence analysis
4. The analysis + link is sent to your **Telegram chat**
5. Seen article IDs are saved to `seen_articles.json` to avoid duplicates

## Customizing

- **Add more feeds**: Edit the `RSS_FEEDS` list in the script
- **Add keywords**: Edit the `KEYWORDS` list
- **Change interval**: Set `CHECK_INTERVAL_SECONDS`
- **Change model**: Set `OLLAMA_MODEL` to any model you have pulled
