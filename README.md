# 🌌 NERI: Performance Tracker Phase 2

**NERI** is a sophisticated, all-in-one performance tracking application designed to help individuals bridge the gap between their physical health and professional growth. By unifying personal development, professional milestones, and health metrics into a single, cohesive dashboard, Neri empowers users to lead a balanced and high-performing lifestyle.

---

## 🚀 Key Features

### 📊 Comprehensive Overview
- **Unified Score**: A daily performance index combining professional and physical achievements.
- **Dynamic Calendar**: Interactive date selection to track historical performance and plan upcoming goals.
- **Real-time Stats**: Instant visualization of completion percentages for all tracking categories.
- **Daily Focus & Reminders**: Sticky-note style reminders and goal highlights to keep you on track.

### 💼 Professional Growth (Profession Section)
- **Task Notebook**: Manage core professional tasks with persistence across days.
- **Career Path Sync**: Automatically generates daily career-oriented tasks based on your user profile.
- **Progress Analytics**: Tracks total vs. completed professional milestones to ensure career momentum.

### 🏃 Physical Well-being (Physical Section)
- **Smart Nutrition**: Personalized protein, fiber, and water targets calculated based on BMI and weight.
- **Daily Workout Routines**: Rotating specialized workout schedules (Cardio, HIIT, Strength, etc.) that change every day.
- **Food & Intake Logs**: Dedicated tracking for water consumption and daily nutrition.

### 👤 Career Profile
- **Comprehensive Identity**: Store detailed professional background including industry, role, and experience.
- **Education Tracking**: Dedicated fields for institution, degree, and year of study.
- **Dynamic Sync**: Your profile data drives the AI-powered task suggestions in the Profession section.

---

## 🏗️ Technical Architecture

### 🛠️ Backend (FastAPI & Python)
- **Modular Routing**: RESTful API design handles seamless data exchange between the frontend and the database.
- **Centralized Logic Engine**: A robust calculation system in `app.py` manages:
  - **Daily Activity Recalculation**: Dynamically computes completion percentages across multiple tables (Tasks, Nutrition, Goals, Reminders).
  - **Deterministic Generation**: Uses seed-based hashing to ensure daily workout routines and nutrition suggestions are consistent for all users on a specific day while rotating daily.
  - **Idempotent Migrations**: A safe, additive-only migration system ensures the database schema stays updated without data loss.

### 🎨 Frontend (HTML5, Vanilla CSS, JS)
- **Modern Dark Aesthetic**: A premium "Glassmorphism" inspired UI with vibrant accents and subtle gradients.
- **Responsive Design**: Fluid layouts that adapt to various screen sizes.
- **Dynamic Interactions**: Real-time UI updates via Fetch API for task toggling, goal additions, and data saving without page reloads.

### 📁 Database Schema (SQLite)
The data persistence layer is built on a relational SQLite architecture optimized for high-performance tracking:
- **`users`**: Secure authentication and core physical metrics (Height, Weight, BMI).
- **`profession_tasks`**: Categorized tasks (Core vs. Career) with date-specific tracking.
- **`daily_activity`**: Aggregated performance snapshots for historical calendar visualization.
- **`user_profiles`**: Deep professional metadata stored separately to maintain schema cleanliness.
- **`nutrition_checklist`**: Daily-generated health tasks mapped to individual users and dates.

---

## 🛠️ Tech Stack

- **Language**: Python 3.x
- **Framework**: FastAPI (Web Server & Routing)
- **Database**: SQLite3 (Relational Management)
- **Frontend**: HTML5, Vanilla CSS3 (Custom Design System), JavaScript (ES6+)
- **APIs**: Integrated Quotes API for daily motivation.

---

## 📂 Project Structure

```text
Performance_Tracker phase 2/
├── app.py              # Main application logic & API routes
├── database.py         # DB connection management
├── schema.sql          # Core table definitions
├── static/             # Assets (CSS, JS, Images)
├── templates/          # HTML views (Overview, Profession, etc.)
└── migrations/         # Maintenance & upgrade scripts
```

---

## 🏁 Getting Started

1. **Install Dependencies**:
   ```bash
   pip install fastapi uvicorn requests
   ```
2. **Initialize Database**:
   The application automatically runs migrations on startup!
3. **Run the App**:
   ```bash
   uvicorn app:app --reload
   ```
4. **Access**:
   Open `http://127.0.0.1:5000` in your browser.

---

*Designed for high-performers by high-performers.*
