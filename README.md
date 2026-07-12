# Port Moresby Power Outage Tracker

A Flask + MapLibre GL JS web application that tracks power outages across Port Moresby suburbs using an interactive map, automated data collection, analytics, and notification services.

The platform provides outage visibility through a dashboard, suburb-based search, status filtering, user reporting, and an administration system for managing verified outage information.

---

# Purpose

This project was developed to demonstrate real-world infrastructure monitoring concepts by combining:

* Automated data collection
* Database management
* Web application development
* API integration
* Background task scheduling
* Notification systems
* Containerized deployment

The goal is to provide a centralized platform for monitoring and managing power outage information across Port Moresby suburbs.

---

# Features

## Outage Monitoring

* Interactive outage map using MapLibre GL JS
* Colour-coded outage markers by suburb status
* Search and filtering by outage type:

  * Active
  * Planned
  * Restored
  * Emergency
* Real-time statistics dashboard

## Data Collection & Automation

* Browser-based web scraper using Playwright
* Automated background updates using APScheduler
* SQLite database storage with duplicate prevention
* Automated outage status tracking

## User Features

* User registration and login
* Favourite suburb subscriptions
* Personal outage dashboard
* Public outage reporting system
* Optional photo and location reporting

## Verification System

Outages follow a verification workflow:

```
Reported
   ↓
Under Review
   ↓
Verified
   ↓
Active
   ↓
Restored
```

Confidence scoring combines:

* Number of reports
* Administrative verification
* Historical outage information

## Notifications

Supports:

* Email notifications
* SMS notifications
* Suburb-based alerts

Users can subscribe to receive updates when outages are created or restored.

## Weather Integration

* Weather data collection using OpenWeather
* Weather conditions stored with outage events
* Weather correlation analysis for identifying possible outage patterns

## Analytics Dashboard

Provides:

* Total outages
* Active outages
* Planned outages
* Emergency outages
* Most affected suburbs
* Restoration time analysis
* Peak outage periods

---

# Technologies Used

## Backend

* Python
* Flask
* SQLite
* REST API development

## Frontend

* HTML
* CSS
* JavaScript
* MapLibre GL JS
* OpenFreeMap

## Automation

* Playwright
* APScheduler

## Deployment

* Docker
* Environment-based configuration
* Git/GitHub version control

## External Services

* OpenWeather API
* LocationIQ Geocoding API
* Email notification services
* SMS notification services

---

# Installation

## 1. Clone Repository

```bash
git clone https://github.com/Thafundraiser007/Power-Outage-Tracker.git
```

Navigate into the project:

```bash
cd Power-Outage-Tracker
```

---

## 2. Create Virtual Environment

Windows:

```bash
python -m venv venv
venv\Scripts\activate
```

Linux/macOS:

```bash
python -m venv venv
source venv/bin/activate
```

---

## 3. Install Dependencies

```bash
pip install -r requirements.txt
```

Install Playwright browser:

```bash
playwright install chromium
```

---

## 4. Configure Environment Variables

Copy the example configuration:

```bash
cp .env.example .env
```

Add your required API keys and configuration values.

Never upload `.env` files containing real credentials.

---

## 5. Run Application

```bash
python app.py
```

Open:

```
http://127.0.0.1:5000
```

---

# Project Structure

```
Power-Outage-Tracker/

├── app.py              Flask application and API routes
├── auth.py             User authentication
├── config.py           Application configuration
├── database.py         SQLite database management
├── scraper.py          Automated outage data collection
├── scheduler.py        Background update scheduler
├── notifications.py    Email and SMS notification system
├── weather.py          Weather API integration
│
├── templates/          HTML templates
├── static/             CSS, JavaScript and frontend assets
│
├── Dockerfile          Container deployment configuration
├── requirements.txt    Python dependencies
├── .env.example        Environment variable template
├── README.md           Documentation
└── .gitignore          Git exclusions
```

---

# Deployment

## Docker Deployment

Build container:

```bash
docker build -t outage-tracker .
```

Run:

```bash
docker run -p 5000:5000 --env-file .env outage-tracker
```

The included Dockerfile provides a consistent deployment environment with required dependencies.

---

# Screenshots

Add screenshots here:

Example:

```
screenshots/
├── dashboard.png
├── map.png
└── admin.png
```

Then display them:

```markdown
![Dashboard](screenshots/dashboard.png)

![Map](screenshots/map.png)
```

---

# Skills Demonstrated

This project demonstrates practical experience with:

* Python application development
* Network monitoring concepts
* Infrastructure automation
* Database management
* API integration
* Data processing
* Web services
* Background task scheduling
* Docker containerization
* Git version control
* System notification workflows

---

# Future Improvements

Possible future enhancements:

* Real-time outage API integration
* Historical outage analytics graphs
* Mobile application support
* Automated testing framework
* Public API documentation
* PostgreSQL migration for larger deployments
* Cloud deployment with monitoring and logging

---

# Author

**Jamill Naipao**

Power Outage Tracker
Built as a portfolio project demonstrating software development, automation, and infrastructure monitoring concepts.
