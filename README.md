# Telegram Content Copier Bot

A bot that copies content from a channel to group topics without forward tags.

## Features
- Creates topics in destination group
- Copies messages between specified links
- Supports all message types (text, media, documents, stickers)
- No "forwarded from" tags
- Progress tracking and reporting
- Configurable delay between copies

## Setup
1. Add bot as admin in both source channel and destination group
2. Set environment variables in `.env` file
3. Deploy to Render or run locally

## Commands
- `/start` - Show welcome message
- `/create_topic TOPIC_NAME` - Create new topic (also accepts `/createtopic`)
- Then send start and end message links
