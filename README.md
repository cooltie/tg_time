# TimeToTrack Bot 🤖⏰

A Telegram bot for tracking work time on projects. Allows real-time time tracking, manual time entry, and detailed statistics viewing.

## 🚀 Features

### Core Functions
- ⏱️ **Real-time tracking** - start and stop timer functionality
- 📝 **Manual time entry** - add time entries retroactively
- 📊 **Detailed statistics** - analyze time by projects and periods
- 💾 **Database storage** - all data securely stored in PostgreSQL
- 🎯 **Multi-project support** - work with multiple projects simultaneously

### Interface
- 🔘 **Inline buttons** - convenient management directly in chat
- ✅ **Data validation** - validation of entered dates and time formats
- 📱 **Intuitive UX** - simple and clear interface

## 📋 Commands

### `/start`
Start working with the bot. Shows:
- List of existing projects (if any)
- "Add new" button to create a new project

### `/manual`
Manual time entry. Step-by-step process:
1. Select project (or create new one)
2. Enter date in `DD MM YY` format (e.g.: `15 08 24`)
3. Enter time in `HH:MM` format (e.g.: `02:30`)
4. Enter comment
5. Confirm and save

### `/stats`
View work statistics:
- 📅 **Weekly** - statistics for the last 7 days
- 📆 **Monthly** - statistics for the last 30 days
- 📊 **By project** - detailed statistics for selected project

## 🎯 Usage Scenarios

### Real-time tracking
1. Send `/start`
2. Select project or create new one
3. Timer starts automatically
4. Press ⏹️ **Stop** when you finish work
5. Enter session comment
6. Data saves automatically

### Manual time entry
1. Send `/manual`
2. Select project
3. Enter date: `15 08 24`
4. Enter time: `03:45`
5. Add comment: `Working on design`
6. Press 💾 **Save**

### View statistics
1. Send `/stats`
2. Choose period:
   - Weekly - shows time for all projects over 7 days
   - Monthly - shows time for all projects over 30 days
   - By project - detailed statistics with daily breakdown

## 📊 Statistics Format

### General statistics (weekly/monthly)
```
📊 Weekly Statistics

🔸 Project A
   Time: 12:30 (5 sessions)

🔸 Project B
   Time: 08:15 (3 sessions)

⏱ Total time: 20:45
```

### Detailed project statistics
```
📊 Project: My Project

⏱ Total time: 45:30
📋 Total sessions: 12

📅 Last 10 days:
• 15.08: 03:45 (2 sessions)
• 14.08: 02:30 (1 session)
• 13.08: 04:15 (3 sessions)
```

## 🗄️ Data Structure

### `users` table
- `id` - unique user ID
- `telegram_id` - user ID in Telegram
- `created_at` - registration date

### `projects` table
- `id` - unique record ID
- `user_id` - reference to user
- `project_name` - project name
- `start_time` - work start time
- `end_time` - work end time
- `duration` - session duration
- `comment` - session comment

## ⚙️ Technical Details

### Technology Stack
- **Python 3.11+**
- **aiogram 3.21+** - library for Telegram Bot API
- **asyncpg** - asynchronous PostgreSQL client
- **python-dotenv** - environment variables management

### Environment Variables
Create `.env` file in project root:
```env
API_TOKEN=your_telegram_bot_token
DATABASE_URL=postgresql://user:password@host:port/database
```

### Installation and Setup
1. Clone the repository:
```bash
git clone https://github.com/cooltie/tg_time.git
cd tg_time
```

2. Create virtual environment:
```bash
python3 -m venv venv
source venv/bin/activate  # Linux/Mac
# or
venv\Scripts\activate     # Windows
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. Configure environment variables in `.env`

5. Run the bot:
```bash
python main.py
```

## 🔒 Security

- All user data is isolated by `telegram_id`
- Environment variables are not committed to repository
- Database uses prepared statements (SQL injection protection)

## 📈 Future Development

- 📊 Export statistics to Excel/CSV
- 📅 Calendar widget for date selection
- 🏷️ Tags and categories for projects
- 📧 Weekly email reports
- 🎯 Goals and progress tracking
- 📱 Web interface for statistics viewing

## 🤝 Contributing

All improvements are welcome! Create Issues and Pull Requests.

## 📄 License

MIT License - see LICENSE file for details.

---

**Created with ❤️ for effective time management**
